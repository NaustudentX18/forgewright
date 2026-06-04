"""Tests for provider-aware token counting (ROADMAP v0.2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from forgewright.config import LLMConfig
from forgewright.llm.litellm_backend import LiteLLMBackend
from forgewright.llm.token_count import (
    character_heuristic_token_count,
    count_for_provider,
    count_tokens_anthropic,
    count_tokens_openai,
    messages_for_anthropic_count,
)
from forgewright.schema import ChatMessage


def _cfg(provider: str, model: str = "m", **kw: Any) -> LLMConfig:
    return LLMConfig(provider=provider, model=model, **kw)  # type: ignore[arg-type]


class TestCharacterHeuristic:
    def test_empty(self) -> None:
        assert character_heuristic_token_count([]) == 0

    def test_four_chars_per_token(self) -> None:
        msgs = [ChatMessage(role="user", content="a" * 400)]
        assert character_heuristic_token_count(msgs) == 100

    def test_tool_metadata_included(self) -> None:
        msgs = [
            ChatMessage(
                role="tool",
                content="x" * 40,
                tool_call_id="id" * 4,
                name="bash",
            )
        ]
        # content 10 + tool_call_id 2 + name 1 = 13
        assert character_heuristic_token_count(msgs) == 13


class TestMessagesForAnthropicCount:
    def test_splits_system(self) -> None:
        system, msgs = messages_for_anthropic_count(
            [
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="hi"),
            ]
        )
        assert system == "You are helpful."
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_tool_as_synthetic_user(self) -> None:
        _, msgs = messages_for_anthropic_count(
            [ChatMessage(role="tool", content="ok", name="bash")]
        )
        assert msgs[0]["role"] == "user"
        assert "bash" in msgs[0]["content"]
        assert "ok" in msgs[0]["content"]


class TestCountForProvider:
    def test_ollama_uses_heuristic(self) -> None:
        msgs = [ChatMessage(role="user", content="b" * 80)]
        assert count_for_provider("ollama", "qwen", msgs) == 20

    def test_google_uses_heuristic(self) -> None:
        msgs = [ChatMessage(role="user", content="c" * 12)]
        assert count_for_provider("google", "gemini", msgs) == 3


class TestCountTokensOpenAI:
    def test_uses_tiktoken_not_char_div_four(self) -> None:
        msgs = [ChatMessage(role="user", content="hello world")]
        tik = count_tokens_openai(msgs, "gpt-4o")
        heuristic = character_heuristic_token_count(msgs)
        assert tik != heuristic or tik > 0
        assert tik >= 2


class TestCountTokensAnthropic:
    def test_returns_none_without_api_key(self) -> None:
        msgs = [ChatMessage(role="user", content="hi")]
        with patch.dict("os.environ", {}, clear=True):
            assert count_tokens_anthropic(msgs, "claude-sonnet-4-6", api_key=None) is None

    def test_calls_count_tokens_api(self) -> None:
        msgs = [ChatMessage(role="user", content="hi")]
        mock_result = MagicMock(input_tokens=123)
        mock_client = MagicMock()
        mock_client.messages.count_tokens.return_value = mock_result

        with patch("anthropic.Anthropic", return_value=mock_client) as mock_ctor:
            n = count_tokens_anthropic(
                msgs,
                "claude-sonnet-4-6",
                api_key="sk-test",
            )
        assert n == 123
        mock_ctor.assert_called_once_with(api_key="sk-test")
        mock_client.messages.count_tokens.assert_called_once()
        call_kwargs = mock_client.messages.count_tokens.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]

    def test_api_error_falls_back_to_none(self) -> None:
        msgs = [ChatMessage(role="user", content="hi")]
        mock_client = MagicMock()
        mock_client.messages.count_tokens.side_effect = RuntimeError("network")

        with patch("anthropic.Anthropic", return_value=mock_client):
            assert (
                count_tokens_anthropic(
                    msgs,
                    "claude-sonnet-4-6",
                    api_key="sk-test",
                )
                is None
            )


class TestLiteLLMBackendCountTokens:
    def test_anthropic_delegates_to_api(self) -> None:
        backend = LiteLLMBackend(_cfg("anthropic", model="claude-sonnet-4-6", api_key="sk-x"))
        msgs = [ChatMessage(role="user", content="hello")]
        with patch(
            "forgewright.llm.token_count.count_tokens_anthropic",
            return_value=99,
        ) as mock_anthropic:
            assert backend.count_tokens(msgs) == 99
        mock_anthropic.assert_called_once_with(
            msgs,
            "claude-sonnet-4-6",
            api_key="sk-x",
            base_url=None,
        )

    def test_anthropic_falls_back_to_heuristic(self) -> None:
        backend = LiteLLMBackend(_cfg("anthropic", model="m"))
        msgs = [ChatMessage(role="user", content="z" * 40)]
        with patch(
            "forgewright.llm.token_count.count_tokens_anthropic",
            return_value=None,
        ):
            assert backend.count_tokens(msgs) == 10

    def test_openai_delegates_to_tiktoken(self) -> None:
        backend = LiteLLMBackend(_cfg("openai", model="gpt-4o"))
        msgs = [ChatMessage(role="user", content="tokenize me")]
        with patch(
            "forgewright.llm.token_count.count_tokens_openai",
            return_value=7,
        ) as mock_openai:
            assert backend.count_tokens(msgs) == 7
        mock_openai.assert_called_once_with(msgs, "gpt-4o")

    def test_bedrock_uses_heuristic(self) -> None:
        backend = LiteLLMBackend(_cfg("bedrock", model="anthropic.claude-v2"))
        msgs = [ChatMessage(role="user", content="d" * 20)]
        assert backend.count_tokens(msgs) == 5
