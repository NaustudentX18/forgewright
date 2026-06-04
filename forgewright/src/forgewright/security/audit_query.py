"""Simple audit-log query language (v0.2).

Expressions are a conjunction of ``field=value`` clauses joined by ``AND``
(case-insensitive). Example::

    tool=bash AND approved=false

Values ``true``, ``false``, and ``null`` are coerced to Python literals.
The ``tool`` field is compared case-insensitively. Nested fields use dot
notation (``user_consent.mode=approve-each``). The alias ``approved``
reads ``user_consent.approved`` when not set at the top level.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["event_matches_query", "filter_events", "parse_audit_query"]

_AND_SPLIT = re.compile(r"\s+AND\s+", re.IGNORECASE)


def parse_audit_query(expr: str) -> list[tuple[str, str]]:
    """Parse a query string into ``(field, value)`` clauses.

    Raises:
        ValueError: On empty input or malformed clauses.
    """
    text = expr.strip()
    if not text:
        raise ValueError("empty query expression")

    clauses: list[tuple[str, str]] = []
    for raw in _AND_SPLIT.split(text):
        part = raw.strip()
        if not part:
            raise ValueError("empty clause between AND operators")
        if "=" not in part:
            raise ValueError(f"expected field=value, got {part!r}")
        field, _, value = part.partition("=")
        field = field.strip()
        value = value.strip()
        if not field:
            raise ValueError(f"missing field name in clause {part!r}")
        if not value:
            raise ValueError(f"missing value in clause {part!r}")
        clauses.append((field, value))
    return clauses


def _coerce_literal(raw: str) -> Any:
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    return raw


def _get_field_value(event: dict[str, Any], field: str) -> Any:
    if "." in field:
        cur: Any = event
        for part in field.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    if field == "approved":
        if field in event:
            return event[field]
        consent = event.get("user_consent")
        if isinstance(consent, dict) and "approved" in consent:
            return consent["approved"]

    return event.get(field)


def _values_equal(actual: Any, expected: Any, *, field: str) -> bool:
    if expected is False and actual is None:
        return True
    if expected is True and actual is None:
        return False
    if actual is None:
        return expected is None

    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return actual == expected
        if isinstance(actual, str):
            low = actual.lower()
            if low in ("true", "false"):
                return (low == "true") == expected
        return False

    if field == "tool":
        return str(actual).casefold() == str(expected).casefold()

    return str(actual) == str(expected)


def event_matches_query(event: dict[str, Any], clauses: list[tuple[str, str]]) -> bool:
    """Return True if ``event`` satisfies every clause."""
    for field, raw_value in clauses:
        expected = _coerce_literal(raw_value)
        actual = _get_field_value(event, field)
        if not _values_equal(actual, expected, field=field):
            return False
    return True


def filter_events(events: list[dict[str, Any]], expr: str) -> list[dict[str, Any]]:
    """Return events from ``events`` that match ``expr``."""
    clauses = parse_audit_query(expr)
    return [ev for ev in events if event_matches_query(ev, clauses)]
