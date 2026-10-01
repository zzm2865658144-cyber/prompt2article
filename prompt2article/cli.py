"""Command-line interface for prompt2article."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, prompts
from .client import LLMError, MockClient, OpenAIChatClient
from .config import Config, ConfigError, load_config
from .generator import Article, ArticleGenerator

PROG = "prompt2article"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="根据提示词生成文章：先拟标题和大纲，再逐节写作，最后可选润色。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            f'  {PROG} "写一篇介绍世界线收束概念的科普文章"\n'
            f'  {PROG} "量子计算的现状" --style tech --words 2000 --polish\n'
            f'  {PROG} --file topic.txt --style wechat --out output/qc.md\n'
            f"  {PROG} --list-styles\n"
            f'  {PROG} "先跑通流程" --offline          # 不需要 API Key\n'
        ),
    )
    parser.add_argument("prompt", nargs="?", help="文章主题/提示词")
    parser.add_argument("--file", type=Path, help="从文件读取提示词（与位置参数二选一）")
    parser.add_argument("--style", default=prompts.DEFAULT_STYLE,
                        help=f"写作风格，默认 {prompts.DEFAULT_STYLE}；用 --list-styles 查看全部")
    parser.add_argument("--list-styles", action="store_true", help="列出所有写作风格并退出")
    parser.add_argument("--words", type=int, default=None, help="目标字数（默认取风格预设）")
    parser.add_argument("--audience", default=None, help="目标读者，会写进提示词")
    parser.add_argument("--language", default="zh", choices=sorted(prompts.LANGUAGE_NAMES),
                        help="输出语言，默认 zh")
    parser.add_argument("--title", default=None, help="直接指定标题，跳过标题生成")
    parser.add_argument("--sections", type=int, default=8, help="最多保留多少个小节，默认 8")
    parser.add_argument("--polish", action="store_true", help="生成后逐节润色（更慢，质量更稳）")
    parser.add_argument("--out", type=Path, default=None,
                        help="输出 Markdown 路径，默认 output/<标题>-<时间>.md")
    parser.add_argument("--stdout", action="store_true", help="打印到标准输出而不写文件")
    parser.add_argument("--json", action="store_true", help="同时输出一份同名 .json 元数据")
    parser.add_argument("--offline", action="store_true",
                        help="使用内置模拟模型，不需要 Key 和网络，用于验证流程")
    parser.add_argument("--model", default=None, help="覆盖模型名")
    parser.add_argument("--base-url", default=None, help="覆盖接口地址（OpenAI 兼容）")
    parser.add_argument("--api-key", default=None, help="显式传入 Key（会留在命令历史里，慎用）")
    parser.add_argument("--temperature", type=float, default=None, help="采样温度")
    parser.add_argument("--timeout", type=float, default=None, help="单次请求超时秒数")
    parser.add_argument("--quiet", action="store_true", help="不打印进度")
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    return parser


def _slugify(text: str, limit: int = 40) -> str:
    """Filesystem-safe stem for the output file."""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", text).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip("-. ")
    return (cleaned[:limit] or "article").rstrip("-. ")


def _resolve_prompt(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    sources = [bool(args.prompt), bool(args.file)]
    if sum(sources) != 1:
        parser.error("请给出提示词：位置参数 或 --file，二选一")
    if args.file:
        try:
            text = args.file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            parser.error(f"读不到 --file {args.file}: {exc}")
        if not text:
            parser.error(f"--file {args.file} 是空文件")
        return text
    return str(args.prompt).strip()


def _make_client(config: Config, offline: bool):
    if offline:
        return MockClient(config)
    return OpenAIChatClient(config)


def _write_outputs(args: argparse.Namespace, article: Article, markdown: str) -> list[Path]:
    written: list[Path] = []
    if args.stdout:
        sys.stdout.write(markdown)
        if not markdown.endswith("\n"):
            sys.stdout.write("\n")
    else:
        target = args.out
        if target is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = Path("output") / f"{_slugify(article.title)}-{stamp}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        written.append(target)

    if args.json:
        meta = {
            "title": article.title,
            "prompt": article.prompt,
            "style": article.style,
            "language": article.language,
            "audience": article.audience,
            "model": article.model,
            "target_words": article.target_words,
            "word_count": article.word_count,
            "generated_at": article.generated_at.isoformat(),
            "sections": [
                {"heading": s.heading, "words": s.word_count, "body": s.body}
                for s in article.sections
            ],
        }
        base = args.out if args.out else (written[0] if written else Path("output") / "article.md")
        sidecar = base.with_suffix(".json")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(sidecar)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_styles:
        print("可用风格：")
        print(prompts.style_table())
        return 0

    prompt = _resolve_prompt(args, parser)
    style = prompts.resolve_style(args.style)
    if args.style not in prompts.STYLES:
        print(f"提示：未知风格 {args.style!r}，已回退到 {style.key}", file=sys.stderr)

    progress = (lambda _m: None) if args.quiet else (
        lambda message: print(f"  · {message}", file=sys.stderr)
    )

    try:
        config = load_config(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
            temperature=args.temperature,
        )
        client = _make_client(config, args.offline)
        if not args.offline:
            config.require_key()

        if not args.quiet:
            mode = "离线模拟" if args.offline else f"{config.model} @ {config.base_url}"
            print(f"{PROG} {__version__} · 风格={style.name} · {mode}", file=sys.stderr)

        generator = ArticleGenerator(client, style, model="mock" if args.offline else config.model)
        article = generator.generate(
            prompt,
            target_words=args.words,
            language=args.language,
            audience=args.audience,
            title=args.title,
            max_sections=max(1, args.sections),
            polish=args.polish,
            progress=progress,
        )
        markdown = article.to_markdown()
        written = _write_outputs(args, article, markdown)

        if not args.quiet:
            for path in written:
                print(f"已写入 {path}  （{article.word_count} 字 / 目标 {article.target_words} 字）",
                      file=sys.stderr)
        return 0
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
