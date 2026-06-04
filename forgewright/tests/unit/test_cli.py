"""Tests for the CLI entry points."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
