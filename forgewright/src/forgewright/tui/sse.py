"""SSE parsing and streaming for the web chat API (httpx).

Mirrors the browser consumer in ``web/static/app.js``: POST to
``/api/sessions/{id}/messages``, read ``text/event-stream``, split on
blank lines, parse ``event:`` / ``data:`` pairs.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

__all__ = ["parse_sse_chunk", "stream_message_sse"]


def parse_sse_chunk(chunk: str) -> tuple[str, dict[str, Any]] | None:
    """Parse one SSE message block (lines separated by ``\\n``, block by ``\\n\\n``)."""
    event: str | None = None
    data_line: str | None = None
    for line in chunk.split("\n"):
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            data_line = line[6:]
    if not event or data_line is None:
        return None
    return event, json.loads(data_line)


async def stream_message_sse(
    client: httpx.AsyncClient,
    base_url: str,
    session_id: str,
    content: str,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """POST a user message and yield ``(event_name, payload)`` from the SSE body."""
    url = f"{base_url.rstrip('/')}/api/sessions/{session_id}/messages"
    buffer = ""
    async with client.stream(
        "POST",
        url,
        json={"content": content},
        headers={"Accept": "text/event-stream"},
    ) as response:
        response.raise_for_status()
        async for piece in response.aiter_text():
            buffer += piece
            parts = buffer.split("\n\n")
            buffer = parts.pop()
            for part in parts:
                if not part.strip():
                    continue
                parsed = parse_sse_chunk(part)
                if parsed is not None:
                    yield parsed
