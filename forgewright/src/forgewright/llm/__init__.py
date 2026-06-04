"""LLM abstraction: Protocol + stub + LiteLLM backend (BYOK)."""

from __future__ import annotations

from typing import Any

from forgewright.llm.base import LLM, LLMBackend
from forgewright.llm.metered import MeteredLLM
from forgewright.llm.stub import StubBackend
from forgewright.llm.token_count import (
    character_heuristic_token_count,
    count_for_provider,
)

__all__ = [
    "LLM",
    "LLMBackend",
    "LiteLLMBackend",
    "MeteredLLM",
    "StubBackend",
    "character_heuristic_token_count",
    "count_for_provider",
]


def __getattr__(name: str) -> Any:
    """Lazily import the BYOK backend to keep stub/CLI startup offline."""
    if name == "LiteLLMBackend":
        from forgewright.llm.litellm_backend import LiteLLMBackend

        return LiteLLMBackend
    raise AttributeError(name)
