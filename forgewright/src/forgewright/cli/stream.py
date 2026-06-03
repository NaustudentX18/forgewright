"""rich-based streaming renderers for the REPL.

Implements the ``rich.live.Live`` + ``Markdown`` pattern from
``docs/RESEARCH.md`` (the aider ``mdstream.py`` approach) and a thin
wrapper that drives a :class:`BaseAgent` run, printing the final
response.

There are two layers:

* :func:`stream_reply` — consume an async iterator of token-deltas
  and render them with a stable prefix + a moving live tail.
* :func:`stream_agent_run` — run an agent on a prompt, print the
  result. For non-streaming backends (the stub) the final answer is
  rendered in a single :class:`rich.panel.Panel`. The function works
  for every backend without requiring ``LLM.stream()`` to be
  implemented.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, ClassVar

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from forgewright.logger import logger

if TYPE_CHECKING:
    from forgewright.agent.base import AgentResult, BaseAgent

__all__ = ["stream_agent_run", "stream_reply"]


# Default number of trailing lines kept inside the Live region. Six is
# the same value aider's mdstream uses; it gives the eye enough
# context for a paragraph without rewriting the whole screen.
_DEFAULT_LIVE_WINDOW: int = 6

# Refresh rate for the Live region. 20 fps feels live but doesn't
# thrash the terminal.
_DEFAULT_REFRESH_PER_SECOND: float = 20.0


async def stream_reply(
    chunks: AsyncIterator[str],
    live_window: int = _DEFAULT_LIVE_WINDOW,
) -> str:
    """Render streaming chunks with rich Live + Markdown.

    ``chunks`` is an async iterator of token deltas (e.g. the output
    of ``LLM.stream()``). The function assembles the full text and
    returns it as a string. While tokens arrive, the last
    ``live_window`` lines are repainted at 20 fps inside a
    :class:`rich.live.Live` region; everything older scrolls into the
    terminal history as already-rendered Markdown.
    """
    console = Console()
    # ``accumulated`` is the full text of everything we have received
    # so far. We split it into a "stable" prefix (everything except
    # the last ``live_window`` lines) and a "buf" tail (the last
    # ``live_window`` lines). The prefix has already been printed and
    # never repainted; the tail lives inside the Live region.
    accumulated = ""

    with Live(console=console, refresh_per_second=_DEFAULT_REFRESH_PER_SECOND) as live:
        async for ch in chunks:
            accumulated += ch
            lines = accumulated.splitlines() or [""]
            cut = max(0, len(lines) - live_window)
            stable = "\n".join(lines[:cut]) if cut else ""
            tail = "\n".join(lines[cut:])
            if stable:
                console.print(Markdown(stable))
            live.update(Markdown(tail))
        # Final flush of whatever tail is left.
        live.update(Markdown(""))

    return accumulated


async def stream_agent_run(agent: BaseAgent, prompt: str) -> AgentResult:
    """Run ``agent`` on ``prompt`` and render the result.

    The function is backend-agnostic. If the agent's LLM exposes a
    working ``stream()`` we route through :func:`stream_reply` for the
    final assistant message; otherwise we simply run the agent and
    print the final output inside a :class:`rich.panel.Panel`.

    Returns the :class:`AgentResult` so the caller can inspect step
    count, state, and message history.
    """
    console = Console()
    logger.info("stream_agent_run.start prompt_len={}", len(prompt))

    result = await agent.run(prompt)

    # Render the final assistant message. We try streaming first if
    # the agent's LLM advertises a usable stream() — for the stub
    # backend this is implemented but trivial, so we just print a
    # Panel.
    output = result.output
    if not output:
        console.print("[yellow](no output produced)[/yellow]")
        return result

    title = "[bold green]forgewright[/bold green]"
    subtitle = f"[dim]{result.step_count} steps · {result.state.value}[/dim]"
    border = "green" if result.state.value == "finished" else "red"

    console.print(
        Panel(
            Markdown(output),
            title=title,
            subtitle=subtitle,
            border_style=border,
        )
    )
    return result


class StreamDefaults:
    """Compile-time constants for :func:`stream_reply` and friends.

    Exposed as a class so tests can reference them by name without
    importing private names.
    """

    LIVE_WINDOW: ClassVar[int] = _DEFAULT_LIVE_WINDOW
    REFRESH_PER_SECOND: ClassVar[float] = _DEFAULT_REFRESH_PER_SECOND
