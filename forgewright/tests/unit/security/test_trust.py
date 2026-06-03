"""Tests for :mod:`forgewright.security.trust`."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from forgewright.security.trust import (
    TrustRegistry,
    TrustRule,
    TrustScope,
    derive_pattern,
    toml_quote,
)

# ---------------------------------------------------------------------------
# Match semantics
# ---------------------------------------------------------------------------


def test_add_and_is_allowed_exact(tmp_path: Path) -> None:
    """Adding ``ls`` allows the bare command."""
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls")
    assert r.is_allowed("ls") is True


def test_add_and_is_allowed_prefix_match(tmp_path: Path) -> None:
    """A literal (non-wildcard) pattern matches a longer command if it
    starts with ``"<pattern> "``.
    """
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls")
    assert r.is_allowed("ls -la") is True
    assert r.is_allowed("ls -la /tmp") is True


def test_add_does_not_match_unrelated_prefix(tmp_path: Path) -> None:
    """``lsof`` must not pass just because ``ls`` is trusted."""
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls")
    assert r.is_allowed("lsof") is False
    assert r.is_allowed("lsass") is False


def test_glob_pattern_matches_args(tmp_path: Path) -> None:
    """A pattern with ``*`` is an :mod:`fnmatch` glob."""
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("git *")
    assert r.is_allowed("git status") is True
    assert r.is_allowed("git log -5") is True
    assert r.is_allowed("git") is False  # glob requires something after git
    assert r.is_allowed("github-cli status") is False


def test_question_mark_glob(tmp_path: Path) -> None:
    """``?`` is the single-character fnmatch wildcard."""
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls?")
    assert r.is_allowed("lsa") is True
    assert r.is_allowed("lsab") is False  # only single char beyond ls


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_list_rules_returns_added(tmp_path: Path) -> None:
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls")
    r.add("git *")
    rules = r.list_rules()
    assert len(rules) == 2
    patterns = {rule.pattern for rule in rules}
    assert patterns == {"ls", "git *"}


def test_remove_returns_true_and_revokes(tmp_path: Path) -> None:
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls")
    assert r.remove("ls") is True
    assert r.is_allowed("ls") is False
    assert r.is_allowed("ls -la") is False


def test_remove_nonexistent_returns_false(tmp_path: Path) -> None:
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    assert r.remove("never_added") is False


def test_clear_session_drops_only_session_rules(tmp_path: Path) -> None:
    r = TrustRegistry(machine_path=tmp_path / "trust.toml")
    r.add("ls", scope=TrustScope.MACHINE, reason="always")
    r.add("pytest *", scope=TrustScope.SESSION, reason="ephemeral")
    r.clear_session()
    patterns = {rule.pattern for rule in r.list_rules()}
    assert "ls" in patterns
    assert "pytest *" not in patterns


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------


def test_machine_scope_persists_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "trust.toml"
    r = TrustRegistry(machine_path=path)
    r.add("echo", scope=TrustScope.MACHINE, reason="smoke test")
    assert path.exists()
    with path.open("rb") as f:
        data = tomllib.load(f)
    assert "rule" in data
    patterns = {entry["pattern"] for entry in data["rule"]}
    assert "echo" in patterns


def test_session_scope_does_not_persist(tmp_path: Path) -> None:
    path = tmp_path / "trust.toml"
    r = TrustRegistry(machine_path=path)
    r.add("ls", scope=TrustScope.SESSION)
    # Nothing on disk.
    assert not path.exists()
    # But still in memory.
    assert r.is_allowed("ls") is True


def test_toml_round_trip(tmp_path: Path) -> None:
    """Write two rules, load a fresh registry, verify they're there."""
    path = tmp_path / "trust.toml"
    r1 = TrustRegistry(machine_path=path)
    r1.add("ls", scope=TrustScope.MACHINE, reason="r1")
    r1.add("git *", scope=TrustScope.MACHINE, reason="r1")
    r2 = TrustRegistry(machine_path=path)
    rules = {rule.pattern: rule for rule in r2.list_rules()}
    assert rules["ls"].scope == TrustScope.MACHINE
    assert rules["ls"].reason == "r1"
    assert rules["git *"].scope == TrustScope.MACHINE
    # And matching still works.
    assert r2.is_allowed("ls -la") is True
    assert r2.is_allowed("git status") is True


def test_remove_persists_deletion(tmp_path: Path) -> None:
    path = tmp_path / "trust.toml"
    r1 = TrustRegistry(machine_path=path)
    r1.add("ls")
    r1.add("cat")
    r1.remove("ls")
    r2 = TrustRegistry(machine_path=path)
    patterns = {rule.pattern for rule in r2.list_rules()}
    assert "ls" not in patterns
    assert "cat" in patterns


def test_handles_missing_or_malformed_toml(tmp_path: Path) -> None:
    """A corrupt trust.toml must not crash the registry."""
    path = tmp_path / "trust.toml"
    path.write_text("this is = not = valid = toml [[[", encoding="utf-8")
    r = TrustRegistry(machine_path=path)
    # No rules loaded, but the registry is usable.
    assert r.list_rules() == []
    r.add("ls")
    assert r.is_allowed("ls") is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_derive_pattern_basic() -> None:
    assert derive_pattern("ls -la /tmp") == "ls *"
    assert derive_pattern("git status") == "git *"


def test_derive_pattern_strips_path_prefix() -> None:
    assert derive_pattern("/usr/bin/git status") == "git *"


def test_derive_pattern_handles_empty() -> None:
    assert derive_pattern("") == ""
    assert derive_pattern("   ") == ""


def test_toml_quote_escapes() -> None:
    assert toml_quote("plain") == '"plain"'
    assert toml_quote('with "quote"') == '"with \\"quote\\""'
    assert toml_quote("back\\slash") == '"back\\\\slash"'


# ---------------------------------------------------------------------------
# TrustRule dataclass
# ---------------------------------------------------------------------------


def test_trustrule_is_frozen() -> None:
    rule = TrustRule(pattern="ls", scope=TrustScope.MACHINE, added_at="2026-06-02T00:00:00Z")
    with pytest.raises((AttributeError, Exception)):
        rule.pattern = "cat"  # type: ignore[misc]


def test_trustrule_to_toml_dict() -> None:
    rule = TrustRule(
        pattern="ls",
        scope=TrustScope.MACHINE,
        added_at="2026-06-02T00:00:00Z",
        reason="test",
    )
    d = rule.to_toml_dict()
    assert d == {
        "pattern": "ls",
        "scope": "machine",
        "added_at": "2026-06-02T00:00:00Z",
        "reason": "test",
    }
