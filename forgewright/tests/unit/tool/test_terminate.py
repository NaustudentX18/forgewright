"""Tests for the TerminateTool."""

from __future__ import annotations

import pytest
from forgewright.schema import ToolResult
from forgewright.tool.terminate import TerminateTool


@pytest.mark.asyncio
async def test_terminates_with_reason() -> None:
    tool = TerminateTool()
    result = await tool(reason="all done")
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.output is not None
    assert "all done" in result.output
    assert "Terminated" in result.output


@pytest.mark.asyncio
async def test_terminates_increments_call_count() -> None:
    tool = TerminateTool()
    await tool(reason="first")
    await tool(reason="second")
    assert tool.call_count == 2


@pytest.mark.asyncio
async def test_terminates_rejects_missing_reason() -> None:
    tool = TerminateTool()
    result = await tool()
    assert result.is_error is True
    assert "Invalid args" in (result.error or "")
    assert "reason" in (result.error or "")


def test_terminate_metadata() -> None:
    tool = TerminateTool()
    assert tool.name == "terminate"
    assert tool.timeout_s == 5
    assert "required" in tool.args_schema
    assert "reason" in tool.args_schema["required"]


def test_terminate_openai_spec() -> None:
    tool = TerminateTool()
    spec = tool.to_openai_tool()
    assert spec["function"]["name"] == "terminate"
    assert "reason" in spec["function"]["parameters"]["properties"]


def test_terminate_anthropic_spec() -> None:
    tool = TerminateTool()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "terminate"
    assert "reason" in spec["input_schema"]["properties"]
