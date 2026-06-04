"""Tests for the CLI entry points."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_python_dash_m_works(tmp_path: Path) -> None:
    """`python -m forgewright --version` prints the version."""
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    result = subprocess.run(
        [sys.executable, "-m", "forgewright", "--version"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=20,
    )
    assert result.returncode == 0
    assert "forgewright" in result.stdout
    assert "0.2.0" in result.stdout


def test_help_prints(tmp_path: Path) -> None:
    """`python -m forgewright --help` prints usage."""
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    result = subprocess.run(
        [sys.executable, "-m", "forgewright", "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=20,
    )
    assert result.returncode == 0
    assert "forgewright" in result.stdout.lower()
    assert "build" in result.stdout


def test_build_command_runs_with_stub(tmp_path: Path) -> None:
    """`python -m forgewright build "hello"` should succeed using the stub."""
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    env["HOME"] = str(tmp_path)  # isolate config dir
    result = subprocess.run(
        [sys.executable, "-m", "forgewright", "build", "hello"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Hello" in result.stdout or "TASK_COMPLETE" in result.stdout


def test_build_command_persists_cap_final_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cap-reached build writes both session metadata and the audit final state."""
    from forgewright.cli.main import build_command
    from forgewright.config import LLMConfig, Settings
    from forgewright.llm.base import LLMBackend
    from forgewright.schema import AssistantTurn
    from forgewright.session import Session

    class CappedBackend(LLMBackend):
        def __init__(self, config: LLMConfig) -> None:
            super().__init__(config)

        async def ask_tool(self, messages, tools, **kw):  # type: ignore[no-untyped-def, override]
            self._usage.output_tokens += 1000
            return AssistantTurn(content="still working", tool_calls=[])

        def supports_tool_calling(self) -> bool:
            return True

    settings = Settings(
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        security={"audit_log": str(tmp_path / "audit.jsonl")},  # type: ignore[arg-type]
    )
    monkeypatch.setattr("forgewright.cli.main.get_settings", lambda: settings)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "forgewright.cli.main.LLMBackend.from_config",
        lambda cfg: CappedBackend(cfg),
    )

    with pytest.raises(SystemExit) as exc_info:
        build_command("hello", max_cost=0.001, max_steps=5)

    assert exc_info.value.code == 2
    sessions = list((tmp_path / ".local/share/forgewright/sessions").glob("*.json"))
    assert sessions
    loaded = Session.load(sessions[0])
    assert loaded.metadata["final_state"] == "cost_limit_reached"
    assert "cost_limit_reached" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
