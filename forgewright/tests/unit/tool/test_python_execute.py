"""Tests for the PythonExecuteTool (subprocess mode)."""

from __future__ import annotations

import sys

import pytest
from forgewright.tool.python_execute import PythonExecuteTool


@pytest.mark.asyncio
async def test_simple_print() -> None:
    """A trivial `print('hi')` runs and the output contains 'hi'."""
    tool = PythonExecuteTool()
    result = await tool(code='print("hi")')
    assert result.is_error is False
    assert "hi" in (result.output or "")


@pytest.mark.asyncio
async def test_stderr_is_captured() -> None:
    """Anything written to sys.stderr is included in the output."""
    tool = PythonExecuteTool()
    result = await tool(code='import sys; sys.stderr.write("oops\\n")')
    assert result.is_error is False
    assert "oops" in (result.output or "")
    assert "stderr" in (result.output or "").lower()


@pytest.mark.asyncio
async def test_nonzero_exit_returns_error() -> None:
    """A non-zero exit code flips `is_error` to True and surfaces the code."""
    tool = PythonExecuteTool()
    result = await tool(code="import sys; sys.exit(2)")
    assert result.is_error is True
    assert "2" in (result.output or "")


@pytest.mark.asyncio
async def test_timeout_kills_subprocess() -> None:
    """A long-running snippet returns is_error when timeout_s elapses."""
    tool = PythonExecuteTool()
    result = await tool(code="import time; time.sleep(10)", timeout_s=1)
    assert result.is_error is True
    err = (result.error or "").lower()
    assert "timeout" in err


@pytest.mark.asyncio
async def test_multiline_code() -> None:
    """A multi-line snippet runs as a single -c invocation."""
    code = "a = 1\nb = 2\nprint(a + b)\n"
    tool = PythonExecuteTool()
    result = await tool(code=code)
    assert result.is_error is False
    assert "3" in (result.output or "")


@pytest.mark.asyncio
async def test_cwd_is_respected(tmp_path: object) -> None:
    """The `cwd` argument changes the subprocess's working directory."""
    target = str(tmp_path)
    tool = PythonExecuteTool()
    result = await tool(
        code="import os; print(os.path.realpath(os.getcwd()))",
        cwd=target,
    )
    assert result.is_error is False
    assert target in (result.output or "")


def test_default_mode_is_subprocess() -> None:
    """The schema's default for `mode` must be 'subprocess'."""
    tool = PythonExecuteTool()
    assert tool.args_schema["properties"]["mode"]["default"] == "subprocess"
    assert "subprocess" in tool.args_schema["properties"]["mode"]["enum"]


def test_metadata() -> None:
    """Static metadata matches the spec."""
    tool = PythonExecuteTool()
    assert tool.name == "python_execute"
    assert tool.timeout_s == 30
    assert "code" in tool.args_schema["required"]
    assert tool.args_schema["properties"]["timeout_s"]["default"] == 5
    assert tool.args_schema["properties"]["timeout_s"]["maximum"] == 300
    assert tool.args_schema["properties"]["timeout_s"]["minimum"] == 1


def test_openai_spec() -> None:
    """Renders a valid OpenAI function-calling spec."""
    tool = PythonExecuteTool()
    spec = tool.to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "python_execute"
    assert "code" in spec["function"]["parameters"]["properties"]


def test_anthropic_spec() -> None:
    """Renders a valid Anthropic tool-use spec."""
    tool = PythonExecuteTool()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "python_execute"
    assert "code" in spec["input_schema"]["properties"]


@pytest.mark.asyncio
async def test_docker_mode_without_docker_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the docker SDK is not importable, the tool returns a clear hint."""
    # Force the lazy `import docker` to fail, regardless of whether the
    # package is actually present in the dev environment.
    monkeypatch.setitem(sys.modules, "docker", None)
    monkeypatch.delitem(sys.modules, "docker.errors", raising=False)
    # Clear any cached import of the docker_mod symbol inside the module.
    monkeypatch.delitem(sys.modules, "forgewright.tool.python_execute", raising=False)

    # Re-import so the module is loaded fresh AFTER sys.modules is poisoned.
    import importlib

    import forgewright.tool.python_execute as mod

    importlib.reload(mod)

    tool = mod.PythonExecuteTool()
    result = await tool(code='print("hi")', mode="docker")
    assert result.is_error is True
    err = result.error or ""
    assert "[sandbox]" in err
    assert "forgewright[sandbox]" in err
    assert "docker" in err.lower()
