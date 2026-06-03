"""Tests for the ToolCollection routing and aggregation."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool
from forgewright.tool.collection import ToolCollection
from forgewright.tool.terminate import TerminateTool


class _Alpha(BaseTool):
    name: ClassVar[str] = "alpha"
    description: ClassVar[str] = "first"
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }

    async def _run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(output=f"alpha:{kwargs.get('x')}")


class _Beta(BaseTool):
    name: ClassVar[str] = "beta"
    description: ClassVar[str] = "second"
    args_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def _run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(output="beta-output")


def test_empty_init() -> None:
    coll = ToolCollection()
    assert len(coll) == 0
    assert list(coll) == []
    assert coll.names() == []


def test_init_with_tools() -> None:
    coll = ToolCollection([_Alpha(), _Beta()])
    assert len(coll) == 2
    assert "alpha" in coll
    assert "beta" in coll


def test_add_and_contains() -> None:
    coll = ToolCollection()
    coll.add(_Alpha())
    assert "alpha" in coll
    assert "missing" not in coll


def test_remove() -> None:
    coll = ToolCollection([_Alpha(), _Beta()])
    coll.remove("alpha")
    assert "alpha" not in coll
    assert "beta" in coll
    # Removing an absent name is a no-op.
    coll.remove("does-not-exist")
    assert len(coll) == 1


def test_add_overwrites_on_collision() -> None:
    coll = ToolCollection([_Alpha()])
    new_alpha = _Alpha()
    coll.add(new_alpha)
    assert coll.get("alpha") is new_alpha


def test_iteration_yields_tools() -> None:
    coll = ToolCollection([_Alpha(), _Beta()])
    names = sorted(t.name for t in coll)
    assert names == ["alpha", "beta"]


def test_get_returns_none_for_unknown() -> None:
    coll = ToolCollection([_Alpha()])
    assert coll.get("alpha") is not None
    assert coll.get("missing") is None


def test_names_returns_sorted_list() -> None:
    coll = ToolCollection([_Beta(), _Alpha()])
    assert coll.names() == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_call_dispatches_to_named_tool() -> None:
    coll = ToolCollection([_Alpha(), _Beta()])
    r = await coll.call("alpha", x=42)
    assert r.is_error is False
    assert r.output == "alpha:42"


@pytest.mark.asyncio
async def test_call_with_unknown_name_returns_error() -> None:
    coll = ToolCollection([_Alpha()])
    r = await coll.call("nope")
    assert r.is_error is True
    assert "Unknown tool" in (r.error or "")
    assert "nope" in (r.error or "")
    assert "alpha" in (r.error or "")  # available list mentions it


@pytest.mark.asyncio
async def test_call_propagates_tool_error() -> None:
    """A ToolResult(is_error=True) from the underlying tool passes through unchanged."""

    class _Fail(BaseTool):
        name: ClassVar[str] = "fail"
        description: ClassVar[str] = "fails"
        args_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

        async def _run(self, **kwargs: Any) -> ToolResult:
            return ToolResult(is_error=True, error="nope")

    coll = ToolCollection([_Fail()])
    r = await coll.call("fail")
    assert r.is_error is True
    assert r.error == "nope"


def test_to_openai_tools_aggregates_specs() -> None:
    coll = ToolCollection([_Alpha(), _Beta(), TerminateTool()])
    specs = coll.to_openai_tools()
    assert len(specs) == 3
    by_name = {s["function"]["name"]: s for s in specs}
    assert set(by_name) == {"alpha", "beta", "terminate"}
    # Each spec has the OpenAI shape.
    for spec in specs:
        assert spec["type"] == "function"
        assert "function" in spec
        assert {"name", "description", "parameters"} <= set(spec["function"])


def test_to_anthropic_tools_aggregates_specs() -> None:
    coll = ToolCollection([_Alpha(), _Beta(), TerminateTool()])
    specs = coll.to_anthropic_tools()
    assert len(specs) == 3
    by_name = {s["name"]: s for s in specs}
    assert set(by_name) == {"alpha", "beta", "terminate"}
    for spec in specs:
        assert {"name", "description", "input_schema"} <= set(spec)


@pytest.mark.asyncio
async def test_call_with_no_kwargs_dispatches_correctly() -> None:
    coll = ToolCollection([_Beta()])
    r = await coll.call("beta")
    assert r.output == "beta-output"
