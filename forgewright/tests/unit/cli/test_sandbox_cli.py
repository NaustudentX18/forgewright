"""Tests for the `forgewright sandbox ...` CLI dispatcher.

Uses :class:`typer.testing.CliRunner` to invoke the root app and assert
on exit codes + table output.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from forgewright.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


# ---------- help / discovery ----------


def test_sandbox_help_lists_actions() -> None:
    """``forgewright sandbox --help`` shows the ``action`` argument."""
    result = runner.invoke(app, ["sandbox", "--help"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "doctor" in out
    assert "set" in out


def test_sandbox_doctor_prints_table_with_both_backends() -> None:
    """``forgewright sandbox doctor`` prints a table with subprocess + docker rows."""
    result = runner.invoke(app, ["sandbox", "doctor"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "subprocess" in out
    assert "docker" in out
    # The subprocess backend is always available.
    assert "ok" in out


def test_sandbox_doctor_exits_zero_when_docker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``doctor`` is non-fatal — unavailability is reported, not an error."""
    # Replace the docker backend with a stub whose ``doctor`` always
    # reports unavailable. This sidesteps sys.modules ordering issues
    # and exercises the CLI's "non-fatal" path.
    from forgewright.cli import sandbox as sandbox_cli
    from forgewright.sandbox import SandboxStatus

    class _NoDocker:
        name = "docker"

        def doctor(self) -> SandboxStatus:
            return SandboxStatus(
                name=self.name,
                available=False,
                reason="docker SDK not installed. Install with: uv pip install 'forgewright[sandbox]'",
                details={},
            )

    class _YesSubprocess:
        name = "subprocess"

        def doctor(self) -> SandboxStatus:
            return SandboxStatus(name=self.name, available=True, reason="ok", details={})

    monkeypatch.setattr(sandbox_cli, "_BACKENDS", [_YesSubprocess(), _NoDocker()])

    result = runner.invoke(app, ["sandbox", "doctor"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "docker" in out
    # The reason column will mention the missing SDK.
    assert "not installed" in out
    assert "uv pip install" in out


# ---------- set ----------


def test_sandbox_set_without_backend_exits_2() -> None:
    """``forgewright sandbox set`` with no ``--backend`` exits 2."""
    result = runner.invoke(app, ["sandbox", "set"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "--backend" in out or "backend" in out


def test_sandbox_set_with_unknown_backend_exits_2() -> None:
    """``forgewright sandbox set --backend gvisor`` (unsupported) exits 2."""
    result = runner.invoke(app, ["sandbox", "set", "--backend", "gvisor"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "gvisor" in out


def test_sandbox_set_docker_prints_confirmation() -> None:
    """``forgewright sandbox set --backend docker`` prints the confirmation message."""
    result = runner.invoke(app, ["sandbox", "set", "--backend", "docker"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "docker" in out
    # The message says "Backend set to" or similar.
    assert "set" in out.lower()
    # The hint about persistence is included.
    assert "v0.2" in out or "config.toml" in out


def test_sandbox_set_subprocess_prints_confirmation() -> None:
    """``forgewright sandbox set --backend subprocess`` also works."""
    result = runner.invoke(app, ["sandbox", "set", "--backend", "subprocess"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "subprocess" in out


def test_sandbox_set_short_flag_works() -> None:
    """``-b`` is the documented short alias for ``--backend``."""
    result = runner.invoke(app, ["sandbox", "set", "-b", "subprocess"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "subprocess" in out


def test_sandbox_set_calls_settings_mutation() -> None:
    """``set --backend docker`` mutates the cached Settings sandbox.backend."""
    from forgewright.config import get_settings

    before = get_settings().sandbox.backend
    try:
        with patch("forgewright.cli.sandbox.console.print") as _:
            result = runner.invoke(app, ["sandbox", "set", "--backend", "docker"])
        assert result.exit_code == 0
        assert get_settings().sandbox.backend == "docker"
    finally:
        get_settings().sandbox.backend = before


# ---------- error handling ----------


def test_sandbox_unknown_action_exits_2() -> None:
    """An unknown sub-action returns exit code 2."""
    result = runner.invoke(app, ["sandbox", "frobnicate"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "frobnicate" in out
