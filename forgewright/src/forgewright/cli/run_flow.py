"""`forgewright flow \"<prompt>\"` — multi-agent planning entry point.

Decomposes a high-level prompt into ordered steps, allocates each step
to a sub-agent, runs them sequentially, and prints a markdown report.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from forgewright.agent import (
    BrowserAgent,
    DataAnalysis,
    Manus,
    MCPAgent,
)
from forgewright.config import get_settings
from forgewright.flow import PlanningFlow
from forgewright.llm import LLMBackend
from forgewright.logger import logger

app = typer.Typer()
console = Console()


# All built-in agent names; the --agents option is filtered against this set.
_KNOWN_AGENT_NAMES: tuple[str, ...] = ("manus", "data_analysis", "browser_agent", "mcp_agent")
_AGENT_CLASSES = {
    "manus": Manus,
    "data_analysis": DataAnalysis,
    "browser_agent": BrowserAgent,
    "mcp_agent": MCPAgent,
}


def _parse_agents(spec: str) -> dict[str, type[Manus]]:
    """Parse the comma-separated `--agents` string into an agent class map."""
    if not spec.strip():
        raise typer.BadParameter("--agents must list at least one agent name.")
    selected: dict[str, type[Manus]] = {}
    for raw in spec.split(","):
        name = raw.strip()
        if not name:
            continue
        if name not in _KNOWN_AGENT_NAMES:
            raise typer.BadParameter(
                f"Unknown agent {name!r}. Valid: {', '.join(_KNOWN_AGENT_NAMES)}"
            )
        selected[name] = _AGENT_CLASSES[name]
    if not selected:
        raise typer.BadParameter("--agents must list at least one agent name.")
    return selected


def flow_command(
    prompt: Annotated[str, typer.Argument(help="The high-level task to decompose and run.")],
    agents: Annotated[
        str,
        typer.Option(
            "--agents",
            help=(
                "Comma-separated agent names "
                "(subset of manus,data_analysis,browser_agent,mcp_agent)."
            ),
        ),
    ] = "manus,data_analysis,browser_agent",
    max_steps: Annotated[
        int,
        typer.Option(
            "--max-steps",
            help="Cap on total sub-agent steps.",
        ),
    ] = 30,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Flow timeout in seconds.",
        ),
    ] = 3600,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Override the LLM provider (stub, openai, anthropic, ...).",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="Override the LLM model name.",
        ),
    ] = None,
) -> None:
    """Decompose a task and run it across multiple sub-agents."""
    settings = get_settings()
    if provider is not None:
        settings.llm.provider = provider  # type: ignore[assignment]
    if model is not None:
        settings.llm.model = model

    try:
        agent_map = _parse_agents(agents)
    except typer.BadParameter as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    llm = LLMBackend.from_config(settings.llm)
    flow = PlanningFlow(
        llm=llm,
        agents=agent_map,
        max_total_steps=max_steps,
        timeout_s=timeout,
    )

    logger.info(
        "flow.start provider={} model={} max_steps={} timeout={} agents={}",
        settings.llm.provider,
        settings.llm.model,
        max_steps,
        timeout,
        sorted(agent_map),
    )

    try:
        result = asyncio.run(flow.run(prompt))
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        sys.exit(130)

    if result.state.value == "error":
        console.print(
            Panel(
                result.output or "Flow ended in error state.",
                title="[red]Flow error[/red]",
                border_style="red",
            )
        )
        sys.exit(1)

    body = result.to_markdown()
    console.print(
        Panel(
            Markdown(body),
            title="[bold green]forgewright flow[/bold green]",
            subtitle=(f"[dim]{result.total_step_count} step(s) · {result.state.value}[/dim]"),
            border_style="green",
        )
    )


__all__ = ["flow_command"]
