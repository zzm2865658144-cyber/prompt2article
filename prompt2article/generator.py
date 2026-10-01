"""The generation pipeline: prompt -> title + outline + sections -> Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

from . import prompts
from .client import ChatClient, Message
from .prompts import Style

ProgressFn = Callable[[str], None]

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s{0,3}[-*+]\s+(.+?)\s*$")
_NUMBER_RE = re.compile(r"^\s{0,3}\d{1,2}\s*[.、)]\s*(.+?)\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


@dataclass
class Section:
    """One `##` block: its heading and the generated body."""

    heading: str
    body: str = ""

    @property
    def word_count(self) -> int:
        return count_words(self.body)


@dataclass
class Article:
    """A finished article plus the metadata needed to reproduce it."""

    title: str
    prompt: str
    style: str
    language: str
    audience: str | None
    sections: list[Section] = field(default_factory=list)
    model: str = ""
    target_words: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def word_count(self) -> int:
        return sum(s.word_count for s in self.sections)

    def to_markdown(self, *, front_matter: bool = True) -> str:
        chunks: list[str] = []
        if front_matter:
            stamp = self.generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            meta = [
                "---",
                f'title: "{_escape_yaml(self.title)}"',
                f'prompt: "{_escape_yaml(self.prompt)}"',
                f"style: {self.style}",
                f"language: {self.language}",
            ]
            if self.audience:
                meta.append(f'audience: "{_escape_yaml(self.audience)}"')
            if self.model:
                meta.append(f"model: {self.model}")
            meta.append(f"generated_at: {stamp}")
            meta.append(f"word_count: {self.word_count}")
            meta.append("---")
            chunks.append("\n".join(meta))
        chunks.append(f"# {self.title}")
        for section in self.sections:
            chunks.append(f"## {section.heading}\n\n{section.body.strip()}")
        return "\n\n".join(chunks).rstrip() + "\n"


def _escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def count_words(text: str) -> int:
    """Count CJK characters individually plus whitespace-separated latin words.

    `len(text.split())` is useless for Chinese, and `len(text)` overcounts English.
    This hybrid is the number a Chinese writer would recognise.
    """
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]", text))
    latin = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", text))
    return cjk + latin


def parse_outline(text: str, fallback: str) -> list[str]:
    """Extract section headings from a model response.

    Accepts markdown headings, bullets and numbered lists -- models drift between
    the three even when told to use `##`. Returns `[fallback]` when nothing usable
    comes back, so the pipeline still produces a single-section article.
    """
    headings: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        match = _HEADING_RE.match(line) or _BULLET_RE.match(line) or _NUMBER_RE.match(line)
        if not match:
            continue
        heading = _BOLD_RE.sub(r"\1", match.group(1)).strip()
        heading = heading.strip("#").strip()
        # A one-word or numeric-only "heading" is noise, not a section.
        if not heading or count_words(heading) == 0:
            continue
        if all(ch in "0123456789.、)（( " for ch in heading):
            continue
        if heading not in headings:
            headings.append(heading)
    return headings or [fallback]


def split_budget(total: int, parts: int) -> list[int]:
    """Split a word budget as evenly as possible, with a sane floor."""
    if parts <= 0:
        return []
    floor = max(120, total // (parts * 2)) if total else 120
    base = max(floor, total // parts) if total else floor
    budget = [base] * parts
    # Give any rounding remainder to the last section, which carries the conclusion.
    budget[-1] = max(floor, total - base * (parts - 1)) if total else floor
    return budget


class ArticleGenerator:
    """Drive a :class:`ChatClient` through the article pipeline."""

    def __init__(self, client: ChatClient, style: Style, *, model: str = "") -> None:
        self.client = client
        self.style = style
        self.model = model

    def generate(
        self,
        prompt: str,
        *,
        target_words: int | None = None,
        language: str = "zh",
        audience: str | None = None,
        title: str | None = None,
        max_sections: int = 8,
        polish: bool = False,
        progress: ProgressFn | None = None,
    ) -> Article:
        notify = progress or (lambda _msg: None)
        words = target_words or self.style.default_words

        article = Article(
            title=title or "",
            prompt=prompt,
            style=self.style.key,
            language=language,
            audience=audience,
            model=self.model,
            target_words=words,
        )

        if not article.title:
            notify("拟定标题…")
            article.title = self._one_line(
                prompts.title_messages(prompt, self.style, language)
            ) or prompt[:40]

        notify("生成大纲…")
        outline_text = self.client.chat(
            prompts.outline_messages(prompt, self.style, language, audience, words)
        )
        headings = parse_outline(outline_text, fallback=article.title)
        if len(headings) > max_sections:
            headings = headings[:max_sections]
        notify(f"大纲 {len(headings)} 节：{' / '.join(headings)}")

        budgets = split_budget(words, len(headings))
        sections: list[Section] = []
        for index, (heading, budget) in enumerate(zip(headings, budgets)):
            notify(f"写作 {index + 1}/{len(headings)}：{heading}（约 {budget} 字）")
            body = self.client.chat(
                prompts.section_messages(
                    prompt, heading, self.style, language, audience, budget, headings, index
                )
            )
            sections.append(Section(heading=heading, body=_strip_duplicate_heading(body, heading)))
        article.sections = sections

        if polish:
            notify("润色全文…")
            # Polish by section: sending the whole article risks output truncation
            # and a single dropped section losing the rest of the piece.
            for index, section in enumerate(article.sections):
                notify(f"润色 {index + 1}/{len(article.sections)}…")
                polished = self.client.chat(
                    prompts.polish_messages(section.body, self.style, language)
                )
                section.body = _strip_duplicate_heading(polished, section.heading)

        notify(f"完成：{article.word_count} 字 / 目标 {words} 字")
        return article

    def _one_line(self, messages: Sequence[Message]) -> str:
        text = self.client.chat(messages).strip()
        # Models like to wrap titles in quotes or prefix them; take the first line.
        first = text.splitlines()[0] if text else ""
        return _BOLD_RE.sub(r"\1", first).strip().strip("\"'“”「」《》# ").strip()


def _strip_duplicate_heading(body: str, heading: str) -> str:
    """Drop a leading heading the model echoed back, so it is not printed twice."""
    text = body.strip()
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        candidate = lines[0].strip().lstrip("#").strip()
        if candidate and candidate == heading.strip():
            lines.pop(0)
    return "\n".join(lines).strip()
