"""Tests for the audit log query language."""

from __future__ import annotations

import pytest
from forgewright.security.audit import AuditEvent, AuditLog
from forgewright.security.audit_query import (
    event_matches_query,
    filter_events,
    parse_audit_query,
)


def test_parse_audit_query_splits_and() -> None:
    clauses = parse_audit_query("tool=bash AND approved=false")
    assert clauses == [("tool", "bash"), ("approved", "false")]


def test_parse_audit_query_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_audit_query("   ")


def test_parse_audit_query_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="field=value"):
        parse_audit_query("toolbash")


def test_event_matches_tool_case_insensitive() -> None:
    event = {"tool": "Bash", "type": "tool"}
    clauses = parse_audit_query("tool=bash")
    assert event_matches_query(event, clauses)


def test_event_matches_approved_false_when_missing() -> None:
    event = {"tool": "Bash", "type": "tool"}
    clauses = parse_audit_query("approved=false")
    assert event_matches_query(event, clauses)


def test_event_matches_approved_from_user_consent() -> None:
    event = {"tool": "Bash", "user_consent": {"approved": True}}
    assert not event_matches_query(event, parse_audit_query("approved=false"))
    assert event_matches_query(event, parse_audit_query("approved=true"))


def test_filter_events_combined_and() -> None:
    rows = [
        {"tool": "Bash", "user_consent": {"approved": False}},
        {"tool": "Bash", "user_consent": {"approved": True}},
        {"tool": "WebSearch", "user_consent": {"approved": False}},
    ]
    out = filter_events(rows, "tool=bash AND approved=false")
    assert len(out) == 1
    assert out[0]["tool"] == "Bash"


def test_audit_log_query_integration(tmp_path) -> None:
    log = AuditLog(tmp_path / "q.jsonl")
    log.append(
        AuditEvent(
            session_id="s0",
            type="tool",
            tool="Bash",
            user_consent={"approved": False},
        )
    )
    log.append(
        AuditEvent(
            session_id="s1",
            type="tool",
            tool="Bash",
            user_consent={"approved": True},
        )
    )
    log.append(
        AuditEvent(
            session_id="s2",
            type="tool",
            tool="WebSearch",
            user_consent={"approved": False},
        )
    )
    hits = log.query("tool=bash AND approved=false")
    assert len(hits) == 1
    assert hits[0].session_id == "s0"
