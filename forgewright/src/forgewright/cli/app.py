"""Root Typer application and `forgewright --version`."""

from __future__ import annotations

import asyncio
import sys

import typer

from forgewright import __version__
from forgewright.cli.audit import audit_command
from forgewright.cli.browse import browse_command
from forgewright.cli.init import init_command
from forgewright.cli.main import build_command
from forgewright.cli.repl import repl_loop
from forgewright.cli.run_flow import flow_command
from forgewright.cli.run_mcp import mcp_command
from forgewright.cli.run_mcp_server import mcp_serve_command
from forgewright.cli.run_resume import resume_command
from forgewright.cli.run_tui import tui_command
from forgewright.cli.run_web import web_command
from forgewright.cli.sandbox import sandbox_command
from forgewright.cli.trust import trust_command

app = typer.Typer(
    name="forgewright",
    help=(
        "forgewright — an open-source, CLI-first AI agent framework.\n\n"
        'Run `forgewright build "<prompt>"` to execute a single task, '
        "`forgewright resume` to continue a previous session, or just "
        "`forgewright` to open the REPL."
    ),
    no_args_is_help=False,
    rich_markup_mode="rich",
    add_completion=False,
    invoke_without_command=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"forgewright {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the forgewright version and exit.",
    ),
) -> None:
    """Top-level dispatcher.

    With no subcommand, opens the interactive REPL. This keeps the
    most common path (`forgewright`) zero-args and zero-friction.
    """
    if version:
        # Never reached — ``_version_callback`` raises Exit.
        return
    if ctx.invoked_subcommand is None:
        # Default action: open the REPL.
        try:
            code = asyncio.run(repl_loop())
        except KeyboardInterrupt:
            code = 130
        sys.exit(code)


# Register subcommands.
app.command(name="build", help="Run a single prompt through the Manus agent.")(build_command)
app.command(name="init", help="Initialize forgewright config in ~/.config/forgewright/.")(
    init_command
)
app.command(
    name="browse",
    help="Open a URL in a headless browser and report the page title (Phase 5 manual path).",
)(browse_command)
app.command(
    name="mcp",
    help=(
        "MCP server / client operations. Sub-actions: serve, connect, "
        "ls, install, trust. Try `forgewright mcp serve --help`."
    ),
)(mcp_command)
app.command(
    name="mcp-serve",
    help="Shortcut for `forgewright mcp serve` (FastMCP server).",
)(mcp_serve_command)
app.command(
    name="flow",
    help=(
        "Decompose a high-level task into ordered sub-agent steps and run them "
        "(Phase 9 multi-agent planning)."
    ),
)(flow_command)
app.command(
    name="audit",
    help=(
        "Inspect the tamper-evident audit log. Sub-actions: verify, tail, export, query. "
        "Try `forgewright audit verify --help`."
    ),
)(audit_command)
app.command(
    name="sandbox",
    help=(
        "Sandbox inspection and configuration. Sub-actions: doctor, set. "
        "Try `forgewright sandbox doctor`."
    ),
)(sandbox_command)
app.command(
    name="trust",
    help=(
        "Manage the command trust registry. Sub-actions: ls, add, rm, clear-session. "
        "Try `forgewright trust ls`."
    ),
)(trust_command)
app.command(name="resume", help="Resume a previous session in the REPL.")(resume_command)
app.command(
    name="web",
    help=(
        "Launch the web chat UI (FastAPI). Use --bind tailscale "
        "--tailscale-serve to expose over Tailscale HTTPS so a phone "
        "on the tailnet can install it as a PWA. Requires the [web] extra."
    ),
)(web_command)
app.command(
    name="tui",
    help=(
        "Launch the Textual terminal UI against a running web server "
        "(same /api/sessions SSE protocol). Requires the [tui] extra."
    ),
)(tui_command)


def main() -> None:
    """Entry point for the `forgewright` console script."""
    app()


if __name__ == "__main__":
    main()
