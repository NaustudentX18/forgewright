"""Simple audit-log query language (v0.2).

Expressions are a conjunction of ``field=value`` clauses joined by ``AND``
(case-insensitive). Example::

    tool=bash AND approved=false

Values may be bare (``bash``) or double-quoted (``"foo AND bar"``) so
that whitespace and the literal substring `` AND `` can appear inside
a value. Inside a quoted value, ``\\`` and ``\\"`` are escape sequences.
The ``AND`` keyword is only recognised outside of quotes.

Values ``true``, ``false``, and ``null`` are coerced to Python literals.
The ``tool`` field is compared case-insensitively. Nested fields use dot
notation (``user_consent.mode=approve-each``). The alias ``approved``
reads ``user_consent.approved`` when not set at the top level.
"""

from __future__ import annotations

from typing import Any

__all__ = ["event_matches_query", "filter_events", "parse_audit_query"]


def _skip_ws(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos].isspace():
        pos += 1
    return pos


def _parse_bare_value(text: str, pos: int) -> tuple[str, int]:
    """Read a bare (unquoted) value starting at ``pos``.

    Returns ``(value, new_pos)``. The value runs to the next whitespace
    or end-of-input. Empty values are not returned — the caller
    distinguishes empty from missing.
    """
    n = len(text)
    start = pos
    while pos < n and not text[pos].isspace():
        pos += 1
    return text[start:pos], pos


def _parse_quoted_value(text: str, pos: int) -> tuple[str, int]:
    """Read a ``"…"`` value starting just after the opening quote.

    Returns ``(value, new_pos)`` where ``new_pos`` is positioned just
    after the closing quote. ``\\`` and ``\\"`` are recognised as
    escapes inside the string.
    """
    chars: list[str] = []
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch == "\\" and pos + 1 < n:
            chars.append(text[pos + 1])
            pos += 2
            continue
        if ch == '"':
            return "".join(chars), pos + 1
        chars.append(ch)
        pos += 1
    raise ValueError("unterminated quoted value")


def parse_audit_query(expr: str) -> list[tuple[str, str]]:
    """Parse a query string into ``(field, value)`` clauses.

    Raises:
        ValueError: On empty input, missing ``=``, missing value, an
            unterminated quoted value, or an ``AND`` that does not
            separate two clauses.
    """
    text = expr.strip()
    if not text:
        raise ValueError("empty query expression")

    clauses: list[tuple[str, str]] = []
    pos = _skip_ws(text, 0)
    n = len(text)
    expect_clause = True
    while pos < n:
        if not expect_clause:
            # We are between clauses: only ``AND`` is allowed here.
            rest = text[pos:]
            head = rest[:3]
            if not head or head[:3].upper() != "AND" or (len(rest) > 3 and not rest[3].isspace()):
                raise ValueError(f"expected AND between clauses, got {rest!r}")
            pos = _skip_ws(text, pos + 3)
            if pos >= n:
                raise ValueError("trailing AND with no clause")
            expect_clause = True
            continue

        # Parse one ``field=value``.
        eq = text.find("=", pos)
        if eq == -1:
            raise ValueError(f"expected field=value, got {text[pos:]!r}")
        field = text[pos:eq].strip()
        if not field:
            raise ValueError(f"missing field name in clause {text[pos:]!r}")
        pos = _skip_ws(text, eq + 1)
        if pos >= n:
            raise ValueError(f"missing value in clause for field {field!r}")
        if text[pos] == '"':
            value, pos = _parse_quoted_value(text, pos + 1)
        else:
            value, pos = _parse_bare_value(text, pos)
        if not value:
            raise ValueError(f"missing value in clause for field {field!r}")
        clauses.append((field, value))
        pos = _skip_ws(text, pos)
        expect_clause = False

    if expect_clause is False and not clauses:
        # No clauses parsed at all (e.g. expression was just whitespace,
        # which the leading ``strip`` already handles, but be explicit).
        raise ValueError("empty query expression")
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
