r"""PlanningFlow — multi-agent orchestrator that decomposes a task into
sub-agent runs and monitors their progress.

Algorithm:

1. Ask the LLM to decompose the high-level prompt into a small ordered
   list of ``{title, description, agent}`` steps (parse JSON, tolerate
   ````json`` fences, fall back to a single ``Manus`` step on failure).
2. Register the steps on the shared :class:`PlanningTool`.
3. For each step in order:
   - mark it ``in_progress``,
   - instantiate the right sub-agent with a tool collection that
     includes the agent's defaults **plus** the shared planning tool,
   - ``await agent.run(...)`` and capture the final output,
   - mark the step ``completed`` (with the truncated output as a note)
     or ``blocked`` if the sub-agent errored.
4. Return a :class:`FlowResult` carrying the final step list, the
   overall state, the rolled-up output, and the message log.

The whole flow is wrapped in :func:`asyncio.wait_for` so a hung
sub-agent cannot exceed ``timeout_s``.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from forgewright.agent import (
    AgentState,
    BrowserAgent,
    DataAnalysis,
    Manus,
    MCPAgent,
)
from forgewright.agent.prompts import load_prompt
from forgewright.agent.tool_call import ToolCallAgent
from forgewright.flow.planning_prompts import DECOMPOSE_PROMPT
from forgewright.flow.planning_tool import PlanningTool, Step, StepStatus
from forgewright.llm import LLM
from forgewright.logger import logger
from forgewright.schema import ChatMessage
from forgewright.tool import ToolCollection

__all__ = ["FlowResult", "PlanningFlow"]


@dataclass
class FlowResult:
    """The end-of-flow summary returned to the caller / CLI."""

    output: str
    state: AgentState
    steps: list[Step]
    total_step_count: int
    messages: list[ChatMessage] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render the flow as a markdown report."""
        if not self.steps:
            return self.output or "_No steps were executed._"
        header = "| id | title | agent | status |\n|---|---|---|---|"
        body = "\n".join(step.to_row() for step in self.steps)
        parts: list[str] = [f"## Plan ({self.total_step_count} step(s))\n", header, body]
        if self.output:
            parts.append("\n## Final output\n")
            parts.append(self.output)
        return "\n".join(parts)


# Match the first ```json ... ``` (or ``` ... ```) block in the text.
_JSON_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*(\[.*?\])\s*```",
    re.DOTALL,
)
# ... or a bare top-level array.
_BARE_ARRAY_RE = re.compile(r"(\[.*\])", re.DOTALL)


class PlanningFlow:
    """Multi-agent orchestrator.

    Decomposes a high-level prompt into a plan, allocates each step to a
    sub-agent, runs the agents sequentially, and tracks progress on a
    shared :class:`PlanningTool`.
    """

    DEFAULT_AGENTS: ClassVar[dict[str, type[Manus]]] = {
        "manus": Manus,
        "data_analysis": DataAnalysis,
        "browser_agent": BrowserAgent,
        "mcp_agent": MCPAgent,
    }

    def __init__(
        self,
        llm: LLM,
        agents: dict[str, type[Manus]] | None = None,
        max_total_steps: int = 30,
        per_agent_max_steps: int = 8,
        timeout_s: int = 3600,
    ) -> None:
        """Configure the flow.

        Args:
            llm: LLM backend used for decomposition and (transitively) by
                every sub-agent. The same backend is shared end-to-end.
            agents: Optional override map of agent-name -> subclass of
                :class:`Manus`. Defaults to the four built-in sub-agents.
            max_total_steps: Hard cap on the number of decomposed steps
                the flow will execute.
            per_agent_max_steps: Per-sub-agent iteration budget.
            timeout_s: Wall-clock cap on the whole flow (default 60 min).
        """
        self.llm = llm
        self.agents = agents or self.DEFAULT_AGENTS
        self.max_total_steps = max_total_steps
        self.per_agent_max_steps = per_agent_max_steps
        self.timeout_s = timeout_s
        self.planning_tool = PlanningTool()

    # ------------------------------------------------------------------ #
    # Decomposition
    # ------------------------------------------------------------------ #

    async def _decompose(self, prompt: str) -> list[dict[str, Any]]:
        """Ask the LLM to split `prompt` into a JSON list of steps.

        Tolerates triple-backtick JSON fences and bare arrays. Falls back
        to a single ``Manus`` step on any parse failure so the flow
        always has something to run.
        """
        messages = [
            ChatMessage(
                role="user",
                content=f"{DECOMPOSE_PROMPT}\n\nTask: {prompt}",
            )
        ]
        try:
            response = await self.llm.ask(messages)
            raw = response.content or ""
        except Exception as exc:  # broad: never let a bad LLM kill the flow
            logger.warning("flow.decompose_llm_error err={}", exc)
            return self._fallback_steps(prompt)

        parsed = self._parse_step_list(raw)
        if parsed is None:
            logger.warning("flow.decompose_parse_failure raw={!r}", raw[:200])
            return self._fallback_steps(prompt)
        # Cap to max_total_steps up front; let the caller log a notice.
        return parsed[: self.max_total_steps]

    @staticmethod
    def _parse_step_list(text: str) -> list[dict[str, Any]] | None:
        """Extract and validate a JSON step list from the LLM's text."""
        match = _JSON_FENCE_RE.search(text) or _BARE_ARRAY_RE.search(text)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("flow.decompose_json_error err={} text={!r}", exc, text[:200])
            return None
        if not isinstance(data, list):
            return None
        cleaned: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            description = item.get("description")
            agent = item.get("agent")
            if not (
                isinstance(title, str) and isinstance(description, str) and isinstance(agent, str)
            ):
                continue
            if not (title.strip() and description.strip() and agent.strip()):
                continue
            cleaned.append(
                {
                    "title": title.strip(),
                    "description": description.strip(),
                    "agent": agent.strip(),
                }
            )
        return cleaned or None

    @staticmethod
    def _fallback_steps(prompt: str) -> list[dict[str, Any]]:
        """The single-step fallback when decomposition fails."""
        return [
            {
                "title": prompt[:80] or "Run task",
                "description": prompt,
                "agent": "manus",
            }
        ]

    # ------------------------------------------------------------------ #
    # Agent construction
    # ------------------------------------------------------------------ #

    def _resolve_agent_class(self, name: str) -> type[Manus]:
        """Look up the agent class for a step, defaulting to :class:`Manus`."""
        return self.agents.get(name, Manus)

    def _build_agent(self, cls: type[Manus], description: str) -> Manus:
        """Build a sub-agent with the planning tool injected.

        The sub-agent's default tool set (read from ``cls.DEFAULT_TOOLS``)
        is unioned with the shared :class:`PlanningTool`. The agent's
        system prompt is rebuilt so its "Currently available tools" line
        stays honest after the planning tool is added.

        We construct the agent with :class:`ToolCallAgent.__init__`
        directly to avoid the subclass's ``__init__`` rebuilding a
        tool collection that omits the planning tool.
        """
        # Instantiate default tools, then add the shared planning tool.
        defaults = [tool_cls() for tool_cls in cls.DEFAULT_TOOLS]
        # The same PlanningTool instance is reused across steps.
        defaults.append(self.planning_tool)
        tools = ToolCollection(defaults)

        system_prompt = load_prompt(cls.DEFAULT_PROMPT) + self._tools_inventory(tools)
        _ = description  # accepted for future templating

        # Bypass cls.__init__ (which would rebuild its own tool set) and
        # call ToolCallAgent.__init__ directly so the planning tool is
        # present in the collection we hand to the agent.
        agent = cls.__new__(cls)
        ToolCallAgent.__init__(
            agent,
            llm=self.llm,
            tools=tools,
            max_steps=self.per_agent_max_steps,
            system_prompt=system_prompt,
        )
        return agent

    @staticmethod
    def _tools_inventory(tools: ToolCollection) -> str:
        """Tail appended to the system prompt listing available tools."""
        names = ", ".join(tools.names())
        return f"\n\nCurrently available tools: {names}."

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    async def _run_step(
        self,
        step: Step,
        description: str,
    ) -> tuple[Step, AgentState, str]:
        """Execute one step: mark in_progress, run sub-agent, mark result."""
        await self.planning_tool(
            action="mark_step",
            step_id=step.id,
            status=StepStatus.IN_PROGRESS,
        )

        cls = self._resolve_agent_class(step.agent)
        try:
            agent = self._build_agent(cls, description)
        except Exception as exc:
            logger.exception("flow.build_agent_error step={} err={}", step.id, exc)
            return step, AgentState.ERROR, f"agent build failed: {exc}"

        prompt = (
            f"{description}\n\n"
            "Update your progress via the planning tool "
            "(`mark_step` when you start/finish, `update_step` for notes). "
            "Call `terminate` with a final reason when you are done."
        )
        try:
            result = await agent.run(prompt, max_steps=self.per_agent_max_steps)
        except Exception as exc:
            logger.exception("flow.step_error step={} err={}", step.id, exc)
            return step, AgentState.ERROR, f"agent raised: {exc}"

        output = (result.output or "").strip()
        return step, result.state, output

    async def _execute(self, steps: list[Step]) -> list[tuple[Step, AgentState, str]]:
        """Run every step in order; a blocked step does not halt the flow."""
        results: list[tuple[Step, AgentState, str]] = []
        for step in steps:
            step_obj, state, output = await self._run_step(step, step.description)
            results.append((step_obj, state, output))
        return results

    @staticmethod
    async def _finalize_step(
        step: Step,
        state: AgentState,
        output: str,
        planner: PlanningTool,
    ) -> None:
        """Mark a step completed or blocked depending on the sub-agent's state."""
        truncated = output[:200] if output else ""
        if state == AgentState.ERROR or not output:
            await planner(
                action="mark_step",
                step_id=step.id,
                status=StepStatus.BLOCKED,
                notes=truncated or f"agent ended in {state.value}",
            )
        else:
            await planner(
                action="mark_step",
                step_id=step.id,
                status=StepStatus.COMPLETED,
                notes=truncated or "(no output)",
            )

    # ------------------------------------------------------------------ #
    # Top-level entry
    # ------------------------------------------------------------------ #

    async def run(self, prompt: str) -> FlowResult:
        """Decompose `prompt` and execute the resulting plan."""
        logger.info("flow.start prompt_len={} agents={}", len(prompt), sorted(self.agents))

        # 1. Decompose.
        raw_steps = await self._decompose(prompt)
        if len(raw_steps) > self.max_total_steps:
            logger.warning(
                "flow.decompose_truncated had={} cap={}",
                len(raw_steps),
                self.max_total_steps,
            )
            raw_steps = raw_steps[: self.max_total_steps]

        # 2. Register.
        create_result = await self.planning_tool(
            action="create_steps",
            steps=raw_steps,
        )
        if create_result.is_error:
            logger.error("flow.create_steps_error error={}", create_result.error)
            return FlowResult(
                output=f"Failed to register plan: {create_result.error}",
                state=AgentState.ERROR,
                steps=[],
                total_step_count=0,
                messages=[],
            )

        steps = list(self.planning_tool.steps.values())

        # 3. Execute (with a wall-clock timeout).
        try:
            results = await asyncio.wait_for(
                self._execute(steps),
                timeout=self.timeout_s,
            )
        except TimeoutError:
            logger.error("flow.timeout timeout_s={}", self.timeout_s)
            await self._block_remaining()
            return FlowResult(
                output=f"Flow timed out after {self.timeout_s}s",
                state=AgentState.ERROR,
                steps=list(self.planning_tool.steps.values()),
                total_step_count=len(self.planning_tool.steps),
                messages=[],
            )

        # 4. Finalize each step.
        messages: list[ChatMessage] = []
        last_output = ""
        overall_state = AgentState.FINISHED
        for step, state, output in results:
            await self._finalize_step(step, state, output, self.planning_tool)
            if output:
                last_output = output
            if state == AgentState.ERROR:
                overall_state = AgentState.ERROR
            messages.append(
                ChatMessage(
                    role="tool",
                    content=(
                        f"step {step.id} ({step.agent}) -> {step.status.value}: {output[:200]}"
                    ),
                    name="planning",
                )
            )

        final_steps = list(self.planning_tool.steps.values())
        return FlowResult(
            output=last_output,
            state=overall_state,
            steps=final_steps,
            total_step_count=len(final_steps),
            messages=messages,
        )

    async def _block_remaining(self) -> None:
        """Mark every step that hasn't finished as `blocked` (used on timeout)."""
        for step in self.planning_tool.steps.values():
            if step.status in (StepStatus.NOT_STARTED, StepStatus.IN_PROGRESS):
                await self.planning_tool(
                    action="mark_step",
                    step_id=step.id,
                    status=StepStatus.BLOCKED,
                    notes="flow timed out",
                )
