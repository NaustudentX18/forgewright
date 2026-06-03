"""Tests for the sha256-chained JSONL audit log.

Covers: append stamping (ts/prev_hash/hash), on-disk format, verify
(positive + tampered), tail, export (jsonl + csv), and crash-recovery
tolerance for a partial last line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Test-time import shim
# --------------------------------------------------------------------------- #
# ``forgewright.security.__init__`` re-exports ``approval`` and ``trust``,
# both of which are still landing in parallel during Phase 10. If either
# has a syntax error or missing dependency, importing
# ``forgewright.security.audit`` (which goes through ``__init__``) blows
# up. We pre-stub those names so this test file can isolate the audit
# module's behavior. The shim is a NO-OP in a clean checkout (we only
# create stubs when the real modules can't be imported).
# --------------------------------------------------------------------------- #

try:
    from forgewright.security.audit import (
        AuditEvent,
        AuditLog,
        AuditVerifyResult,
        _compute_hash,
        _utc_now_iso,
    )
except Exception:  # pragma: no cover - shim path
    _audit_spec = __import__(
        "importlib.util", fromlist=["spec_from_file_location"]
    ).spec_from_file_location(
        "forgewright.security.audit",
        str(Path(__file__).resolve().parents[3] / "src" / "forgewright" / "security" / "audit.py"),
    )
    _audit_mod = __import__("importlib.util", fromlist=["module_from_spec"]).module_from_spec(
        _audit_spec
    )
    sys.modules["forgewright.security.audit"] = _audit_mod
    _audit_spec.loader.exec_module(_audit_mod)
    AuditEvent = _audit_mod.AuditEvent
    AuditLog = _audit_mod.AuditLog
    AuditVerifyResult = _audit_mod.AuditVerifyResult
    _compute_hash = _audit_mod._compute_hash
    _utc_now_iso = _audit_mod._utc_now_iso

# _compute_hash and _utc_now_iso are private but used in two tests; we
# import them with a leading underscore to make the intent clear.

# Per the audit-log spec (ARCHITECTURE.md §11.2): the first event's
# prev_hash is 64 zero hex chars.
GENESIS_PREV_HASH = "0" * 64


# --------------------------------------------------------------------------- #
# Test fixtures
# --------------------------------------------------------------------------- #


def _make_event(
    session_id: str = "s1",
    tool: str | None = "Bash",
    args: dict | None = None,
    actor: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        ts="",
        session_id=session_id,
        type="tool",
        actor=actor or {"type": "tool", "name": "Bash", "version": "0.1.0"},
        tool=tool,
        args=args or {"cmd": "ls"},
    )


# --------------------------------------------------------------------------- #
# AuditEvent.to_dict / from_dict round trip
# --------------------------------------------------------------------------- #


def test_event_to_dict_drops_none_optionals() -> None:
    """to_dict omits optional fields that are None (tight on-disk format)."""
    ev = _make_event()
    d = ev.to_dict()
    assert "tool" in d
    assert "args" in d
    assert "result" not in d
    assert "user_consent" not in d


def test_event_from_dict_round_trip() -> None:
    """from_dict(to_dict(event)) is the identity for populated events."""
    original = _make_event(
        tool="Bash",
        args={"cmd": "ls -la"},
        actor={"type": "tool", "name": "Bash", "version": "0.1.0"},
    )
    original.user_consent = {"mode": "approve-each", "approver": "forest"}
    original.result = {"exit": 0, "stdout_sha256": "ab12"}

    d = original.to_dict(include_hash=True)
    loaded = AuditEvent.from_dict(d)
    assert loaded.to_dict(include_hash=True) == d


def test_event_to_dict_can_omit_hash() -> None:
    """include_hash=False is used during hash recomputation."""
    ev = _make_event()
    ev.hash = "abc"
    d = ev.to_dict(include_hash=False)
    assert "hash" not in d
    assert d["prev_hash"] == ""


# --------------------------------------------------------------------------- #
# Hash helpers
# --------------------------------------------------------------------------- #


def test_utc_now_iso_has_z_suffix() -> None:
    """Timestamps are rendered with ``Z`` (not ``+00:00``)."""
    ts = _utc_now_iso()
    assert ts.endswith("Z")
    assert "+00:00" not in ts


def test_compute_hash_is_deterministic() -> None:
    """Same input => same hash, twice."""
    ev = _make_event(args={"cmd": "ls"})
    d = ev.to_dict(include_hash=False)
    h1 = _compute_hash(d, GENESIS_PREV_HASH)
    h2 = _compute_hash(d, GENESIS_PREV_HASH)
    assert h1 == h2
    assert len(h1) == 64


# --------------------------------------------------------------------------- #
# AuditLog.append
# --------------------------------------------------------------------------- #


def test_append_writes_one_json_line(tmp_path: Path) -> None:
    """append writes exactly one valid JSON line, terminated with ``\\n``."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_make_event(args={"cmd": "ls"}))

    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert text.endswith("\n")
    # Exactly one record, no stray newlines inside the line.
    assert text.count("\n") == 1
    obj = json.loads(text.strip())
    assert obj["session_id"] == "s1"
    assert obj["hash"]  # populated


def test_append_sets_ts_when_empty(tmp_path: Path) -> None:
    """An event with ts='' gets a UTC ISO-8601 timestamp."""
    log = AuditLog(tmp_path / "audit.jsonl")
    ev = _make_event()
    assert ev.ts == ""
    log.append(ev)
    assert ev.ts.endswith("Z")
    assert "T" in ev.ts  # ISO-8601 date-time separator


def test_append_sets_prev_hash_to_previous_event(tmp_path: Path) -> None:
    """prev_hash of event N is the hash of event N-1."""
    log = AuditLog(tmp_path / "audit.jsonl")
    a = log.append(_make_event(args={"cmd": "ls"}))
    b = log.append(_make_event(args={"cmd": "pwd"}))
    assert a.prev_hash == GENESIS_PREV_HASH
    assert b.prev_hash == a.hash
    # b.prev_hash equals a.hash by chain design (b.prev_hash IS a.hash).
    # The interesting property is that a and b themselves hash differently
    # (different payloads).
    assert a.hash != b.hash


def test_append_sets_hash_deterministically(tmp_path: Path) -> None:
    """Hash is reproducible: same payload + prev_hash => same hash."""
    log = AuditLog(tmp_path / "audit.jsonl")
    a = log.append(_make_event(args={"cmd": "ls"}))
    b = log.append(_make_event(args={"cmd": "ls"}))
    # Different prev_hash (chained) so hashes differ.
    assert a.hash != b.hash
    # But each is sha256 of a known payload.
    assert len(a.hash) == 64
    assert all(c in "0123456789abcdef" for c in a.hash)


def test_same_event_same_prev_hash_yields_same_hash(tmp_path: Path) -> None:
    """Hashing a payload with the same prev_hash is deterministic across logs."""
    payload = _make_event(args={"cmd": "ls"}).to_dict(include_hash=False)
    h = _compute_hash(payload, "f" * 64)
    assert h == _compute_hash(payload, "f" * 64)


# --------------------------------------------------------------------------- #
# AuditLog.verify
# --------------------------------------------------------------------------- #


def test_verify_empty_log_is_ok(tmp_path: Path) -> None:
    """A fresh log (no events) verifies as OK."""
    log = AuditLog(tmp_path / "audit.jsonl")
    result = log.verify()
    assert isinstance(result, AuditVerifyResult)
    assert result.ok is True
    assert result.total_events == 0


def test_verify_after_three_appends_is_ok(tmp_path: Path) -> None:
    """A 3-event chain verifies as OK."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for cmd in ("ls", "pwd", "whoami"):
        log.append(_make_event(args={"cmd": cmd}))
    assert log.verify().ok is True


def test_verify_detects_tampered_hash(tmp_path: Path) -> None:
    """A corrupted ``hash`` field is caught and reported with the right index."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(_make_event(args={"cmd": "ls"}))
    log.append(_make_event(args={"cmd": "pwd"}))
    log.append(_make_event(args={"cmd": "whoami"}))

    # Tamper with the hash of the second event.
    lines = path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[1])
    obj["hash"] = "0" * 64
    lines[1] = json.dumps(obj, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Re-load and verify.
    fresh = AuditLog(path)
    result = fresh.verify()
    assert result.ok is False
    assert result.first_bad_index == 1
    assert result.reason is not None
    assert "hash" in result.reason.lower()


def test_verify_detects_tampered_args(tmp_path: Path) -> None:
    """Editing the ``args`` field without re-hashing breaks the chain."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(_make_event(args={"cmd": "ls"}))
    log.append(_make_event(args={"cmd": "pwd"}))

    lines = path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[1])
    # Silently swap the command, but keep the original hash.
    obj["args"] = {"cmd": "rm -rf /"}
    lines[1] = json.dumps(obj, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    fresh = AuditLog(path)
    result = fresh.verify()
    assert result.ok is False
    assert result.first_bad_index == 1
    assert "hash" in (result.reason or "").lower()


def test_load_tolerates_partial_last_line(tmp_path: Path) -> None:
    """A truncated last line from a crash is skipped on load."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(_make_event(args={"cmd": "ls"}))
    log.append(_make_event(args={"cmd": "pwd"}))

    # Append a malformed partial line (simulating a crash mid-write).
    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts": "2026-06-02T11:00:00Z", "session_id": "s1", "ty')

    # Loading must not raise; the partial line is dropped.
    fresh = AuditLog(path)
    assert len(fresh) == 2
    assert fresh.verify().ok is True


# --------------------------------------------------------------------------- #
# AuditLog.tail
# --------------------------------------------------------------------------- #


def test_tail_returns_last_n(tmp_path: Path) -> None:
    """tail(2) returns the last two events in order."""
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.append(_make_event(args={"cmd": f"echo {i}"}))
    tail = log.tail(2)
    assert len(tail) == 2
    assert tail[0].args == {"cmd": "echo 3"}
    assert tail[1].args == {"cmd": "echo 4"}


def test_tail_n_larger_than_log(tmp_path: Path) -> None:
    """tail(N) where N > len returns all events."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_make_event(args={"cmd": "ls"}))
    tail = log.tail(99)
    assert len(tail) == 1


# --------------------------------------------------------------------------- #
# AuditLog.export
# --------------------------------------------------------------------------- #


def test_export_jsonl_returns_file_contents(tmp_path: Path) -> None:
    """export('jsonl') returns the raw on-disk file contents."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(_make_event(args={"cmd": "ls"}))
    log.append(_make_event(args={"cmd": "pwd"}))

    exported = log.export("jsonl")
    assert exported == path.read_text(encoding="utf-8")
    assert exported.count("\n") == 2


def test_export_csv_has_expected_header_and_rows(tmp_path: Path) -> None:
    """export('csv') returns a CSV with the locked header and one row per event."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_make_event(args={"cmd": "ls"}))
    log.append(_make_event(args={"cmd": "pwd"}))

    csv_text = log.export("csv")
    lines = csv_text.strip().splitlines()
    assert lines[0] == "ts,session_id,type,tool,args,result,hash"
    assert len(lines) == 3  # header + 2 rows
    # The ``args`` cell contains a JSON string (escaped, quoted).
    assert "{" in lines[1]
    assert "cmd" in lines[1]
    # Hash is the last column.
    assert lines[1].rsplit(",", 1)[-1] != ""


def test_export_unknown_format_raises(tmp_path: Path) -> None:
    """Unknown formats are rejected loudly (v0.2 will add otel/...)."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_make_event())
    with pytest.raises(ValueError, match="Unknown export format"):
        log.export("otel")


# --------------------------------------------------------------------------- #
# Re-load round trip (persistence)
# --------------------------------------------------------------------------- #


def test_events_persist_across_instances(tmp_path: Path) -> None:
    """A second AuditLog on the same file sees the prior events."""
    path = tmp_path / "audit.jsonl"
    a = AuditLog(path)
    a.append(_make_event(args={"cmd": "ls"}))
    a.append(_make_event(args={"cmd": "pwd"}))

    b = AuditLog(path)
    assert len(b) == 2
    assert b.verify().ok is True
    tail = b.tail(2)
    assert tail[0].args == {"cmd": "ls"}
    assert tail[1].args == {"cmd": "pwd"}
