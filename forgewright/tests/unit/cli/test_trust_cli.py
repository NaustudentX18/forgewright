"""Tests for the ``forgewright trust`` CLI dispatcher."""

from __future__ import annotations

from pathlib import Path

import pytest
from forgewright.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """``get_settings()`` is lru_cache'd; clear it between tests."""
    from forgewright.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def isolated_trust_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Settings.security.trust`` at a temp file for the test."""
    path = tmp_path / "trust.toml"
    monkeypatch.setenv("FORGEWRIGHT_SECURITY__TRUST", str(path))
    return path


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------


def test_trust_ls_prints_table(isolated_trust_path: Path) -> None:
    """`forgewright trust ls` shows registered rules in a table."""
    from forgewright.security.trust import TrustRegistry, TrustScope

    TrustRegistry(machine_path=isolated_trust_path).add("ls", scope=TrustScope.MACHINE)

    result = runner.invoke(app, ["trust", "ls"])
    assert result.exit_code == 0, (result.stdout, getattr(result, "stderr", ""))
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "ls" in out
    assert "machine" in out


def test_trust_ls_empty(isolated_trust_path: Path) -> None:
    """Empty registry prints a friendly message and exits 0."""
    result = runner.invoke(app, ["trust", "ls"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "No trust rules" in out or "0 rules" in out


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_trust_add_creates_rule(isolated_trust_path: Path) -> None:
    """`forgewright trust add "ls"` writes a rule and exits 0."""
    result = runner.invoke(app, ["trust", "add", "ls"])
    assert result.exit_code == 0, (result.stdout, getattr(result, "stderr", ""))
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "Added" in out or "ls" in out
    # The file should now exist.
    assert isolated_trust_path.exists()


def test_trust_add_without_pattern_exits_nonzero(
    isolated_trust_path: Path,
) -> None:
    """`forgewright trust add` with no pattern fails fast."""
    result = runner.invoke(app, ["trust", "add"])
    assert result.exit_code != 0


def test_trust_add_with_glob(isolated_trust_path: Path) -> None:
    """Glob patterns are accepted (passed through verbatim)."""
    result = runner.invoke(app, ["trust", "add", "git *"])
    assert result.exit_code == 0
    assert isolated_trust_path.exists()


def test_trust_add_session_scope_does_not_write(
    isolated_trust_path: Path,
) -> None:
    """Session-scoped rules live in memory only."""
    result = runner.invoke(app, ["trust", "add", "ls", "--scope", "session"])
    assert result.exit_code == 0
    assert not isolated_trust_path.exists()


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------


def test_trust_rm_removes_rule(isolated_trust_path: Path) -> None:
    """`forgewright trust rm "ls"` deletes a rule and exits 0."""
    from forgewright.security.trust import TrustRegistry, TrustScope

    TrustRegistry(machine_path=isolated_trust_path).add("ls", scope=TrustScope.MACHINE)

    result = runner.invoke(app, ["trust", "rm", "ls"])
    assert result.exit_code == 0, (result.stdout, getattr(result, "stderr", ""))
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "Removed" in out or "ls" in out


def test_trust_rm_without_pattern_exits_nonzero(
    isolated_trust_path: Path,
) -> None:
    result = runner.invoke(app, ["trust", "rm"])
    assert result.exit_code != 0


def test_trust_rm_nonexistent_exits_nonzero(isolated_trust_path: Path) -> None:
    result = runner.invoke(app, ["trust", "rm", "nonexistent_pattern"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# clear-session
# ---------------------------------------------------------------------------


def test_trust_clear_session(isolated_trust_path: Path) -> None:
    result = runner.invoke(app, ["trust", "clear-session"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "Cleared" in out or "session" in out.lower()


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------


def test_trust_unknown_action_exits_2(isolated_trust_path: Path) -> None:
    result = runner.invoke(app, ["trust", "frobnicate"])
    assert result.exit_code == 2


def test_trust_help_works() -> None:
    result = runner.invoke(app, ["trust", "--help"])
    assert result.exit_code == 0
