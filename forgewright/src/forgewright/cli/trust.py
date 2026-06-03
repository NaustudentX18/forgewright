"""``forgewright trust`` — manage the command trust registry.

Subcommands:

* ``ls`` — print all rules in a Rich table.
* ``add <pattern>`` — add a rule (default scope: machine).
* ``rm <pattern>`` — remove a rule.
* ``clear-session`` — drop all SESSION-scoped rules.

The registry lives at ``Settings.security.trust`` (default
``~/.config/forgewright/trust.toml``). SESSION rules are in-memory
only and are not visible to a fresh process.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from forgewright.config import get_settings
from forgewright.security.trust import TrustRegistry, TrustScope

console = Console()

__all__ = ["trust_command"]


def _parse_scope(scope: str) -> TrustScope:
    """Parse a user-supplied scope string into a :class:`TrustScope`.

    Typer can't do enum ``Argument`` cleanly without repeating the
    choices literal in two places, so we accept ``str`` and validate
    here. Unknown values produce a clean ``exit 2``.
    """
    try:
        return TrustScope(scope)
    except ValueError:
        valid = ", ".join(s.value for s in TrustScope)
        console.print(f"[red]Unknown scope: {scope!r} (valid: {valid})[/red]")
        raise typer.Exit(2) from None


def trust_command(
    action: str = typer.Argument(
        ...,
        help="Sub-action: ls | add | rm | clear-session.",
    ),
    pattern: str | None = typer.Argument(
        None,
        help="Pattern for add/rm (e.g. 'ls' or 'git *').",
    ),
    scope: str = typer.Option(
        "machine",
        "--scope",
        "-s",
        help="Scope for `add`: machine | repo | session.",
    ),
    reason: str = typer.Option(
        "",
        "--reason",
        "-r",
        help="Free-form note recorded with the rule.",
    ),
) -> None:
    """Manage the command trust registry."""
    settings = get_settings()
    registry = TrustRegistry(machine_path=settings.security.trust)

    if action == "ls":
        _list_rules(registry)
        return

    if action == "add":
        if not pattern:
            console.print("[red]`add` requires a pattern (e.g. `forgewright trust add 'ls'`)[/red]")
            raise typer.Exit(2)
        scope_enum = _parse_scope(scope)
        rule = registry.add(pattern, scope=scope_enum, reason=reason)
        console.print(
            f"[green]✓[/green] Added rule [cyan]{rule.pattern}[/cyan] (scope: {rule.scope.value})"
        )
        return

    if action in ("rm", "remove"):
        if not pattern:
            console.print("[red]`rm` requires a pattern (e.g. `forgewright trust rm 'ls'`)[/red]")
            raise typer.Exit(2)
        if registry.remove(pattern):
            console.print(f"[green]✓[/green] Removed rule [cyan]{pattern}[/cyan]")
            return
        console.print(f"[yellow]No rule matched {pattern!r}[/yellow]")
        raise typer.Exit(1)

    if action in ("clear-session", "clear_session"):
        registry.clear_session()
        console.print("[green]✓[/green] Cleared session-scoped rules")
        return

    console.print(f"[red]Unknown action: {action!r} (valid: ls, add, rm, clear-session)[/red]")
    raise typer.Exit(2)


def _list_rules(registry: TrustRegistry) -> None:
    """Print all rules in a Rich table."""
    rules = registry.list_rules()
    if not rules:
        console.print(
            "[yellow]No trust rules. Add one with `forgewright trust add <pattern>`.[/yellow]"
        )
        return

    table = Table(title=f"Trust registry ({len(rules)} rules)")
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
    console.print(table)
