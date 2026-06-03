"""Tests for :mod:`forgewright.cli.stream`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from forgewright.agent import Manus
from forgewright.cli.stream import stream_agent_run, stream_reply
from forgewright.config import LLMConfig
from forgewright.llm.stub import StubBackend
from forgewright.session import Session


async def _aiter(chunks: list[str]) -> AsyncIterator[str]:
    for ch in chunks:
        yield ch


async def test_stream_reply_consumes_iterator_and_returns_full_text() -> None:
    """``stream_reply`` returns the concatenated input text."""
    chunks = ["Hello", ", ", "world", "!"]
    result = await stream_reply(_aiter(chunks), live_window=2)
    assert result == "Hello, world!"


async def test_stream_reply_handles_empty_iterator() -> None:
    """An empty stream yields an empty string without raising."""
    result = await stream_reply(_aiter([]), live_window=2)
    assert result == ""


async def test_stream_reply_handles_multiline_input() -> None:
    """Multi-line text survives the live window partition intact."""
    text = "line 1\nline 2\nline 3\nline 4\nline 5"
    result = await stream_reply(_aiter(list(text)), live_window=6)
    # All input characters must be preserved in order.
    assert result == text


async def test_stream_agent_run_works_with_stub_backend() -> None:
    """``stream_agent_run`` runs a Manus agent on the stub and returns a result."""
    backend = StubBackend(LLMConfig(provider="stub", model="stub-model"))
    agent = Manus(llm=backend, max_steps=2)
    result = await stream_agent_run(agent, "hello there")
    assert result.state.value in ("finished", "error")
    # The stub always returns a non-empty content for a greeting.
    assert result.output
    assert "Hello" in result.output or "TASK_COMPLETE" in result.output


async def test_stream_agent_run_returns_agent_result_shape() -> None:
    """The returned value is an AgentResult with the documented fields."""
    backend = StubBackend(LLMConfig(provider="stub", model="stub-model"))
    agent = Manus(llm=backend, max_steps=1)
    result = await stream_agent_run(agent, "do a thing")
    assert hasattr(result, "output")
    assert hasattr(result, "step_count")
    assert hasattr(result, "state")
    assert hasattr(result, "messages")
    assert isinstance(result.step_count, int)
    assert result.step_count >= 0
    assert isinstance(result.messages, list)


async def test_stream_agent_run_appends_to_session() -> None:
    """The caller can append the output to a session after a run."""
    backend = StubBackend(LLMConfig(provider="stub", model="stub-model"))
    agent = Manus(llm=backend, max_steps=1)
    session: Any = Session.new()
    session.messages.append({"role": "user", "content": "hi"})
    result = await stream_agent_run(agent, "hi")
    session.messages.append({"role": "assistant", "content": result.output})
    assert len(session.messages) == 2
    assert session.messages[0]["role"] == "user"
    assert session.messages[1]["role"] == "assistant"
