"""LLM abstraction: Protocol + stub + LiteLLM backend (BYOK)."""

from __future__ import annotations

from forgewright.llm.base import LLM, LLMBackend
from forgewright.llm.litellm_backend import LiteLLMBackend
from forgewright.llm.stub import StubBackend
from forgewright.llm.token_count import (
    character_heuristic_token_count,
    count_for_provider,
)

__all__ = [
    "LLM",
    "LLMBackend",
    "LiteLLMBackend",
    "StubBackend",
    "character_heuristic_token_count",
    "count_for_provider",
]
