"""``forgewright audit`` — dispatcher for the tamper-evident audit log.

Sub-actions:

* ``verify`` — recompute the sha256 chain. Exits 0 if OK, non-zero
  with a short reason on the first gap.
* ``tail``   — print the last N events in a Rich table.
* ``export`` — write the log to stdout (or ``--output``) as ``jsonl``
  or ``csv``.
* ``query``  — filter events with ``field=value [AND ...]`` (jsonl to stdout).
"""

from __future__ import annotations

import json
import sys
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from forgewright.config import get_settings
from forgewright.logger import logger
from forgewright.security.audit import AuditLog

console = Console()

__all__ = ["audit_command"]


_AuditAction = Literal["verify", "tail", "export", "query"]
_AuditFormat = Literal["jsonl", "csv"]


def audit_command(
    action: str = typer.Argument(
        ...,
        help="Sub-action: verify | tail | export | query.",
    ),
    query_expr: str | None = typer.Argument(
        None,
        help=(
            "Filter expression for 'query', e.g. "
            '"tool=bash AND approved=false".'
        ),
    ),
    log_path: str | None = typer.Option(
        None,
        "--log",
        "-l",
        help=(
            "Path to audit.jsonl. "
            "Default: settings.security.audit_log "
            "(~/.local/share/forgewright/audit.jsonl)."
        ),
    ),
    n: int = typer.Option(
        10,
        "--num",
        "-n",
        help="Number of events to show for 'tail'.",
    ),
    fmt: str = typer.Option(
        "jsonl",
        "--format",
        "-f",
        help="Export format: jsonl | csv. (OTel/other formats land in v0.2.)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for 'export' (default: stdout).",
    ),
) -> None:
    """Inspect, verify, or export the forgewright audit log."""
    settings = get_settings()
    resolved_path = log_path or settings.security.audit_log
    logger.info("audit.start action={} path={}", action, resolved_path)

    if action == "verify":
        _run_verify(resolved_path)
        return

    if action == "tail":
        _run_tail(resolved_path, n)
        return

    if action == "export":
        _run_export(resolved_path, fmt=fmt, output=output)
        return

    if action == "query":
        if not query_expr:
            console.print("[red]Missing query expression[/red] (e.g. tool=Bash AND approved=false)")
            raise typer.Exit(2)
        _run_query(resolved_path, query_expr)
        return

    console.print(
        f"[red]Unknown action: {action!r}[/red] (expected: verify | tail | export | query)"
    )
    raise typer.Exit(2)


# --------------------------------------------------------------------------- #
# sub-action implementations
# --------------------------------------------------------------------------- #


def _run_verify(path: str) -> None:
    """Recompute the chain and exit non-zero on the first gap."""
    log = AuditLog(path)
    result = log.verify()
    if result.ok:
        console.print(f"[green]OK[/green] {result.total_events} event(s) verified at {path}")
        return

    # 1-based for human consumption.
    line = (result.first_bad_index or 0) + 1
    console.print(f"[red]BROKEN[/red] at line {line} of {path}: {result.reason}")
    raise typer.Exit(1)


def _run_tail(path: str, n: int) -> None:
    """Print the last N events in a Rich table."""
    log = AuditLog(path)
    events = log.tail(n)
    if not events:
        console.print(f"[dim]No audit events at {path}[/dim]")
        return

    table = Table(title=f"Last {len(events)} event(s) from {path}")
    table.add_column("ts", style="cyan", no_wrap=True)
    table.add_column("session", style="bright_black", no_wrap=True)
    table.add_column("type", style="green")
    table.add_column("tool", style="magenta")
    table.add_column("actor", style="blue")
    table.add_column("hash", style="dim", no_wrap=True)

    for ev in events:
        actor_label = ev.actor.get("name", "") if ev.actor else ""
        table.add_row(
            ev.ts,
            ev.session_id or "",
            ev.type,
            ev.tool or "",
            actor_label,
            ev.hash[:12] + "…" if ev.hash else "",
        )
    console.print(table)


def _run_export(path: str, fmt: str, output: str | None) -> None:
    """Export the log as ``jsonl`` or ``csv`` to stdout or ``--output``."""
    if fmt not in ("jsonl", "csv"):
        console.print(f"[red]Unknown --format: {fmt!r}[/red] (supported: jsonl | csv)")
        raise typer.Exit(2)

    log = AuditLog(path)
    payload = log.export(fmt)
    if output:
        # Mirror ``echo > file`` semantics; on disk as utf-8 text.
        with open(output, "w", encoding="utf-8") as f:
            f.write(payload)
            if not payload.endswith("\n"):
                f.write("\n")
        console.print(f"[green]Wrote[/green] {len(payload)} bytes to {output}")
        return

    # Stdout. Add a trailing newline so the consumer doesn't have to.
    if not payload.endswith("\n"):
        payload += "\n"
    sys.stdout.write(payload)
    sys.stdout.flush()


def _run_query(path: str, expr: str) -> None:
    """Filter the log and print matching events as JSONL on stdout."""
    log = AuditLog(path)
    try:
        events = log.query(expr)
    except ValueError as exc:
        console.print(f"[red]Invalid query:[/red] {exc}")
        raise typer.Exit(2) from exc

    if not events:
        console.print(f"[dim]No matching events at {path}[/dim]")
        return

    for ev in events:
        line = json.dumps(ev.to_dict(include_hash=True), ensure_ascii=False)
        sys.stdout.write(line + "\n")
    sys.stdout.flush()
