"""Tests for the H2.2 ``ConversationState`` shim.

Covers: session filtering, replay from an offset, cost aggregation,
LLM-turn iteration counting, and the typed final-state writer. The
shim is built directly on top of :class:`forgewright.security.audit.
AuditLog`, so the tests use the real writer to make sure the
end-to-end pipeline (write -> load -> query) works.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from forgewright.conversation_state import (
    LLM_TURN_TYPE,
    SESSION_END_TYPE,
    ConversationState,
    FinalState,
    TypedEvent,
    write_final_state,
)
from forgewright.cost import cost_for
from forgewright.security.audit import AuditEvent, AuditLog

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


_TEST_ACTOR: dict[str, str] = {"type": "agent", "name": "test", "version": "0.1.0"}


def _tool_event(session_id: str, *, args: dict | None = None) -> AuditEvent:
    return AuditEvent(
        session_id=session_id,
        type="tool",
        actor={"type": "tool", "name": "Bash", "version": "0.1.0"},
        tool="Bash",
        args=args or {"cmd": "ls"},
    )


def _llm_turn(
    session_id: str,
    *,
    model: str = "anthropic/claude-sonnet-4-6",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> AuditEvent:
    return AuditEvent(
        session_id=session_id,
        type=LLM_TURN_TYPE,
        actor=_TEST_ACTOR,
        result={"usage": {"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens}},
    )


# --------------------------------------------------------------------------- #
# from_log
# --------------------------------------------------------------------------- #


def test_from_log_loads_events_for_session(tmp_path: Path) -> None:
    """``from_log`` returns all events for the given session, in order."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_tool_event("A", args={"cmd": "ls"}))
    log.append(_tool_event("A", args={"cmd": "pwd"}))
    log.append(_tool_event("A", args={"cmd": "whoami"}))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")

    assert state.session_id == "A"
    assert state.path == tmp_path / "audit.jsonl"
    assert len(state.events) == 3
    assert [ev["args"] for ev in state.events] == [{"cmd": "ls"}, {"cmd": "pwd"}, {"cmd": "whoami"}]


def test_from_log_filters_other_sessions(tmp_path: Path) -> None:
    """Events for other sessions are dropped."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_tool_event("A", args={"cmd": "ls"}))
    log.append(_tool_event("B", args={"cmd": "pwd"}))
    log.append(_tool_event("A", args={"cmd": "whoami"}))
    log.append(_tool_event("B", args={"cmd": "uname"}))

    state_a = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    state_b = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="B")

    assert len(state_a.events) == 2
    assert len(state_b.events) == 2
    assert all(ev["session_id"] == "A" for ev in state_a.events)
    assert all(ev["session_id"] == "B" for ev in state_b.events)
    assert [ev["args"] for ev in state_a.events] == [{"cmd": "ls"}, {"cmd": "whoami"}]
    assert [ev["args"] for ev in state_b.events] == [{"cmd": "pwd"}, {"cmd": "uname"}]


def test_from_log_missing_file_returns_empty_state(tmp_path: Path) -> None:
    """A non-existent log yields an empty state (no exception)."""
    state = ConversationState.from_log(tmp_path / "does-not-exist.jsonl", session_id="X")
    assert len(state.events) == 0
    assert state.session_id == "X"


# --------------------------------------------------------------------------- #
# replay
# --------------------------------------------------------------------------- #


def test_replay_from_offset_yields_only_new_events(tmp_path: Path) -> None:
    """``replay(n)`` yields only events at index ``>= n``."""
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.append(_tool_event("A", args={"i": i}))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    assert len(state.events) == 5

    replayed = list(state.replay(from_offset=2))
    assert len(replayed) == 3
    assert [ev["args"] for ev in replayed] == [{"i": 2}, {"i": 3}, {"i": 4}]

    # Negative offset is clamped to 0.
    assert len(list(state.replay(from_offset=-1))) == 5
    # Offset past the end yields nothing.
    assert list(state.replay(from_offset=99)) == []


# --------------------------------------------------------------------------- #
# cost_so_far
# --------------------------------------------------------------------------- #


def test_cost_so_far_sums_usage(tmp_path: Path) -> None:
    """``cost_so_far`` sums per-event costs via :func:`cost_for`.

    Uses 1M-token totals so the expected value is exactly representable
    in IEEE-754 (3.0 + 15.0 = 18.0 for the sonnet pricing row), which
    keeps the assertion free of float-rounding noise. The first event
    contributes input cost only; the second contributes output cost
    only; a non-LLM event in between is ignored.
    """
    log = AuditLog(tmp_path / "audit.jsonl")
    model = "anthropic/claude-sonnet-4-6"

    log.append(_llm_turn("A", model=model, input_tokens=1_000_000, output_tokens=0))
    log.append(_tool_event("A", args={"cmd": "ls"}))  # must not contribute
    log.append(_llm_turn("A", model=model, input_tokens=0, output_tokens=1_000_000))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")

    assert state.cost_so_far() == Decimal(str(cost_for(model, 1_000_000, 1_000_000)))
    assert state.cost_so_far() == Decimal("18.0")


def test_cost_so_far_zero_when_no_llm_turns(tmp_path: Path) -> None:
    """``cost_so_far`` returns zero for a session with no LLM calls."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_tool_event("A", args={"cmd": "ls"}))
    log.append(_tool_event("A", args={"cmd": "pwd"}))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    assert state.cost_so_far() == Decimal("0")


# --------------------------------------------------------------------------- #
# iterations
# --------------------------------------------------------------------------- #


def test_iterations_counts_llm_turns(tmp_path: Path) -> None:
    """``iterations`` returns the number of ``type=llm_turn`` events."""
    log = AuditLog(tmp_path / "audit.jsonl")
    for _ in range(3):
        log.append(_llm_turn("A"))
    log.append(_tool_event("A", args={"cmd": "ls"}))
    log.append(_tool_event("A", args={"cmd": "pwd"}))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    assert state.iterations() == 3


def test_iterations_zero_when_no_llm_turns(tmp_path: Path) -> None:
    """``iterations`` returns zero for a session with only tool calls."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_tool_event("A", args={"cmd": "ls"}))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    assert state.iterations() == 0


# --------------------------------------------------------------------------- #
# final_state
# --------------------------------------------------------------------------- #


def test_final_state_returns_last_typed_state(tmp_path: Path) -> None:
    """``final_state`` returns ``result.final_state`` of the last event."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_llm_turn("A"))
    log.append(_tool_event("A", args={"cmd": "ls"}))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    # No session_end yet.
    assert state.final_state() is None

    # Persist a typed final state via the writer and reload.
    write_final_state(log, "A", "completed")
    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    assert state.final_state() == "completed"


@pytest.mark.parametrize(
    "state_value",
    ["completed", "cost_limit_reached", "iteration_limit_reached", "user_aborted", "error"],
)
def test_final_state_round_trips_each_literal(tmp_path: Path, state_value: FinalState) -> None:
    """Every allowed ``FinalState`` value round-trips through the log."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_llm_turn("A"))
    write_final_state(log, "A", state_value)

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    assert state.final_state() == state_value


def test_write_final_state_appends_session_end_event(tmp_path: Path) -> None:
    """``write_final_state`` appends a ``session_end`` event with the right shape."""
    log = AuditLog(tmp_path / "audit.jsonl")
    ev = write_final_state(log, "A", "cost_limit_reached")

    assert ev.type == SESSION_END_TYPE
    assert ev.session_id == "A"
    assert ev.result == {"final_state": "cost_limit_reached"}

    # And the chain still verifies.
    assert log.verify().ok is True


# --------------------------------------------------------------------------- #
# TypedEvent shape (defensive: catches accidental schema drift)
# --------------------------------------------------------------------------- #


def test_typed_event_carries_chain_hashes(tmp_path: Path) -> None:
    """Loaded events expose ``prev_hash`` / ``hash`` so callers can verify."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_llm_turn("A"))

    state = ConversationState.from_log(tmp_path / "audit.jsonl", session_id="A")
    ev: TypedEvent = state.events[0]
    assert len(ev["hash"]) == 64
    assert ev["prev_hash"] == "0" * 64
