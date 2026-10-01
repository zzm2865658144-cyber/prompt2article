"""Integration tests for the local web UI.

These start a real HTTP server on an ephemeral loopback port and drive it with
urllib, so the request parsing, the SSE stream and the file endpoints are all
exercised rather than mocked.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from prompt2article import webapp
from tests._helpers import temp_dir


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._cwd = os.getcwd()
        cls._tmp = temp_dir()
        cls.tmp = cls._tmp.__enter__()
        os.chdir(cls.tmp)

        cls.server = webapp.ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
        cls.server.daemon_threads = True
        cls.server.options = webapp.build_parser().parse_args([])
        cls.server.quiet = True
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        os.chdir(cls._cwd)
        cls._tmp.__exit__(None, None, None)

    # ------------------------------------------------------------- helpers --
    def get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=20) as res:
            return res.status, res.read().decode("utf-8"), res.headers.get("Content-Type", "")

    def generate(self, **overrides) -> list[dict]:
        body = {"prompt": "测试主题", "offline": True, "words": 400, "save": True}
        body.update(overrides)
        req = urllib.request.Request(
            self.base + "/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        events = []
        with urllib.request.urlopen(req, timeout=60) as res:
            self.assertEqual(res.headers.get("Content-Type", "").split(";")[0], "text/event-stream")
            for raw in res.read().decode("utf-8").split("\n\n"):
                for line in raw.split("\n"):
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
        return events

    # ---------------------------------------------------------------- page --
    def test_index_is_served(self) -> None:
        status, html, ctype = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("prompt2article", html)
        self.assertIn("生成文章", html)

    def test_static_assets_are_served(self) -> None:
        _, css, css_type = self.get("/style.css")
        self.assertIn("--accent", css)
        self.assertIn("text/css", css_type)
        _, js, js_type = self.get("/app.js")
        self.assertIn("renderMarkdown", js)
        self.assertIn("javascript", js_type)

    def test_config_lists_every_style(self) -> None:
        _, body, ctype = self.get("/api/config")
        self.assertIn("application/json", ctype)
        cfg = json.loads(body)
        self.assertEqual(len(cfg["styles"]), 8)
        self.assertEqual(cfg["defaultStyle"], "science")
        self.assertIn("hasKey", cfg)
        self.assertIn("zh", cfg["languages"])

    # ------------------------------------------------------------ generate --
    def test_offline_generation_streams_progress_and_saves(self) -> None:
        events = self.generate()
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "start")
        self.assertIn("progress", kinds)
        self.assertEqual(kinds[-1], "done")

        done = events[-1]
        self.assertIn("# 【离线示例】测试主题", done["markdown"])
        self.assertGreater(done["words"], 0)
        self.assertEqual(len(done["sections"]), 4)
        self.assertTrue(done["path"], "应当报告保存路径")

        saved = self.tmp / done["path"]
        self.assertTrue(saved.is_file(), f"{saved} 应该存在")
        self.assertIn("测试主题", saved.read_text(encoding="utf-8"))

    def test_save_can_be_disabled(self) -> None:
        events = self.generate(prompt="不落盘", save=False)
        self.assertEqual(events[-1]["path"], "")

    def test_empty_prompt_is_rejected(self) -> None:
        req = urllib.request.Request(
            self.base + "/api/generate",
            data=json.dumps({"prompt": "   "}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=20)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("主题", json.loads(ctx.exception.read().decode("utf-8"))["error"])

    def test_malformed_body_is_rejected(self) -> None:
        req = urllib.request.Request(
            self.base + "/api/generate",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=20)
        self.assertEqual(ctx.exception.code, 400)

    # --------------------------------------------------------------- files --
    def test_articles_listing_and_fetch(self) -> None:
        self.generate(prompt="列表测试")
        _, body, _ = self.get("/api/articles")
        names = [a["name"] for a in json.loads(body)["articles"]]
        self.assertTrue(names, "刚生成的文章应当出现在列表里")

        name = names[0]
        _, md, ctype = self.get("/api/article?name=" + urllib.parse.quote(name))
        self.assertIn("markdown", ctype)
        self.assertTrue(md.startswith("---"), "生成的 Markdown 应带 front matter")

    def test_path_traversal_is_refused(self) -> None:
        for bad in ("../secret.md", "..\\..\\secret.md", "sub/dir.md", "x.txt"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get("/api/article?name=" + urllib.parse.quote(bad))
            self.assertEqual(ctx.exception.code, 400, bad)

    def test_unknown_route_is_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
