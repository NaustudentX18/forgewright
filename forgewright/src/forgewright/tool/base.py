"""BaseTool — the abstract base class every tool extends."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from forgewright.logger import logger
from forgewright.schema import ToolResult

__all__ = ["BaseTool"]


class BaseTool(ABC):
    """The abstract base of every tool the agent can invoke.

    Subclasses must set `name`, `description`, and `args_schema`, then
    implement `_run()`. The public `__call__()` adds schema validation,
    timeout, and error wrapping.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    args_schema: ClassVar[dict[str, Any]]
    requires: ClassVar[list[str]] = []
    returns_image: ClassVar[bool] = False
    timeout_s: ClassVar[int] = 30

    def __init__(self) -> None:
        """Initialize the per-instance call counter and JSON-schema validator."""
        self._call_count: int = 0
        self._validator: Draft7Validator | None = None
        if hasattr(self, "args_schema"):
            try:
                self._validator = Draft7Validator(self.args_schema)
            except SchemaError as exc:
                logger.error(
                    "tool.invalid_schema name={} err={}",
                    getattr(self, "name", type(self).__name__),
                    exc,
                )
                raise

    @abstractmethod
    async def _run(self, **kwargs: Any) -> ToolResult:
        """Run the tool. Subclasses implement this."""
        raise NotImplementedError

    async def __call__(self, **kwargs: Any) -> ToolResult:
        """Validate args, enforce timeout, run, wrap exceptions in ToolResult."""
        if self._validator is not None:
            try:
                self._validator.validate(kwargs)
            except JsonSchemaValidationError as exc:
                logger.warning(
                    "tool.invalid_args name={} path={} msg={}",
                    self.name,
                    list(exc.absolute_path),
                    exc.message,
                )
                return ToolResult(
                    is_error=True,
                    error=f"Invalid args for tool '{self.name}': {exc.message}",
                )

        self._call_count += 1
        try:
            return await asyncio.wait_for(self._run(**kwargs), timeout=self.timeout_s)
        except TimeoutError:
            logger.warning("tool.timeout name={} timeout_s={}", self.name, self.timeout_s)
            return ToolResult(
                is_error=True,
                error=f"Tool '{self.name}' timed out after {self.timeout_s}s",
            )
        except Exception as exc:  # broad: tools must never crash the agent loop
            logger.exception("tool.error name={}", self.name)
            return ToolResult(is_error=True, error=f"{type(exc).__name__}: {exc}")

    def to_openai_tool(self) -> dict[str, Any]:
        """Render the tool as an OpenAI function-calling spec."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema,
            },
        }

    def as_fastmcp_tool(self) -> Callable[..., Awaitable[ToolResult]]:
        """Return a FastMCP-compatible async function wrapping this tool's ``__call__``.

        Phase 8: ``forgewright.mcp.server`` uses this to register local
        tools with the FastMCP server. FastMCP 3 rejects ``**kwargs``,
        so we build an explicit-arg function from the tool's
        ``args_schema``. Each declared property becomes a named
        keyword-only parameter. We materialize the function via
        ``exec`` so the resulting function object has a real
        ``__annotations__`` dict — Pydantic / FastMCP reads it via
        ``inspect.get_annotations``, which doesn't honor a synthetic
        ``__signature__``.
        """
        properties: dict[str, Any] = (self.args_schema or {}).get("properties", {}) or {}
        required: list[str] = list((self.args_schema or {}).get("required", []) or [])
        param_order = [name for name in properties]
        for name in required:
            if name not in param_order:
                param_order.append(name)

        # Build the source code for a function with one explicit kwarg
        # per schema property. Type annotations are included so the
        # generated function has a proper __annotations__ dict.
        type_map = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
        }
        arg_lines: list[str] = []
        for name in param_order:
            raw_type = properties.get(name, {}).get("type")
            # JSON Schema allows ``"type": ["string", "null"]``. Pick
            # the first non-null entry; default to "string".
            if isinstance(raw_type, list):
                picked = next((t for t in raw_type if t != "null"), raw_type[0])
            else:
                picked = raw_type
            ann = type_map.get(picked or "", "Any")
            if name in required:
                arg_lines.append(f"    {name}: {ann},")
            else:
                arg_lines.append(f"    {name}: {ann} = None,")

        # The body unpacks the keyword arguments into a dict and
        # delegates to ``self.__call__``. We capture ``self`` and
        # ``required`` in the closure via default-argument trickery.
        src = (
            "async def _adapter(\n"
            + "\n".join(arg_lines)
            + "\n):\n"
            + "    call_kwargs = {k: v for k, v in locals().items() if v is not None}\n"
            + "    for k in list(call_kwargs):\n"
            + "        if k not in _required_set and call_kwargs[k] is None:\n"
            + "            call_kwargs.pop(k)\n"
            + "    return await _self(**call_kwargs)\n"
        )

        namespace: dict[str, Any] = {
            "_self": self,
            "_required_set": set(required),
        }
        exec(src, namespace)  # building a typed adapter from a schema
        adapter: Callable[..., Awaitable[ToolResult]] = namespace["_adapter"]
        adapter.__name__ = self.name
        adapter.__qualname__ = f"fastmcp_{self.name}"
        adapter.__doc__ = self.description
        return adapter

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Render the tool as an Anthropic tool-use spec."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_schema,
        }

    @property
    def call_count(self) -> int:
        """Number of times this tool has been invoked."""
        return self._call_count
