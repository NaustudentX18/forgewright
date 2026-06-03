"""`forgewright build \"<prompt>\"` — single-prompt entry point."""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from forgewright.agent import Manus
from forgewright.config import get_settings
from forgewright.llm import LLMBackend
from forgewright.logger import logger
from forgewright.schema import ChatMessage
from forgewright.session import Session, default_sessions_dir

console = Console()


def build_command(
    prompt: Annotated[str, typer.Argument(help="The task to run.")],
    max_steps: Annotated[
        int,
        typer.Option(
            "--max-steps",
            "-n",
            help="Maximum number of agent iterations before stopping.",
        ),
    ] = 8,
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
        typer.Option("--model", "-m", help="Override the LLM model name."),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Open the REPL with the prompt pre-filled as the first user turn.",
        ),
    ] = False,
) -> None:
    """Run a single prompt through the Manus agent and print the result.

    By default the command is non-interactive — it runs one prompt and
    exits. With ``--interactive`` / ``-i`` it opens the REPL with the
    prompt already recorded as the first user message, so the model
    starts responding immediately and the user can continue the
    conversation.
    """
    settings = get_settings()
    if provider is not None:
        settings.llm.provider = provider  # type: ignore[assignment]
    if model is not None:
        settings.llm.model = model

    if interactive:
        from forgewright.cli.repl import repl_main  # local import: avoid circular

        sessions_dir = default_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session = Session.new(metadata={"model": settings.llm.model})
        session.messages.append(ChatMessage(role="user", content=prompt))
        sys.exit(repl_main(initial_session=session))

    llm = LLMBackend.from_config(settings.llm)
    agent = Manus(llm=llm, max_steps=max_steps)

    logger.info(
        "build.start provider={} model={} max_steps={}",
        settings.llm.provider,
        settings.llm.model,
        max_steps,
    )

    try:
        result = asyncio.run(agent.run(prompt, max_steps=max_steps))
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        sys.exit(130)

    if result.state.value == "error":
        console.print(Panel(result.output, title="[red]Error[/red]", border_style="red"))
        sys.exit(1)

    if result.output:
        console.print(
            Panel(
                Markdown(result.output),
                title="[bold green]forgewright[/bold green]",
                subtitle=(f"[dim]{result.step_count} steps · {result.state.value}[/dim]"),
                border_style="green",
            )
        )
    else:
        console.print("[yellow]No output produced.[/yellow]")


__all__ = ["build_command"]
