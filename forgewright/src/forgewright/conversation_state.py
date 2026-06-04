"""Event-sourced ``ConversationState`` shim over the JSONL audit log (H2.2).

Exposes :class:`ConversationState` as a queryable, re-playable view of
one session's audit events. The shim is the foundation for H2.1, H2.3,
and H2.5. It is intentionally a thin wrapper over the existing
:class:`forgewright.security.audit.AuditLog` JSONL — no new persistence
layer.

The typed final-state event writer (:func:`write_final_state`) appends a
``session_end`` event with ``result.final_state`` set to one of the
allowed :data:`FinalState` values. H2.3 uses it to persist
``"cost_limit_reached"`` and ``"iteration_limit_reached"`` instead of
raising an exception.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from forgewright.cost import cost_for
from forgewright.security.audit import AuditEvent, AuditLog

__all__ = [
    "LLM_TURN_TYPE",
    "SESSION_END_TYPE",
    "ConversationState",
    "FinalState",
    "TypedEvent",
    "write_final_state",
]


# Event type strings used by the shim. ``type`` is a free string per the
# audit schema; centralising the constants keeps callers honest.
LLM_TURN_TYPE: str = "llm_turn"
SESSION_END_TYPE: str = "session_end"

# The set of typed final states a session can end in. H2.3 persists
# ``"cost_limit_reached"`` / ``"iteration_limit_reached"`` instead of
# raising; H2.4 uses ``"error"``; manual aborts use ``"user_aborted"``.
FinalState = Literal[
    "completed",
    "cost_limit_reached",
    "iteration_limit_reached",
    "user_aborted",
    "error",
]


class TypedEvent(TypedDict, total=False):
    """A typed view of a single audit-log event.

    Mirrors :class:`forgewright.security.audit.AuditEvent`. Optional
    fields are declared ``total=False`` because the on-disk format
    drops ``None`` values (see :meth:`AuditEvent.to_dict`), so a loaded
    event may legitimately omit ``tool`` / ``args`` / ``result`` /
    ``user_consent``.
    """

    ts: str
    session_id: str
    type: str
    actor: dict[str, str]
    tool: str | None
    args: dict[str, Any] | None
    result: dict[str, Any] | None
    user_consent: dict[str, Any] | None
    prev_hash: str
    hash: str


class ConversationState:
    """A queryable, re-playable view of one session's audit events.

    Built lazily from a JSONL audit log; reads are O(N) over the file
    (fine for v0.3's expected session sizes of hundreds-to-thousands of
    events; a streaming query layer is the v0.4 upgrade).
    """

    def __init__(
        self,
        session_id: str,
        path: Path,
        events: list[TypedEvent],
    ) -> None:
        self.session_id = session_id
        self.path = path
        self.events = events

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def from_log(cls, path: str | Path, session_id: str) -> ConversationState:
        """Load a :class:`ConversationState` for ``session_id`` from the JSONL log.

        Reads the audit log at ``path`` and returns a view containing
        only events whose ``session_id`` matches. Tolerant of malformed
        (partial) lines and a missing file — both yield an empty state
        rather than an error, since the shim is read-only and the
        :class:`AuditLog` is the canonical writer.
        """
        p = Path(path)
        events: list[TypedEvent] = []
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        # Tolerant of partial last lines from a crash.
                        continue
                    if not isinstance(obj, dict):
                        continue
                    if obj.get("session_id") != session_id:
                        continue
                    events.append(cast(TypedEvent, obj))
        return cls(session_id=session_id, path=p, events=events)

    # ------------------------------------------------------------------ #
    # Replay
    # ------------------------------------------------------------------ #

    def replay(self, from_offset: int = 0) -> Iterator[TypedEvent]:
        """Yield events starting at index ``from_offset``.

        ``from_offset`` is clamped to ``>= 0``; passing a value larger
        than ``len(self.events)`` simply yields nothing. Useful for
        incremental consumers (a TUI, a cost-cap watcher) that need
        only events newer than the last one they processed.
        """
        start = max(0, int(from_offset))
        for i in range(start, len(self.events)):
            yield self.events[i]

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def cost_so_far(self) -> Decimal:
        """Sum the cost of all LLM turn events.

        Each event's ``result.usage`` may contain ``input_tokens``,
        ``output_tokens``, and ``model`` keys. Cost is computed via
        :func:`forgewright.cost.cost_for` using the model's pricing
        row. Events that aren't LLM turns, or that lack ``result.usage``,
        contribute zero. Non-numeric token fields are skipped silently
        rather than raising — a corrupt event shouldn't kill the
        dashboard.
        """
        total = Decimal("0")
        for ev in self.events:
            if ev.get("type") != LLM_TURN_TYPE:
                continue
            result = ev.get("result") or {}
            usage: dict[str, Any] = result.get("usage") or {}
            model = usage.get("model", "_default")
            try:
                input_tokens = int(usage.get("input_tokens", 0))
                output_tokens = int(usage.get("output_tokens", 0))
            except (TypeError, ValueError):
                continue
            total += Decimal(str(cost_for(model, input_tokens, output_tokens)))
        return total

    def iterations(self) -> int:
        """Count LLM turn events.

        Each ``type=llm_turn`` event is one iteration of the agent loop.
        """
        return sum(1 for ev in self.events if ev.get("type") == LLM_TURN_TYPE)

    def final_state(self) -> FinalState | None:
        """Return the ``final_state`` of the last event, or ``None``.

        Looks at ``result.final_state`` on the last event. Returns
        ``None`` if there are no events or the last event has no
        final state. The literal-type contract is enforced via
        :func:`cast`; a non-string value is treated as missing.
        """
        if not self.events:
            return None
        last = self.events[-1]
        result = last.get("result") or {}
        state: Any = result.get("final_state")
        if not isinstance(state, str):
            return None
        return cast(FinalState, state)

    # ------------------------------------------------------------------ #
    # Misc
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        return len(self.events)


# ---------------------------------------------------------------------- #
# Writer
# ---------------------------------------------------------------------- #


def write_final_state(
    log: AuditLog,
    session_id: str,
    state: FinalState,
    *,
    actor: dict[str, str] | None = None,
) -> AuditEvent:
    """Append a session-end event with the typed final state.

    The audit log is the source of truth for session outcomes; this
    helper centralises the shape so H2.3 and H2.4 don't diverge.
    Returns the appended :class:`AuditEvent` (with chain hash stamped).
    """
    return log.append(
        AuditEvent(
            session_id=session_id,
            type=SESSION_END_TYPE,
            actor=actor or {"type": "system", "name": "conversation_state"},
            result={"final_state": state},
        )
    )
