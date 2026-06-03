"""Tests for the Phase 11B slash commands in :mod:`forgewright.cli.slash`.

Each test builds a :class:`forgewright.cli.repl.SlashCommands`
instance (with a stub LLM and a fresh session), dispatches a
single command, and asserts the expected side effect. The
dispatcher is the existing Phase 11A one; the wiring is set up by
:func:`forgewright.cli.slash.register_phase_11b` (called from
:mod:`forgewright.cli.repl` at import time).
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from forgewright.agent import Manus
from forgewright.cli.repl import (
    ListInputProvider,
    SlashCommands,
    SlashResult,
    repl_loop,
)
from forgewright.config import LLMConfig, Settings
from forgewright.llm.stub import StubBackend
from forgewright.schema import ChatMessage
from forgewright.security.trust import TrustRegistry, TrustScope
from forgewright.session import Session
from rich.console import Console

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A fresh in-memory ``Settings`` with the stub LLM.

    The trust and audit-log paths are pointed at a temp file
    inside ``tmp_path`` so the tests don't touch the user's real
    ``~/.config/forgewright`` config.
    """
    from forgewright.config import SecurityConfig

    return Settings(
        llm=LLMConfig(provider="stub", model="stub-model"),
        max_steps=2,
        security=SecurityConfig(
            trust=str(tmp_path / "trust.toml"),
            audit_log=str(tmp_path / "audit.jsonl"),
        ),
    )


@pytest.fixture
def console() -> Console:
    """A console backed by a ``StringIO`` so tests can assert on output."""
    return Console(file=StringIO(), force_terminal=False, width=200, no_color=True)


@pytest.fixture
def agent(settings: Settings) -> Manus:
    """A real :class:`Manus` wired to the stub LLM."""
    return Manus(llm=StubBackend(settings.llm), max_steps=settings.max_steps)


@pytest.fixture
def session() -> Session:
    """A fresh session with a few messages so ``/compact`` has something to truncate."""
    return Session(
        id="sess-test",
        created_at="2026-06-02T00:00:00Z",
        updated_at="2026-06-02T00:00:00Z",
        messages=[ChatMessage(role="user", content=f"msg-{i}") for i in range(15)],
        metadata={"model": "stub-model"},
    )


@pytest.fixture
def slash(
    settings: Settings, agent: Manus, session: Session, console: Console, tmp_path: Path
) -> SlashCommands:
    """A wired-up :class:`SlashCommands`` instance for testing."""
    return SlashCommands(
        session=session,
        agent=agent,
        settings=settings,
        console=console,
        sessions_dir=tmp_path,
    )


def _out(console: Console) -> str:
    """Return whatever the console has rendered so far."""
    return console.file.getvalue()  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# /compact
# --------------------------------------------------------------------------- #


def test_compact_truncates_to_last_ten(slash: SlashCommands) -> None:
    """``/compact`` keeps only the last 10 messages."""
    assert len(slash.session.messages) == 15
    slash.dispatch("/compact")
    assert len(slash.session.messages) == 10
    # The first remaining message is the 6th (index 5) of the
    # original list, since we kept the last 10 of 15.
    assert slash.session.messages[0].content == "msg-5"
    assert slash.session.messages[-1].content == "msg-14"


def test_compact_reports_before_and_after(slash: SlashCommands, console: Console) -> None:
    """``/compact`` prints the before / after counts."""
    slash.dispatch("/compact")
    out = _out(console)
    assert "Compacted" in out
    assert "15" in out  # before
    assert "10" in out  # after


def test_compact_with_few_messages_is_noop(slash: SlashCommands) -> None:
    """``/compact`` on a short session is effectively a no-op."""
    slash.session.messages = slash.session.messages[:3]
    slash.dispatch("/compact")
    assert len(slash.session.messages) == 3


# --------------------------------------------------------------------------- #
# /add and /drop
# --------------------------------------------------------------------------- #


def test_add_prints_stub_message(slash: SlashCommands, console: Console) -> None:
    """``/add <path>`` prints the v0.1 stub message."""
    slash.dispatch("/add src/foo.py")
    out = _out(console)
    assert "src/foo.py" in out
    assert "v0.1" in out


def test_drop_prints_stub_message(slash: SlashCommands, console: Console) -> None:
    """``/drop <path>`` prints the v0.1 stub message."""
    slash.dispatch("/drop src/foo.py")
    out = _out(console)
    assert "src/foo.py" in out
    assert "v0.1" in out


# --------------------------------------------------------------------------- #
# /permissions
# --------------------------------------------------------------------------- #


def test_permissions_empty_registry_prints_friendly_message(
    slash: SlashCommands, console: Console
) -> None:
    """``/permissions`` with no rules prints a helpful message."""
    slash.dispatch("/permissions")
    out = _out(console)
    assert "No trust rules" in out


def test_permissions_with_rules_prints_table(
    slash: SlashCommands, console: Console, tmp_path: Path, settings: Settings
) -> None:
    """``/permissions`` renders a table when rules are present."""
    # Seed a rule in the temp trust file.
    trust_path = tmp_path / "trust.toml"
    settings.security.trust = str(trust_path)
    TrustRegistry(machine_path=trust_path).add("ls", scope=TrustScope.MACHINE)
    slash.dispatch("/permissions")
    out = _out(console)
    assert "ls" in out
    assert "machine" in out


# --------------------------------------------------------------------------- #
# /mcp
# --------------------------------------------------------------------------- #


def test_mcp_prints_loaded_servers_message(slash: SlashCommands, console: Console) -> None:
    """``/mcp`` always prints the 'no servers loaded' message in v0.1."""
    slash.dispatch("/mcp")
    out = _out(console)
    assert "MCP servers" in out
    assert "none loaded" in out


# --------------------------------------------------------------------------- #
# /sandbox
# --------------------------------------------------------------------------- #


def test_sandbox_no_arg_shows_current(slash: SlashCommands, console: Console) -> None:
    """``/sandbox`` (no arg) prints the current backend."""
    slash.dispatch("/sandbox")
    out = _out(console)
    assert "subprocess" in out or "docker" in out  # default backend


def test_sandbox_switches_backend(slash: SlashCommands) -> None:
    """``/sandbox <backend>`` mutates ``settings.sandbox.backend``."""
    slash.dispatch("/sandbox docker")
    assert slash.settings.sandbox.backend == "docker"


def test_sandbox_switch_back_to_subprocess(slash: SlashCommands) -> None:
    """``/sandbox subprocess`` is also valid."""
    slash.settings.sandbox.backend = "docker"
    slash.dispatch("/sandbox subprocess")
    assert slash.settings.sandbox.backend == "subprocess"


def test_sandbox_unknown_backend_prints_error(slash: SlashCommands, console: Console) -> None:
    """``/sandbox gvisor-or-whatever`` prints an error and does not switch."""
    slash.dispatch("/sandbox not-a-backend")
    out = _out(console)
    assert "Unknown backend" in out
    # The backend didn't change.
    assert slash.settings.sandbox.backend in {"subprocess", "docker"}


# --------------------------------------------------------------------------- #
# /cost
# --------------------------------------------------------------------------- #


def test_cost_with_stub_reports_zero(slash: SlashCommands, console: Console) -> None:
    """``/cost`` with the stub provider reports 0.00 USD."""
    slash.dispatch("/cost")
    out = _out(console)
    assert "Cost" in out
    assert "$0.00" in out
    # Token counts are shown too.
    assert "Input tokens" in out
    assert "Output tokens" in out


def test_cost_after_recording_tokens(slash: SlashCommands, console: Console) -> None:
    """``/cost`` reports the cost implied by the LLM's current usage."""
    # Bump the stub's usage so there's something to show.
    llm = slash.agent.llm
    assert isinstance(llm, StubBackend)
    llm.usage().input_tokens += 1_000_000
    slash.dispatch("/cost")
    out = _out(console)
    # Stub pricing is zero, so the cost line is still $0.00.
    assert "Cost" in out
    # But the input token count is 1M+.
    assert "1,000,000" in out or "1000000" in out


# --------------------------------------------------------------------------- #
# /init
# --------------------------------------------------------------------------- #


def test_init_writes_agents_md(
    slash: SlashCommands, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/init`` writes an ``AGENTS.md`` to the cwd."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "AGENTS.md").exists()
    slash.dispatch("/init")
    target = tmp_path / "AGENTS.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "AGENTS.md" in text
    assert "Project conventions" in text


def test_init_does_not_overwrite_existing_by_default(
    slash: SlashCommands, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, console: Console
) -> None:
    """``/init`` on an existing file prints a warning and skips the write."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("# existing content\n", encoding="utf-8")
    slash.dispatch("/init")
    # The original content is untouched.
    assert target.read_text(encoding="utf-8") == "# existing content\n"
    out = _out(console)
    assert "already exists" in out


def test_init_overwrites_with_force_arg(
    slash: SlashCommands, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/init overwrite-arg`` writes the stub even if the file exists."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("# old content\n", encoding="utf-8")
    slash.dispatch("/init force")
    text = target.read_text(encoding="utf-8")
    assert "Project conventions" in text
    assert "old content" not in text


# --------------------------------------------------------------------------- #
# /memory
# --------------------------------------------------------------------------- #


def test_memory_prints_workspace_and_count(slash: SlashCommands, console: Console) -> None:
    """``/memory`` prints the workspace root and the message count."""
    slash.dispatch("/memory")
    out = _out(console)
    assert "Workspace root" in out
    assert "Sessions dir" in out
    # The session has 15 messages from the fixture.
    assert "15" in out


# --------------------------------------------------------------------------- #
# /config
# --------------------------------------------------------------------------- #


def test_config_prints_key_fields(slash: SlashCommands, console: Console) -> None:
    """``/config`` shows provider, model, max_steps, audit log, trust path."""
    slash.dispatch("/config")
    out = _out(console)
    assert "stub" in out
    assert "stub-model" in out
    assert "max_steps" in out
    assert "audit_log" in out
    assert "trust" in out


def test_config_masks_api_key(slash: SlashCommands, console: Console) -> None:
    """``/config`` masks the API key, even when one is set."""
    slash.settings.llm.api_key = "sk-supersecret"  # type: ignore[assignment]
    slash.dispatch("/config")
    out = _out(console)
    assert "sk-supersecret" not in out
    assert "****" in out


# --------------------------------------------------------------------------- #
# /perm — permission mode cycle
# --------------------------------------------------------------------------- #


def test_perm_starts_at_default(slash: SlashCommands) -> None:
    """Before ``/perm`` is called, the mode is ``default`` (or unset)."""
    # The fixture metadata doesn't include permission_mode yet.
    assert slash.session.metadata.get("permission_mode", "default") == "default"


def test_perm_cycles_through_all_modes(slash: SlashCommands) -> None:
    """``/perm`` walks the cycle and wraps back to the first mode."""
    from forgewright.cli.slash import PERMISSION_MODES

    seen: list[str] = []
    for _ in range(len(PERMISSION_MODES) + 1):
        slash.dispatch("/perm")
        seen.append(slash.session.metadata["permission_mode"])
    # We saw every mode exactly once, then wrapped to the first.
    assert seen[: len(PERMISSION_MODES)] == PERMISSION_MODES
    assert seen[-1] == PERMISSION_MODES[0]


def test_perm_updates_settings(slash: SlashCommands) -> None:
    """``/perm`` propagates the new mode into the live ``Settings``."""
    slash.dispatch("/perm")
    new_mode = slash.session.metadata["permission_mode"]
    assert slash.settings.security.permission_mode == new_mode


def test_perm_unknown_mode_recovers(
    slash: SlashCommands,
) -> None:
    """A bogus mode in metadata is treated as 'before default' and cycles correctly."""
    slash.session.metadata["permission_mode"] = "not-a-real-mode"
    slash.dispatch("/perm")
    # The new mode should be PERMISSION_MODES[0] (since unknown -> idx=-1, +1 -> 0).
    from forgewright.cli.slash import PERMISSION_MODES

    assert slash.session.metadata["permission_mode"] == PERMISSION_MODES[0]


# --------------------------------------------------------------------------- #
# /exit  (sanity — re-asserted here so this file stands alone)
# --------------------------------------------------------------------------- #


def test_exit_signals_exit(slash: SlashCommands) -> None:
    """``/exit`` returns ``SlashResult.EXIT``."""
    assert slash.dispatch("/exit") is SlashResult.EXIT


# --------------------------------------------------------------------------- #
# Integration: end-to-end REPL with the new commands
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_repl_loop_handles_compact_then_exit(
    tmp_path: Path, settings: Settings, session: Session
) -> None:
    """A full REPL run with ``/compact`` + ``/exit`` exits cleanly with 0."""
    provider = ListInputProvider(["/compact", "/exit"])
    code = await repl_loop(
        initial_session=session,
        input_provider=provider,
        sessions_dir=tmp_path,
        settings=settings,
    )
    assert code == 0
    # The session was persisted.
    assert list(tmp_path.glob("*.json"))


@pytest.mark.asyncio
async def test_repl_loop_handles_perm_cycle(
    tmp_path: Path, settings: Settings, session: Session
) -> None:
    """A full REPL run with several ``/perm`` calls exits cleanly."""
    provider = ListInputProvider(["/perm", "/perm", "/perm", "/exit"])
    await repl_loop(
        initial_session=session,
        input_provider=provider,
        sessions_dir=tmp_path,
        settings=settings,
    )
    # The session was persisted with the cycled permission mode.
    loaded = Session.load(tmp_path / f"{session.id}.json")
    assert "permission_mode" in loaded.metadata


# --------------------------------------------------------------------------- #
# Registration sanity
# --------------------------------------------------------------------------- #


def test_extended_commands_are_registered() -> None:
    """Every Phase 11B command is in the dispatch table after import."""
    expected = {
        "compact",
        "add",
        "drop",
        "permissions",
        "mcp",
        "sandbox",
        "cost",
        "init",
        "memory",
        "config",
        "perm",
    }
    assert expected.issubset(set(SlashCommands._COMMANDS))
