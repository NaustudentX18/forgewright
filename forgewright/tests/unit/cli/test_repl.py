"""Tests for :mod:`forgewright.cli.repl`."""

from __future__ import annotations

from pathlib import Path

import pytest
from forgewright.agent import Manus
from forgewright.cli.repl import (
    HELP_TABLE,
    ListInputProvider,
    SlashCommands,
    SlashResult,
    repl_loop,
)
from forgewright.config import LLMConfig, Settings
from forgewright.llm.stub import StubBackend
from forgewright.session import Session
from rich.console import Console

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_settings() -> Settings:
    """Build a fresh in-memory ``Settings`` instance for the test."""
    return Settings(llm=LLMConfig(provider="stub", model="stub-model"), max_steps=2)


def _make_console() -> Console:
    """A console that writes to a StringIO so tests can assert output."""
    from io import StringIO

    return Console(file=StringIO(), force_terminal=False, width=200, no_color=True)


def _make_agent(settings: Settings) -> Manus:
    return Manus(llm=StubBackend(settings.llm), max_steps=settings.max_steps)


def _make_slash(tmp_path: Path) -> SlashCommands:
    settings = _make_settings()
    agent = _make_agent(settings)
    session = Session.new(metadata={"model": settings.llm.model})
    return SlashCommands(
        session=session,
        agent=agent,
        settings=settings,
        console=_make_console(),
        sessions_dir=tmp_path,
    )


# --------------------------------------------------------------------------- #
# repl_loop
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_repl_loop_exit_returns_zero(tmp_path: Path) -> None:
    """``repl_loop`` returns 0 when the user types ``/exit``."""
    provider = ListInputProvider(["/exit"])
    code = await repl_loop(
        input_provider=provider,
        sessions_dir=tmp_path,
        settings=_make_settings(),
    )
    assert code == 0
    # The session was persisted to disk.
    files = list(tmp_path.glob("*.json"))
    assert files, "session file should have been written on /exit"


@pytest.mark.asyncio
async def test_repl_loop_eof_returns_zero(tmp_path: Path) -> None:
    """``repl_loop`` exits cleanly on EOF (empty input list)."""
    provider = ListInputProvider([])
    code = await repl_loop(
        input_provider=provider,
        sessions_dir=tmp_path,
        settings=_make_settings(),
    )
    assert code == 0


@pytest.mark.asyncio
async def test_repl_loop_initial_session_kept_on_exit(tmp_path: Path) -> None:
    """A pre-loaded session is preserved and re-saved on ``/exit``."""
    from forgewright.schema import ChatMessage

    s = Session(
        id="preserved",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
        messages=[ChatMessage(role="user", content="from before")],
    )
    provider = ListInputProvider(["/exit"])
    await repl_loop(
        initial_session=s,
        input_provider=provider,
        sessions_dir=tmp_path,
        settings=_make_settings(),
    )
    loaded = Session.load(tmp_path / "preserved.json")
    assert len(loaded.messages) == 1
    assert loaded.messages[0].content == "from before"


# --------------------------------------------------------------------------- #
# Slash command dispatch
# --------------------------------------------------------------------------- #


def test_slash_help_prints_command_table(tmp_path: Path) -> None:
    """``/help`` prints the slash command table."""
    slash = _make_slash(tmp_path)
    result = slash.dispatch("/help")
    assert result is SlashResult.CONTINUE
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    # The Markdown table is rendered; the cell text is preserved.
    assert "/help" in out
    assert "/exit" in out
    assert "/clear" in out
    assert "/resume" in out
    assert "/sessions" in out


def test_slash_clear_calls_console_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``/clear`` calls ``console.clear()``."""
    slash = _make_slash(tmp_path)
    called: dict[str, int] = {"n": 0}
    slash.console.clear = lambda: called.__setitem__("n", called["n"] + 1)  # type: ignore[method-assign]
    result = slash.dispatch("/clear")
    assert result is SlashResult.CONTINUE
    assert called["n"] == 1


def test_slash_exit_signals_exit(tmp_path: Path) -> None:
    """``/exit`` returns ``SlashResult.EXIT`` and saves the session."""
    slash = _make_slash(tmp_path)
    result = slash.dispatch("/exit")
    assert result is SlashResult.EXIT
    # Session was saved.
    assert list(tmp_path.glob("*.json"))


def test_slash_status_includes_session_id(tmp_path: Path) -> None:
    """``/status`` output mentions the current session id."""
    slash = _make_slash(tmp_path)
    sid = slash.session.id
    slash.dispatch("/status")
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert sid in out
    assert "messages" in out.lower() or "Messages" in out


def test_slash_sessions_lists_saved_sessions(tmp_path: Path) -> None:
    """``/sessions`` lists the sessions on disk."""
    # Seed two sessions.
    Session(id="aaaa", created_at="2026-06-01T00:00:00Z", updated_at="2026-06-01T00:00:00Z").save(
        tmp_path
    )
    Session(id="bbbb", created_at="2026-06-02T00:00:00Z", updated_at="2026-06-02T00:00:00Z").save(
        tmp_path
    )
    slash = _make_slash(tmp_path)
    slash.dispatch("/sessions")
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "aaaa" in out
    assert "bbbb" in out


def test_slash_sessions_empty_dir(tmp_path: Path) -> None:
    """``/sessions`` on an empty dir prints a friendly message."""
    slash = _make_slash(tmp_path)
    slash.dispatch("/sessions")
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "No saved sessions" in out


def test_slash_unknown_command(tmp_path: Path) -> None:
    """Unknown commands print a help line and continue."""
    slash = _make_slash(tmp_path)
    result = slash.dispatch("/frobnicate")
    assert result is SlashResult.CONTINUE
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "frobnicate" in out


def test_slash_does_nothing_on_empty_input(tmp_path: Path) -> None:
    """An empty string is treated as 'continue' without dispatching."""
    slash = _make_slash(tmp_path)
    assert slash.dispatch("") is SlashResult.CONTINUE
    assert slash.dispatch("not a slash command") is SlashResult.CONTINUE


def test_slash_model_shows_current_model_when_no_arg(tmp_path: Path) -> None:
    """``/model`` (no arg) prints the current model."""
    slash = _make_slash(tmp_path)
    slash.dispatch("/model")
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "stub" in out
    assert "stub-model" in out


def test_slash_model_switches_model(tmp_path: Path) -> None:
    """``/model <name>`` updates the settings and rebuilds the agent."""
    slash = _make_slash(tmp_path)
    slash.dispatch("/model new-model")
    assert slash.settings.llm.model == "new-model"


def test_slash_resume_last_with_no_sessions(tmp_path: Path) -> None:
    """``/resume last`` on an empty dir prints an error and continues."""
    slash = _make_slash(tmp_path)
    result = slash.dispatch("/resume")
    assert result is SlashResult.CONTINUE
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "No saved sessions" in out


def test_slash_resume_explicit_id_loads_session(tmp_path: Path) -> None:
    """``/resume <id>`` replaces the current session with the loaded one."""
    target = Session(
        id="target",
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
        messages=[{"role": "user", "content": "previous"}],  # type: ignore[arg-type]
    )
    target.save(tmp_path)
    slash = _make_slash(tmp_path)
    assert slash.session.id != "target"
    slash.dispatch("/resume target")
    assert slash.session.id == "target"
    assert slash.session.messages[0].content == "previous"


def test_slash_resume_unknown_id(tmp_path: Path) -> None:
    """``/resume <id>`` on a missing file prints an error."""
    slash = _make_slash(tmp_path)
    result = slash.dispatch("/resume nope")
    assert result is SlashResult.CONTINUE
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "nope" in out


def test_slash_doctor_prints_llm_status(tmp_path: Path) -> None:
    """``/doctor`` prints the LLM provider and a status line."""
    slash = _make_slash(tmp_path)
    slash.dispatch("/doctor")
    out = slash.console.file.getvalue()  # type: ignore[union-attr]
    assert "stub" in out
    assert "ok" in out


# --------------------------------------------------------------------------- #
# ListInputProvider
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_input_provider_raises_eof_when_exhausted() -> None:
    """Once the list is empty, ``read`` raises :class:`EOFError`."""
    provider = ListInputProvider([])
    with pytest.raises(EOFError):
        await provider.read("> ")
    assert provider.prompts_seen == ["> "]


@pytest.mark.asyncio
async def test_list_input_provider_replays_in_order() -> None:
    """``read`` returns values in the order they were supplied."""
    provider = ListInputProvider(["hi", "/help", "/exit"])
    assert await provider.read("> ") == "hi"
    assert await provider.read("> ") == "/help"
    assert await provider.read("> ") == "/exit"
    with pytest.raises(EOFError):
        await provider.read("> ")


# --------------------------------------------------------------------------- #
# help table text
# --------------------------------------------------------------------------- #


def test_help_table_lists_every_documented_command() -> None:
    """The help table mentions every command from the v0.1 spec."""
    for cmd in (
        "/help",
        "/clear",
        "/exit",
        "/status",
        "/model",
        "/resume",
        "/sessions",
        "/doctor",
    ):
        assert cmd in HELP_TABLE
