"""BaseAgent — the smallest viable agent: state, memory, step loop."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from forgewright.config import get_settings
from forgewright.cost import CostLimitReached, IterationLimitReached
from forgewright.llm import LLM
from forgewright.logger import logger
from forgewright.schema import ChatMessage


class AgentState(StrEnum):
    """The lifecycle states of an agent."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"
    # H2.3 — typed final states for per-session cost / iteration caps.
    # These are *not* errors; the loop terminates cleanly with a
    # descriptive state so the caller (CLI, REPL, tests) can surface
    # a friendly message instead of a stack trace.
    COST_LIMIT_REACHED = "cost_limit_reached"
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"


@dataclass
class AgentResult:
    """The final result of an agent run."""

    output: str
    step_count: int
    state: AgentState
    # Typed final-state string for persistence. When a cap fires, the
    # loop sets this to ``"cost_limit_reached"`` /
    # ``"iteration_limit_reached"``; otherwise ``None``. Callers that
    # write to a :class:`forgewright.session.Session` can copy this
    # straight into ``session.metadata["final_state"]``.
    final_state: str | None = None
    messages: list[ChatMessage] = field(default_factory=list)


class Memory:
    """Bounded message history with a simple stuck-loop detector."""

    def __init__(self, max_messages: int | None = None) -> None:
        cap = max_messages if max_messages is not None else get_settings().agent.memory_max_messages
        self._buf: deque[ChatMessage] = deque(maxlen=cap)
        self._last_assistant: str | None = None
        self._duplicate_count = 0

    def append(self, message: ChatMessage) -> None:
        self._buf.append(message)
        if message.role == "assistant":
            if message.content == self._last_assistant:
                self._duplicate_count += 1
            else:
                self._duplicate_count = 0
            self._last_assistant = message.content

    def snapshot(self) -> list[ChatMessage]:
        return list(self._buf)

    def is_stuck(self, threshold: int = 2) -> bool:
        return self._duplicate_count >= threshold

    def __len__(self) -> int:
        return len(self._buf)


class BaseAgent:
    """The base of the agent stack. Adds state, memory, and a step loop."""

    def __init__(self, llm: LLM, max_steps: int = 8) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.state: AgentState = AgentState.IDLE
        self.step_count: int = 0
        self.memory = Memory()

    async def run(self, prompt: str, max_steps: int | None = None) -> AgentResult:
        """Run the agent until it signals FINISHED, errors, or hits max_steps."""
        cap = max_steps or self.max_steps
        self.state = AgentState.RUNNING
        self.step_count = 0
        self.memory.append(ChatMessage(role="user", content=prompt))
        logger.info("agent.start prompt_len={} cap={}", len(prompt), cap)

        while self.state == AgentState.RUNNING and self.step_count < cap:
            self.step_count += 1
            try:
                await self.step()
            except CostLimitReached as exc:
                # H2.3 — cost cap is a typed final state, not an error.
                # The MeteredLLM wrapper raises this pre-call so the LLM
                # is never invoked against an already-exhausted budget.
                logger.warning(
                    "agent.cost_limit_reached cost={:.4f} cap={:.4f}",
                    exc.cost,
                    exc.cap,
                )
                self.state = AgentState.COST_LIMIT_REACHED
                return AgentResult(
                    output=str(exc),
                    step_count=self.step_count,
                    state=self.state,
                    final_state="cost_limit_reached",
                    messages=self.memory.snapshot(),
                )
            except IterationLimitReached as exc:
                # H2.3 — iteration cap is also a typed final state.
                logger.warning(
                    "agent.iteration_limit_reached iterations={} cap={}",
                    exc.iterations,
                    exc.cap,
                )
                self.state = AgentState.ITERATION_LIMIT_REACHED
                return AgentResult(
                    output=str(exc),
                    step_count=self.step_count,
                    state=self.state,
                    final_state="iteration_limit_reached",
                    messages=self.memory.snapshot(),
                )
            except Exception as exc:
                logger.exception("agent.step error")
                self.state = AgentState.ERROR
                return AgentResult(
                    output=str(exc),
                    step_count=self.step_count,
                    state=self.state,
                    messages=self.memory.snapshot(),
                )

            if self.memory.is_stuck():
                logger.warning("agent.stuck step={}", self.step_count)
                self.memory.append(
                    ChatMessage(
                        role="system",
                        content=(
                            "You appear to be repeating the same response. "
                            "Restate your goal and try a different strategy. "
                            "If a tool is broken, escalate to the user via ask_human."
                        ),
                    )
                )

        if self.state == AgentState.RUNNING:
            logger.info("agent.max_steps reached step={}", self.step_count)
            self.state = AgentState.FINISHED

        last = self.memory.snapshot()[-1] if len(self.memory) else None
        return AgentResult(
            output=last.content if last else "",
            step_count=self.step_count,
            state=self.state,
            messages=self.memory.snapshot(),
        )

    async def step(self) -> None:
        """One iteration: ask the LLM and append the response.

        Subclasses override this to add think/act phases or tool dispatch.
        """
        response = await self.llm.ask(self.memory.snapshot())
        self.memory.append(response)
        if "TASK_COMPLETE" in response.content:
            self.state = AgentState.FINISHED


__all__ = ["AgentResult", "AgentState", "BaseAgent", "Memory"]
