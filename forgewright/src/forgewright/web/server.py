"""FastAPI web chat server for forgewright.

**Scope.** This module adds a thin web UI on top of the existing
:class:`forgewright.agent.Manus` agent loop. It does *not* modify the
agent or the tool collection. SSE progress events are emitted by a
small observable wrapper around the agent's
:class:`forgewright.tool.ToolCollection` — see
:class:`_ObservableToolCollection` below.

**SSE event protocol.** Five event types are emitted (one per SSE
``event:`` line, JSON-encoded ``data:`` payload):

* ``thinking``  — the LLM is being asked. Emitted once at the start of
  each run.
* ``tool_call`` — the agent decided to call a tool; emitted just before
  dispatch.
* ``tool_result`` — the tool returned; emitted just after dispatch.
* ``final`` — the agent finished; ``data.content`` is the full last
  assistant message (also persisted on the session).
* ``error`` — something went wrong; ``data.message`` is human-readable.

**Cancellation.** A client disconnect causes FastAPI to cancel the
generator. The persistence step runs unconditionally in a
``finally`` block so the session is never left half-written, then the
:class:`asyncio.CancelledError` is re-raised.

**Chosen approach.** Observable wrapper around
``agent.tools``. We temporarily replace ``Manus.tools`` (a
:class:`forgewright.tool.ToolCollection`) with an instance of
:class:`_ObservableToolCollection` that proxies every method but
records ``tool_call`` and ``tool_result`` events into a shared
buffer. This is the minimum-scope way to instrument the loop
without touching the agent or its base classes.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from forgewright import __version__
from forgewright.agent import Manus
from forgewright.config import Settings, get_settings
from forgewright.llm import LLMBackend
from forgewright.logger import logger
from forgewright.schema import ChatMessage
from forgewright.security.audit import query_stream
from forgewright.session import Session, default_sessions_dir
from forgewright.tool import ToolCollection

_STATIC_DIR = Path(__file__).parent / "static"

# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class MessageRequest(BaseModel):
    """Body of ``POST /api/sessions/{id}/messages``."""

    model_config = {"extra": "forbid"}

    content: str = Field(min_length=1, description="User message text.")


class SessionSummary(BaseModel):
    """Compact view of a session for the sidebar listing."""

    id: str
    created_at: str
    updated_at: str
    message_count: int
    title: str


# --------------------------------------------------------------------------- #
# ToolCollection event hook
# --------------------------------------------------------------------------- #


class _ObservableToolCollection:
    """Proxy that records ``tool_call``/``tool_result`` events on dispatch.

    Proxies every other attribute to the underlying
    :class:`ToolCollection`, so spec generation (``to_openai_tools``,
    ``to_anthropic_tools``) and tool enumeration keep working.
    """

    def __init__(self, inner: ToolCollection, sink: list[dict[str, Any]]) -> None:
        self._inner = inner
        self._sink = sink

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def call(self, name: str, **kwargs: Any) -> Any:
        self._sink.append({"event": "tool_call", "data": {"tool": name, "args": kwargs}})
        start = time.perf_counter()
        try:
            result = await self._inner.call(name, **kwargs)
        except Exception as exc:  # pragma: no cover — defensive
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._sink.append(
                {
                    "event": "tool_result",
                    "data": {
                        "tool": name,
                        "output": "",
                        "is_error": True,
                        "duration_ms": duration_ms,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                }
            )
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        self._sink.append(
            {
                "event": "tool_result",
                "data": {
                    "tool": name,
                    "output": result.output or "",
                    "is_error": bool(result.is_error),
                    "duration_ms": duration_ms,
                },
            }
        )
        return result


# --------------------------------------------------------------------------- #
# Title helper
# --------------------------------------------------------------------------- #


def _session_title(messages: list[ChatMessage]) -> str:
    """Return a short title for the sidebar — first user message, truncated."""
    for m in messages:
        if m.role == "user" and m.content.strip():
            text = m.content.strip().replace("\n", " ")
            return text[:60] + ("…" if len(text) > 60 else "")
    return "(empty)"


def _tokenize(text: str) -> list[str]:
    """Split ``text`` into streaming chunks for the typewriter effect.

    The chunks preserve the original text exactly when concatenated
    (we keep the separator with the next chunk). Whitespace and
    newlines are emitted as their own chunks so the visible animation
    looks like word-by-word typing.
    """
    if not text:
        return []
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
    return out


def _to_summary(session: Session) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=len(session.messages),
        title=_session_title(session.messages),
    )


# --------------------------------------------------------------------------- #
# SSE streaming
# --------------------------------------------------------------------------- #


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event as a wire-ready string (with trailing blank)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class _StreamBuffers:
    """Per-session buffers used while an agent run is in flight."""

    events: list[dict[str, Any]] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    error: str | None = None
    assistant_text: str = ""


# session_id -> _StreamBuffers
_active_runs: dict[str, _StreamBuffers] = {}


def _register_run(session_id: str) -> _StreamBuffers:
    buf = _StreamBuffers()
    _active_runs[session_id] = buf
    return buf


def _pop_run(session_id: str) -> _StreamBuffers | None:
    return _active_runs.pop(session_id, None)


async def stream_agent_run(
    agent: Manus,
    user_msg: ChatMessage,
    session: Session,
    buf: _StreamBuffers,
) -> None:
    """Run the agent; emit events on ``buf``; append the assistant turn.

    This is the **observable** path: we replace ``agent.tools`` with
    :class:`_ObservableToolCollection` for the duration of the run, so
    every tool dispatch leaves an event in ``buf.events``. After
    :meth:`Manus.run` returns we restore the original tools and
    append the final assistant message to the session.
    """
    # Append the user message in-memory; the session is persisted
    # only after the run finishes so a half-finished turn is never
    # written to disk.
    session.messages.append(user_msg)
    buf.events.append(
        {"event": "thinking", "data": {"step": 0, "max_steps": agent.max_steps}}
    )

    original_tools = agent.tools
    agent.tools = _ObservableToolCollection(original_tools, buf.events)  # type: ignore[assignment]
    try:
        result = await agent.run(user_msg.content, max_steps=agent.max_steps)
    except Exception as exc:
        logger.exception("web.agent_run error")
        buf.error = f"{type(exc).__name__}: {exc}"
        buf.events.append({"event": "error", "data": {"message": buf.error}})
        return
    finally:
        # Always restore the original tools so future invocations
        # behave normally.
        agent.tools = original_tools
        buf.done.set()

    if result.state.value == "error":
        buf.error = result.output or "agent error"
        buf.events.append({"event": "error", "data": {"message": buf.error}})

    final_text = result.output or ""
    if final_text:
        session.messages.append(ChatMessage(role="assistant", content=final_text))
        buf.assistant_text = final_text
    # Stream ``final_text`` to the UI word-by-word so the client can
    # render a typewriter effect (event: token). We chunk on whitespace
    # so multi-byte / punctuation tokens stay intact; the final
    # ``event: final`` carries the full text for any non-streaming
    # consumer (and so the session reload still works correctly).
    for chunk in _tokenize(final_text):
        buf.events.append({"event": "token", "data": {"content": chunk}})
    buf.events.append({"event": "final", "data": {"content": final_text}})


async def _sse_event_stream(
    session_id: str,
    session: Session,
    user_msg: ChatMessage,
    sessions_dir: Path,
    agent: Manus,
) -> AsyncGenerator[str, None]:
    """Yield SSE events for one user message; persist when the run is done."""
    buf = _register_run(session_id)
    runner = asyncio.create_task(stream_agent_run(agent, user_msg, session, buf))
    cursor = 0
    try:
        while not buf.done.is_set() or cursor < len(buf.events):
            while cursor < len(buf.events):
                evt = buf.events[cursor]
                cursor += 1
                yield _sse(evt["event"], evt["data"])
            if buf.done.is_set():
                break
            # Wait briefly for more events; the runner task sets
            # ``done`` once the agent returns.
            try:
                await asyncio.wait_for(buf.done.wait(), timeout=0.1)
            except TimeoutError:
                continue
    except asyncio.CancelledError:
        logger.info("web.sse.cancelled session_id={}", session_id)
        if not runner.done():
            runner.cancel()
        raise
    finally:
        # Persist whatever the agent produced, even on client
        # disconnect. We swallow only the well-known cancellation /
        # I/O-completion errors; anything else is logged with the
        # session id so H2.5 fan-out has structured error events to
        # forward.
        try:
            await runner
        except (asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        except Exception as exc:  # noqa: BLE001 — last-line logging
            logger.warning(
                "web.sse.runner_error session_id={} err={!r}",
                session_id,
                exc,
            )
        try:
            session.save(sessions_dir)
        except OSError as exc:  # pragma: no cover — disk
            logger.warning("web.session.save_failed err={}", exc)
        _pop_run(session_id)


# --------------------------------------------------------------------------- #
# Lifespan
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Make sure the default sessions directory exists on startup."""
    default_sessions_dir().mkdir(parents=True, exist_ok=True)
    yield


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #

#: Hard cap on POST ``/share-in`` bodies. The PWA share target is
#: manifest-advertised to installed PWAs, accepts anonymous HTTP, and
#: would otherwise be a DoS sink for a single oversized upload.
#: 1 MB is enough for the share text + a small screenshot; anything
#: larger should be uploaded via the regular ``POST /api/sessions/.../messages``
#: attachment path (or refused at the client).
_SHARE_IN_MAX_BYTES: int = 1_000_000


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.

    Accepts an optional ``settings`` override so tests can inject a
    stub-backed configuration without mutating the global cache.
    """
    app = FastAPI(
        title="forgewright web",
        version=__version__,
        lifespan=_lifespan,
    )
    app.state.settings_override = settings

    if _STATIC_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="static",
        )

    def _settings() -> Settings:
        if app.state.settings_override is not None:
            return app.state.settings_override  # type: ignore[no-any-return]
        return get_settings()

    def _sessions_dir() -> Path:
        return default_sessions_dir()

    def _session_path(sid: str) -> Path:
        return _sessions_dir() / f"{sid}.json"

    def _load_session(sid: str) -> Session:
        path = _session_path(sid)
        if not path.exists():
            raise HTTPException(status_code=404, detail="session not found")
        try:
            return Session.load(path)
        except (OSError, ValueError) as exc:
            logger.warning("web.session.load_failed sid={} err={}", sid, exc)
            raise HTTPException(
                status_code=400, detail=f"could not load session: {exc}"
            ) from exc

    # ---- routes --------------------------------------------------------- #

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root() -> FileResponse:
        """Serve the single-page chat UI."""
        index = _STATIC_DIR / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="UI not built")
        return FileResponse(str(index))

    def _share_redirect(
        *,
        title: str = "",
        text: str = "",
        url: str = "",
        attachment: str = "",
    ) -> RedirectResponse:
        """Build a composer prefill from a Web Share Target payload."""
        parts = ["[Shared to forgewright — treat as AskHuman context]"]
        if title:
            parts.append(f"Title: {title}")
        if url:
            parts.append(f"URL: {url}")
        if text:
            parts.append(f"Text: {text}")
        if attachment:
            parts.append(attachment)
        shared = quote("\n".join(parts), safe="")
        return RedirectResponse(url=f"/?shared={shared}&new=1", status_code=303)

    @app.get("/share-in", include_in_schema=False)
    async def share_in_get(
        title: str = "",
        text: str = "",
        url: str = "",
    ) -> RedirectResponse:
        """GET share target (link/text) → redirect into the chat composer."""
        return _share_redirect(title=title, text=text, url=url)

    @app.post("/share-in", include_in_schema=False)
    async def share_in_post(request: Request) -> Response:
        """POST share target (optional file) → redirect into the composer.

        The body is size-capped to :data:`_SHARE_IN_MAX_BYTES` to keep an
        anonymous, manifest-advertised endpoint from being abused as a
        DoS sink. The cap is enforced both via the ``Content-Length``
        header (cheap precheck) and via a streaming chunked read (so
        lying or chunked clients are also bounded).
        """
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > _SHARE_IN_MAX_BYTES:
            return PlainTextResponse("payload too large", status_code=413)

        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > _SHARE_IN_MAX_BYTES:
                return PlainTextResponse("payload too large", status_code=413)
            chunks.append(chunk)
        # Cache the bounded body so ``request.form()`` re-parses it
        # rather than re-reading the network stream.
        request._body = b"".join(chunks)  # type: ignore[attr-defined]

        form = await request.form()
        title = str(form.get("title") or "")
        text = str(form.get("text") or "")
        link = str(form.get("url") or "")
        attachment = ""
        media = form.get("media")
        if media is not None and hasattr(media, "filename"):
            filename = getattr(media, "filename", "") or "attachment"
            size = getattr(media, "size", 0) or 0
            content_type = getattr(media, "content_type", "") or "application/octet-stream"
            attachment = f"Attachment: {filename} ({size} bytes, {content_type})"
        return _share_redirect(
            title=title,
            text=text,
            url=link,
            attachment=attachment,
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        s = _settings()
        return {
            "status": "ok",
            "version": __version__,
            "provider": s.llm.provider,
            "model": s.llm.model,
        }

    @app.get("/api/sessions", response_model=list[SessionSummary])
    async def list_sessions() -> list[SessionSummary]:
        recent = Session.list_recent(_sessions_dir(), limit=50)
        return [_to_summary(s) for s in recent]

    @app.post("/api/sessions", response_model=dict[str, Any])
    async def create_session() -> dict[str, Any]:
        session = Session.new(metadata={"created_via": "web"})
        session.save(_sessions_dir())
        return session.to_dict()

    @app.get("/api/sessions/{session_id}", response_model=dict[str, Any])
    async def get_session(session_id: str) -> dict[str, Any]:
        return _load_session(session_id).to_dict()

    @app.get("/api/sessions/{session_id}/events")
    async def get_session_events(
        session_id: str, since: str = "0"
    ) -> StreamingResponse:
        """Stream audit-log events for this session from a byte offset.

        Implements H1.1's append-only log fan-out: clients poll
        ``?since=<offset>`` to receive only events appended after the
        last response. Semantics of ``since``:

        * Missing or ``"0"``  — start at the beginning of the file.
        * ``"-1"`` or ``"tail"`` — start at the current EOF (no events
          until a follow-up poll after the writer appends).
        * Any other integer — start at that byte offset; a mid-line
          offset is rounded up to the next line boundary so a stale
          cursor never surfaces a half-formed event.

        The response is ``application/x-ndjson`` — one JSON event per
        line. The current end of the audit log is returned in
        ``X-Current-Offset`` so the client can poll again with
        ``?since=<that value>``.
        """
        # Confirm the session exists (404 otherwise). The audit log is
        # global; we just filter it by ``session_id`` via the query
        # expression passed to :func:`query_stream`.
        _load_session(session_id)
        s = _settings()
        log_path = Path(s.security.audit_log)
        current_size = log_path.stat().st_size if log_path.exists() else 0

        if since in ("-1", "tail"):
            start = current_size
        elif since == "" or since == "0":
            start = 0
        else:
            try:
                start = int(since)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid 'since' value: {since!r} (expected int, -1, or 'tail')",
                ) from exc
            if start < 0:
                raise HTTPException(
                    status_code=400, detail="'since' must be >= 0 (use -1 or 'tail' for EOF)"
                )

        # session_id is a uuid4 hex string — safe to embed as a bare
        # value in the audit query language. Wrap in quotes anyway to
        # be defensive against future id formats (e.g. prefixed ids).
        safe_sid = session_id.replace('"', '\\"')
        expr = f'session_id="{safe_sid}"'

        def event_source() -> Iterator[str]:
            for ev in query_stream(log_path, since=start, expr=expr):
                yield json.dumps(ev.to_dict(include_hash=True), ensure_ascii=False) + "\n"

        return StreamingResponse(
            event_source(),
            media_type="application/x-ndjson",
            headers={"X-Current-Offset": str(current_size)},
        )

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> None:
        path = _session_path(session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="session not found")
        path.unlink()

    @app.post("/api/sessions/{session_id}/abort", status_code=204)
    async def abort_session(session_id: str) -> None:
        """Best-effort cancel of an in-flight run for this session."""
        buf = _active_runs.get(session_id)
        if buf is not None:
            buf.error = "aborted by user"
            buf.events.append({"event": "error", "data": {"message": "aborted"}})
            buf.done.set()
        return None

    @app.post("/api/sessions/{session_id}/messages")
    async def post_message(
        session_id: str, body: MessageRequest, request: Request
    ) -> StreamingResponse:
        if not body.content.strip():
            raise HTTPException(status_code=422, detail="content must be non-empty")

        session = _load_session(session_id)
        s = _settings()
        llm = LLMBackend.from_config(s.llm)
        agent = Manus(llm=llm, max_steps=s.max_steps)

        user_msg = ChatMessage(role="user", content=body.content)
        sessions_dir = _sessions_dir()

        async def event_source() -> AsyncGenerator[str, None]:
            async for chunk in _sse_event_stream(
                session_id=session_id,
                session=session,
                user_msg=user_msg,
                sessions_dir=sessions_dir,
                agent=agent,
            ):
                if await request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(event_source(), media_type="text/event-stream")

    return app


# Module-level instance so ``uvicorn forgewright.web.server:app`` works.
app = create_app()


__all__ = ["MessageRequest", "SessionSummary", "app", "create_app", "stream_agent_run"]
