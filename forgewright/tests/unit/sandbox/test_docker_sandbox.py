"""Tests for :class:`forgewright.sandbox.docker_sandbox.DockerSandbox`.

All tests mock the docker SDK so no real daemon or container is required.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from unittest.mock import MagicMock, patch

import pytest
from forgewright.sandbox import DockerSandbox, Sandbox, SandboxResult
from forgewright.sandbox.docker_sandbox import DockerSandbox as DirectClass


def _install_docker_mock(
    monkeypatch: pytest.MonkeyPatch, *, ping_raises: bool = False
) -> MagicMock:
    """Install a fake ``docker`` module that supports ``docker.from_env()``."""
    fake_client = MagicMock(name="docker.DockerClient")
    if ping_raises:
        fake_client.ping.side_effect = ConnectionError("daemon down")
    else:
        fake_client.ping.return_value = True

    fake_module = MagicMock(name="docker")
    fake_module.from_env.return_value = fake_client

    # ``import docker`` happens inside ``_ensure_client``; make it succeed.
    sys.modules["docker"] = fake_module
    monkeypatch.setattr("forgewright.sandbox.docker_sandbox.docker", fake_module, raising=False)
    return fake_client


def test_docker_satisfies_protocol() -> None:
    """The class is structurally a ``Sandbox``."""
    assert isinstance(DockerSandbox(), Sandbox)


def test_docker_class_exposed_from_package() -> None:
    """``from forgewright.sandbox import DockerSandbox`` works."""
    assert DirectClass is DockerSandbox


def test_constructor_stores_security_limits() -> None:
    """All security limits are stored on the instance."""
    s = DockerSandbox(
        image="alpine:3.19",
        mem_limit="256m",
        pids_limit=64,
        network_mode="bridge",
        read_only=False,
        cap_drop=["NET_RAW"],
        user="1000:1000",
        working_dir="/sandbox",
    )
    assert s.image == "alpine:3.19"
    assert s.mem_limit == "256m"
    assert s.pids_limit == 64
    assert s.network_mode == "bridge"
    assert s.read_only is False
    assert s.cap_drop == ["NET_RAW"]
    assert s.user == "1000:1000"
    assert s.working_dir == "/sandbox"


def test_default_cap_drop_is_all() -> None:
    """``cap_drop`` defaults to ``["ALL"]`` (drop every capability)."""
    s = DockerSandbox()
    assert s.cap_drop == ["ALL"]


def test_doctor_returns_unavailable_when_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no docker SDK installed, ``doctor`` reports it as unavailable."""
    # Force ImportError for the docker module.
    monkeypatch.setitem(sys.modules, "docker", None)  # type: ignore[arg-type]

    s = DockerSandbox()
    # Also make sure a previous test didn't leave a cached client.
    s._client = None
    # Re-import the module so the patched ``docker`` takes effect.
    status = s.doctor()
    assert status.name == "docker"
    assert status.available is False
    assert "docker SDK not installed" in status.reason
    # The error message also surfaces the install hint.
    assert "[sandbox]" in status.reason or "uv pip install" in status.reason


def test_doctor_returns_unavailable_when_daemon_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stopped daemon → ``ping()`` raises → doctor reports unavailable."""
    s = DockerSandbox()
    s._client = None
    _install_docker_mock(monkeypatch, ping_raises=True)
    status = s.doctor()
    assert status.available is False
    assert "daemon down" in status.reason


def test_doctor_returns_available_with_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """With SDK + healthy daemon, doctor reports available with config details."""
    s = DockerSandbox()
    s._client = None
    _install_docker_mock(monkeypatch, ping_raises=False)
    status = s.doctor()
    assert status.available is True
    assert status.reason == "ok"
    assert status.details["image"] == "python:3.12-slim"
    assert status.details["mem_limit"] == "512m"
    assert status.details["pids_limit"] == 256
    assert status.details["network_mode"] == "none"
    assert status.details["read_only"] is True


async def test_run_raises_runtimeerror_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``run()`` returns a ``SandboxResult`` with the install hint when SDK is absent."""
    monkeypatch.setitem(sys.modules, "docker", None)  # type: ignore[arg-type]
    s = DockerSandbox()
    s._client = None
    result = await s.run("echo hi")
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 1
    assert "docker SDK not installed" in result.stderr
    assert "uv pip install" in result.stderr


async def test_run_returns_sandbox_result_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mocked ``containers.run`` yields the right ``SandboxResult``."""
    fake_client = _install_docker_mock(monkeypatch, ping_raises=False)
    fake_client.containers.run.return_value = b"hello from container\n"

    s = DockerSandbox()
    s._client = None
    result = await s.run("echo hi")

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout == "hello from container\n"

    # The container run was invoked with our hard-limits.
    fake_client.containers.run.assert_called_once()
    call = fake_client.containers.run.call_args
    assert call.args[0] == "python:3.12-slim"
    assert call.kwargs["mem_limit"] == "512m"
    assert call.kwargs["pids_limit"] == 256
    assert call.kwargs["network_mode"] == "none"
    assert call.kwargs["read_only"] is True
    assert call.kwargs["cap_drop"] == ["ALL"]
    assert call.kwargs["user"] == "nobody"
    assert call.kwargs["remove"] is True
    assert call.kwargs["stdout"] is True
    assert call.kwargs["stderr"] is True


async def test_run_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the container takes too long, ``run`` reports ``timed_out=True``."""
    _install_docker_mock(monkeypatch, ping_raises=False)

    async def _blocker(awaitable, timeout=None):  # type: ignore[no-untyped-def]
        # Await the inner coroutine (to_thread) so it doesn't leak, then
        # raise TimeoutError to mimic the production timeout path.
        if asyncio.iscoroutine(awaitable):
            with contextlib.suppress(Exception):
                await awaitable
        raise TimeoutError

    s = DockerSandbox()
    s._client = None
    with patch("asyncio.wait_for", _blocker):
        result = await s.run("sleep 999", timeout_s=1)
    assert result.timed_out is True
    assert result.exit_code == -1


async def test_run_wraps_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception inside the container call is captured into ``stderr``."""
    fake_client = _install_docker_mock(monkeypatch, ping_raises=False)
    fake_client.containers.run.side_effect = RuntimeError("boom")
    s = DockerSandbox()
    s._client = None
    result = await s.run("true")
    assert result.exit_code == 1
    assert "boom" in result.stderr
    assert result.timed_out is False


async def test_cleanup_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cleanup()`` is a no-op (we use ``remove=True`` so nothing accumulates)."""
    _install_docker_mock(monkeypatch, ping_raises=False)
    s = DockerSandbox()
    assert await s.cleanup() is None
