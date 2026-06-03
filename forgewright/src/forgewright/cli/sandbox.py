"""`forgewright sandbox ...` — inspect backends and set the default.

Subcommands:

* ``doctor`` — print a table showing each backend's availability and
  the reason it's missing (if any). The strongest available backend is
  highlighted in green.
* ``set`` — set the active backend for the rest of the session. The
  change is not persisted to ``config.toml`` in v0.1; that lands in v0.2.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from forgewright.config import get_settings
from forgewright.logger import logger
from forgewright.sandbox import (
    DockerSandbox,
    Sandbox,
    SandboxStatus,
    SubprocessSandbox,
)

console = Console()
__all__ = ["sandbox_command"]


# Strongest → weakest. The first available one is the recommended pick.
_BACKENDS: list[Sandbox] = [SubprocessSandbox(), DockerSandbox()]


def _pick_recommended(statuses: list[SandboxStatus]) -> str | None:
    """Return the name of the strongest available backend, or ``None``."""
    by_name = {s.name: s for s in statuses}
    for backend in _BACKENDS:
        s = by_name.get(backend.name)
        if s is not None and s.available:
            return s.name
    return None


def _render_doctor_table(statuses: list[SandboxStatus]) -> Table:
    """Build a rich ``Table`` from a list of status probes."""
    recommended = _pick_recommended(statuses)
    table = Table(title="forgewright sandbox doctor", show_header=True, header_style="bold")
    table.add_column("Backend", style="cyan", no_wrap=True)
    table.add_column("Available", justify="center")
    table.add_column("Reason", style="dim")
    table.add_column("Recommended", justify="center")

    for s in statuses:
        is_recommended = s.name == recommended
        available_cell = "[green]yes[/green]" if s.available else "[red]no[/red]"
        reason = s.reason if s.reason != "ok" or not s.available else "ok"
        recommended_cell = "[bold green]★[/bold green]" if is_recommended else ""
        table.add_row(s.name, available_cell, reason, recommended_cell)
    return table


def sandbox_command(
    action: str = typer.Argument(
        ...,
        help="Sub-action: doctor | set.",
    ),
    backend: str = typer.Option(
        None,
        "--backend",
        "-b",
        help="Backend to set (subprocess | docker). Required for 'set'.",
    ),
) -> None:
    """Sandbox inspection and configuration."""
    logger.debug("sandbox.cli action={} backend={}", action, backend)

    if action == "doctor":
        statuses = [b.doctor() for b in _BACKENDS]
        console.print(_render_doctor_table(statuses))
        # ``doctor`` always exits 0 — unavailability is reported, not fatal.
        return

    if action == "set":
        if not backend:
            console.print("[red]--backend required for 'set'[/red]")
            raise typer.Exit(2)
        valid = {b.name for b in _BACKENDS}
        if backend not in valid:
            console.print(
                f"[red]Unknown backend: {backend!r}. "
                f"Choose one of: {', '.join(sorted(valid))}[/red]"
            )
            raise typer.Exit(2)

        # Mutate the cached Settings sandbox.backend in place. This is a
        # session-scoped change; the value in config.toml is untouched
        # (persistence is a v0.2 concern).
        settings = get_settings()
        settings.sandbox.backend = backend  # type: ignore[assignment]
        console.print(
            f"[green]Backend set to {backend!r}[/green] "
            "[dim](effective this session only — persistence lands in v0.2; "
            "edit ~/.config/forgewright/config.toml to keep the change)[/dim]"
        )
        return

    console.print(f"[red]Unknown action: {action!r}. Use 'doctor' or 'set'.[/red]")
    raise typer.Exit(2)
