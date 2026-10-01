"""prompt2article -- generate an article from a prompt.

Pipeline: title -> outline -> per-section writing -> optional polish,
against any OpenAI-compatible chat endpoint.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Article",
    "ArticleGenerator",
    "Config",
    "LLMError",
    "MockClient",
    "OpenAIChatClient",
    "Section",
    "Style",
    "STYLES",
    "load_config",
]

from .client import LLMError, MockClient, OpenAIChatClient
from .config import Config, load_config
from .generator import Article, ArticleGenerator, Section
from .prompts import STYLES, Style
