"""Deterministic stub LLM backend — no network, no credentials."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

from forgewright.config import LLMConfig
from forgewright.llm.base import LLMBackend
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    ToolSpec,
)


class StubBackend(LLMBackend):
    """A scripted LLM that responds deterministically.

    Useful for:
    - End-to-end smoke tests (no API key required).
    - Demos and screenshots.
    - CI without a real provider.

    The script is a list of (predicate, response) pairs. The first predicate
    that matches the last user message wins. The default script is a small
    friendly dialogue that ends in TASK_COMPLETE so the agent loop terminates.
    """

    DEFAULT_SCRIPT: ClassVar[list[tuple[str, str]]] = [
        (r"^(hi|hello|hey)\b", "Hello. I'm the forgewright stub provider. TASK_COMPLETE"),
        (r"TASK_COMPLETE", "TASK_COMPLETE"),
        (
            r".*",
            "I can help with that. Let me think about it... TASK_COMPLETE",
        ),
    ]

    def __init__(self, config: LLMConfig | None = None) -> None:
        super().__init__(config or LLMConfig(provider="stub"))
        self._call_count = 0
        self._import_re()

    def _import_re(self) -> None:
        import re

        self._compiled = [
            (re.compile(pattern, re.IGNORECASE), response)
            for pattern, response in self.DEFAULT_SCRIPT
        ]

    def supports_tool_calling(self) -> bool:
        return True

    async def ask(self, messages: list[ChatMessage], **kw: Any) -> ChatMessage:
        self._call_count += 1
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        content = self._match(last_user)
        self._bump_usage(content)
        return ChatMessage(role="assistant", content=content)

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        **kw: Any,
    ) -> AssistantTurn:
        # The stub never invokes a tool on its own.
        return AssistantTurn(content="I have no tools to call. TASK_COMPLETE", tool_calls=[])

    async def stream(
        self,
        messages: list[ChatMessage],
        **kw: Any,
    ) -> AsyncIterator[str]:
        response = await self.ask(messages, **kw)
        for word in response.content.split():
            yield word + " "

    def _match(self, user_text: str) -> str:
        for pattern, response in self._compiled:
            if pattern.search(user_text):
                return response
        return "TASK_COMPLETE"

    def _bump_usage(self, content: str) -> None:
        # Approximate: 1 token per 4 chars.
        self._usage.input_tokens += 50
        self._usage.output_tokens += max(1, len(content) // 4)


__all__ = ["StubBackend"]
