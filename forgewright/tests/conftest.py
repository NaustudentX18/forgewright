"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest


@pytest.fixture
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Provide a fresh event loop for each test (avoids cross-test pollution)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
