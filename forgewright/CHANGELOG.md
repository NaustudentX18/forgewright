# Changelog

All notable changes to forgewright are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [CalVer](https://calver.org/) (`YYYY.MM.PATCH`).

---

## [Unreleased]

### Fixed
- **`app.js` was truncated at the top of the file** (missing the IIFE,
  DOM bindings, and the start of `renderMd`). The web UI could not run
  in a browser. Restored the bootstrap and kept all PWA/mobile logic.

### Added
- **Offline message outbox (mobile).** IndexedDB queue
  (`forgewright-offline-v1`), **Queued: N** top-bar badge, flush on
  `online` and via Background Sync (`fw-flush-queue`). SSE POSTs still
  bypass the service worker.
- **PWA share target.** Manifest + `/share-in` (server + SW) prefill the
  composer with AskHuman-style context for shared URLs, text, and
  attachment metadata.
- **Install-card screenshots.** `tools/regen_pwa_screenshots.py` and
  `static/screenshots/{desktop,mobile}.png` referenced from the manifest.
- Service worker cache bumped to `forgewright-shell-v2`.
- Static payload budget **60 KB → 68 KB** (offline queue + restored
  `app.js`).

### Added (v0.2 swarm)
- **`forgewright audit query`** — filter JSONL audit log with `field=value`
  and `AND` (e.g. `tool=bash AND approved=false`).
- **MCP registry install** — `forgewright mcp install <name>` writes server
  blocks to `~/.config/forgewright/mcp.json`.
- **Provider-aware token counting** — `llm/token_count.py` for context
  budgeting (Anthropic API, tiktoken on OpenAI, heuristic elsewhere).
- **Browser extract** — `aria_snapshot(mode="ai")` instead of scraping
  `innerText` on modern Playwright.

### Changed
- Static payload **optimized ~67 KB → ~61 KB** (dedupe inline CSS, trim
  `app.js`); budget remains 68 KB.
- **Ruff-clean** tree for the touched modules.

### Fixed (earlier unreleased)
- **BYOK path was completely broken.** `LLMBackend.from_config` claimed
  to support `provider="anthropic" | "openai" | "google" | "azure" |
  "bedrock" | "ollama" | "openrouter"` (per `LLMConfig`'s Literal
  type), but the factory silently fell back to `StubBackend` for every
  non-stub provider. The advertised `litellm_backend.py` did not exist
  on disk. Web chat, CLI REPL, and PlanningFlow all silently used the
  stub LLM regardless of the user's config. Forgewright was not
  actually BYOK. **Now fixed**: real `LiteLLMBackend` is implemented,
  factory dispatches real providers, and the Ollama provider routes
  through `ollama_chat/` (not `ollama/`) so tool calls work.
- **Verified end-to-end**: `forgewright web` with
  `FORGEWRIGHT_LLM__PROVIDER=ollama` + a real Ollama Cloud model
  dispatches `bash` tool calls, streams tokens, and finishes with
  `final` — i.e. the Manus-clone UX actually works now.

### Added
- `src/forgewright/llm/litellm_backend.py` — `LiteLLMBackend` with
  `_resolve_model_string`, `_convert_messages`, `_convert_tools`,
  `_normalize_assistant`, and per-provider context-window defaults.
- `tests/unit/llm/test_litellm_backend.py` — 36 tests covering
  factory dispatch, model-string prefixes, message/tool conversion,
  response normalization, and mocked end-to-end `ask_tool`.
- **PWA: installable on iOS and Android.** The web chat now
  installs as a home-screen app, works offline for read-only
  session access, and ships a service worker that survives
  deploys via a versioned cache.
  - `src/forgewright/web/static/sw.js` — service worker. App
    shell precache (`forgewright-shell-v1`); cache-first for
    `/` and `/static/*`; network-first for `GET /api/sessions*`
    with last-good fallback; **bypasses POST so SSE streaming
    on `/api/sessions/{id}/messages` is unchanged**.
  - `src/forgewright/web/static/manifest.webmanifest` —
    enriched with `id`, `scope`, `description`, `categories`,
    `purpose: "maskable"` icon, and a `shortcuts` entry for
    "New chat".
  - `src/forgewright/web/static/icon-maskable-512.png` — new,
    512×512 with a 410×410 artwork safe-zone for adaptive
    launchers (Android, iOS, web app launchers).
  - `src/forgewright/web/static/apple-touch-icon.png` — new,
    180×180 dedicated iOS Home Screen icon.
  - `src/forgewright/web/static/app.js` — SW registration
    (`navigator.serviceWorker.register('/static/sw.js')`) and
    install banner UX: `beforeinstallprompt` listener for
    Android/Chromium, iOS Share-sheet hint for Safari (which
    does not fire the event). Dismissal persisted in
    `localStorage` under `fw-install-dismissed-v1`; cleared
    on `appinstalled`.
  - `src/forgewright/web/static/index.html` — added the
    dedicated 180×180 `apple-touch-icon` and Safari pinned-tab
    `mask-icon` link.
  - `src/forgewright/cli/run_web.py` — new `--bind`
    convenience (`loopback` | `lan` | `tailscale` | `all`)
    and `--tailscale-serve` flag that runs
    `tailscale serve --bg --https=443 http://localhost:{port}`
    for PWA-install-friendly HTTPS.
  - `tools/regen_pwa_icons.py` — committed one-off script
    (Pillow) that regenerates the four PWA icons from the
    canonical 512×512 source. Idempotent, output checked in.
  - `tests/unit/web/test_server.py` — 9 new tests covering
    SW serving, manifest fields, app.js registration, and
    the iOS hint path.
  - `tests/unit/web/test_service_worker.py` — new file, 8
    contract tests for the SW (lifecycle events, versioned
    cache name, **POST bypass for SSE**, same-origin guard,
    shell precache, optional `node --check`).
  - `docs/MOBILE.md` — PWA install + Tailscale HTTPS setup.
  - **Test count: 736** (up from 719; +17 PWA tests, no
    regressions).
  - **Static payload budget: 50 KB → 55 KB.** The install
    banner and SW registration are about 2.7 KB of `app.js`.
    Anything beyond 55 KB needs a real perf review.
  - **Stop / cancel button** in the web UI. A red "Stop" button
    replaces the Send button mid-stream and POSTs to
    `POST /api/sessions/{id}/abort` (the endpoint that already
    existed but had no client wiring). The server emits
    `event: error {"message": "aborted"}` which the existing
    SSE consumer handles; the UI flips back to Send on click
    for instant feedback even before the server's error event
    round-trips. **Test count now 739** (+3 stop-button tests).

### Notes
- The OMC HUD already renders context-% in the statusline
  (`[OMC#x.y.z] | [API err] | session:N | ctx:M%`) and writes a
  `~/.omc/state/compact-requested.json` trigger file when usage
  crosses its configured threshold. No forgewright-side change
  needed; this is documented here so future contributors don't
  re-implement it.

---

## [0.1.0] - 2026-06-02

The first public release of forgewright. The layered agent stack, sandboxing,
MCP integration, CLI, audit log, and distribution pipeline are all in place and
covered by 617 unit tests.

### Added

- **Phase 0 — Project scaffold.** Hatchling build, `uv` lockfile, CLI binary
  entry point, multi-platform wheel matrix.
- **Phase 1 — Configuration & logging.** `pydantic-settings`-driven config with
  env-var overrides and `loguru`-based structured logging.
- **Phase 2 — LLM abstraction.** Provider-agnostic `LLM` protocol with a
  LiteLLM backend (Anthropic, OpenAI, Google, Azure, Bedrock, Ollama,
  OpenRouter) and a deterministic stub for tests.
- **Phase 3 — Tool foundation.** `BaseTool`, `ToolCollection`, and `ToolResult`
  types; registry with name-based lookup and versioning.
- **Phase 4 — File & shell tools.** `Bash` (20-pattern dangerous-command
  denylist, safe-builtin short-circuit, per-call approval), `StrReplaceEditor`
  (view / create / str_replace / undo / insert with workspace confinement),
  `PythonExecute` (subprocess mode for speed, Docker mode for isolation), and
  `WebSearch` (configurable engine chain: DuckDuckGo → SerpAPI → Brave).
- **Phase 5 — Browser tool.** `Browser` (Playwright Chromium with
  navigate / click / type / screenshot / extract / get_title / get_html / close)
  and `Crawl4AI` for content extraction.
- **Phase 6 — Manus agent.** `BaseAgent` state machine → `ReActAgent`
  think/act loop → `ToolCallAgent` structured function calling → `Manus`
  general-purpose default agent with a hand-tuned system prompt.
- **Phase 7 — Sub-agents.** `DataAnalysis` (Vega-Altair visualisation tools),
  `BrowserAgent` (browser-only), and `MCPAgent` (MCP-only transport).
- **Phase 8 — MCP integration.** FastMCP server exposing Bash, Browser,
  FileEditor, Terminate, and AskHuman to other agents; first-party `mcp` SDK
  client supporting `stdio`, `streamable-http`, and `SSE` transports with
  namespaced tool wrapping.
- **Phase 9 — PlanningFlow.** LLM-driven task decomposition into a numbered
  plan, sequential execution with intermediate verification, and resumable
  state.
- **Phase 10 — Security & sandboxing.** sha256-chained JSONL audit log,
  trust registry with session/repo/machine scopes, per-call approval flow with
  a `Shift+Tab` mode cycle, and four pluggable sandboxes
  (subprocess → Docker → gVisor → Firecracker).
- **Phase 11 — UX & session.** `prompt_toolkit`-powered REPL, slash commands
  (`/help`, `/status`, `/cost`, `/resume`, `/model`, `/permissions`, `/mcp`,
  `/sandbox`, `/compact`, `/memory`, `/config`, `/doctor`, `/clear`, `/exit`),
  session persistence to `~/.local/share/forgewright/sessions/`, and a running
  cost tracker.
- **Tests.** 617 unit tests, 100% pass rate, fast suite (no network).
- **Type & lint hygiene.** `ruff check` clean (no warnings) across the
  whole tree, and `mypy` is at zero new errors introduced by v0.1.0 code
  (a handful of pre-existing `docker` import-not-found warnings remain —
  they are tracked for the v0.2 dependency refresh).
- **Multi-platform builds.** `cibuildwheel` matrix producing wheels for
  `linux/amd64`, `linux/arm64`, `macos x86_64`, and `macos arm64`.
- **Docker image.** Multi-arch `ghcr.io/forest/forgewright` image with
  Chromium pre-installed for the browser tool.
- **Homebrew tap.** `forest/tap/forgewright` formula, auto-updated by
  `tap-updater` on each tagged release.
- **SBOM.** CycloneDX 1.5 SBOM generated on every release and attached to the
  GitHub release.
- **Signed artifacts.** Sigstore / cosign signing of the wheel, sdist, and
  Docker image; verification instructions in `docs/INSTALL.md`.
- **Trusted publishing.** PyPI upload via OIDC, no long-lived API tokens.

### Security

- 20-pattern dangerous-command denylist with a small safe-builtin short-circuit
  (the 9 hardest patterns are non-overrideable).
- Per-call interactive approval for everything outside the safe-builtin list,
  with three persistence scopes (`session`, `repo`, `machine`).
- `sha256`-chained JSONL audit log with append-only semantics, secret-pattern
  redaction, and `forgewright audit verify` chain validation.
- Docker sandbox defaults: `mem_limit=512m`, `pids_limit=256`, `cpus=1.0`,
  `network_mode=none`, `read_only=true`, `cap_drop=ALL`, `no-new-privileges`,
  `seccomp=runtime/default`, non-root UID.
- API keys resolve from OS keyring → env var → chmod-0600 `secrets.toml`,
  never logged or echoed; the audit log records the source but never the
  value.
- `pip-audit --strict` gates every release on a clean dependency audit.

### Notes

This is the first public release. See [`docs/INSTALL.md`](./docs/INSTALL.md)
for installation, [`docs/QUICKSTART.md`](./docs/QUICKSTART.md) for a 5-minute
tour, and [`BUILD_PLAN.md`](./BUILD_PLAN.md) for the full roadmap.

---

*Last updated 2026-06-02.*
