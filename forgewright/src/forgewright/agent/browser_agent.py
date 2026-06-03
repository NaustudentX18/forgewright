"""BrowserAgent — browser-only sub-agent.

A focused ``Manus`` subclass that exposes only the browser tool plus
``ask_human`` (for escalation) and ``terminate`` (for clean shutdown).
The persona prompt is loaded from ``agent/prompts/browser.md``.
"""

from __future__ import annotations

from typing import ClassVar

from forgewright.agent.manus import Manus
from forgewright.tool import AskHumanTool, BrowserUseTool, TerminateTool
from forgewright.tool.base import BaseTool

__all__ = ["BrowserAgent"]


class BrowserAgent(Manus):
    """Browser-only sub-agent. Uses the BrowserUseTool plus ask_human/terminate.

    The ``__init__`` is inherited from :class:`Manus`, which already reads
    ``self.DEFAULT_TOOLS`` and ``self.DEFAULT_PROMPT`` to assemble the
    tool collection and load the persona prompt.
    """

    DEFAULT_TOOLS: ClassVar[tuple[type[BaseTool], ...]] = (
        BrowserUseTool,
        AskHumanTool,
        TerminateTool,
    )
    DEFAULT_PROMPT: ClassVar[str] = "browser"
