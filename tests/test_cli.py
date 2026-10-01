"""CLI-level tests: argument handling, offline run, output files."""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from prompt2article.cli import main
from tests._helpers import temp_dir


class CliTests(unittest.TestCase):
    def _run(self, argv: list[str], inspect=None) -> tuple[int, str, str]:
        """Run main() with the cwd pointed at a scratch directory.

        `inspect` is called with that directory before it is cleaned up, so a
        test can assert on files the run was supposed to produce.
        """
        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        with temp_dir() as tmp:
            os.chdir(tmp)
            try:
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(argv)
                if inspect is not None:
                    inspect(Path(tmp))
            finally:
                os.chdir(cwd)
        return code, out.getvalue(), err.getvalue()

    def test_list_styles_exits_zero(self) -> None:
        code, out, _ = self._run(["--list-styles"])
        self.assertEqual(code, 0)
        self.assertIn("science", out)
        self.assertIn("科普", out)

    def test_offline_run_writes_markdown_and_json(self) -> None:
        def check(tmp: Path) -> None:
            target = tmp / "deep" / "article.md"
            self.assertTrue(target.exists(), "应写出 Markdown")
            text = target.read_text(encoding="utf-8")
            self.assertIn("# 【离线示例】测试主题", text)
            sidecar = target.with_suffix(".json")
            self.assertTrue(sidecar.exists(), "应写出 .json 元数据")
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(meta["style"], "science")
            self.assertGreater(meta["word_count"], 0)
            self.assertEqual(len(meta["sections"]), 4)

        code, _, err = self._run(
            ["测试主题", "--offline", "--quiet",
             "--out", "deep/article.md", "--json", "--words", "600"],
            inspect=check,
        )
        self.assertEqual(code, 0, err)

    def test_stdout_mode_writes_no_file(self) -> None:
        def check(tmp: Path) -> None:
            self.assertFalse((tmp / "output").exists(), "stdout 模式不应产生 output 目录")

        code, out, err = self._run(["主题", "--offline", "--quiet", "--stdout"], inspect=check)
        self.assertEqual(code, 0, err)
        self.assertIn("# 【离线示例】主题", out)

    def test_requires_exactly_one_prompt_source(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._run(["--offline"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_api_key_is_a_config_error(self) -> None:
        # No --offline, and the environment is cleared so no key can be found.
        saved = {k: os.environ.pop(k, None) for k in
                 ("P2A_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")}
        try:
            code, _, err = self._run(["主题", "--quiet", "--api-key", ""])
            self.assertEqual(code, 2)
            self.assertIn("API Key", err)
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    def test_prompt_file_input(self) -> None:
        with temp_dir() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                topic = Path(tmp) / "topic.txt"
                topic.write_text("从文件读来的主题", encoding="utf-8")
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(["--file", str(topic), "--offline", "--quiet", "--stdout"])
            finally:
                os.chdir(cwd)
            self.assertEqual(code, 0, err.getvalue())
            self.assertIn("从文件读来的主题", out.getvalue())


if __name__ == "__main__":
    unittest.main()
