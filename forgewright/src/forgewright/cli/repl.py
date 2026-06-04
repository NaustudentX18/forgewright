"""The interactive REPL: prompt_toolkit input + rich rendering + slash commands.

The REPL is a thin orchestration layer over four pieces:

* :class:`forgewright.agent.Manus` (the agent)
* :class:`forgewright.cli.stream.stream_agent_run` (the renderer)
* :class:`forgewright.session.Session` (the persistence)
* A slash-command dispatcher (below) for non-prompt commands.

Slash commands are dispatched *before* the input reaches the agent;
they never cost a token. The minimum set in v0.1 is ``/help``,
``/clear``, ``/exit``, ``/status``, ``/model``, ``/resume``,
``/sessions``, and ``/doctor``. The remaining commands from the
build plan (``/compact``, ``/add``, ``/drop``, ``/permissions``,
``/mcp``, ``/sandbox``, ``/cost``, ``/init``, ``/memory``,
``/config``) are deferred to a follow-up agent (Phase 11B).
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol, cast

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from forgewright.agent import Manus
from forgewright.cli.caps import resolve_session_caps, wrap_llm_with_caps
from forgewright.cli.stream import stream_agent_run
from forgewright.config import Settings, get_settings
from forgewright.conversation_state import FinalState, write_final_state
from forgewright.llm import LLMBackend
from forgewright.logger import logger
from forgewright.schema import ChatMessage
from forgewright.security.audit import AuditLog
from forgewright.session import Session, default_sessions_dir

__all__ = [
    "HELP_TABLE",
    "InputProvider",
    "ListInputProvider",
    "PromptInputProvider",
    "SlashCommands",
    "SlashResult",
    "repl_loop",
    "repl_main",
]


# --------------------------------------------------------------------------- #
# Slash-command data
# --------------------------------------------------------------------------- #


class SlashResult(StrEnum):
    """The outcome of a slash command."""

    CONTINUE = "continue"
    EXIT = "exit"


# Markdown-friendly slash-command help table. The exact text is
# exercised by tests; do not change it without updating them.
HELP_TABLE: str = (
    "| Command | Description |\n"
    "| --- | --- |\n"
    "| /help | Show this help |\n"
    "| /clear | Clear the screen |\n"
    "| /exit | Save and exit |\n"
    "| /status | Show session status |\n"
    "| /model [name] | Show or switch the model |\n"
    "| /resume [id|last] | Resume a previous session |\n"
    "| /sessions | List recent sessions |\n"
    "| /doctor | Run diagnostics |"
)


# --------------------------------------------------------------------------- #
# Input provider
# --------------------------------------------------------------------------- #


class InputProvider(Protocol):
    """A swappable input source for the REPL.

    The default implementation uses ``prompt_toolkit`` (with file
    history); tests use :class:`ListInputProvider` to feed a fixed
    list of inputs.
    """

    async def read(self, prompt: str) -> str: ...


@dataclass
class PromptInputProvider:
    """Default :class:`InputProvider` backed by ``prompt_toolkit``."""

    history_path: Path | None = None
    _session: PromptSession[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        history = FileHistory(str(self.history_path)) if self.history_path else None
        self._session = PromptSession(history=history)

    async def read(self, prompt: str) -> str:
        """Block until the user types a line and presses Enter."""
        assert self._session is not None
        return await self._session.prompt_async(prompt)


@dataclass
class ListInputProvider:
    """Test helper — replays a fixed list of inputs.

    Raises :class:`EOFError` once the list is exhausted. Each value is
    returned on a single call to :meth:`read`. Every prompt string the
    REPL emits is appended to :attr:`prompts_seen`, which is handy for
    asserting loop behaviour in tests.
    """

    inputs: list[str]
    _index: int = field(default=0, init=False, repr=False)
    prompts_seen: list[str] = field(default_factory=list, init=False, repr=False)

    async def read(self, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        if self._index >= len(self.inputs):
            raise EOFError
        value = self.inputs[self._index]
        self._index += 1
        return value


# --------------------------------------------------------------------------- #
# Slash command dispatcher
# --------------------------------------------------------------------------- #


@dataclass
class SlashCommands:
    """Dispatch slash commands to handler methods.

    Handlers are simple instance methods named ``cmd_<name>`` and
    registered in :attr:`_COMMANDS`. They may mutate the session
    (``self.session``) or the agent (``self.agent``) in place. The
    dispatcher itself never raises; unknown commands print a help
    line and return :attr:`SlashResult.CONTINUE`.
    """

    session: Session
    agent: Manus
    settings: Settings
    console: Console
    sessions_dir: Path

    _COMMANDS: ClassVar[dict[str, str]] = {
        "help": "cmd_help",
        "clear": "cmd_clear",
        "exit": "cmd_exit",
        "status": "cmd_status",
        "model": "cmd_model",
        "resume": "cmd_resume",
        "sessions": "cmd_sessions",
        "doctor": "cmd_doctor",
    }

    # Phase 11B polish commands are registered at import time by
    # ``_register_phase_11b_commands`` (one import + one call; see
    # the bottom of this module). Defining the dict literal above
    # keeps the Phase 11A surface visible at a glance; the
    # ``setdefault`` call in the registration function merges the
    # extended entries in without overwriting anything.

    # ------------------------------------------------------------------ #
    # Public dispatch
    # ------------------------------------------------------------------ #

    def dispatch(self, raw: str) -> SlashResult | bool:
        """Route ``raw`` to the matching handler.

        Returns :attr:`SlashResult.CONTINUE` (or ``True``) to keep
        looping, :attr:`SlashResult.EXIT` (or ``False``) to stop.
        The bool aliases make it easy to call from a ``while`` loop
        without an extra enum import.
        """
        raw = raw.strip()
        if not raw.startswith("/"):
            return SlashResult.CONTINUE
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            self.console.print(f"[red]Parse error: {exc}[/red]")
            return SlashResult.CONTINUE
        name = parts[0][1:].lower()
        args = parts[1:]
        handler_name = self._COMMANDS.get(name)
        if handler_name is None:
            self.console.print(f"[red]Unknown command: /{name}[/red] (try /help)")
            return SlashResult.CONTINUE
        handler: Callable[[list[str]], SlashResult | bool] = getattr(self, handler_name)
        return handler(args)

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    def cmd_help(self, _args: list[str]) -> SlashResult:
        """``/help`` — print the slash command table."""
        self.console.print(Markdown(HELP_TABLE))
        return SlashResult.CONTINUE

    def cmd_clear(self, _args: list[str]) -> SlashResult:
        """``/clear`` — clear the screen, keep the session intact."""
        self.console.clear()
        return SlashResult.CONTINUE

    def cmd_exit(self, _args: list[str]) -> SlashResult:
        """``/exit`` — persist the session and signal the REPL to stop."""
        try:
            self.session.save(self.sessions_dir)
            self.console.print(
                f"[dim]Session saved → {self.sessions_dir}/{self.session.id}.json[/dim]"
            )
        except OSError as exc:
            logger.warning("repl.save_failed err={}", exc)
            self.console.print(f"[yellow]Could not save session: {exc}[/yellow]")
        return SlashResult.EXIT

    def cmd_status(self, _args: list[str]) -> SlashResult:
        """``/status`` — show session id, step count, message count, model."""
        step_count = getattr(self.agent, "step_count", "?")
        model = self.settings.llm.model
        provider = self.settings.llm.provider
        table = Table(title="session status", show_header=True, header_style="bold")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value")
        table.add_row("session id", self.session.id)
        table.add_row("messages", str(len(self.session.messages)))
        table.add_row("agent step", str(step_count))
        table.add_row("model", f"{provider}:{model}")
        table.add_row("max_steps", str(self.settings.max_steps))
        self.console.print(table)
        return SlashResult.CONTINUE

    def cmd_model(self, args: list[str]) -> SlashResult:
        """``/model [name]`` — show the current model or switch to ``name``."""
        if not args:
            cfg = self.settings.llm
            self.console.print(f"[cyan]{cfg.provider}[/cyan]:[bold]{cfg.model}[/bold]")
            return SlashResult.CONTINUE
        new_model = args[0]
        old = self.settings.llm.model
        self.settings.llm.model = new_model
        cap_usd, cap_iter = resolve_session_caps(self.settings)
        new_llm = wrap_llm_with_caps(
            LLMBackend.from_config(self.settings.llm),
            max_usd=cap_usd,
            max_iterations=cap_iter,
        )
        # Rebuild the agent around the new LLM while preserving the
        # in-flight state and memory.
        old_state = self.agent.state
        old_step = self.agent.step_count
        old_memory = self.agent.memory
        self.agent = Manus(llm=new_llm, max_steps=self.settings.max_steps)
        self.agent.state = old_state
        self.agent.step_count = old_step
        self.agent.memory = old_memory
        self.console.print(f"[green]Model:[/green] {old} → {new_model}")
        return SlashResult.CONTINUE

    def cmd_resume(self, args: list[str]) -> SlashResult:
        """``/resume [id|last]`` — load a session from disk and continue."""
        target = args[0] if args else "last"
        if target == "last":
            recent = Session.list_recent(self.sessions_dir, limit=1)
            if not recent:
                self.console.print("[red]No saved sessions.[/red]")
                return SlashResult.CONTINUE
            loaded = recent[0]
        else:
            path = self.sessions_dir / f"{target}.json"
            if not path.exists():
                self.console.print(f"[red]Session not found: {target}[/red]")
                return SlashResult.CONTINUE
            try:
                loaded = Session.load(path)
            except (OSError, ValueError) as exc:
                self.console.print(f"[red]Could not load session: {exc}[/red]")
                return SlashResult.CONTINUE
        self.session = loaded
        self.console.print(
            f"[green]Resumed session[/green] [dim]{loaded.id}[/dim] "
            f"({len(loaded.messages)} messages)"
        )
        return SlashResult.CONTINUE

    def cmd_sessions(self, _args: list[str]) -> SlashResult:
        """``/sessions`` — list recent sessions (id, updated_at, message count)."""
        recent = Session.list_recent(self.sessions_dir, limit=10)
        if not recent:
            self.console.print("[dim]No saved sessions yet.[/dim]")
            return SlashResult.CONTINUE
        table = Table(title="recent sessions", show_header=True, header_style="bold")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Updated", style="green")
        table.add_column("Messages", justify="right")
        for s in recent:
            table.add_row(s.id[:12], s.updated_at, str(len(s.messages)))
        self.console.print(table)
        return SlashResult.CONTINUE

    def cmd_doctor(self, _args: list[str]) -> SlashResult:
        """``/doctor`` — print LLM diagnostics (sandbox via shell in v0.1)."""
        provider = self.settings.llm.provider
        model = self.settings.llm.model
        self.console.print(f"[cyan]LLM:[/cyan] {provider}:{model} — [green]ok[/green]")
        self.console.print(
            "[dim](sandbox diagnostics are run with `forgewright sandbox doctor` "
            "from the shell)[/dim]"
        )
        return SlashResult.CONTINUE


# --------------------------------------------------------------------------- #
# REPL loop
# --------------------------------------------------------------------------- #


_DEFAULT_PROMPT: str = "> "


async def repl_loop(
    initial_session: Session | None = None,
    input_provider: InputProvider | None = None,
    sessions_dir: str | Path | None = None,
    settings: Settings | None = None,
) -> int:
    """Open the interactive REPL.

    Parameters
    ----------
    initial_session
        A pre-loaded session to continue. When ``None`` a fresh
        :class:`Session` is created.
    input_provider
        Override the input source. Tests pass a
        :class:`ListInputProvider`; production code uses
        :class:`PromptInputProvider` (the default).
    sessions_dir
        Where sessions are persisted. Defaults to
        :func:`forgewright.session.default_sessions_dir`.
    settings
        Override the global :class:`Settings` instance. Useful for
        tests that want a stub LLM.

    Returns
    -------
    int
        The process exit code. Currently always ``0``; the field is
        present for symmetry with the CLI's exit-code contract.
    """
    console = Console()
    settings = settings or get_settings()
    sessions_dir = Path(sessions_dir) if sessions_dir else default_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session = initial_session or Session.new(metadata={"model": settings.llm.model})
    cap_usd, cap_iter = resolve_session_caps(settings)
    llm = wrap_llm_with_caps(
        LLMBackend.from_config(settings.llm),
        max_usd=cap_usd,
        max_iterations=cap_iter,
    )
    agent = Manus(llm=llm, max_steps=settings.max_steps)

    if input_provider is None:
        history_path = sessions_dir.parent / "repl_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        input_provider = PromptInputProvider(history_path=history_path)

    slash = SlashCommands(
        session=session,
        agent=agent,
        settings=settings,
        console=console,
        sessions_dir=sessions_dir,
    )

    console.print(
        f"[dim]forgewright REPL — session {session.id} "
        f"(model {settings.llm.provider}:{settings.llm.model})[/dim]"
    )
    console.print("[dim]Type /help for a list of commands.[/dim]")

    while True:
        try:
            user_input = await input_provider.read(_DEFAULT_PROMPT)
        except (EOFError, KeyboardInterrupt):
            # Mirror ``/exit`` — persist and leave the loop.
            slash.dispatch("/exit")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            outcome = slash.dispatch(user_input)
            if outcome is SlashResult.EXIT or outcome is False:
                break
            continue

        # Ordinary prompt — record, run, record, persist.
        session.messages.append(ChatMessage(role="user", content=user_input))
        try:
            result = await stream_agent_run(agent, user_input)
        except Exception as exc:
            logger.exception("repl.agent_run error")
            console.print(f"[red]Error: {exc}[/red]")
            continue
        if result.output:
            session.messages.append(ChatMessage(role="assistant", content=result.output))
        session.metadata.setdefault("model", settings.llm.model)
        session.metadata["step_count"] = result.step_count
        session.metadata["last_state"] = result.state.value
        if result.final_state is not None:
            session.metadata["final_state"] = result.final_state
            write_final_state(
                AuditLog(settings.security.audit_log),
                session.id,
                cast(FinalState, result.final_state),
                actor={"type": "system", "name": "forgewright.repl"},
            )
        try:
            session.save(sessions_dir)
        except OSError as exc:
            logger.warning("repl.auto_save_failed err={}", exc)

    return 0


# --------------------------------------------------------------------------- #
# Sync entry point for the CLI dispatcher
# --------------------------------------------------------------------------- #


def repl_main(initial_session: Session | None = None) -> int:
    """Synchronous wrapper around :func:`repl_loop` for Typer commands."""
    try:
        return asyncio.run(repl_loop(initial_session=initial_session))
    except KeyboardInterrupt:
        return 130


# --------------------------------------------------------------------------- #
# Phase 11B wiring — one import + one registration loop.
# --------------------------------------------------------------------------- #


def _register_phase_11b_commands() -> None:
    """Register the Phase 11B slash commands on :class:`SlashCommands`.

    See :mod:`forgewright.cli.slash` for the command implementations
    and :func:`forgewright.cli.slash.register_phase_11b` for the
    registration semantics. This wrapper is module-private; the
    public surface is the augmented :class:`SlashCommands` class.
    """
    from forgewright.cli.slash import register_phase_11b  # the one import

    register_phase_11b(SlashCommands)  # the one registration call


# The Phase 11B polish commands (``/compact``, ``/add``, ``/drop``,
# ``/permissions``, ``/mcp``, ``/sandbox``, ``/cost``, ``/init``,
# ``/memory``, ``/config``, ``/perm``) are defined in
# :mod:`forgewright.cli.slash` and attached to :class:`SlashCommands`
# here. The wiring is intentionally a single call so adding new
# polish commands only requires editing :mod:`forgewright.cli.slash`.
_register_phase_11b_commands()
