"""BaseAgent — the smallest viable agent: state, memory, step loop."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from forgewright.llm import LLM
from forgewright.logger import logger
from forgewright.schema import ChatMessage


class AgentState(StrEnum):
    """The lifecycle states of an agent."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class AgentResult:
    """The final result of an agent run."""

    output: str
    step_count: int
    state: AgentState
    messages: list[ChatMessage] = field(default_factory=list)


class Memory:
    """Bounded message history with a simple stuck-loop detector."""

    def __init__(self, max_messages: int = 200) -> None:
        self._buf: deque[ChatMessage] = deque(maxlen=max_messages)
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
