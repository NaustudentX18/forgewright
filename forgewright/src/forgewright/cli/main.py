"""`forgewright build \"<prompt>\"` — single-prompt entry point."""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated, cast

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from forgewright.agent import AgentState, Manus
from forgewright.cli.caps import resolve_session_caps, wrap_llm_with_caps
from forgewright.config import get_settings
from forgewright.conversation_state import FinalState, write_final_state
from forgewright.llm import LLMBackend
from forgewright.logger import logger
from forgewright.schema import ChatMessage
from forgewright.security.audit import AuditLog
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
    max_cost: Annotated[
        float | None,
        typer.Option(
            "--max-cost",
            help=(
                "Per-session USD cost cap. Aborts the loop with a typed "
                "cost_limit_reached final state when the running cost "
                "exceeds this value. Use 0 for unlimited (the default)."
            ),
        ),
    ] = None,
    max_iterations: Annotated[
        int | None,
        typer.Option(
            "--max-iterations",
            help=(
                "Per-session LLM-call iteration cap. Aborts the loop with "
                "a typed iteration_limit_reached final state when the "
                "iteration count reaches this value. Use 0 for unlimited."
            ),
        ),
    ] = None,
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

    # H2.3 — resolve per-session caps. CLI flags win over settings so
    # the user can override their default config for a single run.
    cap_usd, cap_iter = resolve_session_caps(
        settings,
        max_cost=max_cost,
        max_iterations=max_iterations,
    )

    if interactive:
        from forgewright.cli.repl import repl_main  # local import: avoid circular

        sessions_dir = default_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session = Session.new(metadata={"model": settings.llm.model})
        session.messages.append(ChatMessage(role="user", content=prompt))
        sys.exit(repl_main(initial_session=session))

    backend = LLMBackend.from_config(settings.llm)
    # Wrap in MeteredLLM so the cost/iteration caps are enforced
    # before every LLM call. Free-tier models (stub/free prefix) are
    # no-ops inside the wrapper.
    llm = wrap_llm_with_caps(backend, max_usd=cap_usd, max_iterations=cap_iter)
    agent = Manus(llm=llm, max_steps=max_steps)

    logger.info(
        "build.start provider={} model={} max_steps={} max_cost={} max_iter={}",
        settings.llm.provider,
        settings.llm.model,
        max_steps,
        cap_usd,
        cap_iter,
    )

    try:
        result = asyncio.run(agent.run(prompt, max_steps=max_steps))
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        sys.exit(130)

    if result.final_state is not None:
        sessions_dir = default_sessions_dir()
        session = Session.new(
            metadata={
                "model": settings.llm.model,
                "provider": settings.llm.provider,
                "final_state": result.final_state,
                "last_state": result.state.value,
                "step_count": result.step_count,
            }
        )
        session.messages.append(ChatMessage(role="user", content=prompt))
        if result.output:
            session.messages.append(ChatMessage(role="assistant", content=result.output))
        session.save(sessions_dir)
        write_final_state(
            AuditLog(settings.security.audit_log),
            session.id,
            cast(FinalState, result.final_state),
            actor={"type": "system", "name": "forgewright.build"},
        )

    if result.state == AgentState.ERROR:
        console.print(Panel(result.output, title="[red]Error[/red]", border_style="red"))
        sys.exit(1)

    # H2.3 — typed final states for cap-reached runs. Surface a
    # friendly yellow panel instead of an error.
    if result.state in (AgentState.COST_LIMIT_REACHED, AgentState.ITERATION_LIMIT_REACHED):
        title = (
            "[yellow]Cost limit reached[/yellow]"
            if result.state == AgentState.COST_LIMIT_REACHED
            else "[yellow]Iteration limit reached[/yellow]"
        )
        console.print(
            Panel(
                result.output,
                title=title,
                subtitle=(
                    f"[dim]{result.step_count} steps · {result.state.value}[/dim]"
                ),
                border_style="yellow",
            )
        )
        sys.exit(2)

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
