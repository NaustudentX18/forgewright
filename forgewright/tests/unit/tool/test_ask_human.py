"""Tests for the AskHumanTool (non-TTY mode only)."""

from __future__ import annotations

import pytest
from forgewright.tool.ask_human import AskHumanTool


@pytest.mark.asyncio
async def test_non_tty_returns_error() -> None:
    """In CI (stdin is a pipe), the tool must short-circuit rather than block."""
    tool = AskHumanTool()
    result = await tool(question="What now?")
    assert result.is_error is True
    assert (
        "non-interactive" in (result.error or "").lower() or "human" in (result.error or "").lower()
    )


@pytest.mark.asyncio
async def test_non_tty_accepts_optional_default() -> None:
    """The `default` arg is optional; the non-TTY branch is taken regardless."""
    tool = AskHumanTool()
    result = await tool(question="Pick one", default="A")
    assert result.is_error is True


def test_ask_human_metadata() -> None:
    tool = AskHumanTool()
    assert tool.name == "ask_human"
    assert tool.timeout_s == 300
    schema = tool.args_schema
    assert "question" in schema["required"]
    assert "default" in schema["properties"]


def test_ask_human_openai_spec() -> None:
    tool = AskHumanTool()
    spec = tool.to_openai_tool()
    assert spec["function"]["name"] == "ask_human"
    props = spec["function"]["parameters"]["properties"]
    assert "question" in props
    assert "default" in props


def test_ask_human_anthropic_spec() -> None:
    tool = AskHumanTool()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "ask_human"
    assert "question" in spec["input_schema"]["properties"]
