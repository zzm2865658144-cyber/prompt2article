"""Local web UI for prompt2article.

A single-file HTTP server built on the standard library -- no framework, no
install step, matching the project's zero-dependency rule.

Why a server at all instead of a static page that calls the API from the
browser: the API key would have to live in JavaScript the page can read, and
most providers (DeepSeek included) do not send CORS headers for browser calls.
Keeping the key server-side and proxying solves both, and it lets the whole
existing pipeline -- styles, outline, per-section writing, polish -- be reused
instead of reimplemented in JavaScript.

Endpoints
    GET  /                    the single page
    GET  /style.css /app.js   static assets
    GET  /api/config          styles, defaults, and whether a key is configured
    POST /api/generate        run the pipeline, streaming progress as SSE
    GET  /api/articles        previously generated files
    GET  /api/article?name=   one generated file's raw Markdown

Bound to 127.0.0.1 by default: this is a local tool, and generation costs money.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__, prompts
from .cli import _slugify
from .client import LLMError, MockClient, OpenAIChatClient
from .config import ConfigError, load_config
from .generator import ArticleGenerator

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756
WEB_DIR = Path(__file__).resolve().parent / "web"
OUTPUT_DIR = Path("output")
MAX_BODY = 256 * 1024

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

SAFE_NAME = re.compile(r"^[^\\/:*?\"<>|\r\n]{1,120}\.md$")


class Handler(BaseHTTPRequestHandler):
    """One instance per request; `server.options` carries the CLI settings."""

    server_version = f"prompt2article/{__version__}"
    protocol_version = "HTTP/1.0"  # connection closes per response; no chunked encoding needed

    # ---------------------------------------------------------------- utils --
    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    # ------------------------------------------------------------------ GET --
    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        route = parsed.path

        if route in STATIC_FILES:
            name, ctype = STATIC_FILES[route]
            path = WEB_DIR / name
            if not path.is_file():
                self._send(500, f"missing asset: {name}".encode(), "text/plain; charset=utf-8")
                return
            self._send(200, path.read_bytes(), ctype)
            return

        if route == "/api/config":
            self._json(200, self._config_payload())
            return

        if route == "/api/articles":
            self._json(200, {"articles": _list_articles()})
            return

        if route == "/api/article":
            name = (parse_qs(parsed.query).get("name") or [""])[0]
            if not SAFE_NAME.match(name):
                self._json(400, {"error": "文件名不合法"})
                return
            path = OUTPUT_DIR / name
            if not path.is_file():
                self._json(404, {"error": "找不到这个文件"})
                return
            self._send(200, path.read_bytes(), "text/markdown; charset=utf-8")
            return

        self._json(404, {"error": "not found"})

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    # ----------------------------------------------------------------- POST --
    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/generate":
            self._json(404, {"error": "not found"})
            return
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"请求体不合法：{exc}"})
            return
        self._generate(payload)

    # ------------------------------------------------------------- pipeline --
    def _config_payload(self) -> dict[str, Any]:
        try:
            config = load_config()
            has_key = config.has_key
            model, base_url = config.model, config.base_url
        except ConfigError:
            has_key, model, base_url = False, "", ""
        return {
            "version": __version__,
            "hasKey": has_key,
            "model": model,
            "baseUrl": base_url,
            "defaultStyle": prompts.DEFAULT_STYLE,
            "defaultWords": prompts.STYLES[prompts.DEFAULT_STYLE].default_words,
            "languages": prompts.LANGUAGE_NAMES,
            "styles": [
                {"key": s.key, "name": s.name, "summary": s.summary, "words": s.default_words}
                for s in prompts.STYLES.values()
            ],
        }

    def _sse_start(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _sse(self, event: dict[str, Any]) -> None:
        """Write one event. Never raises: the client may have navigated away."""
        try:
            data = json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
            raise _ClientGone from None

    def _generate(self, payload: dict[str, Any]) -> None:
        opts = self.server.options  # type: ignore[attr-defined]
        offline = bool(payload.get("offline")) or bool(getattr(opts, "force_offline", False))
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            self._json(400, {"error": "请先填写文章主题"})
            return

        style_key = str(payload.get("style") or prompts.DEFAULT_STYLE)
        style = prompts.resolve_style(style_key)
        try:
            words = max(200, int(payload.get("words") or style.default_words))
        except (TypeError, ValueError):
            words = style.default_words
        try:
            sections = max(1, min(20, int(payload.get("sections") or 8)))
        except (TypeError, ValueError):
            sections = 8
        audience = str(payload.get("audience") or "").strip() or None
        language = str(payload.get("language") or "zh")
        title = str(payload.get("title") or "").strip() or None
        polish = bool(payload.get("polish"))
        save = payload.get("save", True) is not False

        self._sse_start()
        try:
            config = load_config()
            if not offline:
                config.require_key()
            client = MockClient(config) if offline else OpenAIChatClient(config)
            model = "mock" if offline else config.model

            self._sse({"type": "start", "style": style.name, "model": model, "words": words})

            def progress(message: str) -> None:
                self._sse({"type": "progress", "message": message})

            generator = ArticleGenerator(client, style, model=model)
            article = generator.generate(
                prompt,
                target_words=words,
                language=language,
                audience=audience,
                title=title,
                max_sections=sections,
                polish=polish,
                progress=progress,
            )
            markdown = article.to_markdown()
            path = _save(article.title, markdown) if save else None
            self._sse({
                "type": "done",
                "title": article.title,
                "markdown": markdown,
                "words": article.word_count,
                "targetWords": article.target_words,
                "sections": [{"heading": s.heading, "words": s.word_count} for s in article.sections],
                "path": str(path) if path else "",
            })
        except ConfigError as exc:
            self._sse({"type": "error", "message": str(exc)})
        except LLMError as exc:
            self._sse({"type": "error", "message": str(exc)})
        except _ClientGone:
            return
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the page
            self._sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})


class _ClientGone(Exception):
    """The browser closed the stream; stop quietly."""


def _save(title: str, markdown: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = OUTPUT_DIR / f"{_slugify(title)}-{stamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def _list_articles(limit: int = 30) -> list[dict[str, Any]]:
    if not OUTPUT_DIR.is_dir():
        return []
    files = sorted(OUTPUT_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in files[:limit]:
        stat = path.stat()
        out.append({
            "name": path.name,
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt2article-web",
        description="在浏览器里根据提示词生成文章（本地服务，默认只监听 127.0.0.1）。",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址，默认 {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--offline", action="store_true", help="强制离线模拟模式（忽略页面上的开关）")
    parser.add_argument("--quiet", action="store_true", help="不打印每个请求的日志")
    parser.add_argument("--version", action="version", version=f"prompt2article {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not WEB_DIR.is_dir():
        print(f"找不到前端目录：{WEB_DIR}", file=sys.stderr)
        return 1

    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"启动失败：{args.host}:{args.port} 无法监听（{exc}）。换个端口：--port 8757", file=sys.stderr)
        return 1

    server.daemon_threads = True
    server.options = args          # type: ignore[attr-defined]
    server.quiet = args.quiet      # type: ignore[attr-defined]
    url = f"http://{args.host}:{args.port}/"

    print(f"prompt2article {__version__} 已启动")
    print(f"  地址：{url}")
    print(f"  输出目录：{OUTPUT_DIR.resolve()}")
    print("  按 Ctrl+C 停止")
    if args.offline:
        print("  (离线模拟模式：内容是占位文字)")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
