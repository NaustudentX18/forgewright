"""Tamper-evident, sha256-chained JSONL audit log.

Each line of ``audit.jsonl`` is one event. The hash chain is:

    hash_n = sha256(
        json.dumps(event_n_with_hash_None, sort_keys=True).encode()
        + prev_hash_n.encode()
    ).hexdigest()

The first event has ``prev_hash = "0" * 64``. The file is opened with
``O_APPEND`` (via Python's append mode) so concurrent writers from
separate processes don't interleave. Every write is flushed to disk for
crash safety.

This is Phase 10 of BUILD_PLAN.md; Phase 11 (REPL) will need a callable
interface (``log_event(event_dict)``) that hashes + appends in a
thread-safe manner. That interface is the public :meth:`AuditLog.append`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forgewright.logger import logger
from forgewright.security.audit_query import event_matches_query, parse_audit_query

__all__ = ["AuditEvent", "AuditLog", "AuditVerifyResult"]


# 64-char hex string used as the prev_hash of the very first event.
_GENESIS_PREV_HASH: str = "0" * 64


def _utc_now_iso() -> str:
    """Return an ISO-8601 timestamp in UTC with a ``Z`` suffix.

    Python's :py:meth:`datetime.isoformat` renders UTC as ``+00:00``;
    the audit-log schema (ARCHITECTURE.md §11.2, SECURITY.md §9) uses
    ``Z`` for human readability, so we translate.
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _compute_hash(event_dict: dict[str, Any], prev_hash: str) -> str:
    """Compute the sha256 chain hash for an event payload.

    Per the spec:

        hash = sha256(
            json.dumps({**event, "hash": None}, sort_keys=True).encode()
            + prev_hash.encode()
        ).hexdigest()
    """
    payload = {**event_dict, "hash": None}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded + prev_hash.encode("utf-8")).hexdigest()


@dataclass
class AuditEvent:
    """A single audit-log event.

    Mirrors the schema in ARCHITECTURE.md §11.2 and SECURITY.md §9.
    Optional fields default to ``None``/empty so tool call sites can
    build an event with just the required fields.
    """

    ts: str = ""
    session_id: str = ""
    type: str = ""
    actor: dict[str, str] = field(default_factory=dict)
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    user_consent: dict[str, Any] | None = None
    prev_hash: str = ""
    hash: str = ""

    def to_dict(self, include_hash: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Drops ``None`` optionals so the on-disk representation is tight.
        When ``include_hash`` is False, the ``hash`` field is omitted
        (used when recomputing the chain during verify).
        """
        out: dict[str, Any] = {
            "ts": self.ts,
            "session_id": self.session_id,
            "type": self.type,
            "actor": dict(self.actor),
        }
        if self.tool is not None:
            out["tool"] = self.tool
        if self.args is not None:
            out["args"] = self.args
        if self.result is not None:
            out["result"] = self.result
        if self.user_consent is not None:
            out["user_consent"] = self.user_consent
        out["prev_hash"] = self.prev_hash
        if include_hash:
            out["hash"] = self.hash
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditEvent:
        """Build an :class:`AuditEvent` from a JSON dict (loaded from disk)."""
        return cls(
            ts=d.get("ts", ""),
            session_id=d.get("session_id", ""),
            type=d.get("type", ""),
            actor=dict(d.get("actor", {})),
            tool=d.get("tool"),
            args=d.get("args"),
            result=d.get("result"),
            user_consent=d.get("user_consent"),
            prev_hash=d.get("prev_hash", ""),
            hash=d.get("hash", ""),
        )


@dataclass
class AuditVerifyResult:
    """Outcome of :meth:`AuditLog.verify`."""

    ok: bool
    total_events: int
    first_bad_index: int | None = None
    reason: str | None = None


class AuditLog:
    """Append-only, sha256-chained JSONL audit log.

    Thread/Process safety: appends open the file in append mode
    (``O_APPEND``) so concurrent writers from separate processes do not
    interleave lines; within a single process, Python's GIL plus the
    short critical section (open/write/close) is sufficient. For Phase
    11's REPL, a single :class:`AuditLog` instance per session is the
    intended usage.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._events: list[AuditEvent] = []
        self._load_existing()

    # ------------------------------------------------------------------ #
    # I/O
    # ------------------------------------------------------------------ #

    def _load_existing(self) -> None:
        """Load any existing events from disk into memory.

        On load we run :meth:`verify` and log a warning if the chain is
        broken — we don't raise because the writer is for appending new
        events, not for fixing a corrupted log.
        """
        if not self.path.exists():
            # Create the file (and parents) so subsequent appends are
            # plain ``open(... "a")`` calls without race windows.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch()
            return

        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Tolerant of a partial last line from a crash.
                    logger.warning(
                        "audit.load: skipping invalid JSON at line {} (likely "
                        "truncated tail from a crash)",
                        line_no,
                    )
                    continue
                events.append(AuditEvent.from_dict(obj))

        self._events = events

        result = self.verify()
        if not result.ok:
            logger.warning(
                "audit.load: existing chain is broken at line {}: {}",
                result.first_bad_index,
                result.reason,
            )

    def append(self, event: AuditEvent) -> AuditEvent:
        """Stamp ``prev_hash`` + ``hash`` + ``ts`` and append.

        Steps:
          1. If ``event.ts`` is empty, set it to ``_utc_now_iso()``.
          2. Set ``event.prev_hash`` to the last event's ``hash``
             (or the genesis zeros for the first event).
          3. Compute ``event.hash`` per the spec.
          4. Append to in-memory list.
          5. Write one JSON line to disk and flush.

        Returns the same event with the chain fields populated, so
        callers can include it in reports/logs.
        """
        if not event.ts:
            event.ts = _utc_now_iso()
        if self._events:
            event.prev_hash = self._events[-1].hash
        else:
            event.prev_hash = _GENESIS_PREV_HASH
        event.hash = _compute_hash(event.to_dict(include_hash=False), event.prev_hash)

        self._events.append(event)

        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(include_hash=True), ensure_ascii=False))
            f.write("\n")
            f.flush()

        return event

    def tail(self, n: int = 10) -> list[AuditEvent]:
        """Return the last ``n`` events (or all of them if fewer)."""
        if n <= 0:
            return []
        return list(self._events[-n:])

    def query(self, expr: str) -> list[AuditEvent]:
        """Return events matching a simple ``field=value [AND ...]`` expression."""
        clauses = parse_audit_query(expr)
        return [
            ev
            for ev in self._events
            if event_matches_query(ev.to_dict(include_hash=True), clauses)
        ]

    def __len__(self) -> int:
        return len(self._events)

    # ------------------------------------------------------------------ #
    # Verification
    # ------------------------------------------------------------------ #

    def verify(self) -> AuditVerifyResult:
        """Recompute the chain and return a :class:`AuditVerifyResult`.

        Checks, in order:
          1. Each event's ``prev_hash`` matches the prior event's
             ``hash`` (or genesis zeros for index 0).
          2. Each event's ``hash`` matches
             ``_compute_hash(event_minus_hash, prev_hash)``.

        On failure, ``first_bad_index`` is the 0-based line number of
        the first event that failed, and ``reason`` is a short
        explanation. The function short-circuits at the first error.
        """
        prev_hash = _GENESIS_PREV_HASH
        for idx, event in enumerate(self._events):
            if event.prev_hash != prev_hash:
                return AuditVerifyResult(
                    ok=False,
                    total_events=len(self._events),
                    first_bad_index=idx,
                    reason=(
                        f"prev_hash mismatch at event {idx}: "
                        f"expected {prev_hash!r}, got {event.prev_hash!r}"
                    ),
                )
            expected = _compute_hash(event.to_dict(include_hash=False), event.prev_hash)
            if event.hash != expected:
                return AuditVerifyResult(
                    ok=False,
                    total_events=len(self._events),
                    first_bad_index=idx,
                    reason=(
                        f"hash mismatch at event {idx}: expected {expected!r}, got {event.hash!r}"
                    ),
                )
            prev_hash = event.hash
        return AuditVerifyResult(ok=True, total_events=len(self._events))

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #

    def export(self, fmt: str = "jsonl") -> str:
        """Render the log in the requested format.

        * ``"jsonl"`` — raw on-disk contents (one JSON object per line).
        * ``"csv"``   — header + one row per event. ``args`` and
          ``result`` are rendered as compact JSON strings in a single
          cell so the CSV stays flat and round-trips through Excel.

        OpenTelemetry and other formats are deferred to v0.2.
        """
        if fmt == "jsonl":
            if not self.path.exists():
                return ""
            return self.path.read_text(encoding="utf-8")

        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ts", "session_id", "type", "tool", "args", "result", "hash"])
            for ev in self._events:
                writer.writerow(
                    [
                        ev.ts,
                        ev.session_id,
                        ev.type,
                        ev.tool or "",
                        json.dumps(ev.args, ensure_ascii=False, sort_keys=True)
                        if ev.args is not None
                        else "",
                        json.dumps(ev.result, ensure_ascii=False, sort_keys=True)
                        if ev.result is not None
                        else "",
                        ev.hash,
                    ]
                )
            return buf.getvalue()

        raise ValueError(f"Unknown export format: {fmt!r} (supported: jsonl, csv)")
