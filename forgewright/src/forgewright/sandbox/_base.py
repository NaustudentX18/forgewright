"""Shared types for the sandbox package.

The :class:`Sandbox` Protocol, plus the :class:`SandboxResult` and
:class:`SandboxStatus` value types, live here in their own module so
the concrete backends can import them without triggering a circular
import through ``forgewright.sandbox.__init__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

__all__ = ["Sandbox", "SandboxResult", "SandboxStatus"]


@dataclass(frozen=True)
class SandboxResult:
    """The outcome of a single ``Sandbox.run`` call."""

    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    timed_out: bool = False


@dataclass(frozen=True)
class SandboxStatus:
    """A health probe for a single backend, returned by ``Sandbox.doctor``."""

    name: str
    available: bool
    reason: str  # human-readable; "ok" or "docker SDK not installed" etc.
    details: dict[str, Any]


@runtime_checkable
class Sandbox(Protocol):
    """The contract every code-execution backend must satisfy.

    Backends in v0.1: :class:`SubprocessSandbox`, :class:`DockerSandbox`.
    GVisor and Firecracker land in v0.2.
    """

    name: ClassVar[str]

    async def run(
        self,
        cmd: str,
        *,
        timeout_s: int = 30,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult: ...

    async def write(self, path: str | Path, content: str | bytes) -> None: ...

    async def read(self, path: str | Path) -> str: ...

    async def cleanup(self) -> None: ...

    def doctor(self) -> SandboxStatus: ...
