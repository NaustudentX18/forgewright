"""LiteLLM backend — provider-agnostic real LLM access (Anthropic, OpenAI,
Google, Azure, Bedrock, Ollama, OpenRouter).

This is the BYOK path. :class:`LLMBackend.from_config` dispatches here for
every non-stub provider so that ``provider="ollama"`` actually hits Ollama
instead of silently falling back to :class:`StubBackend`.

Wire format: OpenAI-style function calling. ``BaseTool.to_openai_tool()``
produces the spec; the OpenAI chat-completions API is the lingua franca
that ``litellm`` normalizes across providers. Anthropic, Google, Bedrock,
and the rest all accept (or can be coerced to accept) the same shape.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import litellm

from forgewright.config import LLMConfig
from forgewright.llm.base import LLMBackend
from forgewright.logger import logger
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    ToolCall,
    ToolSpec,
)

# Quieten litellm's own log lines — we already have loguru configured.
litellm.suppress_debug_info = True
litellm.drop_params = True  # silently drop params a provider doesn't accept


class LiteLLMBackend(LLMBackend):
    """Provider-agnostic backend. Handles every provider LiteLLM supports."""

    # Map our config.provider → litellm model prefix.
    # ``ollama_chat/`` (NOT ``ollama/``) is required for tool calls —
    # ``ollama/`` uses the legacy /api/generate endpoint which does not
    # support native function calling.
    PROVIDER_PREFIX: ClassVar[dict[str, str]] = {
        "openai": "openai/",
        "anthropic": "anthropic/",
        "google": "gemini/",
        "azure": "azure/",
        "bedrock": "bedrock/",
        "ollama": "ollama_chat/",
        "openrouter": "openrouter/",
    }

    # Per-provider context-window defaults when the model name doesn't
    # carry one (e.g. ``max_input_tokens``) and we don't have a more
    # specific lookup.
    DEFAULT_CONTEXT_TOKENS: ClassVar[dict[str, int]] = {
        "openai": 128_000,
        "anthropic": 200_000,
        "google": 1_000_000,
        "azure": 128_000,
        "bedrock": 200_000,
        "ollama": 32_000,
        "openrouter": 128_000,
    }

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._model_string = self._resolve_model_string(config)

    @classmethod
    def _resolve_model_string(cls, config: LLMConfig) -> str:
        """Build the litellm model string for this provider+model."""
        prefix = cls.PROVIDER_PREFIX.get(config.provider, "")
        if prefix:
            return f"{prefix}{config.model}"
        return config.model

    # --- per-call params ------------------------------------------------- #

    def _completion_params(self, stream: bool = False) -> dict[str, Any]:
        """Common kwargs for every litellm call."""
        params: dict[str, Any] = {
            "model": self._model_string,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": stream,
        }
        # API key: only set if provided (env fallback handled by litellm).
        if self._config.api_key:
            params["api_key"] = self._config.api_key
        # base_url: provider-specific. For Ollama, this is the host.
        if self._config.base_url:
            if self._config.provider == "ollama":
                params["api_base"] = self._config.base_url
            else:
                params["base_url"] = self._config.base_url
        return params

    def _convert_messages(
        self, messages: list[ChatMessage]
    ) -> list[dict[str, Any]]:
        """Forgewright ChatMessage → litellm messages dict.

        Forgewright stores assistant turns with tool_calls already merged
        onto the assistant message in a separate field; we re-inject them
        so litellm can round-trip them.
        """
        out: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "tool":
                entry["tool_call_id"] = m.tool_call_id
                if m.name:
                    entry["name"] = m.name
            out.append(entry)
        return out

    def _convert_tools(self, tools: list[ToolSpec] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Forgewright ToolSpec (or already-rendered OpenAI dict) → OpenAI tools list.

        ``ToolCallAgent._tool_specs()`` passes ``self.tools.to_openai_tools()``,
        which is already the right shape. We accept both for flexibility.
        """
        if not tools:
            return []
        # If the caller already passed OpenAI-shaped dicts, use them as-is.
        if isinstance(tools[0], dict):
            return list(tools)  # type: ignore[list-item]
        # Otherwise each entry is a ToolSpec (Pydantic model with .name etc.).
        specs = [t for t in tools if isinstance(t, ToolSpec)]  # type: ignore[union-attr]
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.args_schema
                    or {"type": "object", "properties": {}},
                },
            }
            for spec in specs
        ]

    def _normalize_assistant(self, response: Any) -> AssistantTurn:
        """litellm ModelResponse → forgewright AssistantTurn."""
        try:
            choice = response.choices[0]
            msg = choice.message
        except (IndexError, AttributeError) as exc:
            logger.error("litellm.malformed_response resp={}", response)
            raise RuntimeError(f"malformed litellm response: {exc}") from exc

        content = msg.content or ""
        # litellm returns tool_calls as a list of objects with .id, .function.name,
        # and .function.arguments (a JSON string).
        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            args_raw = tc.function.arguments or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
            except json.JSONDecodeError:
                logger.warning("litellm.bad_tool_args raw={}", args_raw)
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.id or "",
                    name=getattr(tc.function, "name", "") or "",
                    args=args,
                )
            )

        # Bump usage.
        if getattr(response, "usage", None):
            u = response.usage
            self._usage.input_tokens += int(getattr(u, "prompt_tokens", 0) or 0)
            self._usage.output_tokens += int(getattr(u, "completion_tokens", 0) or 0)

        return AssistantTurn(content=content, tool_calls=tool_calls)

    # --- LLM protocol methods -------------------------------------------- #

    async def ask(
        self,
        messages: list[ChatMessage],
        **kw: Any,  # noqa: ARG002 - reserved for future per-call overrides
    ) -> ChatMessage:
        """Plain completion, no tools. Returns just the assistant content."""
        params = self._completion_params(stream=False)
        params["messages"] = self._convert_messages(messages)
        response = await litellm.acompletion(**params)
        self._normalize_assistant(response)  # bumps usage
        return ChatMessage(role="assistant", content=response.choices[0].message.content or "")

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | list[dict[str, Any]],
        **kw: Any,  # noqa: ARG002 - reserved for future per-call overrides
    ) -> AssistantTurn:
        """Function-calling completion. The core Manus-style path."""
        params = self._completion_params(stream=False)
        params["messages"] = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            params["tools"] = converted_tools
        response = await litellm.acompletion(**params)
        return self._normalize_assistant(response)

    async def stream(
        self,
        messages: list[ChatMessage],
        **kw: Any,  # noqa: ARG002 - reserved for future per-call overrides
    ) -> AsyncIterator[str]:
        """Async token stream. Yields plain strings (no events)."""
        params = self._completion_params(stream=True)
        params["messages"] = self._convert_messages(messages)
        response = await litellm.acompletion(**params)
        async for chunk in response:
            try:
                delta = chunk.choices[0].delta
            except (IndexError, AttributeError):
                continue
            piece = getattr(delta, "content", None)
            if piece:
                yield piece

    def max_context_tokens(self) -> int:
        """Per-provider default. LiteLLM also exposes per-model lookups
        via ``litellm.get_max_tokens(model)``; we keep it simple for now."""
        return self.DEFAULT_CONTEXT_TOKENS.get(self._config.provider, 128_000)

    def supports_tool_calling(self) -> bool:
        """Every provider we route through LiteLLM supports tool calls.
        Individual models on Ollama / OpenRouter may not — we trust the
        user to pick a model that does."""
        return self._config.provider != "stub"


__all__ = ["LiteLLMBackend"]
