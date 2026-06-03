"""Agent layer: Base -> ReAct -> ToolCall -> Manus -> sub-agents."""

from __future__ import annotations

from forgewright.agent.base import AgentResult, AgentState, BaseAgent, Memory
from forgewright.agent.browser_agent import BrowserAgent
from forgewright.agent.data_analysis import DataAnalysis
from forgewright.agent.manus import Manus
from forgewright.agent.mcp_agent import MCPAgent
from forgewright.agent.prompts import load_prompt
from forgewright.agent.react import ReActAgent
from forgewright.agent.tool_call import ToolCallAgent

__all__ = [
    "AgentResult",
    "AgentState",
    "BaseAgent",
    "BrowserAgent",
    "DataAnalysis",
    "MCPAgent",
    "Manus",
    "Memory",
    "ReActAgent",
    "ToolCallAgent",
    "load_prompt",
]
