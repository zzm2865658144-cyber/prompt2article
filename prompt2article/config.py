"""Runtime configuration, resolved from the environment and an optional .env file.

No third-party dependency: a `.env` file is a convenience, never a requirement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 3

#: Checked in order; the first non-empty one wins.
API_KEY_VARS = ("P2A_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")


class ConfigError(RuntimeError):
    """Raised when the configuration cannot produce a usable client."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal `KEY=VALUE` file.

    Supports `#` comments, blank lines, optional `export `, and single or double
    quoted values. Deliberately not a full dotenv implementation -- it exists so
    a user can drop a key in a file instead of exporting it every shell.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class Config:
    """Everything needed to talk to an OpenAI-compatible endpoint."""

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    temperature: float = 0.7
    env_file: Path | None = None

    @property
    def chat_endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    @property
    def has_key(self) -> bool:
        return bool(self.api_key.strip())

    def require_key(self) -> None:
        if not self.has_key:
            vars_hint = " / ".join(API_KEY_VARS)
            raise ConfigError(
                "找不到 API Key。三种办法任选其一：\n"
                f"  1) 设置环境变量：{vars_hint}\n"
                "  2) 在本目录复制 .env.example 为 .env，填入 P2A_API_KEY=...\n"
                "  3) 用 --api-key 显式传入（注意会留在命令历史里）\n"
                "只想先看流程可以加 --offline，用内置的模拟模型跑通。"
            )

    def with_overrides(self, **kwargs: object) -> "Config":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean)  # type: ignore[arg-type]


def load_config(
    env_file: Path | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
    temperature: float | None = None,
) -> Config:
    """Build a :class:`Config` from explicit arguments, the environment, then `.env`.

    Precedence, highest first: explicit argument, real environment, `.env` file,
    built-in default. A real environment variable therefore always beats a stale
    `.env`, which is the behaviour people expect when they export a key to test.
    """
    path = Path(env_file) if env_file is not None else Path.cwd() / ".env"
    file_values = parse_env_file(path)

    def pick(name: str, default: str) -> str:
        return os.environ.get(name) or file_values.get(name) or default

    key = api_key
    if not key:
        for name in API_KEY_VARS:
            found = os.environ.get(name) or file_values.get(name)
            if found:
                key = found
                break

    raw_timeout = pick("P2A_TIMEOUT", str(DEFAULT_TIMEOUT))
    raw_retries = pick("P2A_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
    raw_temp = pick("P2A_TEMPERATURE", "0.7")
    try:
        timeout_value = float(timeout) if timeout is not None else float(raw_timeout)
    except ValueError:
        timeout_value = DEFAULT_TIMEOUT
    try:
        retries = int(float(raw_retries))
    except ValueError:
        retries = DEFAULT_MAX_RETRIES
    try:
        temp = float(temperature) if temperature is not None else float(raw_temp)
    except ValueError:
        temp = 0.7

    return Config(
        api_key=(key or "").strip(),
        base_url=(base_url or pick("P2A_BASE_URL", DEFAULT_BASE_URL)).strip(),
        model=(model or pick("P2A_MODEL", DEFAULT_MODEL)).strip(),
        timeout=timeout_value,
        max_retries=max(0, retries),
        temperature=temp,
        env_file=path if path.exists() else None,
    )
