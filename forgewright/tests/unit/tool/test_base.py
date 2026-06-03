"""Tests for the BaseTool ABC."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool


class _Echo(BaseTool):
    """Minimal concrete tool: echoes the `text` argument back."""

    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echo a string back."
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def _run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(output=kwargs.get("text", ""))


class _Boom(BaseTool):
    """A tool that always raises."""

    name: ClassVar[str] = "boom"
    description: ClassVar[str] = "Always raises."
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    async def _run(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("kaboom")


class _Slow(BaseTool):
    """A tool that sleeps past its timeout."""

    name: ClassVar[str] = "slow"
    description: ClassVar[str] = "Sleeps past its timeout."
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }
    timeout_s: ClassVar[int] = 1

    async def _run(self, **kwargs: Any) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(output="done")


class _Add(BaseTool):
    """Schema with additionalProperties=false to test strict validation."""

    name: ClassVar[str] = "add"
    description: ClassVar[str] = "Add two numbers."
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }

    async def _run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(output=str(kwargs["a"] + kwargs["b"]))


@pytest.mark.asyncio
async def test_call_returns_tool_result() -> None:
    tool = _Echo()
    result = await tool(text="hi")
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.output == "hi"
    assert result.error is None


@pytest.mark.asyncio
async def test_call_counts_invocations() -> None:
    tool = _Echo()
    assert tool.call_count == 0
    await tool(text="a")
    await tool(text="b")
    await tool(text="c")
    assert tool.call_count == 3


@pytest.mark.asyncio
async def test_schema_validation_rejects_missing_required() -> None:
    tool = _Echo()
    result = await tool()  # missing 'text'
    assert result.is_error is True
    assert "Invalid args" in (result.error or "")
    assert "echo" in (result.error or "")
    # Validation failure should NOT increment the call counter.
    assert tool.call_count == 0


@pytest.mark.asyncio
async def test_schema_validation_rejects_extra_properties() -> None:
    tool = _Add()
    result = await tool(a=1, b=2, c=3)  # c is not in schema
    assert result.is_error is True
    assert "Invalid args" in (result.error or "")


@pytest.mark.asyncio
async def test_schema_validation_rejects_wrong_type() -> None:
    tool = _Add()
    result = await tool(a="not-a-number", b=2)
    assert result.is_error is True
    assert "Invalid args" in (result.error or "")


@pytest.mark.asyncio
async def test_timeout_returns_error_result() -> None:
    tool = _Slow()
    result = await tool()
    assert result.is_error is True
    assert "timed out" in (result.error or "").lower()
    assert "slow" in (result.error or "")
    # The slow tool's run would have been called, so counter did increment.
    assert tool.call_count == 1


@pytest.mark.asyncio
async def test_exception_wrapped_in_error_result() -> None:
    tool = _Boom()
    result = await tool()
    assert result.is_error is True
    assert "kaboom" in (result.error or "")
    assert "RuntimeError" in (result.error or "")


def test_to_openai_tool_shape() -> None:
    tool = _Echo()
    spec = tool.to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "echo"
    assert spec["function"]["description"] == "Echo a string back."
    assert spec["function"]["parameters"] == tool.args_schema


def test_to_anthropic_tool_shape() -> None:
    tool = _Echo()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "echo"
    assert spec["description"] == "Echo a string back."
    assert spec["input_schema"] == tool.args_schema


def test_default_class_attrs() -> None:
    """A subclass without explicit overrides should still expose sensible defaults."""

    class _Minimal(BaseTool):
        name: ClassVar[str] = "m"
        description: ClassVar[str] = "d"
        args_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def _run(self, **kwargs: Any) -> ToolResult:
            return ToolResult(output="x")

    t = _Minimal()
    assert t.requires == []
    assert t.returns_image is False
    assert t.timeout_s == 30
