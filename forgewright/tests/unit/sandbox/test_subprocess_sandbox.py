"""Tests for :class:`forgewright.sandbox.subprocess_sandbox.SubprocessSandbox`."""

from __future__ import annotations

from forgewright.sandbox import Sandbox, SandboxResult, SubprocessSandbox
from forgewright.sandbox.subprocess_sandbox import SubprocessSandbox as DirectClass


def test_subprocess_satisfies_protocol() -> None:
    """The class is structurally a ``Sandbox``."""
    assert isinstance(SubprocessSandbox(), Sandbox)


def test_subprocess_doctor_is_ok() -> None:
    """``doctor()`` reports the backend as available with no reason."""
    s = SubprocessSandbox()
    status = s.doctor()
    assert status.name == "subprocess"
    assert status.available is True
    assert status.reason == "ok"


def test_subprocess_doctor_reports_its_own_name() -> None:
    """The doctor's name matches the class attribute."""
    s = SubprocessSandbox()
    assert s.doctor().name == s.name


async def test_run_echo_returns_stdout() -> None:
    """``echo hello`` writes ``hello\\n`` to stdout and exits 0."""
    s = SubprocessSandbox()
    result = await s.run("echo hello")
    assert isinstance(result, SandboxResult)
    assert result.stdout == "hello\n"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stderr == ""


async def test_run_nonzero_exit_code_is_propagated() -> None:
    """``exit 1`` is reported as ``exit_code=1`` without timing out."""
    s = SubprocessSandbox()
    result = await s.run("exit 1")
    assert result.exit_code == 1
    assert result.timed_out is False


async def test_run_sleep_timeout_is_reported() -> None:
    """A slow command with a tiny timeout is reported as ``timed_out=True``."""
    s = SubprocessSandbox()
    result = await s.run("sleep 5", timeout_s=1)
    assert result.timed_out is True
    assert result.exit_code == -1


async def test_write_then_read_roundtrips(tmp_path) -> None:
    """``write`` then ``read`` round-trips text content."""
    s = SubprocessSandbox()
    p = tmp_path / "sub" / "hello.txt"
    await s.write(p, "howdy partner\n")
    assert await s.read(p) == "howdy partner\n"


async def test_write_bytes_then_read_roundtrips(tmp_path) -> None:
    """``write`` accepts bytes; the text form is decoded with ``errors=replace``."""
    s = SubprocessSandbox()
    p = tmp_path / "blob.txt"
    # Use UTF-8-valid bytes for the round-trip.
    await s.write(p, b"bytes line\n")
    assert await s.read(p) == "bytes line\n"


async def test_cleanup_is_noop() -> None:
    """``cleanup()`` is a no-op and returns ``None``."""
    s = SubprocessSandbox()
    assert await s.cleanup() is None


async def test_cwd_is_honored(tmp_path) -> None:
    """Commands run with ``cwd`` see that directory as their working dir."""
    s = SubprocessSandbox()
    result = await s.run("pwd", cwd=str(tmp_path))
    assert result.stdout.strip() == str(tmp_path)


async def test_env_is_passed_through(tmp_path) -> None:
    """Custom env vars are visible to the child process."""
    s = SubprocessSandbox()
    result = await s.run("printenv FW_TEST_VAR", env={"FW_TEST_VAR": "ping"})
    assert result.stdout.strip() == "ping"


async def test_run_class_is_exposed_from_package() -> None:
    """``from forgewright.sandbox import SubprocessSandbox`` works."""
    assert DirectClass is SubprocessSandbox
