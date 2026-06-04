"""Tests for the LiteLLM backend (BYOK path).

These tests do NOT hit the network. They verify:
- ``from_config`` dispatches real providers to ``LiteLLMBackend``
- The model string is built correctly per provider
- ``_convert_messages`` and ``_convert_tools`` produce OpenAI-shaped dicts
- ``_normalize_assistant`` parses litellm responses into ``AssistantTurn``
- Missing api_key is allowed (litellm falls back to env)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from forgewright.config import LLMConfig
from forgewright.llm import LiteLLMBackend, LLMBackend, StubBackend
from forgewright.schema import AssistantTurn, ChatMessage, ToolCall, ToolSpec


def _cfg(provider: str, model: str = "m", **kw: Any) -> LLMConfig:
    """Helper: build an LLMConfig ignoring the Literal provider for tests
    that parametrize over providers. Runtime validates the literal anyway."""
    return LLMConfig(provider=provider, model=model, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Factory dispatch
# --------------------------------------------------------------------------- #


class TestFromConfig:
    @pytest.mark.parametrize(
        "provider",
        ["openai", "anthropic", "google", "azure", "bedrock", "ollama", "openrouter"],
    )
    def test_real_provider_routes_to_litellm(self, provider: str) -> None:
        cfg = _cfg(provider, model="m")
        backend = LLMBackend.from_config(cfg)
        assert isinstance(backend, LiteLLMBackend), (
            f"{provider} should use LiteLLMBackend, got {type(backend).__name__}"
        )

    def test_stub_provider_routes_to_stub(self) -> None:
        cfg = _cfg("stub", model="stub-model")
        backend = LLMBackend.from_config(cfg)
        assert isinstance(backend, StubBackend)

    def test_no_silent_fallback_for_unknown_provider(self) -> None:
        """The old code silently fell back to StubBackend for any
        non-stub provider. That was the bug we're fixing. We expect
        a Literal-validation error from Pydantic now."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _cfg("not-a-real-provider", model="m")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Model string
# --------------------------------------------------------------------------- #


class TestModelString:
    @pytest.mark.parametrize(
        ("provider", "model", "expected"),
        [
            ("anthropic", "claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
            ("openai", "gpt-5", "openai/gpt-5"),
            # ollama MUST use the chat endpoint so tool calls work — see
            # the comment in ``PROVIDER_PREFIX`` for the rationale.
            ("ollama", "qwen3-14b-agent", "ollama_chat/qwen3-14b-agent"),
            ("openrouter", "meta/llama-3", "openrouter/meta/llama-3"),
            ("google", "gemini-2.5", "gemini/gemini-2.5"),
        ],
    )
    def test_prefix_added(self, provider: str, model: str, expected: str) -> None:
        cfg = _cfg(provider, model=model)
        b = LiteLLMBackend(cfg)
        assert b._model_string == expected


# --------------------------------------------------------------------------- #
# Conversion helpers
# --------------------------------------------------------------------------- #


class TestConvertMessages:
    def test_user_message(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        out = b._convert_messages([ChatMessage(role="user", content="hi")])
        assert out == [{"role": "user", "content": "hi"}]

    def test_system_message(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        out = b._convert_messages([ChatMessage(role="system", content="you are X")])
        assert out[0]["role"] == "system"

    def test_tool_message_keeps_id_and_name(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        out = b._convert_messages(
            [ChatMessage(role="tool", content="ok", tool_call_id="tc1", name="bash")]
        )
        assert out[0]["tool_call_id"] == "tc1"
        assert out[0]["name"] == "bash"


class TestConvertTools:
    def test_empty(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        assert b._convert_tools([]) == []

    def test_from_specs(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        specs = [
            ToolSpec(
                name="bash",
                description="run a shell command",
                args_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
            )
        ]
        out = b._convert_tools(specs)
        assert out == [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "run a shell command",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                },
            }
        ]

    def test_from_already_openai_dicts(self) -> None:
        """When the caller (ToolCallAgent) already passes OpenAI tools,
        we should pass them through unchanged."""
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "x",
                    "description": "y",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        assert b._convert_tools(openai_tools) == openai_tools


# --------------------------------------------------------------------------- #
# Response normalization (mocked litellm)
# --------------------------------------------------------------------------- #


def _mock_response(content: str, tool_calls: list[Any] | None = None) -> MagicMock:
    """Build a litellm.ModelResponse-shaped mock."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return response


def _mock_tool_call(tc_id: str, name: str, args_json: str) -> MagicMock:
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args_json
    return tc


class TestNormalizeAssistant:
    def test_text_only(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        turn = b._normalize_assistant(_mock_response("hello"))
        assert turn == AssistantTurn(content="hello", tool_calls=[])

    def test_with_tool_call(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        resp = _mock_response(
            "let me check",
            tool_calls=[_mock_tool_call("tc1", "bash", '{"cmd":"ls"}')],
        )
        turn = b._normalize_assistant(resp)
        assert turn.content == "let me check"
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0] == ToolCall(id="tc1", name="bash", args={"cmd": "ls"})

    def test_bumps_usage(self) -> None:
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        # Take a snapshot copy (TokenUsage is a Pydantic model — usage() returns
        # the same instance, so a reference snapshot would always match).
        before = b.usage().model_copy()
        b._normalize_assistant(_mock_response("hi"))
        after = b.usage().model_copy()
        assert after.input_tokens - before.input_tokens == 10
        assert after.output_tokens - before.output_tokens == 20

    def test_handles_bad_tool_args(self) -> None:
        """A malformed JSON string in tool args should not crash."""
        b = LiteLLMBackend(_cfg("anthropic", model="m"))
        resp = _mock_response(
            "x",
            tool_calls=[_mock_tool_call("tc1", "bash", "{not json")],
        )
        turn = b._normalize_assistant(resp)
        assert turn.tool_calls[0].args == {}


# --------------------------------------------------------------------------- #
# Per-call params
# --------------------------------------------------------------------------- #


class TestCompletionParams:
    def test_ollama_uses_api_base(self) -> None:
        cfg = _cfg(
            "ollama", model="qwen3-14b-agent", base_url="http://pc.local:11434"
        )
        b = LiteLLMBackend(cfg)
        params = b._completion_params()
        assert params["api_base"] == "http://pc.local:11434"
        assert params["model"] == "ollama_chat/qwen3-14b-agent"
        assert "base_url" not in params

    def test_anthropic_uses_base_url(self) -> None:
        cfg = _cfg(
            "anthropic", model="claude-sonnet-4-6", base_url="https://proxy.example"
        )
        b = LiteLLMBackend(cfg)
        params = b._completion_params()
        assert params["base_url"] == "https://proxy.example"
        assert "api_base" not in params

    def test_api_key_only_when_set(self) -> None:
        cfg = _cfg("anthropic", model="m")
        b = LiteLLMBackend(cfg)
        assert "api_key" not in b._completion_params()
        cfg2 = _cfg("anthropic", model="m", api_key="sk-xyz")
        b2 = LiteLLMBackend(cfg2)
        assert b2._completion_params()["api_key"] == "sk-xyz"


# --------------------------------------------------------------------------- #
# End-to-end against mocked litellm
# --------------------------------------------------------------------------- #


class TestAskToolEndToEnd:
    @pytest.mark.asyncio
    async def test_ask_tool_with_tools(self) -> None:
        cfg = _cfg("anthropic", model="m", api_key="sk-x")
        b = LiteLLMBackend(cfg)
        resp = _mock_response(
            "ok",
            tool_calls=[_mock_tool_call("tc1", "bash", '{"cmd":"ls"}')],
        )
        with patch("forgewright.llm.litellm_backend.litellm.acompletion", new=AsyncMock(return_value=resp)) as m:
            turn = await b.ask_tool(
                [ChatMessage(role="user", content="hi")],
                [
                    ToolSpec(
                        name="bash",
                        description="run cmd",
                        args_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
                    )
                ],
            )
        assert turn.tool_calls[0].name == "bash"
        # Confirm litellm got the OpenAI-shaped tool list.
        kwargs = m.call_args.kwargs
        assert kwargs["model"] == "anthropic/m"
        assert kwargs["tools"][0]["function"]["name"] == "bash"
        assert kwargs["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_ask_tool_no_tools_path(self) -> None:
        cfg = _cfg("anthropic", model="m")
        b = LiteLLMBackend(cfg)
        resp = _mock_response("hi")
        with patch("forgewright.llm.litellm_backend.litellm.acompletion", new=AsyncMock(return_value=resp)) as m:
            turn = await b.ask_tool([ChatMessage(role="user", content="hi")], [])
        assert turn.content == "hi"
        # No tools in the wire call.
        assert "tools" not in m.call_args.kwargs


# --------------------------------------------------------------------------- #
# Supports tool calling
# --------------------------------------------------------------------------- #


class TestSupportsToolCalling:
    @pytest.mark.parametrize(
        "provider",
        ["openai", "anthropic", "google", "azure", "bedrock", "ollama", "openrouter"],
    )
    def test_every_real_provider_supports_tools(self, provider: str) -> None:
        cfg = LLMConfig(provider=provider, model="m")  # type: ignore[arg-type]
        b = LiteLLMBackend(cfg)
        assert b.supports_tool_calling() is True
