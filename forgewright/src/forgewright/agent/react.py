"""ReActAgent — two-phase (think, act) loop for free-form tool parsing."""

from __future__ import annotations

import json
import re

from forgewright.agent.base import AgentState, BaseAgent
from forgewright.agent.prompts import load_prompt
from forgewright.llm import LLM
from forgewright.logger import logger
from forgewright.schema import ChatMessage, ToolResult
from forgewright.tool import ToolCollection

__all__ = ["ReActAgent"]


# Match `Action: <name>` and `Action Input: <json>` anywhere in the response.
# DOTALL so the JSON object can span newlines. Non-greedy so a second
# `Action:` line later in the text doesn't poison the first match.
_ACTION_RE = re.compile(r"Action:\s*(\w+)", re.IGNORECASE)
_INPUT_RE = re.compile(r"Action Input:\s*(\{.*?\})", re.IGNORECASE | re.DOTALL)


class ReActAgent(BaseAgent):
    """ReAct: explicit think/act phases.

    Useful for models that don't yet support structured function calling.
    The agent asks the LLM for free-form text, parses `Action:` and
    `Action Input:`, dispatches the tool call, and appends an observation.
    """

    def __init__(
        self,
        llm: LLM,
        tools: ToolCollection,
        max_steps: int = 8,
        system_prompt: str | None = None,
    ) -> None:
        super().__init__(llm=llm, max_steps=max_steps)
        self.tools = tools
        prompt = system_prompt or load_prompt("react")
        self.memory.append(ChatMessage(role="system", content=prompt))

    async def think(self) -> str:
        """Ask the LLM to produce a Thought + Action + Action Input block."""
        response = await self.llm.ask(self.memory.snapshot())
        return response.content

    async def act(self, thought: str) -> ToolResult:
        """Parse the Action and Action Input from the thought, dispatch the tool."""
        action, action_input = self._parse_action(thought)
        if action is None:
            # No tool call — treat as terminal.
            self.state = AgentState.FINISHED
            return ToolResult(output="(no action)")
        if action == "terminate":
            self.state = AgentState.FINISHED
            reason = ""
            if isinstance(action_input, dict):
                reason = str(action_input.get("reason", "done"))
            return ToolResult(output=f"Terminated: {reason or 'done'}")
        return await self.tools.call(action, **action_input)

    async def step(self) -> None:
        """One iteration: think -> act -> observe."""
        thought = await self.think()
        self.memory.append(ChatMessage(role="assistant", content=thought))
        result = await self.act(thought)
        observation = f"Observation: {result.output or result.error}"
        self.memory.append(ChatMessage(role="tool", content=observation))
        if "TASK_COMPLETE" in thought or self.state == AgentState.FINISHED:
            self.state = AgentState.FINISHED

    @staticmethod
    def _parse_action(text: str) -> tuple[str | None, dict[str, object]]:
        """Parse `Action: name` and `Action Input: {json}` from the LLM's text.

        Returns `(action_name, args_dict)` on success.
        Returns `(None, {})` if either the `Action:` line is missing, the
        `Action Input:` line is missing, or the JSON fails to parse.
        """
        action_match = _ACTION_RE.search(text)
        if action_match is None:
            return None, {}
        action = action_match.group(1).strip()

        input_match = _INPUT_RE.search(text)
        if input_match is None:
            return action, {}
        raw = input_match.group(1)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("react.invalid_json err={} raw={!r}", exc, raw[:200])
            return action, {}
        if not isinstance(parsed, dict):
            logger.warning("react.not_object type={}", type(parsed).__name__)
            return action, {}
        return action, dict(parsed)
