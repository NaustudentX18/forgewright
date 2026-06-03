"""Sandbox Protocol + concrete backends for code execution.

Every code-execution surface (PythonExecute tool, MCP-wrapped tools, the
REPL) runs through a `Sandbox` so the security profile is consistent.

This package ships:

* `Sandbox` — a :class:`typing.Protocol` every backend implements.
* `SandboxResult` / `SandboxStatus` — value types returned by the backends.
* `SubprocessSandbox` — no isolation, fastest path; for trusted code only.
* `DockerSandbox` — hard-sandboxed via the Docker SDK; the recommended
  default for untrusted code.

The Protocol is ``runtime_checkable`` so ``isinstance(obj, Sandbox)`` is
valid in user code and tests.
"""

from __future__ import annotations

from forgewright.sandbox._base import Sandbox, SandboxResult, SandboxStatus
from forgewright.sandbox.docker_sandbox import DockerSandbox
from forgewright.sandbox.subprocess_sandbox import SubprocessSandbox

__all__ = [
    "DockerSandbox",
    "Sandbox",
    "SandboxResult",
    "SandboxStatus",
    "SubprocessSandbox",
]
