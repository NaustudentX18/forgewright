# forgewright — Roadmap

> **Last updated:** 2026-06-03
> **Tracking:** [GitHub Milestones](https://github.com/NaustudentX18/forgewright/milestones)
> **Long-form plan:** [`BUILD_PLAN.md`](./BUILD_PLAN.md) · **Research:** [`docs/RESEARCH.md`](./docs/RESEARCH.md)

This is the high-signal view. Three tiers, no hand-waving.

- **Shipped** — released, in `main`, behind a tag.
- **Next** — scoped, in active work, in a milestone.
- **Maybe** — desired, not scoped, not promised. Open a Discussion if you
  want one of these bumped to **Next**.

We use [CalVer](https://calver.org/) (`YYYY.MM.PATCH`) and ship at least
once a month. The 1.0 bar is "no default-deny rule that hasn't been
documented, every command on `forgewright --help` works, and the audit
log is sha256-verifiable on a fresh clone."

---

## ✅ Shipped

### v0.1.0 — *Foundation* (2026-06-02)

The full BUILD_PLAN §3-§11. 617 unit tests, 0 regressions.

| Area | What landed |
|---|---|
| **Phase 0–1** | Hatchling build, `uv` lockfile, CLI entry point, multi-platform wheel matrix, pydantic-settings config, loguru logging |
| **Phase 2** | `LLM` protocol + `LiteLLMBackend` (Anthropic, OpenAI, Google, Azure, Bedrock, Ollama, OpenRouter) + deterministic stub for tests |
| **Phase 3** | `BaseTool`, `ToolCollection`, `ToolResult`, versioned registry |
| **Phase 4** | `Bash` (20-pattern denylist, safe-builtin short-circuit, per-call approval) · `StrReplaceEditor` (workspace-confined view/create/str_replace/undo/insert) · `PythonExecute` (subprocess + Docker modes) · `WebSearch` (DuckDuckGo → SerpAPI → Brave chain) |
| **Phase 5** | `Browser` (Playwright Chromium) + `Crawl4AI` |
| **Phase 6** | `BaseAgent` → `ReActAgent` → `ToolCallAgent` → `Manus` agent stack |
| **Phase 7** | `DataAnalysis` (Altair), `BrowserAgent`, `MCPAgent` |
| **Phase 8** | FastMCP server (Bash, Browser, FileEditor, Terminate, AskHuman) + first-party `mcp` SDK client (stdio / streamable-http / SSE) |
| **Phase 9** | `PlanningFlow` (LLM-driven task decomposition, sequential execution, resumable) |
| **Phase 10** | sha256-chained JSONL audit log, trust registry (session/repo/machine scopes), per-call approval, four pluggable sandboxes (subprocess → Docker → gVisor → Firecracker) |
| **Phase 11** | `prompt_toolkit` REPL, slash commands (`/help`, `/status`, `/cost`, `/resume`, `/model`, `/permissions`, `/mcp`, `/sandbox`, `/compact`, `/memory`, `/config`, `/doctor`, `/clear`, `/exit`), session persistence, cost tracker |
| **Release** | `cibuildwheel` matrix (linux/amd64, linux/arm64, macos x86_64, macos arm64), `ghcr.io/forest/forgewright` Docker image, Homebrew tap `forest/tap/forgewright`, CycloneDX SBOM, cosign signing, PyPI trusted publishing via OIDC, `pip-audit --strict` gate |

### v0.1.1 — *PWA-ready* (Unreleased, branch `master`)

739 unit tests (+122 from v0.1.0). Three commits on `master`.

- **BYOK path actually works** (was silently falling back to stub for every
  non-stub provider). Real `LiteLLMBackend` implemented, factory dispatches
  real providers, Ollama routes through `ollama_chat/` so tool calls work.
  Verified end-to-end with `FORGEWRIGHT_LLM__PROVIDER=ollama` + a real
  Ollama Cloud model: bash tool calls stream, finish with `final`.
- **Installable PWA** — `manifest.webmanifest` enriched with `id`, `scope`,
  description, categories, maskable 512 icon, "New chat" shortcut.
  Dedicated 180×180 `apple-touch-icon`, 512×512 maskable icon for adaptive
  launchers. `docs/MOBILE.md` covers install + Tailscale HTTPS.
- **Service worker** (`static/sw.js`) — versioned app-shell precache,
  network-first for `GET /api/sessions` with last-good fallback, **POST
  bypass so SSE streaming is unchanged**. 8 contract tests + 9 PWA tests
  in `tests/unit/web/test_service_worker.py` and `test_server.py`.
- **Tailscale HTTPS one-shot** — `forgewright web --bind tailscale
  --tailscale-serve` runs `tailscale serve --bg --https=443
  http://localhost:{port}` for PWA-install-friendly HTTPS. iOS install
  works.
- **Stop / cancel button** — red mid-stream button POSTs to the existing
  `/api/sessions/{id}/abort` endpoint. Server emits `event: error
  {"message":"aborted"}`. 3 new tests, optimistic UI flip on click.
- **Mobile-first contract tests** — viewport meta, safe-area insets,
  `100dvh`, manifest endpoints, content-type contracts. Static payload
  budget bumped 50 KB → 55 KB honestly (PWA banner + SW registration is
  ~2.7 KB), documented in CHANGELOG.

---

## 🔜 Next

### v0.2 — *TUI + offline queue* (target 2026-07)

- **Textual TUI** as a peer to the web chat. Reuses the SSE consumer, adds
  a sidebar tree, vim-keys, command palette. The web chat stays primary.
- ~~**Offline message queue**~~ — **Shipped on `master`:** IndexedDB outbox,
  Background Sync (`fw-flush-queue`), **Queued: N** badge, auto-flush on
  `online`. SSE POSTs still bypass the SW.
- ~~**Manifest screenshots**~~ — **Shipped:** `tools/regen_pwa_screenshots.py`
  + `static/screenshots/{desktop,mobile}.png` referenced from the manifest.
- ~~**Mobile-share target**~~ — **Shipped:** manifest `share_target` →
  `/share-in`, server redirect + SW POST handler, composer prefill for
  AskHuman-style context (URL/text/attachment metadata).
- ~~**MCP registry client**~~ — **Shipped:** `forgewright mcp install <name>`
  fetches `registry.modelcontextprotocol.io`, writes `~/.config/forgewright/mcp.json`.
- ~~**Real Playwright a11y tree**~~ — **Shipped:** `browser` `extract` uses
  `page.aria_snapshot(mode="ai")` (Playwright 1.49+; legacy snapshot fallback).
- ~~**Tiktoken-free token counting**~~ — **Shipped:** `llm/token_count.py`
  (OpenAI/Azure tiktoken, Anthropic `count_tokens`, else chars÷4).
- **Windows wheels** — cibuildwheel matrix grows to include
  `*-win64`. ARM64 Windows still out.
- ~~**Audit log query tool**~~ — **Shipped:** `forgewright audit query
  "tool=bash AND approved=false"`.

### v0.3 — *Multi-agent workflows* (target 2026-08)

- **Crew-style flows** as a first-class primitive. `Crew([Manus(...),
  BrowserAgent(...), DataAnalysis(...)])` with explicit handoff. Today
  `PlanningFlow` is single-agent with sequential steps.
- **Workspace sharing** between agents — one agent's file edits are
  visible to the next without an explicit `StrReplaceEditor` round-trip.
- **Cost caps per session** — `forgewright build --max-cost=$2.00` aborts
  the loop and persists a "cost limit reached" final state. Today the
  cost tracker is display-only.
- **Provider failover** — if Anthropic 5xx, fall over to OpenRouter with
  a configurable model mapping. Today the retry is the same provider.
- **Realtime webchat collab** — multi-user session over a WebSocket
  fan-out. Edits broadcast to other connected clients. PWA SW caches
  the fan-out WS as well as the SSE.

---

## 🌱 Maybe

Things we want but haven't scoped. Open a Discussion to bump one up.

- **Voice in / voice out.** Whisper.cpp for STT, Piper for TTS, both
  in-process on a Pi 5. Useful for the agent-in-your-pocket framing.
- ~~**Mobile-share target.**~~ Moved to **Shipped** (see v0.2 above).
- **gVisor + Firecracker CI runners.** Today's `sandbox doctor` works,
  but the CI matrix doesn't actually run inside a sandbox. We pretend
  the audit log is enough. It isn't.
- **Workspace persistence** beyond sessions. `forgewright workspace`
  CLI that boots a long-lived `/workspace` directory the agent can
  treat as its home (think Daytona / E2B, but local).
- **BYO-sandbox** for "I trust no one, I run my own." Point
  `forgewright.toml` at a remote Docker host, an E2B org, a Modal
  account, a Firecracker microVM, or a gVisor `runsc`. The `Sandbox`
  interface is already pluggable; we just haven't shipped the adapters.
- **Plugin marketplace.** Discoverable, signed, versioned third-party
  `BaseTool` and `BaseAgent` packages. The MCP server list is the
  template.
- **A real Tauri / native shell.** The PWA is great. A 4 MB native
  binary with the same UI and IPC to a local `forgewright serve` would
  be slightly better (system notifications, file-drop targets, menubar
  tray). Big lift; revisit after v0.3 lands.
- **Federated sessions.** Sync a session across two `forgewright web`
  instances (e.g. desktop + phone) so a task started on one can be
  resumed on the other. Probably a CRDT over the JSONL log.

---

## Out of scope, called out

These are explicit *not* on the roadmap, so future contributors don't
re-litigate the discussion.

- **Hosted SaaS, account system, telemetry, token markup.** The
  business model is "you run it, you own it, you pay your LLM provider
  directly." See [Philosophy §1](./README.md#philosophy).
- **Drop-in replacement for an existing agent framework.** If you want
  the OpenHands UX, use OpenHands. forgewright ships its own
  opinions.
- **Crawler-of-the-week.** We picked `crawl4ai` and we'll defend it
  through v1.0. Adapters can be plugins.

---

## How to influence the roadmap

1. **Open a Discussion** with the `roadmap` label. Reference which tier
   and which item.
2. **For new ideas**, link a use-case ("I want to do X"), not a solution
   ("forgewright should add feature Y"). Solutions get scoped in the PR
   review, use-cases get scoped in the discussion.
3. **For Next-tier items**, the path to **Shipped** is: scope PR → TDD
   → tests passing → changelog entry → merge → tag.

We try to reply to every discussion within a week. We commit to the
calendar; we don't commit to the order within a release.
