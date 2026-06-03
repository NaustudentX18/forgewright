"""`forgewright resume [id|last]` — open a saved session in the REPL."""

from __future__ import annotations

import typer
from rich.console import Console

from forgewright.cli.repl import repl_main
from forgewright.logger import logger
from forgewright.session import Session, default_sessions_dir

__all__ = ["resume_command"]

console = Console()


def resume_command(
    session_id: str = typer.Argument(
        "last",
        help="Session ID, or 'last' for the most recent.",
    ),
) -> None:
    """Resume a previous session in the REPL.

    With no argument (or ``last``), opens the most recently updated
    session. With a session id, opens the session whose filename is
    ``<id>.json`` in the sessions directory.
    """
    sessions_dir = default_sessions_dir()
    logger.debug("resume.start id={!r} dir={}", session_id, sessions_dir)

    if session_id == "last":
        recent = Session.list_recent(sessions_dir, limit=1)
        if not recent:
            console.print("[red]No saved sessions.[/red]")
            raise typer.Exit(1)
        session = recent[0]
    else:
        path = sessions_dir / f"{session_id}.json"
        if not path.exists():
            console.print(f"[red]Session not found: {session_id}[/red]")
            raise typer.Exit(1)
        try:
            session = Session.load(path)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Could not load session {session_id}: {exc}[/red]")
            raise typer.Exit(1) from exc

    console.print(
        f"[green]Resuming[/green] [dim]{session.id}[/dim] ({len(session.messages)} messages)"
    )
    raise typer.Exit(repl_main(initial_session=session))
