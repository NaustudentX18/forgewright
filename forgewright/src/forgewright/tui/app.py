"""Textual TUI — sidebar + message pane over the web SSE API."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, RichLog, Static

from forgewright.tui.sse import stream_message_sse

__all__ = ["ForgewrightTuiApp"]


class ForgewrightTuiApp(App[None]):
    """Minimal chat TUI: session sidebar placeholder and message log."""

    TITLE = "forgewright"
    CSS = """
    #sidebar {
        width: 28;
        min-width: 20;
        border-right: tall $accent;
        padding: 0 1;
    }
    #messages {
        height: 1fr;
    }
    #composer {
        dock: bottom;
        height: 3;
        padding: 0 1 1 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, base_url: str = "http://127.0.0.1:8787") -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self._session_id: str | None = None
        self._sessions: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("Sessions", id="sidebar-title")
                yield ListView(id="session-list")
            with Vertical():
                yield RichLog(id="messages", highlight=True, markup=True)
                yield Input(placeholder="Message (requires forgewright web)", id="composer")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#messages", RichLog).write(
            f"[dim]API[/dim] {self.base_url} — start the server with "
            "[bold]forgewright web[/bold], then type a message."
        )
        self.refresh_sessions()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.send_user_message(text)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._sessions):
            return
        self._select_session(self._sessions[idx])

    @work(exclusive=True)
    async def refresh_sessions(self) -> None:
        """Load ``GET /api/sessions`` into the sidebar list."""
        list_view = self.query_one("#session-list", ListView)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/api/sessions")
                response.raise_for_status()
                sessions: list[dict[str, Any]] = response.json()
        except httpx.HTTPError as exc:
            self.notify(f"Could not load sessions: {exc}", severity="error", timeout=8)
            return

        self._sessions = sessions
        await list_view.clear()
        if not sessions:
            await list_view.append(ListItem(Static("(no sessions yet)")))
            return
        for summary in sessions:
            title = summary.get("title") or summary.get("id", "session")
            await list_view.append(ListItem(Static(str(title))))
        if self._session_id is None and sessions:
            self._select_session(sessions[0])

    def _select_session(self, summary: dict[str, Any]) -> None:
        sid = str(summary.get("id", ""))
        if not sid:
            return
        self._session_id = sid
        title = summary.get("title") or sid
        log = self.query_one("#messages", RichLog)
        log.write(f"[bold]── {title}[/bold] ({sid[:8]}…)")
        self.load_session_messages(sid)

    @work(exclusive=True)
    async def load_session_messages(self, session_id: str) -> None:
        """Hydrate the message pane from ``GET /api/sessions/{id}``."""
        log = self.query_one("#messages", RichLog)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/api/sessions/{session_id}")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            log.write(f"[red]load failed:[/red] {exc}")
            return

        for msg in data.get("messages") or []:
            role = msg.get("role", "?")
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            prefix = "[cyan]you[/cyan]" if role == "user" else "[green]assistant[/green]"
            log.write(f"{prefix}: {content}")

    @work(exclusive=True)
    async def send_user_message(self, text: str) -> None:
        """Ensure a session exists, POST the message, consume SSE into the log."""
        log = self.query_one("#messages", RichLog)
        log.write(f"[cyan]you[/cyan]: {text}")

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                session_id = await self._ensure_session(client)
                assistant_parts: list[str] = []
                async for event, payload in stream_message_sse(
                    client, self.base_url, session_id, text
                ):
                    self._handle_sse_event(event, payload, log, assistant_parts)
                if assistant_parts:
                    log.write("[green]assistant[/green]: " + "".join(assistant_parts))
        except httpx.HTTPError as exc:
            log.write(f"[red]send failed:[/red] {exc}")
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self.refresh_sessions()

    async def _ensure_session(self, client: httpx.AsyncClient) -> str:
        if self._session_id:
            return self._session_id
        response = await client.post(f"{self.base_url}/api/sessions", json={})
        response.raise_for_status()
        data = response.json()
        sid = str(data["id"])
        self._session_id = sid
        return sid

    def _handle_sse_event(
        self,
        event: str,
        payload: dict[str, Any],
        log: RichLog,
        assistant_parts: list[str],
    ) -> None:
        if event == "thinking":
            log.write("[dim]thinking…[/dim]")
        elif event == "tool_call":
            tool = payload.get("tool", "tool")
            log.write(f"[yellow]tool[/yellow] → {tool}")
        elif event == "tool_result":
            tool = payload.get("tool", "tool")
            log.write(f"[yellow]tool[/yellow] ← {tool}")
        elif event == "token":
            piece = payload.get("content") or ""
            if piece:
                assistant_parts.append(str(piece))
        elif event == "final":
            content = (payload.get("content") or "").strip()
            if content and not assistant_parts:
                assistant_parts.append(content)
        elif event == "error":
            msg = payload.get("message", "unknown error")
            log.write(f"[red]error[/red]: {msg}")
