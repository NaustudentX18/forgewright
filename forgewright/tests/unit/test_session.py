"""Tests for :mod:`forgewright.session`."""

from __future__ import annotations

import json
import re
from pathlib import Path

from forgewright.schema import ChatMessage
from forgewright.session import Session, default_sessions_dir, now_iso


def test_to_dict_from_dict_roundtrip() -> None:
    """A session round-trips through ``to_dict``/``from_dict`` unchanged."""
    s = Session(
        id="roundtrip-id",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T01:00:00Z",
        messages=[ChatMessage(role="user", content="hi")],
        metadata={"model": "stub-model", "k": 1},
    )
    data = s.to_dict()
    assert data["id"] == "roundtrip-id"
    assert data["created_at"] == "2026-06-02T00:00:00Z"
    assert data["schema_version"] == 1
    assert data["messages"] == [
        {"role": "user", "content": "hi", "tool_call_id": None, "name": None}
    ]
    assert data["metadata"] == {"model": "stub-model", "k": 1}

    rebuilt = Session.from_dict(data)
    assert rebuilt.id == s.id
    assert rebuilt.created_at == s.created_at
    assert rebuilt.updated_at == s.updated_at
    assert len(rebuilt.messages) == 1
    assert rebuilt.messages[0].role == "user"
    assert rebuilt.messages[0].content == "hi"
    assert rebuilt.metadata == s.metadata


def test_save_writes_json_file(tmp_path: Path) -> None:
    """``save`` writes a pretty-printed JSON file at the expected path."""
    s = Session(
        id="save-id",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
    )
    path = s.save(tmp_path)
    assert path == tmp_path / "save-id.json"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    # Pretty-printed (2-space indent) per the spec.
    assert "\n  " in text
    parsed = json.loads(text)
    assert parsed["id"] == "save-id"


def test_load_reads_saved_session(tmp_path: Path) -> None:
    """``load`` reads a session previously written with ``save``."""
    s = Session(
        id="load-id",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
        messages=[ChatMessage(role="assistant", content="ok")],
    )
    s.save(tmp_path)
    loaded = Session.load(tmp_path / "load-id.json")
    assert loaded.id == "load-id"
    assert len(loaded.messages) == 1
    assert loaded.messages[0].role == "assistant"
    assert loaded.messages[0].content == "ok"


def test_list_recent_sorted_by_updated_at_desc(tmp_path: Path) -> None:
    """``list_recent`` returns the N newest sessions first.

    ``save()`` bumps ``updated_at`` to the current time, so we hand-
    write the JSON for this test to keep the timestamps deterministic.
    """
    payloads = [
        {"id": "a", "created_at": "2026-06-01T00:00:00Z", "updated_at": "2026-06-01T00:00:00Z"},
        {"id": "b", "created_at": "2026-06-02T00:00:00Z", "updated_at": "2026-06-02T00:00:00Z"},
        {"id": "c", "created_at": "2026-06-01T12:00:00Z", "updated_at": "2026-06-01T12:00:00Z"},
    ]
    for payload in payloads:
        (tmp_path / f"{payload['id']}.json").write_text(json.dumps(payload))

    recent = Session.list_recent(tmp_path, limit=10)
    ids = [s.id for s in recent]
    assert ids == ["b", "c", "a"]


def test_list_recent_respects_limit(tmp_path: Path) -> None:
    """``list_recent(limit=N)`` returns at most N sessions."""
    for i in range(5):
        Session(
            id=f"s-{i}",
            created_at=f"2026-06-0{i + 1}T00:00:00Z",
            updated_at=f"2026-06-0{i + 1}T00:00:00Z",
        ).save(tmp_path)
    assert len(Session.list_recent(tmp_path, limit=2)) == 2


def test_default_timestamps_and_uuid() -> None:
    """A freshly-built session has a uuid id and ISO-8601 UTC timestamps."""
    s = Session.new()
    # 32 hex chars (uuid4().hex).
    assert re.fullmatch(r"[0-9a-f]{32}", s.id)
    iso = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
    assert re.fullmatch(iso, s.created_at)
    assert re.fullmatch(iso, s.updated_at)
    # Both timestamps equal at construction (created == updated).
    assert s.created_at == s.updated_at


def test_session_with_messages_round_trips_via_disk(tmp_path: Path) -> None:
    """A session with messages round-trips through save + load."""
    s = Session(
        id="with-msgs",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
        ],
    )
    s.save(tmp_path)
    loaded = Session.load(tmp_path / "with-msgs.json")
    assert len(loaded.messages) == 2
    assert loaded.messages[0].role == "user"
    assert loaded.messages[1].role == "assistant"
    assert loaded.messages[1].content == "hello"


def test_save_bumps_updated_at(tmp_path: Path) -> None:
    """``save`` updates ``updated_at`` to the current time."""
    s = Session(
        id="bump",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )
    s.save(tmp_path)
    loaded = Session.load(tmp_path / "bump.json")
    assert loaded.updated_at != "2020-01-01T00:00:00Z"
    assert loaded.created_at == "2020-01-01T00:00:00Z"  # unchanged


def test_now_iso_format() -> None:
    """``now_iso`` returns a string matching the documented format."""
    value = now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)


def test_default_sessions_dir_under_home() -> None:
    """``default_sessions_dir`` lives under the user's home directory."""
    p = default_sessions_dir()
    assert p.name == "sessions"
    assert p.parent.name == "forgewright"
    assert p.parent.parent.name == "share"


def test_list_recent_on_missing_dir_returns_empty(tmp_path: Path) -> None:
    """``list_recent`` on a nonexistent dir returns an empty list."""
    assert Session.list_recent(tmp_path / "does-not-exist", limit=10) == []


def test_list_recent_skips_corrupt_files(tmp_path: Path) -> None:
    """A single corrupt JSON file doesn't break the listing."""
    Session(
        id="good",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
    ).save(tmp_path)
    (tmp_path / "bad.json").write_text("{not valid json")
    sessions = Session.list_recent(tmp_path, limit=10)
    assert len(sessions) == 1
    assert sessions[0].id == "good"


def test_metadata_round_trips_with_arbitrary_keys(tmp_path: Path) -> None:
    """Arbitrary metadata keys survive the save/load round trip."""
    s = Session.new(metadata={"model": "claude-x", "k": 42, "nested": {"a": 1}})
    s.save(tmp_path)
    loaded = Session.load(tmp_path / f"{s.id}.json")
    assert loaded.metadata == {"model": "claude-x", "k": 42, "nested": {"a": 1}}


def test_session_accepts_dicts_for_messages() -> None:
    """The dataclass normalises dict-shaped messages to ``ChatMessage``."""
    s = Session(
        id="x",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
        messages=[{"role": "user", "content": "hi"}],  # type: ignore[list-item]
    )
    assert all(isinstance(m, ChatMessage) for m in s.messages)
    assert s.messages[0].content == "hi"


def test_uuid_helper_is_hex() -> None:
    """The default ``Session.new`` id is a 32-char hex string."""
    s = Session.new()
    # No dashes (uuid4().hex strips them).
    assert "-" not in s.id
    # Valid hex.
    int(s.id, 16)
    # And the right kind of uuid (uuid4 has version nibble 4).
    assert s.id[12] == "4"
