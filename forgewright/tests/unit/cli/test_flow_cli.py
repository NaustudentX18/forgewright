"""Tests for the `forgewright flow` CLI dispatcher."""

from __future__ import annotations

import os

from forgewright.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


def test_flow_help_shows_options() -> None:
    """`forgewright flow --help` shows the available options."""
    result = runner.invoke(app, ["flow", "--help"])
    # Typer returns 0 on a clean --help render.
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "--agents" in out
    assert "--max-steps" in out
    assert "--timeout" in out


def test_flow_runs_with_stub_provider(monkeypatch: object) -> None:
    """`forgewright flow "do thing"` exits 0 under the stub provider."""
    monkeypatch.setattr(  # type: ignore[attr-defined]
        os.environ,
        "FORGEWRIGHT_LLM__PROVIDER",
        "stub",
        raising=False,
    )
    # CliRunner.invoke doesn't always thread env, so we use a runner
    # that does, and just assert the exit code.
    result = runner.invoke(
        app,
        ["flow", "do thing", "--max-steps", "2", "--timeout", "30"],
        env={"FORGEWRIGHT_LLM__PROVIDER": "stub"},
    )
    # The stub always returns TASK_COMPLETE, so the flow finishes 0.
    assert result.exit_code == 0, (result.stdout, getattr(result, "stderr", ""))
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    # The plan table is rendered.
    assert "step" in out.lower() or "s1" in out or "manus" in out.lower()


def test_flow_rejects_unknown_agent() -> None:
    """`--agents` with an unknown name exits 2 (Typer BadParameter)."""
    result = runner.invoke(
        app,
        ["flow", "do thing", "--agents", "nope_agent", "--max-steps", "2"],
        env={"FORGEWRIGHT_LLM__PROVIDER": "stub"},
    )
    # Typer converts BadParameter into exit 2.
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "nope_agent" in out or "Unknown agent" in out or "Valid" in out
