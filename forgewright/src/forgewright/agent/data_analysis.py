"""DataAnalysis — the data analysis sub-agent (Python + viz + file editing)."""

from __future__ import annotations

from typing import ClassVar

from forgewright.agent.manus import Manus
from forgewright.tool import DataVisualization, PythonExecuteTool, StrReplaceEditor, TerminateTool
from forgewright.tool.base import BaseTool

__all__ = ["DataAnalysis"]


class DataAnalysis(Manus):
    """Data analysis sub-agent: Python + visualization + file editing.

    Bash is intentionally excluded — the orchestrator owns shell access.
    WebSearch and AskHuman are also out of scope: this agent works the
    problem the user hands it and reports back, it doesn't widen the
    information surface or escalate mid-task.
    """

    DEFAULT_TOOLS: ClassVar[tuple[type[BaseTool], ...]] = (
        PythonExecuteTool,
        StrReplaceEditor,
        DataVisualization,
        TerminateTool,
    )
    DEFAULT_PROMPT: ClassVar[str] = "data_analysis"
