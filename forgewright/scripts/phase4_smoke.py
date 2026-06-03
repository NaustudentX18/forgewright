"""Phase 4 smoke: build a ToolCollection of the 5 concrete tools, exercise each."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from forgewright.tool import (
    AskHumanTool,
    BashTool,
    PythonExecuteTool,
    StrReplaceEditor,
    TerminateTool,
    ToolCollection,
)

workspace = Path.home() / ".local" / "share" / "forgewright" / "workspace"
workspace.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="forgewright_smoke_"))


async def main() -> int:
    print("--- Phase 4 smoke ---")
    tools = ToolCollection(
        [
            TerminateTool(),
            AskHumanTool(),
            BashTool(),
            PythonExecuteTool(),
            StrReplaceEditor(),
        ]
    )
    print(f"loaded {len(tools)} tools: {tools.names()}")

    r = await tools.call("bash", cmd="echo hello from bash")
    assert r.is_error is False
    assert "hello from bash" in r.output
    print(f"  bash OK: {r.output.splitlines()[0]}")

    r = await tools.call("bash", cmd="rm -rf /")
    assert r.is_error is True
    assert "Refused" in (r.error or "")
    print("  bash.denylist OK: refused 'rm -rf /'")

    r = await tools.call("python_execute", code="print('hi from py'); 2+2")
    assert r.is_error is False
    assert "hi from py" in r.output
    print(f"  python_execute OK: {r.output.splitlines()[0]}")

    editor = StrReplaceEditor()
    target = tmp / "test.md"
    r = await editor(
        command="create",
        path=str(target),
        file_text="line one\nline two\nline three\n",
        allow_outside_workspace=True,
    )
    assert not r.is_error
    r = await editor(
        command="str_replace",
        path=str(target),
        old_str="line two",
        new_str="LINE TWO",
        allow_outside_workspace=True,
    )
    assert not r.is_error
    r = await editor(command="view", path=str(target), allow_outside_workspace=True)
    assert "LINE TWO" in r.output
    r = await editor(command="undo_edit", path=str(target), allow_outside_workspace=True)
    assert not r.is_error
    r = await editor(command="view", path=str(target), allow_outside_workspace=True)
    assert "line two" in r.output
    assert "LINE TWO" not in r.output
    print("  editor OK: create + str_replace + undo")

    r = await tools.call("terminate", reason="phase 4 smoke complete")
    assert not r.is_error
    assert "Terminated" in r.output
    print(f"  terminate OK: {r.output}")

    openai_specs = tools.to_openai_tools()
    anthropic_specs = tools.to_anthropic_tools()
    assert len(openai_specs) == 5
    assert len(anthropic_specs) == 5
    print(f"  specs OK: {len(openai_specs)} openai, {len(anthropic_specs)} anthropic")

    print("PHASE 4 SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
