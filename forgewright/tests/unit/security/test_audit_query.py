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


# ---------------------------------------------------------------------- #
# Quoted-value syntax
# ---------------------------------------------------------------------- #


def test_parse_quoted_value_with_AND_substring() -> None:
    """A value containing the literal substring `` AND `` must be queryable."""
    clauses = parse_audit_query('text="foo AND bar"')
    assert clauses == [("text", "foo AND bar")]


def test_parse_quoted_value_with_whitespace() -> None:
    """Quoted values preserve internal whitespace."""
    clauses = parse_audit_query('reason="user said no"')
    assert clauses == [("reason", "user said no")]


def test_parse_quoted_value_with_escaped_quote() -> None:
    """Escaped ``\\"`` inside a quoted value is preserved as ``"``."""
    clauses = parse_audit_query(r'note="he said \"hi\""')
    assert clauses == [("note", 'he said "hi"')]


def test_parse_quoted_value_combined_with_bare() -> None:
    """Bare and quoted clauses can be mixed with AND."""
    clauses = parse_audit_query('tool=bash AND reason="user said no"')
    assert clauses == [("tool", "bash"), ("reason", "user said no")]


def test_parse_quoted_value_unterminated_raises() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        parse_audit_query('text="no close')


def test_parse_audit_query_rejects_trailing_and() -> None:
    with pytest.raises(ValueError, match="AND"):
        parse_audit_query("tool=bash AND")


def test_parse_audit_query_rejects_garbage_between_clauses() -> None:
    with pytest.raises(ValueError, match="AND"):
        parse_audit_query("tool=bash OR approved=false")


def test_event_matches_quoted_value_with_AND_substring() -> None:
    """The matching engine must honour the quoted-value parsing."""
    event = {"text": "foo AND bar"}
    assert event_matches_query(event, parse_audit_query('text="foo AND bar"'))
    assert not event_matches_query(event, parse_audit_query('text="baz"'))


# ---------------------------------------------------------------------- #
# Streaming query (H1.1 — append-only log fan-out)
# ---------------------------------------------------------------------- #


def test_query_stream_returns_an_iterator(tmp_path) -> None:
    """``query_stream`` is lazy: it returns an iterator, not a list."""
    import inspect
    from collections.abc import Iterator

    from forgewright.security.audit import query_stream

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent(session_id="s1", type="tool", tool="Bash"))

    gen = query_stream(path)
    # Generator/iterator — the file has not been fully read.
    assert isinstance(gen, Iterator)
    assert inspect.isgenerator(gen)
    # Consuming it works.
    events = list(gen)
    assert len(events) == 1
    assert events[0].session_id == "s1"


def test_audit_query_streams_10k_events_without_loading_all(tmp_path) -> None:
    """10k events streamed line-by-line, peak heap < the on-disk size.

    The regression we're guarding against: H1.1 used ``list(query(...))``
    which materialised the whole JSONL in RAM. With a generator the
    working set should be roughly the size of one event (~hundreds of
    bytes), not the size of the file (~MB).
    """
    import tracemalloc

    from forgewright.security.audit import query_stream

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(10_000):
        log.append(
            AuditEvent(
                session_id=f"s{i % 5}",
                type="tool",
                tool="Bash",
                args={"cmd": f"echo {i}"},
            )
        )
    file_size = path.stat().st_size
    assert file_size > 1_000_000, f"sanity: 10k events wrote {file_size} bytes"

    tracemalloc.start()
    try:
        # Walk the generator. ``query_stream`` reads line by line so
        # the working set is O(1) per yielded event, not O(N).
        total = sum(1 for _ in query_stream(path))
        assert total == 10_000
    finally:
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()

    # We allocate AuditEvent objects along the way (each ~hundreds of
    # bytes), so the peak is necessarily larger than zero but should
    # be at least an order of magnitude below the on-disk file size.
    # 5 MB is a generous upper bound; in practice it's < 1 MB.
    assert peak < 5 * 1024 * 1024, f"peak heap {peak} bytes is too large for streaming"
    assert peak < file_size // 2, (
        f"peak heap {peak} bytes is >= half the on-disk size {file_size} "
        f"— query_stream is materialising the log"
    )


def test_audit_log_query_stream_method_reads_from_file(tmp_path) -> None:
    """``AuditLog.query_stream`` reads the file, not the in-memory list.

    This is the "H1.1 streaming matcher" wired into the class API. A
    second :class:`AuditLog` instance with a freshly-appended event
    would not see that event in ``self._events``, but the file-backed
    stream would.
    """
    from forgewright.security.audit import query_stream

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent(session_id="s1", type="tool", tool="Bash"))
    log.append(AuditEvent(session_id="s2", type="tool", tool="WebSearch"))

    # Append a third event by going around the in-memory list, so the
    # existing ``log._events`` is stale by one.
    with path.open("a", encoding="utf-8") as f:
        f.write(
            '{"ts":"2026-06-04T00:00:00Z","session_id":"s3","type":"tool",'
            '"actor":{},"tool":"Bash","prev_hash":"0","hash":"x"}\n'
        )

    # Class method streams from the file — sees all three.
    streamed = list(log.query_stream("tool=bash"))
    assert {e.session_id for e in streamed} == {"s1", "s3"}
    # Module-level function is equivalent.
    streamed2 = list(query_stream(path, expr="tool=bash"))
    assert {e.session_id for e in streamed2} == {"s1", "s3"}


def test_query_stream_respects_since_offset(tmp_path) -> None:
    """``since`` skips events at byte offsets < the given value."""
    from forgewright.security.audit import query_stream

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(5):
        log.append(
            AuditEvent(
                session_id="s1",
                type="tool",
                tool="Bash",
                args={"cmd": f"echo {i}"},
            )
        )
    # Skip the first 2 events by seeking to the byte offset where the
    # 3rd event starts. Reading the file gives us that boundary.
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    boundary = sum(len(line) + 1 for line in lines[:2])  # +1 for \n
    streamed = list(query_stream(path, since=boundary))
    assert len(streamed) == 3
    assert streamed[0].args == {"cmd": "echo 2"}


def test_query_stream_mid_line_since_rounds_up(tmp_path) -> None:
    """A ``since`` that lands mid-line advances to the next newline."""
    from forgewright.security.audit import query_stream

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent(session_id="s1", type="tool", tool="Bash"))
    log.append(AuditEvent(session_id="s2", type="tool", tool="Bash"))

    # At offset 1 the file's first byte is ``{`` (not a newline), so
    # the partial first line is dropped and we resume at the next
    # full event. This is the safe default — a stale cursor that
    # lands mid-line never surfaces a torn event.
    streamed = list(query_stream(path, since=1))
    assert [e.session_id for e in streamed] == ["s2"]

    # The same behaviour at a deeper offset.
    streamed = list(query_stream(path, since=5))
    assert [e.session_id for e in streamed] == ["s2"]


def test_query_stream_past_eof_yields_nothing(tmp_path) -> None:
    """``since >= file size`` returns an empty iterator (not an error)."""
    from forgewright.security.audit import query_stream

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent(session_id="s1", type="tool", tool="Bash"))

    size = path.stat().st_size
    assert list(query_stream(path, since=size)) == []
    assert list(query_stream(path, since=size + 100)) == []
