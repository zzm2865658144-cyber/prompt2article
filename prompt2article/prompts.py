"""Prompt construction: article styles and the message builders for each stage.

The pipeline is deliberately multi-stage (title -> outline -> sections -> optional
polish) rather than one big request. Long articles written in a single call drift,
repeat themselves and lose the thread; asking for an outline first and then one
section at a time keeps length and coherence under control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .client import Message


@dataclass(frozen=True)
class Style:
    """A named writing style."""

    key: str
    name: str
    summary: str
    tone: str
    default_words: int = 1200


STYLES: dict[str, Style] = {
    "science": Style(
        key="science",
        name="科普",
        summary="准确、易懂，面向非专业读者，善用类比",
        tone=(
            "你是一位优秀的科普作者。要求：概念准确、术语首次出现时用一句话解释、"
            "多用具体类比和生活化例子、避免堆砌名词、每段只讲一件事。"
        ),
    ),
    "opinion": Style(
        key="opinion",
        name="评论",
        summary="观点鲜明，有论证和反驳，不骑墙",
        tone=(
            "你是一位犀利的评论作者。要求：开头就亮出核心判断、每个论点都要有事实或"
            "逻辑支撑、主动回应最强的反对意见、结论明确不模棱两可。"
        ),
    ),
    "tutorial": Style(
        key="tutorial",
        name="教程",
        summary="步骤清晰，可复现，包含前置条件与排错",
        tone=(
            "你是一位耐心的技术教程作者。要求：先写清前置条件和目标、步骤可照做、"
            "给出具体命令或代码、指出常见错误及排查方法、不要跳步。"
        ),
    ),
    "essay": Style(
        key="essay",
        name="叙事散文",
        summary="有场景和细节，节奏舒缓，重感受",
        tone=(
            "你是一位散文作者。要求：用具体场景和细节推进、句子长短交错、"
            "少用抽象概括、克制抒情、让读者自己得出结论。"
        ),
    ),
    "academic": Style(
        key="academic",
        name="学术",
        summary="结构规范，措辞克制，区分事实与推测",
        tone=(
            "你是一位严谨的研究者。要求：措辞克制、区分已证实与推测、"
            "指出方法的局限、避免绝对化表述、不使用营销腔。"
        ),
    ),
    "wechat": Style(
        key="wechat",
        name="公众号",
        summary="开头抓人，短段落，金句收尾",
        tone=(
            "你是一位公众号主编。要求：开头三行内抓住读者、段落短（不超过 4 行）、"
            "小标题有信息量、结尾给一句能被引用的话、不要标题党到失真。"
        ),
    ),
    "tech": Style(
        key="tech",
        name="技术博客",
        summary="面向同行，重原理、权衡与坑",
        tone=(
            "你是一位资深工程师写博客。要求：直接讲问题与方案、说明取舍和代价、"
            "给出可验证的细节、主动指出自己方案的不足、不写空泛的行业展望。"
        ),
    ),
    "speech": Style(
        key="speech",
        name="演讲稿",
        summary="口语化，有呼告和节奏，适合朗读",
        tone=(
            "你是一位演讲稿撰写者。要求：句子适合朗读、有停顿和重复带来的节奏、"
            "多用「我们」、避免书面长句、结尾有明确的行动号召。"
        ),
    ),
}

DEFAULT_STYLE = "science"

LANGUAGE_NAMES = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
}


def resolve_style(key: str | None) -> Style:
    if not key:
        return STYLES[DEFAULT_STYLE]
    return STYLES.get(key, STYLES[DEFAULT_STYLE])


def style_table() -> str:
    """Human-readable list, used by `--list-styles` and the README."""
    lines = []
    for style in STYLES.values():
        lines.append(f"  {style.key:<10} {style.name:<6} {style.summary}")
    return "\n".join(lines)


def system_prompt(style: Style, language: str, audience: str | None) -> str:
    parts = [
        style.tone,
        f"全文使用{LANGUAGE_NAMES.get(language, language)}写作。",
        "只输出正文内容本身，不要写任何关于「接下来我会……」的元话语，也不要复述指令。",
    ]
    if audience:
        parts.append(f"目标读者：{audience}。用词和例子都要贴合这批读者。")
    parts.append("使用 Markdown 排版：小标题用 ## / ###，列表和代码块按需使用。")
    return "\n".join(parts)


def title_messages(prompt: str, style: Style, language: str) -> list[Message]:
    return [
        {"role": "system", "content": system_prompt(style, language, None)},
        {
            "role": "user",
            "content": (
                "请为下面这篇文章拟一个标题。\n"
                "只输出标题本身，不要引号、不要序号、不要解释。\n\n"
                f"主题：{prompt}"
            ),
        },
    ]


def outline_messages(
    prompt: str, style: Style, language: str, audience: str | None, target_words: int
) -> list[Message]:
    return [
        {"role": "system", "content": system_prompt(style, language, audience)},
        {
            "role": "user",
            "content": (
                "请先输出大纲，不要写正文。\n"
                f"目标总字数约 {target_words} 字，请据此决定小节数量和每节深浅。\n"
                "格式要求：每行一个小节，以 `## ` 开头，标题要有信息量（不要「第一部分」这种空标题）。\n"
                "只输出大纲本身，不要任何前言后语。\n\n"
                f"主题：{prompt}"
            ),
        },
    ]


def section_messages(
    prompt: str,
    heading: str,
    style: Style,
    language: str,
    audience: str | None,
    section_words: int,
    outline: Sequence[str],
    index: int,
) -> list[Message]:
    context = "\n".join(f"- {h}" for h in outline)
    return [
        {"role": "system", "content": system_prompt(style, language, audience)},
        {
            "role": "user",
            "content": (
                f"全文大纲如下：\n{context}\n\n"
                f"现在只写第 {index + 1} 节。\n"
                f"小节：{heading}\n"
                f"篇幅约 {section_words} 字。\n"
                "要求：直接开始写这一节的内容，不要重复输出小节标题，不要写其它小节，"
                "也不要写全文总结（除非这一节本身就是结论）。\n"
                "前后小节由别人写，所以不要写「如上所述」「下一节我们将」这类衔接语。\n\n"
                f"全文主题：{prompt}"
            ),
        },
    ]


def polish_messages(body: str, style: Style, language: str) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                f"你是一位资深编辑，负责润色一篇{style.name}文章。"
                "只做这些事：删冗余、修病句、统一术语、让段落过渡自然、修正 Markdown 格式。"
                "不要新增观点，不要改变结构，不要改变小标题，不要把篇幅改短很多。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请润色下面这篇文章，直接输出润色后的完整 Markdown 全文"
                f"（使用{LANGUAGE_NAMES.get(language, language)}）：\n\n{body}"
            ),
        },
    ]
