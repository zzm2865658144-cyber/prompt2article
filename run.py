"""IDE entry point (PyCharm / VS Code).

**Right-click this file and choose Run** -- no run configuration needed.

Two things this file does that the package alone cannot:

1. With no arguments it starts the interactive prompts, so the Run console asks
   for a topic instead of exiting with a usage error. Running
   ``prompt2article/__main__.py`` directly does not work: a single file has no
   package context, so its ``from .cli import main`` fails with
   "attempted relative import with no known parent package".

2. It pins the working directory to this file's folder before importing
   anything, so ``.env`` is found and generated articles land in
   ``<project>/output/`` regardless of what the IDE's "Working directory" field
   says.

To pass real arguments instead, fill in the Run Configuration's
"Parameters" field, e.g. ``"量子计算的现状" --style tech --words 2000``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

API_KEY_VARS = ("P2A_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")


def _configured() -> bool:
    """True when a key could plausibly be found, so real generation may work."""
    if (PROJECT_ROOT / ".env").exists():
        return True
    return any(os.environ.get(name) for name in API_KEY_VARS)


def main() -> int:
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from prompt2article.cli import main as cli_main

    argv = sys.argv[1:] or ["--interactive"]

    # Mirror 生成文章.bat: with nothing configured, still produce something
    # rather than walking the user through the prompts and failing at the end.
    explicit = any(a == "--offline" or a.startswith("--api-key") for a in argv)
    if not explicit and not _configured():
        print(
            "[!] 没有找到 .env，也没有 API Key —— 本次以离线模拟模式运行（内容是占位文字）。",
            file=sys.stderr,
        )
        print(
            "    要生成真实文章：把 .env.example 复制为 .env，填入 P2A_API_KEY。",
            file=sys.stderr,
        )
        argv = [*argv, "--offline"]

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
