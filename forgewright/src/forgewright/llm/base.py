"""LLM Protocol — the contract every backend implements."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from forgewright.config import LLMConfig
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    TokenUsage,
    ToolSpec,
)


@runtime_checkable
class LLM(Protocol):
    """The interface every LLM backend must satisfy."""

    async def ask(
        self,
        messages: list[ChatMessage],
        **kw: Any,
    ) -> ChatMessage: ...

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        **kw: Any,
    ) -> AssistantTurn: ...

    def stream(
        self,
        messages: list[ChatMessage],
        **kw: Any,
    ) -> AsyncIterator[str]: ...

    def count_tokens(self, messages: list[ChatMessage]) -> int: ...

    def max_context_tokens(self) -> int: ...

    def supports_tool_calling(self) -> bool: ...

    def usage(self) -> TokenUsage: ...


class LLMBackend:
    """Base class for backend implementations.

    Subclasses (StubBackend, LiteLLMBackend) implement the LLM Protocol.
    `from_config` is the factory entry point used by the CLI and tests.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._usage = TokenUsage()

    @property
    def config(self) -> LLMConfig:
        return self._config

    def usage(self) -> TokenUsage:
        return self._usage

    def max_context_tokens(self) -> int:
        return 200_000

    def supports_tool_calling(self) -> bool:
        return False

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        from forgewright.llm.token_count import character_heuristic_token_count

        return character_heuristic_token_count(messages)

    @classmethod
    def from_config(cls, config: LLMConfig) -> LLMBackend:
        """Build the right backend for ``config.provider``.

        Real providers (Anthropic, OpenAI, Google, Azure, Bedrock, Ollama,
        OpenRouter) route to :class:`forgewright.llm.litellm_backend.LiteLLMBackend`.
        ``provider="stub"`` is reserved for tests and offline dev.
        """
        if config.provider == "stub":
            from forgewright.llm.stub import StubBackend

            return StubBackend(config)

        from forgewright.llm.litellm_backend import LiteLLMBackend

        return LiteLLMBackend(config)

    async def ask(self, messages: list[ChatMessage], **kw: Any) -> ChatMessage:
        raise NotImplementedError

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        **kw: Any,
    ) -> AssistantTurn:
        raise NotImplementedError

    def stream(
        self,
        messages: list[ChatMessage],
        **kw: Any,
    ) -> AsyncIterator[str]:
        raise NotImplementedError


__all__ = ["LLM", "LLMBackend"]
