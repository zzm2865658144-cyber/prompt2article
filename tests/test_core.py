"""Tests for the pure helpers: word counting, outline parsing, budget split."""

from __future__ import annotations

import unittest

from prompt2article.generator import (
    Article,
    ArticleGenerator,
    Section,
    _strip_duplicate_heading,
    count_words,
    parse_outline,
    split_budget,
)
from prompt2article.client import MockClient
from prompt2article.config import Config, parse_env_file
from prompt2article.prompts import STYLES, resolve_style


class CountWordsTests(unittest.TestCase):
    def test_counts_each_cjk_character(self) -> None:
        self.assertEqual(count_words("世界线收束"), 5)

    def test_counts_latin_words_not_characters(self) -> None:
        self.assertEqual(count_words("hello brave new world"), 4)

    def test_mixes_both(self) -> None:
        # 使用排版 = 4 CJK characters, plus one latin token ("Markdown")
        self.assertEqual(count_words("使用 Markdown 排版"), 5)

    def test_empty_and_punctuation_only(self) -> None:
        self.assertEqual(count_words(""), 0)
        self.assertEqual(count_words("，。！？——"), 0)


class ParseOutlineTests(unittest.TestCase):
    def test_markdown_headings(self) -> None:
        text = "## 背景\n## 现状\n## 结论"
        self.assertEqual(parse_outline(text, "兜底"), ["背景", "现状", "结论"])

    def test_bullets_and_numbering_are_accepted(self) -> None:
        text = "- 背景\n* 现状\n1. 结论\n2) 展望"
        self.assertEqual(parse_outline(text, "兜底"), ["背景", "现状", "结论", "展望"])

    def test_strips_bold_and_hashes(self) -> None:
        self.assertEqual(parse_outline("## **重点**", "兜底"), ["重点"])

    def test_deduplicates(self) -> None:
        self.assertEqual(parse_outline("## 背景\n## 背景", "兜底"), ["背景"])

    def test_falls_back_when_nothing_usable(self) -> None:
        self.assertEqual(parse_outline("抱歉，我无法完成。", "兜底"), ["兜底"])
        self.assertEqual(parse_outline("", "兜底"), ["兜底"])
        self.assertEqual(parse_outline("## 1.\n## 2、", "兜底"), ["兜底"])


class SplitBudgetTests(unittest.TestCase):
    def test_sums_to_total(self) -> None:
        for total, parts in [(1200, 4), (900, 3), (5000, 7), (300, 2)]:
            self.assertEqual(sum(split_budget(total, parts)), total)

    def test_respects_floor(self) -> None:
        budget = split_budget(200, 5)
        self.assertTrue(all(b >= 120 for b in budget), budget)

    def test_zero_parts(self) -> None:
        self.assertEqual(split_budget(1000, 0), [])


class StripHeadingTests(unittest.TestCase):
    def test_removes_echoed_heading(self) -> None:
        body = "## 背景\n\n正文内容。"
        self.assertEqual(_strip_duplicate_heading(body, "背景"), "正文内容。")

    def test_keeps_unrelated_first_line(self) -> None:
        self.assertEqual(_strip_duplicate_heading("正文。", "背景"), "正文。")

    def test_handles_leading_blank_lines(self) -> None:
        self.assertEqual(_strip_duplicate_heading("\n\n# 背景\n正文", "背景"), "正文")


class ArticleMarkdownTests(unittest.TestCase):
    def test_front_matter_and_body(self) -> None:
        article = Article(
            title="测试标题",
            prompt="测试提示词",
            style="science",
            language="zh",
            audience=None,
            sections=[Section("第一节", "内容一"), Section("第二节", "内容二")],
            model="mock",
        )
        md = article.to_markdown()
        self.assertIn('title: "测试标题"', md)
        self.assertIn("model: mock", md)
        self.assertTrue(md.startswith("---\n"))
        self.assertIn("# 测试标题", md)
        self.assertIn("## 第一节", md)
        self.assertIn("内容二", md)

    def test_quotes_in_front_matter_are_escaped(self) -> None:
        article = Article("a" * 1, '他说"你好"', "science", "zh", None)
        self.assertIn('prompt: "他说\\"你好\\""', article.to_markdown())


class GenerateEndToEndTests(unittest.TestCase):
    def test_offline_pipeline_produces_sections(self) -> None:
        client = MockClient(Config())
        style = resolve_style("science")
        generator = ArticleGenerator(client, style, model="mock")
        article = generator.generate(
            "世界线收束", target_words=900, audience="普通读者", progress=lambda _m: None
        )
        self.assertEqual(article.title, "【离线示例】世界线收束")
        self.assertEqual(len(article.sections), 4)
        self.assertTrue(all(s.body.strip() for s in article.sections))
        self.assertGreater(article.word_count, 0)
        md = article.to_markdown()
        self.assertIn("# 【离线示例】世界线收束", md)

    def test_explicit_title_skips_title_call(self) -> None:
        client = MockClient(Config())
        generator = ArticleGenerator(client, resolve_style("tech"), model="mock")
        article = generator.generate("主题X", title="我定的标题", target_words=400)
        self.assertEqual(article.title, "我定的标题")
        first_user = client.calls[0][-1]["content"]
        self.assertIn("输出大纲", first_user, "给定标题后第一个请求就应该是在要大纲")

    def test_max_sections_truncates(self) -> None:
        client = MockClient(Config())
        generator = ArticleGenerator(client, resolve_style("science"), model="mock")
        article = generator.generate("主题Y", target_words=800, max_sections=2)
        self.assertEqual(len(article.sections), 2)

    def test_polish_adds_calls_per_section(self) -> None:
        plain = MockClient(Config())
        ArticleGenerator(plain, resolve_style("science"), model="mock").generate(
            "主题Z", target_words=600
        )
        polished = MockClient(Config())
        ArticleGenerator(polished, resolve_style("science"), model="mock").generate(
            "主题Z", target_words=600, polish=True
        )
        self.assertGreater(len(polished.calls), len(plain.calls))


class ConfigTests(unittest.TestCase):
    def test_parse_env_file_handles_quotes_and_comments(self) -> None:
        from pathlib import Path

        from tests._helpers import temp_dir

        with temp_dir() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# comment\n"
                "\n"
                "P2A_API_KEY='sk-quoted'\n"
                'export P2A_MODEL="deepseek-reasoner"\n'
                "P2A_BASE_URL=https://example.test/v1\n"
                "BROKEN_LINE\n",
                encoding="utf-8",
            )
            values = parse_env_file(path)
            self.assertEqual(values["P2A_API_KEY"], "sk-quoted")
            self.assertEqual(values["P2A_MODEL"], "deepseek-reasoner")
            self.assertEqual(values["P2A_BASE_URL"], "https://example.test/v1")
            self.assertNotIn("BROKEN_LINE", values)

    def test_missing_env_file_is_empty(self) -> None:
        from pathlib import Path

        self.assertEqual(parse_env_file(Path("definitely/not/here.env")), {})

    def test_chat_endpoint_has_no_double_slash(self) -> None:
        self.assertEqual(
            Config(base_url="https://x.test/v1/").chat_endpoint,
            "https://x.test/v1/chat/completions",
        )

    def test_all_styles_resolve(self) -> None:
        for key in STYLES:
            self.assertEqual(resolve_style(key).key, key)
        self.assertEqual(resolve_style("nope").key, "science")
        self.assertEqual(resolve_style(None).key, "science")


if __name__ == "__main__":
    unittest.main()
