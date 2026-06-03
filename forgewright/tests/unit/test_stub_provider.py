"""Tests for the stub LLM backend."""

from __future__ import annotations

import pytest
from forgewright.llm.stub import StubBackend
from forgewright.schema import ChatMessage, ToolSpec


@pytest.mark.asyncio
async def test_stub_responds_to_greeting() -> None:
    backend = StubBackend()
    response = await backend.ask([ChatMessage(role="user", content="hello there")])
    assert response.role == "assistant"
    assert "Hello" in response.content or "hello" in response.content.lower()


@pytest.mark.asyncio
async def test_stub_finishes_task() -> None:
    backend = StubBackend()
    response = await backend.ask([ChatMessage(role="user", content="refactor this code")])
    assert "TASK_COMPLETE" in response.content


@pytest.mark.asyncio
async def test_stub_ask_tool_returns_empty_tool_calls() -> None:
    backend = StubBackend()
    turn = await backend.ask_tool(
        [ChatMessage(role="user", content="hi")],
        tools=[ToolSpec(name="noop", description="x", args_schema={})],
    )
    assert turn.tool_calls == []
    assert "TASK_COMPLETE" in turn.content


@pytest.mark.asyncio
async def test_stub_stream_yields_words() -> None:
    backend = StubBackend()
    chunks: list[str] = []
    async for chunk in backend.stream([ChatMessage(role="user", content="hello")]):
        chunks.append(chunk)
    text = "".join(chunks)
    assert len(text) > 0


def test_stub_count_tokens_approximates() -> None:
    backend = StubBackend()
    n = backend.count_tokens([ChatMessage(role="user", content="a" * 400)])
    assert n == 100  # 400 / 4


def test_stub_supports_tool_calling() -> None:
    backend = StubBackend()
    assert backend.supports_tool_calling() is True


def test_stub_usage_increments() -> None:
    backend = StubBackend()
    initial = backend.usage().output_tokens
    import asyncio

    asyncio.run(backend.ask([ChatMessage(role="user", content="hi")]))
    assert backend.usage().output_tokens > initial
