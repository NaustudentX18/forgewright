"""LLM abstraction: Protocol + stub + LiteLLM backend (BYOK)."""

from __future__ import annotations

from forgewright.llm.base import LLM, LLMBackend
from forgewright.llm.litellm_backend import LiteLLMBackend
from forgewright.llm.stub import StubBackend

__all__ = ["LLM", "LLMBackend", "LiteLLMBackend", "StubBackend"]
