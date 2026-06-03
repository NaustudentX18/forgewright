"""PlanningTool — the agent-callable tool for managing plan steps.

The orchestrator (and any sub-agent) calls this tool to register the plan,
update step status, and leave progress notes. A single shared instance is
threaded through the whole flow so every actor sees the same step ledger.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["PlanningTool", "Step", "StepStatus"]


class StepStatus(enum.StrEnum):
    """Lifecycle states for a single plan step."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Step:
    """One row in the plan ledger."""

    id: str
    title: str
    description: str
    agent: str
    status: StepStatus = StepStatus.NOT_STARTED
    notes: str = ""
    history: list[str] = field(default_factory=list)

    def to_row(self) -> str:
        """Render this step as a single markdown table row."""
        return f"| {self.id} | {self.title} | {self.agent} | {self.status.value} |"

    def to_summary(self) -> str:
        """Render a long-form summary of this single step."""
        lines = [
            f"### {self.id}: {self.title}",
            f"- **agent:** {self.agent}",
            f"- **status:** {self.status.value}",
            f"- **description:** {self.description}",
        ]
        if self.notes:
            lines.append(f"- **notes:** {self.notes}")
        if self.history:
            lines.append("- **history:**")
            lines.extend(f"  - {entry}" for entry in self.history)
        return "\n".join(lines)


class PlanningTool(BaseTool):
    """The shared ledger of plan steps.

    The orchestrator calls ``create_steps`` once at the start of a flow.
    Each sub-agent then calls ``mark_step``/``update_step`` to keep the
    ledger in sync. ``list_steps``/``get_step`` are read-only views.

    A single ``PlanningTool`` instance is shared across the whole flow
    so every actor sees the same step state.
    """

    name: ClassVar[str] = "planning"
    description: ClassVar[str] = (
        "Manage the current plan: create_steps, update_step, mark_step, list_steps, get_step."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_steps",
                    "update_step",
                    "mark_step",
                    "list_steps",
                    "get_step",
                ],
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "agent": {"type": "string"},
                    },
                    "required": ["title", "description", "agent"],
                },
            },
            "step_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": [s.value for s in StepStatus],
            },
            "notes": {"type": "string"},
        },
        "required": ["action"],
    }
    timeout_s: ClassVar[int] = 5

    def __init__(self) -> None:
        super().__init__()
        self._steps: dict[str, Step] = {}
        self._counter: int = 0

    @property
    def steps(self) -> dict[str, Step]:
        """Return a shallow copy of the current step ledger."""
        return dict(self._steps)

    def _next_id(self) -> str:
        """Allocate the next sequential step id (`s1`, `s2`, ...)."""
        self._counter += 1
        return f"s{self._counter}"

    @staticmethod
    def _now() -> str:
        """ISO-8601 UTC timestamp for history entries."""
        return datetime.now(UTC).isoformat(timespec="seconds")

    def _format_table(self, steps: list[Step]) -> str:
        """Render a markdown table for the given step list."""
        if not steps:
            return "_No steps in the plan._"
        header = "| id | title | agent | status |\n|---|---|---|---|"
        body = "\n".join(step.to_row() for step in steps)
        return f"{header}\n{body}"

    async def _run(  # type: ignore[override]
        self,
        *,
        action: str,
        steps: list[dict[str, Any]] | None = None,
        step_id: str | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> ToolResult:
        """Dispatch on `action` and return a markdown response."""
        if action == "create_steps":
            return self._create_steps(steps or [])
        if action == "update_step":
            return self._update_step(step_id, notes)
        if action == "mark_step":
            return self._mark_step(step_id, status, notes)
        if action == "list_steps":
            return self._list_steps()
        if action == "get_step":
            return self._get_step(step_id)
        return ToolResult(
            is_error=True,
            error=f"Unknown action: {action!r}",
        )

    def _create_steps(self, steps: list[dict[str, Any]]) -> ToolResult:
        """Register a batch of new steps and return them as a markdown table."""
        if not steps:
            return ToolResult(
                is_error=True,
                error="`steps` must be a non-empty list of {title, description, agent} objects.",
            )
        created: list[Step] = []
        for raw in steps:
            title = str(raw.get("title", "")).strip()
            description = str(raw.get("description", "")).strip()
            agent = str(raw.get("agent", "")).strip()
            if not title or not description or not agent:
                return ToolResult(
                    is_error=True,
                    error=(
                        "Each step must have non-empty `title`, `description`, and `agent`. "
                        f"Got: {raw!r}"
                    ),
                )
            step = Step(
                id=self._next_id(),
                title=title,
                description=description,
                agent=agent,
            )
            self._steps[step.id] = step
            created.append(step)
        logger.info("planning.created count={}", len(created))
        return ToolResult(output=self._format_table(created))

    def _update_step(self, step_id: str | None, notes: str | None) -> ToolResult:
        """Append a free-form note to the step's history."""
        if not step_id or step_id not in self._steps:
            return ToolResult(
                is_error=True,
                error=f"Unknown step_id: {step_id!r}",
            )
        if not notes:
            return ToolResult(
                is_error=True,
                error="`notes` is required for update_step.",
            )
        step = self._steps[step_id]
        stamp = self._now()
        entry = f"[{stamp}] {notes}"
        step.history.append(entry)
        if step.notes:
            step.notes = f"{step.notes}\n{entry}"
        else:
            step.notes = entry
        logger.info("planning.update step={} notes_len={}", step_id, len(notes))
        return ToolResult(output=f"Updated {step_id}.\n\n{step.to_summary()}")

    def _mark_step(
        self,
        step_id: str | None,
        status: str | None,
        notes: str | None,
    ) -> ToolResult:
        """Set the step's status; auto-append a note when entering `completed`."""
        if not step_id or step_id not in self._steps:
            return ToolResult(
                is_error=True,
                error=f"Unknown step_id: {step_id!r}",
            )
        if status is None:
            return ToolResult(
                is_error=True,
                error="`status` is required for mark_step.",
            )
        try:
            new_status = StepStatus(status)
        except ValueError as exc:
            valid = ", ".join(s.value for s in StepStatus)
            return ToolResult(
                is_error=True,
                error=f"Invalid status {status!r}. Valid: {valid} ({exc})",
            )
        step = self._steps[step_id]
        previous = step.status
        step.status = new_status
        stamp = self._now()
        entry_parts = [f"status {previous.value} -> {new_status.value}"]
        if new_status == StepStatus.COMPLETED:
            completion = notes or "completed"
            entry_parts.append(completion)
        elif notes:
            entry_parts.append(notes)
        entry = f"[{stamp}] " + " | ".join(entry_parts)
        step.history.append(entry)
        if step.notes:
            step.notes = f"{step.notes}\n{entry}"
        else:
            step.notes = entry
        logger.info(
            "planning.mark step={} previous={} new={}",
            step_id,
            previous.value,
            new_status.value,
        )
        return ToolResult(output=f"Marked {step_id} as {new_status.value}.\n\n{step.to_summary()}")

    def _list_steps(self) -> ToolResult:
        """Return a markdown table of every step in the ledger."""
        ordered = [self._steps[k] for k in sorted(self._steps)]
        return ToolResult(output=self._format_table(ordered))

    def _get_step(self, step_id: str | None) -> ToolResult:
        """Return a markdown summary of a single step."""
        if not step_id or step_id not in self._steps:
            return ToolResult(
                is_error=True,
                error=f"Unknown step_id: {step_id!r}",
            )
        return ToolResult(output=self._steps[step_id].to_summary())
