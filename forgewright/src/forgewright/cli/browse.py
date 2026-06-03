"""`forgewright browse <prompt>` — manual URL fetch via BrowserUseTool.

For now this is the simple "navigate + report" path: it opens a headless
Chromium, navigates to ``--url``, prints the page title (and a small
diagnostic panel), and always closes the browser at the end. The "smart"
extraction — ask an LLM to read the page and answer ``<prompt>`` — lands in
Phase 7 with the :class:`BrowserAgent` sub-agent. The CLI signature is
intentionally forward-compatible.
"""

from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.panel import Panel

from forgewright.logger import logger
from forgewright.tool.browser import BrowserUseTool

console = Console()


def browse_command(
    prompt: str = typer.Argument(
        ...,
        help=(
            "What to fetch from the page. Accepted for symmetry with the other "
            "CLI commands; the current implementation only navigates + reads "
            "the title. LLM-driven extraction lands in Phase 7 (BrowserAgent)."
        ),
    ),
    url: str = typer.Option(
        "https://example.com",
        "--url",
        "-u",
        help="URL to open.",
    ),
    headless: bool = typer.Option(
        True,
        "--headless/--no-headless",
        help="Run the browser with (default) or without a visible window.",
    ),
) -> None:
    """Fetch a single fact from a URL by driving a headless browser."""
    logger.info("browse.start prompt={!r} url={} headless={}", prompt, url, headless)
    try:
        result = asyncio.run(_run_browse(prompt=prompt, url=url, headless=headless))
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        sys.exit(130)

    if result is None:
        # The internal coroutine already printed an error panel.
        sys.exit(1)


async def _run_browse(*, prompt: str, url: str, headless: bool) -> None:
    """Open the browser, navigate, print the result, and always close."""
    tool = BrowserUseTool(headless=headless)
    try:
        nav = await tool(action="navigate", url=url)
        if nav.is_error:
            console.print(
                Panel(
                    nav.error or "Unknown error during navigation.",
                    title="[red]browse failed[/red]",
                    border_style="red",
                )
            )
            return None

        title = await tool(action="get_title")
        if title.is_error:
            console.print(
                Panel(
                    title.error or "Unknown error reading title.",
                    title="[red]browse failed[/red]",
                    border_style="red",
                )
            )
            return None

        body = (
            f"[bold]URL:[/bold]    {url}\n"
            f"[bold]Title:[/bold]  {title.output}\n"
            f"[bold]Prompt:[/bold] {prompt}\n\n"
            "[dim]LLM-driven extraction from the page is not yet wired; "
            "use the agent (`forgewright build`) for that.[/dim]"
        )
        console.print(
            Panel(
                body,
                title="[bold green]forgewright browse[/bold green]",
                border_style="green",
            )
        )
        return None
    finally:
        await tool.close()


__all__ = ["browse_command"]
