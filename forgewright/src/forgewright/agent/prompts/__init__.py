"""Markdown prompt files for each agent.

Each subclass of `BaseAgent` loads a default system prompt from this package
by calling `load_prompt("<name>")`. Override `system_prompt` in `__init__` to
ship a custom one.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["load_prompt"]


def load_prompt(name: str) -> str:
    """Read `agent/prompts/<name>.md` and return its text contents.

    The path is resolved relative to this module so the file is found no
    matter the current working directory. Raises `FileNotFoundError` if
    the prompt does not exist — this is intentional: a missing prompt is
    a build-time bug, not a runtime condition.
    """
    path = Path(__file__).parent / f"{name}.md"
    return path.read_text(encoding="utf-8")
