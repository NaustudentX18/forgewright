"""Tests for ``forgewright resume ...``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import typer
from forgewright.cli.run_resume import resume_command
from forgewright.session import Session
from typer.testing import CliRunner


# Build a minimal Typer app that mirrors what ``cli/app.py`` does.
# We can't use the root app directly because it spawns a REPL on
# import; we want a unit test that exits as soon as the command
# dispatches to the REPL.
#
# We need a sibling command so the app behaves as a Typer *group*;
# with only one command, Typer auto-dispatches and ignores the
# command name, so the ``["resume", "..."]`` invocation pattern
# wouldn't work.
def _noop() -> None:  # pragma: no cover - registration shim only
    """Sibling command so the app behaves as a Typer group."""


app = typer.Typer(help="forgewright test app (resume dispatcher only)")
app.command(name="resume")(resume_command)
app.command(name="_noop")(_noop)

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _seed_session(
    sessions_dir: Path,
    sid: str = "abc123",
    updated_at: str = "2026-06-02T00:00:00Z",
    n_messages: int = 1,
) -> Session:
    """Write a session to ``sessions_dir`` and return it."""
    s = Session(
        id=sid,
        created_at="2026-06-01T00:00:00Z",
        updated_at=updated_at,
        messages=[{"role": "user", "content": "previous turn"}] * n_messages,  # type: ignore[list-item]
    )
    s.save(sessions_dir)
    return s


# --------------------------------------------------------------------------- #
# resume_command
# --------------------------------------------------------------------------- #


def test_resume_last_opens_repl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``forgewright resume last`` opens the REPL with the most recent session.

    The test stubs out :func:`repl_main` so we don't actually start a
    REPL — we just assert the command dispatched into it with the
    loaded session and that the session id was mentioned in the
    pre-REPL banner.
    """
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _seed_session(sessions_dir, sid="latestone", updated_at="2026-06-02T00:00:00Z")

    # Redirect the default sessions dir to tmp_path.
    monkeypatch.setattr("forgewright.cli.run_resume.default_sessions_dir", lambda: sessions_dir)

    captured: dict[str, Any] = {}

    def fake_repl_main(initial_session: Session | None = None) -> int:
        captured["session"] = initial_session
        # Mirror what the real command does: typer.Exit(0) after the
        # REPL finishes.
        return 0

    monkeypatch.setattr("forgewright.cli.run_resume.repl_main", fake_repl_main)

    result = runner.invoke(app, ["resume", "last"], catch_exceptions=False)
    # typer.Exit(code) sets the runner's exit_code, so 0 == success.
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert captured["session"] is not None
    assert captured["session"].id == "latestone"
    # The session id is shown in the banner before the REPL starts.
    out = (result.stdout or "") + (result.stderr or "")
    assert "latestone" in out


def test_resume_explicit_id_opens_repl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``forgewright resume <id>`` opens the matching session."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _seed_session(sessions_dir, sid="alpha", updated_at="2026-06-01T00:00:00Z")
    _seed_session(sessions_dir, sid="beta", updated_at="2026-06-02T00:00:00Z")

    monkeypatch.setattr("forgewright.cli.run_resume.default_sessions_dir", lambda: sessions_dir)

    captured: dict[str, Any] = {}

    def fake_repl_main(initial_session: Session | None = None) -> int:
        captured["session"] = initial_session
        return 0

    monkeypatch.setattr("forgewright.cli.run_resume.repl_main", fake_repl_main)

    result = runner.invoke(app, ["resume", "alpha"], catch_exceptions=False)
    assert result.exit_code == 0
    assert captured["session"].id == "alpha"


def test_resume_nonexistent_session_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``forgewright resume <missing>`` exits 1 and does not start the REPL."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr("forgewright.cli.run_resume.default_sessions_dir", lambda: sessions_dir)

    repl_called: dict[str, bool] = {"v": False}

    def fake_repl_main(initial_session: Session | None = None) -> int:
        repl_called["v"] = True
        return 0

    monkeypatch.setattr("forgewright.cli.run_resume.repl_main", fake_repl_main)

    result = runner.invoke(app, ["resume", "does-not-exist"], catch_exceptions=False)
    assert result.exit_code != 0
    assert repl_called["v"] is False
    out = (result.stdout or "") + (result.stderr or "")
    assert "does-not-exist" in out


def test_resume_last_with_no_saved_sessions_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``forgewright resume last`` with no sessions exits 1."""
    sessions_dir = tmp_path / "empty"
    sessions_dir.mkdir()
    monkeypatch.setattr("forgewright.cli.run_resume.default_sessions_dir", lambda: sessions_dir)

    repl_called: dict[str, bool] = {"v": False}

    def fake_repl_main(initial_session: Session | None = None) -> int:
        repl_called["v"] = True
        return 0

    monkeypatch.setattr("forgewright.cli.run_resume.repl_main", fake_repl_main)

    result = runner.invoke(app, ["resume", "last"], catch_exceptions=False)
    assert result.exit_code != 0
    assert repl_called["v"] is False
    out = (result.stdout or "") + (result.stderr or "")
    assert "No saved sessions" in out


def test_resume_rejects_corrupt_session_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A corrupt session file makes ``resume <id>`` exit non-zero."""

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "corrupt.json").write_text("{not json")
    monkeypatch.setattr("forgewright.cli.run_resume.default_sessions_dir", lambda: sessions_dir)

    repl_called: dict[str, bool] = {"v": False}

    def fake_repl_main(initial_session: Session | None = None) -> int:
        repl_called["v"] = True
        return 0

    monkeypatch.setattr("forgewright.cli.run_resume.repl_main", fake_repl_main)

    result = runner.invoke(app, ["resume", "corrupt"], catch_exceptions=False)
    assert result.exit_code != 0
    assert repl_called["v"] is False
