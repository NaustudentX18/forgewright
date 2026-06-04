"""StrReplaceEditor — view/create/edit/undo text files within a workspace root."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from typing import Any, ClassVar

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool
from forgewright.workspace import Workspace

__all__ = ["StrReplaceEditor"]


class _OutsideWorkspace(Exception):
    """Internal sentinel: a resolved path escaped the workspace root."""


class StrReplaceEditor(BaseTool):
    """View, create, edit, and undo edits to text files within a workspace root."""

    name: ClassVar[str] = "str_replace_editor"
    description: ClassVar[str] = (
        "View, create, edit, and undo edits to text files. "
        "Use command='view' to read, 'create' to write a new file, "
        "'str_replace' to swap a unique string, 'insert' to add a line, "
        "'undo_edit' to revert the last edit."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
            },
            "path": {
                "type": "string",
                "description": "Absolute or workspace-relative path.",
            },
            "file_text": {
                "type": "string",
                "description": "Content for 'create'.",
            },
            "old_str": {
                "type": "string",
                "description": "The unique string to replace (str_replace).",
            },
            "new_str": {
                "type": "string",
                "description": "The replacement (str_replace) or text to insert.",
            },
            "insert_line": {
                "type": "integer",
                "description": "Line number AFTER which to insert (insert).",
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[start, end] line numbers for view. 1-indexed, inclusive.",
            },
            "allow_outside_workspace": {
                "type": "boolean",
                "default": False,
                "description": "If true, skip the workspace path-confinement check.",
            },
        },
        "required": ["command", "path"],
    }
    timeout_s: ClassVar[int] = 30
    _workspace_root: ClassVar[Path] = Path.home() / ".local" / "share" / "forgewright" / "workspace"

    def __init__(self) -> None:
        """Initialize the per-instance undo-history map and base validator."""
        super().__init__()
        self._history: dict[Path, deque[str]] = {}
        # When set, path resolution is confined to ``self.workspace.root``
        # and writes land inside that root. Wired by ``ToolCollection``
        # (see H1.2). ``None`` preserves the legacy class-level root.
        self.workspace: Workspace | None = None

    async def _run(  # type: ignore[override]
        self,
        *,
        command: str,
        path: str,
        file_text: str | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
        view_range: list[int] | None = None,
        allow_outside_workspace: bool = False,
    ) -> ToolResult:
        """Dispatch to the requested command after path-confinement."""
        try:
            target = self._resolve_path(path, allow_outside_workspace)
        except _OutsideWorkspace as exc:
            return ToolResult(is_error=True, error=str(exc))

        if command == "view":
            return await asyncio.to_thread(self._view, target, view_range)
        if command == "create":
            if file_text is None:
                return ToolResult(
                    is_error=True, error="`file_text` is required for command='create'."
                )
            return await asyncio.to_thread(self._create, target, file_text)
        if command == "str_replace":
            if old_str is None or new_str is None:
                return ToolResult(
                    is_error=True,
                    error="`old_str` and `new_str` are required for command='str_replace'.",
                )
            return await asyncio.to_thread(self._str_replace, target, old_str, new_str)
        if command == "insert":
            if new_str is None or insert_line is None:
                return ToolResult(
                    is_error=True,
                    error="`new_str` and `insert_line` are required for command='insert'.",
                )
            return await asyncio.to_thread(self._insert, target, insert_line, new_str)
        if command == "undo_edit":
            return await asyncio.to_thread(self._undo_edit, target)
        return ToolResult(is_error=True, error=f"Unknown command: {command}")

    def _resolve_path(self, path: str, allow_outside: bool) -> Path:
        """Resolve `path` and ensure it lives inside the workspace root (unless overridden)."""
        root = self.workspace.root if self.workspace is not None else self._workspace_root
        resolved = Path(path).resolve()
        if allow_outside:
            return resolved
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            logger.warning("str_replace_editor.outside_workspace path={} root={}", path, root)
            raise _OutsideWorkspace(
                f"Path '{path}' is outside the workspace. "
                "Pass allow_outside_workspace=true to override."
            ) from exc
        return resolved

    @staticmethod
    def _gutter(content: str, start_line: int) -> str:
        """Render `content` with a `cat -n`-style line-number gutter starting at `start_line`."""
        if not content:
            return ""
        lines = content.splitlines()
        width = len(str(start_line + len(lines) - 1))
        return "\n".join(
            f"{str(start_line + i).rjust(width)}\t{line}" for i, line in enumerate(lines)
        )

    def _view(self, path: Path, view_range: list[int] | None) -> ToolResult:
        """Read the file and optionally slice by [start, end] inclusive 1-indexed line numbers."""
        if not path.exists() or not path.is_file():
            logger.info("str_replace_editor.view.missing path={}", path)
            return ToolResult(is_error=True, error=f"File not found: {path}")
        content = path.read_text(encoding="utf-8")
        if view_range is not None:
            if len(view_range) != 2:
                return ToolResult(
                    is_error=True,
                    error="`view_range` must be a 2-element list [start, end].",
                )
            lines = content.splitlines()
            total = len(lines)
            if total == 0:
                return ToolResult(output="")
            start = max(1, min(view_range[0], total))
            end = max(start, min(view_range[1], total))
            sliced = "\n".join(lines[start - 1 : end])
            return ToolResult(output=self._gutter(sliced, start))
        return ToolResult(output=self._gutter(content, 1))

    def _create(self, path: Path, file_text: str) -> ToolResult:
        """Write `file_text` to `path`, refusing to overwrite an existing file."""
        if path.exists():
            logger.info("str_replace_editor.create.exists path={}", path)
            return ToolResult(is_error=True, error=f"File already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._push_snapshot(path)
        path.write_text(file_text, encoding="utf-8")
        logger.info("str_replace_editor.create path={} bytes={}", path, len(file_text))
        return ToolResult(output=f"File created at {path}")

    def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        """Replace the unique occurrence of `old_str` with `new_str` in the file."""
        if not path.exists() or not path.is_file():
            return ToolResult(is_error=True, error=f"File not found: {path}")
        content = path.read_text(encoding="utf-8")
        count = content.count(old_str)
        if count == 0:
            return ToolResult(is_error=True, error=f"`old_str` not found in {path}.")
        if count > 1:
            return ToolResult(
                is_error=True,
                error=f"`old_str` is not unique in {path}: found {count} occurrences.",
            )
        self._push_snapshot(path)
        path.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
        logger.info(
            "str_replace_editor.replace path={} old_bytes={} new_bytes={}",
            path,
            len(old_str),
            len(new_str),
        )
        return ToolResult(output=f"Replacement applied to {path}")

    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        """Insert `new_str` as a single new line after `insert_line` (1-indexed; 0 = top)."""
        if not path.exists() or not path.is_file():
            return ToolResult(is_error=True, error=f"File not found: {path}")
        if "\n" in new_str or "\r" in new_str:
            return ToolResult(
                is_error=True,
                error="`new_str` for insert must be a single line (no embedded newlines).",
            )
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        if insert_line < 0 or insert_line > len(lines):
            return ToolResult(
                is_error=True,
                error=(f"insert_line {insert_line} is out of range (file has {len(lines)} lines)."),
            )
        self._push_snapshot(path)
        lines.insert(insert_line, new_str)
        new_content = "\n".join(lines)
        if content.endswith("\n") or not content:
            new_content += "\n"
        path.write_text(new_content, encoding="utf-8")
        logger.info("str_replace_editor.insert path={} line={}", path, insert_line + 1)
        return ToolResult(output=f"Inserted line at {insert_line + 1} in {path}")

    def _undo_edit(self, path: Path) -> ToolResult:
        """Revert the most recent edit on `path` from the per-instance undo stack."""
        stack = self._history.get(path)
        if not stack:
            return ToolResult(is_error=True, error=f"No edits to undo for {path}")
        snapshot = stack.pop()
        if snapshot == "":
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(snapshot, encoding="utf-8")
        logger.info("str_replace_editor.undo path={} remaining={}", path, len(stack))
        return ToolResult(output=f"Reverted {path} to previous state")

    def _push_snapshot(self, path: Path) -> None:
        """Snapshot the current on-disk content of `path` (or `""` if absent) onto the stack."""
        if path not in self._history:
            self._history[path] = deque(maxlen=10)
        snapshot = path.read_text(encoding="utf-8") if path.exists() else ""
        self._history[path].append(snapshot)
