"""Tests for the PlanningTool (the shared plan-step ledger)."""

from __future__ import annotations

import pytest
from forgewright.flow.planning_tool import PlanningTool, StepStatus
from forgewright.schema import ToolResult

# --------------------------------------------------------------------------- #
# create_steps
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_steps_assigns_sequential_ids() -> None:
    """`create_steps` allocates `s1`, `s2`, ... in order."""
    tool = PlanningTool()
    result = await tool(
        action="create_steps",
        steps=[
            {"title": "Step A", "description": "do A", "agent": "manus"},
            {"title": "Step B", "description": "do B", "agent": "data_analysis"},
        ],
    )
    assert result.is_error is False
    ids = sorted(tool.steps.keys())
    assert ids == ["s1", "s2"]
    assert tool.steps["s1"].title == "Step A"
    assert tool.steps["s1"].agent == "manus"
    assert tool.steps["s1"].status == StepStatus.NOT_STARTED
    assert tool.steps["s2"].agent == "data_analysis"


@pytest.mark.asyncio
async def test_create_steps_returns_markdown_table() -> None:
    """The output of `create_steps` is a markdown table with all new rows."""
    tool = PlanningTool()
    result = await tool(
        action="create_steps",
        steps=[
            {"title": "T1", "description": "d1", "agent": "manus"},
            {"title": "T2", "description": "d2", "agent": "browser_agent"},
        ],
    )
    assert result.output is not None
    assert "| id | title | agent | status |" in result.output
    assert "| s1 | T1 | manus | not_started |" in result.output
    assert "| s2 | T2 | browser_agent | not_started |" in result.output


@pytest.mark.asyncio
async def test_create_steps_rejects_empty_list() -> None:
    """An empty `steps` argument produces an error result."""
    tool = PlanningTool()
    result = await tool(action="create_steps", steps=[])
    assert result.is_error is True
    assert "non-empty" in (result.error or "")


@pytest.mark.asyncio
async def test_create_steps_rejects_missing_fields() -> None:
    """A step missing `agent` produces an error result."""
    tool = PlanningTool()
    result = await tool(
        action="create_steps",
        steps=[{"title": "T", "description": "d", "agent": ""}],
    )
    assert result.is_error is True
    assert "non-empty" in (result.error or "")


# --------------------------------------------------------------------------- #
# mark_step
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_mark_step_updates_status_and_appends_note() -> None:
    """`mark_step` mutates the status and records a history entry."""
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[{"title": "T", "description": "d", "agent": "manus"}],
    )
    result = await tool(
        action="mark_step",
        step_id="s1",
        status="in_progress",
    )
    assert result.is_error is False
    assert tool.steps["s1"].status == StepStatus.IN_PROGRESS
    # The notes were appended automatically.
    assert "in_progress" in tool.steps["s1"].notes
    # The history recorded the transition.
    assert tool.steps["s1"].history


@pytest.mark.asyncio
async def test_mark_step_completed_appends_completion_note() -> None:
    """Marking `completed` auto-appends a completion note."""
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[{"title": "T", "description": "d", "agent": "manus"}],
    )
    await tool(action="mark_step", step_id="s1", status="completed")
    step = tool.steps["s1"]
    assert step.status == StepStatus.COMPLETED
    assert "completed" in step.notes
    assert any("completed" in entry for entry in step.history)


@pytest.mark.asyncio
async def test_mark_step_unknown_id_returns_error() -> None:
    """`mark_step` with an unknown step_id returns a ToolResult error."""
    tool = PlanningTool()
    result = await tool(action="mark_step", step_id="nope", status="completed")
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "Unknown step_id" in (result.error or "")


@pytest.mark.asyncio
async def test_mark_step_invalid_status_returns_error() -> None:
    """An invalid status enum value is rejected.

    The schema validator catches bad enum values at the boundary, so
    the resulting error mentions ``Invalid args`` rather than the
    runtime check.
    """
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[{"title": "T", "description": "d", "agent": "manus"}],
    )
    result = await tool(action="mark_step", step_id="s1", status="bogus")
    assert result.is_error is True
    assert "Invalid args" in (result.error or "") or "Invalid status" in (result.error or "")


# --------------------------------------------------------------------------- #
# update_step
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_step_appends_notes() -> None:
    """`update_step` appends a timestamped note to the step's history."""
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[{"title": "T", "description": "d", "agent": "manus"}],
    )
    result = await tool(action="update_step", step_id="s1", notes="halfway done")
    assert result.is_error is False
    step = tool.steps["s1"]
    assert "halfway done" in step.notes
    # History captured the note.
    assert any("halfway done" in entry for entry in step.history)
    # The output is the full summary of the step.
    assert "### s1: T" in result.output


@pytest.mark.asyncio
async def test_update_step_unknown_id_returns_error() -> None:
    """`update_step` on a missing id returns an error."""
    tool = PlanningTool()
    result = await tool(action="update_step", step_id="nope", notes="x")
    assert result.is_error is True


@pytest.mark.asyncio
async def test_update_step_requires_notes() -> None:
    """`update_step` with no notes returns an error."""
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[{"title": "T", "description": "d", "agent": "manus"}],
    )
    result = await tool(action="update_step", step_id="s1")
    assert result.is_error is True
    assert "`notes` is required" in (result.error or "")


# --------------------------------------------------------------------------- #
# list_steps / get_step
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_steps_returns_markdown_table() -> None:
    """`list_steps` returns a markdown table containing every step."""
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[
            {"title": "T1", "description": "d1", "agent": "manus"},
            {"title": "T2", "description": "d2", "agent": "data_analysis"},
        ],
    )
    result = await tool(action="list_steps")
    assert result.is_error is False
    assert "| id | title | agent | status |" in result.output
    assert "| s1 | T1 | manus | not_started |" in result.output
    assert "| s2 | T2 | data_analysis | not_started |" in result.output


@pytest.mark.asyncio
async def test_list_steps_empty_returns_placeholder() -> None:
    """`list_steps` with no steps returns a placeholder, not a crash."""
    tool = PlanningTool()
    result = await tool(action="list_steps")
    assert result.is_error is False
    assert "No steps" in result.output


@pytest.mark.asyncio
async def test_get_step_returns_summary() -> None:
    """`get_step` returns a long-form summary of a single step."""
    tool = PlanningTool()
    await tool(
        action="create_steps",
        steps=[{"title": "Alpha", "description": "first", "agent": "manus"}],
    )
    result = await tool(action="get_step", step_id="s1")
    assert result.is_error is False
    assert "### s1: Alpha" in result.output
    assert "first" in result.output
    assert "manus" in result.output


@pytest.mark.asyncio
async def test_get_step_unknown_id_returns_error() -> None:
    """`get_step` on a missing id returns an error."""
    tool = PlanningTool()
    result = await tool(action="get_step", step_id="nope")
    assert result.is_error is True
    assert "Unknown step_id" in (result.error or "")


# --------------------------------------------------------------------------- #
# Schema metadata
# --------------------------------------------------------------------------- #


def test_planning_tool_metadata() -> None:
    """Name, schema-required, and timeout are stable."""
    tool = PlanningTool()
    assert tool.name == "planning"
    assert tool.timeout_s == 5
    schema = tool.args_schema
    assert "action" in schema["required"]
    # Status enum contains every StepStatus value.
    status_enum = schema["properties"]["status"]["enum"]
    for s in StepStatus:
        assert s.value in status_enum


def test_planning_tool_openai_spec() -> None:
    """OpenAI wire-format spec is well-formed."""
    tool = PlanningTool()
    spec = tool.to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "planning"
    params = spec["function"]["parameters"]
    assert "action" in params["required"]
    assert "steps" in params["properties"]
    assert "step_id" in params["properties"]
    assert "status" in params["properties"]


def test_planning_tool_anthropic_spec() -> None:
    """Anthropic wire-format spec is well-formed."""
    tool = PlanningTool()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "planning"
    assert "action" in spec["input_schema"]["required"]


def test_steps_property_returns_copy() -> None:
    """`steps` returns a copy so callers can't mutate internal state."""
    tool = PlanningTool()
    snap = tool.steps
    snap["s99"] = "intruder"  # type: ignore[assignment]
    assert "s99" not in tool.steps
