"""Phase 11B slash commands — the polish layer on top of Phase 11A.

Phase 11A shipped the minimum command set in
:mod:`forgewright.cli.repl` (``/help``, ``/clear``, ``/exit``,
``/status``, ``/model``, ``/resume``, ``/sessions``, ``/doctor``).
This module adds the rest of the commands from the build plan's
Phase 11 table:

* ``/compact``       — truncate the session history to the last 10 turns.
* ``/add <path>``    — v0.1 stub (auto-discovery in v0.2).
* ``/drop <path>``   — v0.1 stub.
* ``/permissions``   — print the trust registry table.
* ``/mcp``           — list loaded MCP servers (none in v0.1).
* ``/sandbox [backend]`` — show or switch the sandbox backend.
* ``/cost``          — print running token cost.
* ``/init``          — write a minimal ``AGENTS.md`` to the cwd.
* ``/memory``        — print workspace root and message count.
* ``/config``        — print a few key ``Settings`` fields.
* ``/perm``          — cycle the ``permission_mode`` in session metadata.

Wiring
------

The commands are attached to the existing
:class:`forgewright.cli.repl.SlashCommands` class by
:func:`register_phase_11b`, which is called once at import time of
:mod:`forgewright.cli.repl` (one import + one call, the only
changes to that file). Adding a new command to this module
requires only that you:

1. Define a ``cmd_<name>`` method on the :class:`Phase11BCommands`
   mixin below.
2. Add the ``"<name>": "cmd_<name>"`` entry to
   :data:`EXTENDED_COMMANDS`.

No changes to :mod:`forgewright.cli.repl` are needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table

from forgewright.config import get_settings
from forgewright.cost import cost_for
from forgewright.logger import logger
from forgewright.security.trust import TrustRegistry
from forgewright.session import default_sessions_dir

if TYPE_CHECKING:
    from rich.console import Console

    from forgewright.agent import Manus
    from forgewright.cli.repl import SlashCommands
    from forgewright.config import Settings
    from forgewright.session import Session

__all__ = [
    "EXTENDED_COMMANDS",
    "PERMISSION_MODES",
    "Phase11BCommands",
    "register_phase_11b",
]


# The Shift+Tab cycle. ``default`` and ``plan`` are the only modes
# that prompt for tool calls; the rest are documented in
# ``docs/PERMISSION_MODES.md`` (a follow-up). ``PERMISSION_MODES`` is
# the canonical list — the ``/perm`` command cycles through it and
# wraps at the end.
PERMISSION_MODES: list[str] = [
    "default",
    "acceptEdits",
    "plan",
    "auto",
    "dontAsk",
    "bypass",
]


# Mapping from the slash command name (without ``/``) to the
# ``cmd_<name>`` method that implements it on
# :class:`forgewright.cli.repl.SlashCommands`. The dispatch table in
# :class:`SlashCommands` looks the method up by name; this dict
# registers the new entries.
EXTENDED_COMMANDS: dict[str, str] = {
    "compact": "cmd_compact",
    "add": "cmd_add",
    "drop": "cmd_drop",
    "permissions": "cmd_permissions",
    "mcp": "cmd_mcp",
    "sandbox": "cmd_sandbox",
    "cost": "cmd_cost",
    "init": "cmd_init",
    "memory": "cmd_memory",
    "config": "cmd_config",
    "perm": "cmd_perm",
}


# Backends the ``/sandbox`` slash command accepts. The list must
# stay in sync with :data:`forgewright.cli.sandbox._BACKENDS`.
_SANDBOX_BACKENDS: tuple[str, ...] = ("subprocess", "docker", "gvisor")

# Path of the ``AGENTS.md`` stub that ``/init`` writes to the cwd.
_AGENTS_MD_STUB: str = "# AGENTS.md\n# Project conventions go here.\n"

# Sentinel return value for "command was handled, keep the loop
# going". The dispatch table in :class:`SlashCommands` already
# treats ``True`` as "continue"; we use it for clarity.
_CONTINUE: bool = True


class Phase11BCommands:
    """Mixin holding the Phase 11B slash command implementations.

    The methods are intentionally side-effecting: they mutate the
    session, settings, or trust registry in place. The mixin is
    monkey-patched onto :class:`forgewright.cli.repl.SlashCommands`
    by :func:`register_phase_11b`; the methods below reference
    ``self.session``, ``self.settings``, ``self.console``,
    ``self.agent``, and ``self.sessions_dir`` exactly as the
    Phase 11A handlers do.

    Every method returns ``True`` ("handled, keep looping"). The
    dispatch loop's :func:`is False` / ``SlashResult.EXIT`` check
    is the only thing that breaks the loop, so ``True`` is the
    safe default.
    """

    # Declare the ``SlashCommands`` instance attributes for
    # type-checkers. At runtime these annotations are no-ops — the
    # real attributes live on the dataclass target — but mypy and
    # friends will resolve ``self.session`` etc. without complaint.
    if TYPE_CHECKING:
        session: Session
        agent: Manus
        settings: Settings
        console: Console
        sessions_dir: Path

    # The methods below are typed against ``self`` carrying the
    # SlashCommands attributes. We keep them as a mixin (rather
    # than a protocol) because Python needs the actual functions
    # in the class dict for ``getattr(self, "cmd_compact")`` to
    # work.

    # ------------------------------------------------------------------ #
    # Compact + file read-set (stubs in v0.1)
    # ------------------------------------------------------------------ #

    def cmd_compact(self, args: list[str]) -> bool:
        """``/compact`` — truncate the session history to the last 10 turns.

        v0.1 is the cheap version: just slice the message list.
        The LLM-based summarisation described in the build plan
        lands in v0.2.
        """
        before = len(self.session.messages)
        self.session.messages = self.session.messages[-10:]
        after = len(self.session.messages)
        self.console.print(f"[green]Compacted[/green] to last {after} messages (was {before}).")
        return _CONTINUE

    def cmd_add(self, args: list[str]) -> bool:
        """``/add <path>`` — add a file to the agent's read-set (v0.1 stub)."""
        path = args[0] if args else "(no path)"
        self.console.print(
            f"[yellow]/add[/yellow] {path}: "
            "files are auto-discovered from the workspace root in v0.1; "
            "explicit /add lands in v0.2."
        )
        return _CONTINUE

    def cmd_drop(self, args: list[str]) -> bool:
        """``/drop <path>`` — remove a file from the read-set (v0.1 stub)."""
        path = args[0] if args else "(no path)"
        self.console.print(
            f"[yellow]/drop[/yellow] {path}: "
            "files are auto-discovered from the workspace root in v0.1; "
            "explicit /drop lands in v0.2."
        )
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Trust registry
    # ------------------------------------------------------------------ #

    def cmd_permissions(self, args: list[str]) -> bool:
        """``/permissions`` — print the trust registry as a Rich table."""
        registry = TrustRegistry(machine_path=self.settings.security.trust)
        rules = registry.list_rules()

        if not rules:
            self.console.print(
                "[yellow]No trust rules. Add one with `forgewright trust add <pattern>`.[/yellow]"
            )
            return _CONTINUE

        table = Table(
            title=f"trust registry ({len(rules)} rules)",
            show_header=True,
            header_style="bold",
        )
        table.add_column("Pattern", style="cyan", no_wrap=True)
        table.add_column("Scope", style="green")
        table.add_column("Added at", style="dim")
        table.add_column("Reason", style="dim")
        for rule in rules:
            table.add_row(
                rule.pattern,
                rule.scope.value,
                rule.added_at,
                rule.reason or "",
            )
        self.console.print(table)
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # MCP
    # ------------------------------------------------------------------ #

    def cmd_mcp(self, args: list[str]) -> bool:
        """``/mcp`` — show loaded MCP servers.

        v0.1 has no auto-load: the runtime hook is wired into
        :class:`forgewright.agent.MCPAgent` (Phase 8) but the REPL
        does not connect to any server on startup. ``get_settings``
        does not yet have an ``mcp.servers`` field, so the command
        always prints the stub message for now.
        """
        self.console.print("MCP servers: (none loaded; use the MCP CLI to connect)")
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Sandbox
    # ------------------------------------------------------------------ #

    def cmd_sandbox(self, args: list[str]) -> bool:
        """``/sandbox [backend]`` — show or switch the sandbox backend."""
        if not args:
            self.console.print(
                f"[cyan]Current sandbox backend:[/cyan] "
                f"[bold]{self.settings.sandbox.backend}[/bold]"
            )
            return _CONTINUE

        backend = args[0]
        if backend not in _SANDBOX_BACKENDS:
            self.console.print(
                f"[red]Unknown backend: {backend!r}. "
                f"Choose one of: {', '.join(_SANDBOX_BACKENDS)}[/red]"
            )
            return _CONTINUE

        old = self.settings.sandbox.backend
        self.settings.sandbox.backend = backend  # type: ignore[assignment]
        self.console.print(
            f"[green]Sandbox backend:[/green] {old} → [bold]{backend}[/bold] "
            "[dim](session-scoped; persistence in v0.2)[/dim]"
        )
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Cost
    # ------------------------------------------------------------------ #

    def cmd_cost(self, args: list[str]) -> bool:
        """``/cost`` — print the running token cost.

        Pulls the LLM's own :meth:`LLM.usage` for token counts and
        prices them against the static table in
        :mod:`forgewright.cost`. The REPL does not yet own a
        :class:`CostTracker`; the cost reported here is computed
        from the LLM's cumulative usage on each invocation. A
        dedicated tracker that the REPL ``.record()``s on every
        LLM call is a follow-up.
        """
        # The agent carries the LLM; if it's missing (e.g. a unit
        # test with a fake agent) we print a friendly error rather
        # than crashing. ``getattr`` is the safest way to look
        # through the mixin indirection.
        agent = getattr(self, "agent", None)
        llm = getattr(agent, "llm", None) if agent is not None else None
        if llm is None:
            self.console.print("[red]No LLM attached to the agent.[/red]")
            return _CONTINUE
        usage = llm.usage()
        total = cost_for(self.settings.llm.model, usage.input_tokens, usage.output_tokens)
        self.console.print(
            f"[cyan]Input tokens:[/cyan]  {usage.input_tokens}\n"
            f"[cyan]Output tokens:[/cyan] {usage.output_tokens}\n"
            f"[cyan]Cost (USD):[/cyan]    ${total:.4f}\n"
            f"[dim](model: {self.settings.llm.model})[/dim]"
        )
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Init
    # ------------------------------------------------------------------ #

    def cmd_init(self, args: list[str]) -> bool:
        """``/init`` — scaffold a minimal ``AGENTS.md`` in the cwd."""
        target = Path.cwd() / "AGENTS.md"
        if target.exists() and not args:
            self.console.print(
                f"[yellow]AGENTS.md already exists at {target}[/yellow] "
                "[dim](pass any arg to overwrite)[/dim]"
            )
            return _CONTINUE
        target.write_text(_AGENTS_MD_STUB, encoding="utf-8")
        self.console.print(f"[green]Wrote[/green] {target}")
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Memory
    # ------------------------------------------------------------------ #

    def cmd_memory(self, args: list[str]) -> bool:
        """``/memory`` — show the memory / workspace discovery state."""
        # v0.1 doesn't have a separate memory subsystem; the
        # "workspace root" is the parent directory of the audit
        # log (i.e. ``~/.local/share/forgewright``), and the
        # message count is the session length.
        workspace = str(Path(self.settings.security.audit_log).parent)
        n = len(self.session.messages)
        self.console.print(
            f"[cyan]Workspace root:[/cyan] {workspace}\n"
            f"[cyan]Sessions dir:[/cyan]  {default_sessions_dir()}\n"
            f"[cyan]Message count:[/cyan] {n}"
        )
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def cmd_config(self, args: list[str]) -> bool:
        """``/config`` — show the current effective config (secrets masked)."""
        cfg = self.settings
        api_key = cfg.llm.api_key
        # Mask the API key so the screen doesn't end up in a
        # screencast / shoulder-surf. An empty key is reported
        # plainly.
        masked = "****" if api_key else "(none)"
        table = Table(title="effective config", show_header=True, header_style="bold")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value")
        table.add_row("provider", cfg.llm.provider)
        table.add_row("model", cfg.llm.model)
        table.add_row("api_key", masked)
        table.add_row("max_steps", str(cfg.max_steps))
        table.add_row("sandbox.backend", cfg.sandbox.backend)
        table.add_row("audit_log", cfg.security.audit_log)
        table.add_row("trust", cfg.security.trust)
        table.add_row("permission_mode", cfg.security.permission_mode)
        self.console.print(table)
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Permission mode cycle
    # ------------------------------------------------------------------ #

    def cmd_perm(self, args: list[str]) -> bool:
        """``/perm`` — cycle the permission mode in the session metadata.

        The :data:`PERMISSION_MODES` list defines the cycle. The
        current mode is read from
        ``session.metadata["permission_mode"]``. A missing or
        unrecognised value is treated as "before the start" of the
        cycle, so the first ``/perm`` call lands on
        :data:`PERMISSION_MODES` element 0 (``"default"``).
        Subsequent calls advance one step and wrap at the end.

        The new mode is also propagated to
        ``settings.security.permission_mode`` so a permission-aware
        tool picks up the change mid-session.

        ``prompt_toolkit`` key bindings for ``Shift+Tab`` are not
        wired in v0.1; this command is the manual equivalent.
        """
        current = self.session.metadata.get("permission_mode")
        # Treat "no mode set" and "unknown mode" identically: the
        # next /perm call lands on the first element of the cycle.
        # This matches the Shift+Tab behaviour of "the first press
        # always picks the default".
        idx = PERMISSION_MODES.index(current) if current in PERMISSION_MODES else -1
        new_idx = (idx + 1) % len(PERMISSION_MODES)
        new_mode = PERMISSION_MODES[new_idx]
        self.session.metadata["permission_mode"] = new_mode
        self.settings.security.permission_mode = new_mode  # type: ignore[assignment]
        next_mode = PERMISSION_MODES[(new_idx + 1) % len(PERMISSION_MODES)]
        self.console.print(
            f"[green]Permission mode:[/green] [bold]{new_mode}[/bold] "
            f"[dim](next: {next_mode})[/dim]"
        )
        return _CONTINUE

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _get_agent_llm(self) -> object | None:
        """Return the live LLM handle from the agent, or ``None`` if absent.

        The REPL constructs the agent with ``Manus(llm=...)``, so
        ``self.agent.llm`` is the contract. Tests that build a
        ``SlashCommands`` with a fake agent (no ``llm`` attr) get
        ``None`` back, which the callers treat as "no LLM
        available" rather than crashing.

        Kept as a method (rather than inlined into
        :meth:`cmd_cost`) so other Phase 11B commands can reuse
        it. The registration step copies it onto
        :class:`SlashCommands` via
        :func:`register_phase_11b`.
        """
        agent = getattr(self, "agent", None)
        if agent is None:
            return None
        return getattr(agent, "llm", None)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


# Cache of classes we've already patched. The dispatch table is
# a ``ClassVar[dict]`` on ``SlashCommands``, so registering twice
# is harmless — but patching methods twice would replace them
# with identical copies and trigger the linter's "redundant
# assignment" warning on a hot-reload path.
_REGISTERED: set[type] = set()


def register_phase_11b(slash_commands_cls: type[SlashCommands]) -> None:
    """Monkey-patch the Phase 11B commands onto ``SlashCommands``.

    Idempotent: calling it twice does not duplicate methods or
    dispatch entries. The function is invoked from
    :mod:`forgewright.cli.repl` once, at import time. Adding a new
    polish command requires only that you edit
    :class:`Phase11BCommands` and :data:`EXTENDED_COMMANDS` — this
    file's wiring is automatic.

    We import :class:`SlashCommands` lazily so
    :mod:`cli.repl` can import this module without triggering a
    circular import at package-init time.

    The function copies *every* public method defined on
    :class:`Phase11BCommands` onto the target class — not just
    the entries in :data:`EXTENDED_COMMANDS`. The reason is that
    the ``cmd_*`` handlers call helpers like
    :meth:`Phase11BCommands._get_agent_llm`; those helpers must
    be reachable as instance attributes too, otherwise the
    descriptor protocol would resolve them on the mixin class
    (where ``self.agent`` is unbound) instead of on the target
    instance. The dispatch table is populated only from
    :data:`EXTENDED_COMMANDS`, so helpers are not exposed as
    user-facing slash commands.
    """
    if slash_commands_cls in _REGISTERED:
        return
    mixin = Phase11BCommands
    # Walk the mixin's class dict and copy anything that looks
    # like a public method (no leading underscores). This keeps
    # the registration simple: adding a new helper to the mixin
    # doesn't require updating this function.
    for attr_name, attr_value in vars(mixin).items():
        if attr_name.startswith("_") and not attr_name.startswith("__"):
            # Private helpers like ``_get_agent_llm`` need to be
            # attached too — they are called by ``cmd_*`` methods
            # via ``self.<name>``. Dunder names are excluded.
            setattr(slash_commands_cls, attr_name, attr_value)
            continue
        if attr_name.startswith("__"):
            continue
        if not callable(attr_value):
            continue
        setattr(slash_commands_cls, attr_name, attr_value)
    for cmd_name, method_name in EXTENDED_COMMANDS.items():
        slash_commands_cls._COMMANDS.setdefault(cmd_name, method_name)
    _REGISTERED.add(slash_commands_cls)
    logger.debug(
        "slash.phase_11b_registered cls={} commands={}",
        slash_commands_cls.__name__,
        sorted(EXTENDED_COMMANDS),
    )


# ``get_settings`` is imported above for completeness; the slash
# commands consult the live ``self.settings`` rather than calling
# the cached singleton, so the import is otherwise unused. Mark
# it as such for the linter.
_ = get_settings
