"""Tests for the ToolCollection routing and aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool
from forgewright.tool.collection import ToolCollection
from forgewright.tool.str_replace_editor import StrReplaceEditor
from forgewright.tool.terminate import TerminateTool
from forgewright.workspace import LocalWorkspace


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


# --------------------------------------------------------------------------- #
# Workspace threading (H1.2)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_tool_collection_uses_workspace_when_provided(tmp_path: Path) -> None:
    """``str_replace_editor`` writes land inside the workspace root, not the CWD.

    A path that lives inside the workspace resolves cleanly and the
    file ends up on disk under the workspace root.
    """
    ws = LocalWorkspace(tmp_path)
    editor = StrReplaceEditor()
    coll = ToolCollection([editor], workspace=ws)

    target = tmp_path / "out.txt"
    result = await coll.call(
        "str_replace_editor",
        command="create",
        path=str(target),
        file_text="hello",
    )
    assert result.is_error is False
    assert target.read_text(encoding="utf-8") == "hello"
    # The editor is the SAME instance — the collection mutated its
    # ``workspace`` attribute in place.
    assert editor.workspace is ws


@pytest.mark.asyncio
async def test_tool_collection_workspace_optional(tmp_path: Path) -> None:
    """No workspace -> no mutation, existing behaviour preserved."""
    editor = StrReplaceEditor()
    coll = ToolCollection([editor])
    assert coll.workspace is None
    assert editor.workspace is None


@pytest.mark.asyncio
async def test_tool_collection_set_workspace_after_init(tmp_path: Path) -> None:
    """``set_workspace`` propagates to every tool that opts in."""
    editor = StrReplaceEditor()
    coll = ToolCollection([editor])
    ws = LocalWorkspace(tmp_path)
    coll.set_workspace(ws)
    assert editor.workspace is ws


@pytest.mark.asyncio
async def test_tool_collection_workspace_blocks_outside_workspace(tmp_path: Path) -> None:
    """A path outside the workspace is still denied by the editor."""
    ws = LocalWorkspace(tmp_path)
    coll = ToolCollection([StrReplaceEditor()], workspace=ws)
    result = await coll.call(
        "str_replace_editor",
        command="view",
        path="/etc/passwd",
    )
    assert result.is_error is True
    assert "outside the workspace" in (result.error or "")
