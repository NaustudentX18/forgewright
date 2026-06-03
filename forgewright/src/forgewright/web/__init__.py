"""Web chat interface for forgewright (FastAPI + SSE).

This subpackage adds an optional browser UI to the existing CLI. The
``[web]`` extra installs FastAPI and uvicorn; the core package does
not depend on either. Importing :mod:`forgewright.web.server` requires
those packages to be installed.
"""

from __future__ import annotations

__all__ = ["__version__"]
