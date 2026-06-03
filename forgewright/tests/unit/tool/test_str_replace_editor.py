"""Tests for the StrReplaceEditor tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from forgewright.schema import ToolResult
from forgewright.tool.str_replace_editor import StrReplaceEditor


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the editor's workspace root at a fresh tmp_path for each test."""
    monkeypatch.setattr(StrReplaceEditor, "_workspace_root", tmp_path)
    return tmp_path


@pytest.fixture
def tool() -> StrReplaceEditor:
    """Return a fresh StrReplaceEditor instance."""
    return StrReplaceEditor()


# --- view command -----------------------------------------------------------


@pytest.mark.asyncio
async def test_view_reads_file_with_line_numbers(tool: StrReplaceEditor, workspace: Path) -> None:
    """view returns the file with a 1-indexed gutter prefix on every line."""
    f = workspace / "hello.txt"
    f.write_text("first line\nsecond line\nthird line\n")
    result = await tool(command="view", path=str(f))
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    out = result.output
    assert "first line" in out
    assert "second line" in out
    assert "third line" in out
    # Gutter markers
    assert "1\tfirst line" in out
    assert "2\tsecond line" in out
    assert "3\tthird line" in out


@pytest.mark.asyncio
async def test_view_with_view_range(tool: StrReplaceEditor, workspace: Path) -> None:
    """view_range=[start, end] returns only the inclusive 1-indexed slice."""
    f = workspace / "hello.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = await tool(command="view", path=str(f), view_range=[2, 4])
    assert result.is_error is False
    out = result.output
    assert "b" in out
    assert "c" in out
    assert "d" in out
    # Gutter shows 2, 3, 4
    assert "2\tb" in out
    assert "3\tc" in out
    assert "4\td" in out
    # No gutter for line 1 or 5
    assert "1\ta" not in out
    assert "5\te" not in out


@pytest.mark.asyncio
async def test_view_missing_file_errors(tool: StrReplaceEditor, workspace: Path) -> None:
    """view on a missing path returns is_error=True."""
    f = workspace / "nope.txt"
    result = await tool(command="view", path=str(f))
    assert result.is_error is True
    assert "File not found" in (result.error or "")


# --- create command ---------------------------------------------------------


@pytest.mark.asyncio
async def test_create_writes_file(tool: StrReplaceEditor, workspace: Path) -> None:
    """create writes the file_text to the path and creates parent dirs."""
    f = workspace / "nested" / "new.txt"
    result = await tool(command="create", path=str(f), file_text="hello world")
    assert result.is_error is False
    assert "File created" in result.output
    assert f.read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
async def test_create_existing_file_refuses(tool: StrReplaceEditor, workspace: Path) -> None:
    """create refuses to overwrite an existing file and leaves content untouched."""
    f = workspace / "existing.txt"
    f.write_text("original")
    result = await tool(command="create", path=str(f), file_text="new content")
    assert result.is_error is True
    assert "already exists" in (result.error or "")
    assert f.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_create_missing_file_text_errors(tool: StrReplaceEditor, workspace: Path) -> None:
    """create without file_text returns an is_error result."""
    f = workspace / "x.txt"
    result = await tool(command="create", path=str(f))
    assert result.is_error is True
    assert "file_text" in (result.error or "")


# --- str_replace command ----------------------------------------------------


@pytest.mark.asyncio
async def test_str_replace_unique(tool: StrReplaceEditor, workspace: Path) -> None:
    """str_replace swaps a unique old_str and writes the new content."""
    f = workspace / "code.py"
    f.write_text("def foo():\n    return 1\n")
    result = await tool(
        command="str_replace",
        path=str(f),
        old_str="return 1",
        new_str="return 42",
    )
    assert result.is_error is False
    assert "Replacement applied" in result.output
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 42\n"


@pytest.mark.asyncio
async def test_str_replace_non_unique_errors(tool: StrReplaceEditor, workspace: Path) -> None:
    """str_replace with a non-unique old_str errors and leaves the file untouched."""
    f = workspace / "code.py"
    original = "foo\nfoo\nfoo\n"
    f.write_text(original)
    result = await tool(command="str_replace", path=str(f), old_str="foo", new_str="bar")
    assert result.is_error is True
    assert "not unique" in (result.error or "")
    assert f.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_str_replace_missing_errors(tool: StrReplaceEditor, workspace: Path) -> None:
    """str_replace with a missing old_str errors and leaves the file untouched."""
    f = workspace / "code.py"
    original = "hello world"
    f.write_text(original)
    result = await tool(command="str_replace", path=str(f), old_str="absent", new_str="present")
    assert result.is_error is True
    assert "not found" in (result.error or "")
    assert f.read_text(encoding="utf-8") == original


# --- insert command ---------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_at_line_zero(tool: StrReplaceEditor, workspace: Path) -> None:
    """insert with insert_line=0 prepends a new top line."""
    f = workspace / "code.py"
    f.write_text("first\nsecond\n")
    result = await tool(command="insert", path=str(f), insert_line=0, new_str="zeroth")
    assert result.is_error is False
    assert "Inserted line at 1" in result.output
    assert f.read_text(encoding="utf-8") == "zeroth\nfirst\nsecond\n"


@pytest.mark.asyncio
async def test_insert_in_middle(tool: StrReplaceEditor, workspace: Path) -> None:
    """insert with insert_line=N inserts AFTER line N (1-indexed)."""
    f = workspace / "code.py"
    f.write_text("first\nthird\n")
    result = await tool(command="insert", path=str(f), insert_line=1, new_str="second")
    assert result.is_error is False
    assert "Inserted line at 2" in result.output
    assert f.read_text(encoding="utf-8") == "first\nsecond\nthird\n"


@pytest.mark.asyncio
async def test_insert_out_of_range_errors(tool: StrReplaceEditor, workspace: Path) -> None:
    """insert with insert_line beyond the file length returns is_error."""
    f = workspace / "code.py"
    f.write_text("a\nb\n")
    result = await tool(command="insert", path=str(f), insert_line=10, new_str="x")
    assert result.is_error is True
    assert "out of range" in (result.error or "")
    assert f.read_text(encoding="utf-8") == "a\nb\n"


# --- undo_edit command ------------------------------------------------------


@pytest.mark.asyncio
async def test_undo_edit_reverts_str_replace(tool: StrReplaceEditor, workspace: Path) -> None:
    """undo_edit reverts the file to the state before the most recent str_replace."""
    f = workspace / "code.py"
    f.write_text("alpha\nbeta\n")
    r1 = await tool(command="str_replace", path=str(f), old_str="alpha", new_str="ALPHA")
    assert r1.is_error is False
    assert f.read_text(encoding="utf-8") == "ALPHA\nbeta\n"
    r2 = await tool(command="undo_edit", path=str(f))
    assert r2.is_error is False
    assert "Reverted" in r2.output
    assert f.read_text(encoding="utf-8") == "alpha\nbeta\n"


@pytest.mark.asyncio
async def test_undo_edit_reverts_insert(tool: StrReplaceEditor, workspace: Path) -> None:
    """undo_edit reverts the file to the state before the most recent insert."""
    f = workspace / "code.py"
    f.write_text("a\nb\nc\n")
    r1 = await tool(command="insert", path=str(f), insert_line=1, new_str="X")
    assert r1.is_error is False
    assert f.read_text(encoding="utf-8") == "a\nX\nb\nc\n"
    r2 = await tool(command="undo_edit", path=str(f))
    assert r2.is_error is False
    assert f.read_text(encoding="utf-8") == "a\nb\nc\n"


@pytest.mark.asyncio
async def test_undo_edit_reverts_create(tool: StrReplaceEditor, workspace: Path) -> None:
    """undo_edit removes a file that was created via create."""
    f = workspace / "new.txt"
    r1 = await tool(command="create", path=str(f), file_text="hello")
    assert r1.is_error is False
    assert f.exists()
    r2 = await tool(command="undo_edit", path=str(f))
    assert r2.is_error is False
    assert not f.exists()


@pytest.mark.asyncio
async def test_undo_edit_empty_stack_errors(tool: StrReplaceEditor, workspace: Path) -> None:
    """undo_edit with no history for the path returns is_error."""
    f = workspace / "code.py"
    f.write_text("untouched")
    result = await tool(command="undo_edit", path=str(f))
    assert result.is_error is True
    assert "No edits to undo" in (result.error or "")
    assert f.read_text(encoding="utf-8") == "untouched"


# --- path confinement -------------------------------------------------------


@pytest.mark.asyncio
async def test_path_outside_workspace_denied(tool: StrReplaceEditor, workspace: Path) -> None:
    """A path that resolves outside the workspace is denied by default."""
    result = await tool(command="view", path="/etc/passwd")
    assert result.is_error is True
    assert "outside the workspace" in (result.error or "")


@pytest.mark.asyncio
async def test_allow_outside_workspace_bypasses_check(
    tool: StrReplaceEditor,
    workspace: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """allow_outside_workspace=true lets the tool read files outside the workspace."""
    other_dir = tmp_path_factory.mktemp("outside_workspace")
    outside_file = other_dir / "outside.txt"
    outside_file.write_text("outside content\n", encoding="utf-8")
    result = await tool(command="view", path=str(outside_file), allow_outside_workspace=True)
    assert result.is_error is False
    assert "outside content" in result.output


@pytest.mark.asyncio
async def test_symlink_escape_denied(
    tool: StrReplaceEditor,
    workspace: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A symlink inside the workspace that points outside is denied."""
    other_dir = tmp_path_factory.mktemp("symlink_target")
    target = other_dir / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = workspace / "escape"
    link.symlink_to(target)
    result = await tool(command="view", path=str(link))
    assert result.is_error is True
    assert "outside the workspace" in (result.error or "")


@pytest.mark.asyncio
async def test_create_outside_workspace_denied(tool: StrReplaceEditor, workspace: Path) -> None:
    """create outside the workspace is also denied."""
    result = await tool(command="create", path="/tmp/forbidden_new.txt", file_text="nope")
    assert result.is_error is True
    assert "outside the workspace" in (result.error or "")


# --- metadata / spec --------------------------------------------------------


def test_metadata() -> None:
    """Static metadata (name, timeout, schema enums) is as specified."""
    tool = StrReplaceEditor()
    assert tool.name == "str_replace_editor"
    assert tool.timeout_s == 30
    required = tool.args_schema["required"]
    assert "command" in required
    assert "path" in required
    enums = tool.args_schema["properties"]["command"]["enum"]
    assert set(enums) == {"view", "create", "str_replace", "insert", "undo_edit"}


def test_openai_spec() -> None:
    """OpenAI function-calling spec includes the editor with all commands."""
    tool = StrReplaceEditor()
    spec = tool.to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "str_replace_editor"
    props = spec["function"]["parameters"]["properties"]
    assert "command" in props
    assert "path" in props
    assert "old_str" in props
    assert "view_range" in props


def test_anthropic_spec() -> None:
    """Anthropic tool-use spec mirrors the JSON schema."""
    tool = StrReplaceEditor()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "str_replace_editor"
    props = spec["input_schema"]["properties"]
    assert "command" in props
    assert "allow_outside_workspace" in props


@pytest.mark.asyncio
async def test_call_count_increments(tool: StrReplaceEditor, workspace: Path) -> None:
    """The base class call counter ticks on every invocation."""
    f = workspace / "x.txt"
    f.write_text("hi")
    await tool(command="view", path=str(f))
    await tool(command="view", path=str(f))
    assert tool.call_count == 2
