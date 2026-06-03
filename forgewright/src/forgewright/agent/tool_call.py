"""ToolCallAgent — native function-calling loop with concurrent dispatch."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from forgewright.agent.base import AgentState, BaseAgent
from forgewright.agent.prompts import load_prompt
from forgewright.llm import LLM
from forgewright.logger import logger
from forgewright.schema import ChatMessage
from forgewright.tool import ToolCollection

__all__ = ["ToolCallAgent"]


class ToolCallAgent(BaseAgent):
    """ToolCallAgent — uses the LLM's native function-calling API.

    Calls `llm.ask_tool(messages, tool_specs)`. If the response has tool
    calls, dispatches them through the ToolCollection concurrently. If no
    tool call, treats the content as the final response.
    """

    def __init__(
        self,
        llm: LLM,
        tools: ToolCollection,
        max_steps: int = 8,
        system_prompt: str | None = None,
        tool_spec_provider: Literal["openai", "anthropic"] = "openai",
    ) -> None:
        super().__init__(llm=llm, max_steps=max_steps)
        self.tools = tools
        self.tool_spec_provider = tool_spec_provider
        prompt = system_prompt or load_prompt("tool_call")
        self.memory.append(ChatMessage(role="system", content=prompt))

    def _tool_specs(self) -> list[dict[str, Any]]:
        """Render the tool collection in the active provider's wire format."""
        if self.tool_spec_provider == "openai":
            return self.tools.to_openai_tools()
        return self.tools.to_anthropic_tools()

    async def step(self) -> None:
        """One iteration: ask_tool -> dispatch -> observe (concurrent)."""
        response = await self.llm.ask_tool(
            self.memory.snapshot(),
            self._tool_specs(),  # type: ignore[arg-type]
        )
        # Persist the assistant turn (content + any tool calls are kept on
        # the same message).
        self.memory.append(
            ChatMessage(
                role="assistant",
                content=response.content,
            )
        )
        if not response.tool_calls:
            # No work requested — final response. Honor the explicit token.
            if "TASK_COMPLETE" in response.content:
                self.state = AgentState.FINISHED
            return

        # Dispatch every requested tool call concurrently. Each call is
        # validated and time-bounded by BaseTool, so a slow tool doesn't
        # block the others.
        results = await asyncio.gather(
            *(self.tools.call(tc.name, **tc.args) for tc in response.tool_calls)
        )
        for tc, result in zip(response.tool_calls, results, strict=False):
            observation = f"Tool '{tc.name}' returned:\n{result.output or result.error}"
            self.memory.append(
                ChatMessage(
                    role="tool",
                    content=observation,
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )
            # Finish on a `terminate` tool call, or on a non-error result
            # that contains the explicit completion token.
            if tc.name == "terminate" or (
                not result.is_error and "TASK_COMPLETE" in (result.output or "")
            ):
                self.state = AgentState.FINISHED
            logger.info(
                "tool_call.dispatched name={} is_error={} id={}",
                tc.name,
                result.is_error,
                tc.id,
            )
