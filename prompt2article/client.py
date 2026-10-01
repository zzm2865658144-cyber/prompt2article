"""Chat clients.

`OpenAIChatClient` speaks the OpenAI-compatible `/chat/completions` shape over the
standard library, so the project has zero install requirements. `MockClient` is a
deterministic stand-in used by `--offline` and by the test suite.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .config import Config

Message = dict[str, str]


class LLMError(RuntimeError):
    """Any failure while obtaining a completion, with an actionable message."""


class ChatClient(Protocol):
    """The one method the generator depends on."""

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        ...


def _explain_http_error(status: int, body: str) -> str:
    """Turn a status code into something a user can act on."""
    detail = body.strip()
    if len(detail) > 400:
        detail = detail[:400] + "…"
    if status == 401:
        reason = "认证失败：API Key 无效或已过期"
    elif status == 402:
        reason = "余额不足：账户需要充值"
    elif status == 403:
        reason = "无权限：该 Key 不能访问这个模型"
    elif status == 404:
        reason = "接口或模型不存在：检查 --base-url 与 --model"
    elif status == 429:
        reason = "触发限流：请求太快或超出配额"
    elif 500 <= status < 600:
        reason = f"服务端错误（{status}）：稍后重试"
    else:
        reason = f"请求失败（{status}）"
    return f"{reason}\n  body: {detail}" if detail else reason


@dataclass
class OpenAIChatClient:
    """Minimal OpenAI-compatible chat client with bounded retries."""

    config: Config
    _opener: urllib.request.OpenerDirector = field(
        default_factory=urllib.request.build_opener, repr=False
    )

    RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.config.require_key()
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": list(messages),
            "temperature": self.config.temperature if temperature is None else temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.chat_endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.config.api_key.strip()}",
                "Accept": "application/json",
                "User-Agent": "prompt2article/0.1",
            },
        )

        attempt = 0
        while True:
            attempt += 1
            try:
                with self._opener.open(request, timeout=self.config.timeout) as response:
                    return self._parse(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
                if exc.code in self.RETRYABLE_STATUS and attempt <= self.config.max_retries:
                    self._sleep(attempt)
                    continue
                raise LLMError(_explain_http_error(exc.code, detail)) from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                if attempt <= self.config.max_retries:
                    self._sleep(attempt)
                    continue
                raise LLMError(
                    "网络请求失败：连不上 "
                    f"{self.config.chat_endpoint}\n"
                    f"  原因: {exc}\n"
                    "  排查: 检查网络/代理；如在国内且直连不通，可设置 HTTPS_PROXY 环境变量。"
                ) from exc

    @staticmethod
    def _parse(raw: str) -> str:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"响应不是合法 JSON：{raw[:200]}") from exc
        try:
            choices = data["choices"]
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"响应结构不符合预期：{json.dumps(data, ensure_ascii=False)[:300]}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("模型返回了空内容。")
        return content.strip()

    def _sleep(self, attempt: int) -> None:
        # 1s, 2s, 4s … capped so a long outage does not stall for minutes.
        time.sleep(min(2 ** (attempt - 1), 8))


@dataclass
class MockClient:
    """Deterministic offline client.

    It does not try to imitate a real writer: it returns a clearly-labelled
    placeholder that echoes the instruction, which is enough to exercise the
    whole pipeline (outline -> sections -> render) with no key and no network.
    """

    config: Config
    calls: list[list[Message]] = field(default_factory=list)

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append([dict(m) for m in messages])
        user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")

        if "只输出标题" in user:
            topic = self._topic(user)
            return f"【离线示例】{topic}"
        if "输出大纲" in user:
            topic = self._topic(user)
            return "\n".join(
                [
                    f"## 一、{topic}的背景",
                    f"## 二、{topic}的关键问题",
                    f"## 三、{topic}的实践路径",
                    f"## 四、结论与展望",
                ]
            )
        heading = self._heading(user)
        return (
            f"> 离线模式占位内容，用于验证流程。真实文章请配置 API Key 后去掉 `--offline`。\n\n"
            f"### {heading}\n\n"
            f"这里会展开「{heading}」这一节。当前指令摘要：\n\n"
            f"```\n{system.splitlines()[0] if system else '(no system prompt)'}\n```\n"
        )

    @staticmethod
    def _topic(text: str) -> str:
        for line in text.splitlines():
            if line.startswith("主题："):
                return line[len("主题："):].strip()
        return "示例主题"

    @staticmethod
    def _heading(text: str) -> str:
        for line in text.splitlines():
            if line.startswith("小节："):
                return line[len("小节："):].strip()
        return "示例小节"
