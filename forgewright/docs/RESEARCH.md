# Research Synthesis — forgewright

> **Date:** 2026-06-02. **Status:** v0.1 planning input. All findings informed `BUILD_PLAN.md` and `README.md`. Source citations are at the bottom of each section.

This document captures the research that informed the project's name, positioning, tech stack, UX patterns, and security model. Read this if you want to understand *why* the build plan looks the way it does.

---

## 1. Naming & branding

### Survey of existing open-source AI agent projects
Three naming patterns recur: short coined words (`aider`, `plandex`, `smolagents`, `goose`); descriptive compounds (`LangChain`, `LlamaIndex`, `AutoGen`); and the `Open-` prefix (`OpenHands`, `OpenDevin`). Names that stick share four traits: ≤3 syllables, pronounceable on first sight, suggest *agency or craft*, and the bare GitHub org + PyPI name are claimable. Mythological names (Aegis, Iris, Argus) carry baggage and are nearly always squatted.

### Candidate evaluation

| Candidate | GitHub | PyPI | Vibe |
|---|---|---|---|
| `atelier` | Taken (dormant) | Taken | Refined, indie |
| `aegis` | Taken (dormant) | Taken | Defensive, classic |
| `aether` | Taken (empty user) | Taken | Ethereal |
| **`forgewright`** | **Available** | **Available** | **Craft, maker, decisive** |
| `thewright` | Available | Available | Quiet, deliberate |
| `smithy` | Taken (squatted) | Taken (AWS) | Forge family, conflicted |
| `opencrucible` | Available (404) | Available | Heat, transformation |
| `promethean` | Personal user | Available | Mythic, bold |
| `hearth` | Taken | Taken | Warm, community |
| `nimbus` | Taken (active competitor) | Taken | Cloud, conflicted |
| `tinker` | Taken | Taken | Curious, hobbyist |
| `maverick` | Taken | Taken | Solo, brash |
| `iris` | Taken (passport-reader) | Taken | Messenger, conflicted |
| `loom` | Dormant | Taken | Weaving, classic |
| `wright` | Personal user | Available | Clean, craft suffix |

### Decision: **forgewright**

Coined compound of *forge* (where things are shaped under heat) and *wright* (Old English suffix for a maker — playwright, shipwright, wheelwright). Signals deliberate craft and agentic doing in one word, no mythological baggage, no `open-` prefix crowding. Both `github.com/forgewright` and `pypi.org/forgewright` are effectively unclaimed. Pairs naturally with verbs: `forgewright build`, `forgewright plan`, `forgewright apply`.

**Tagline:** *Forge agents. Wright code. In your terminal, with your keys.*

**Install preview:** `curl -fsSL forgewright.dev/install.sh | bash`

**Brand mark (text, terminal-friendly):**
```
   ╱╲
  ╱  ╲    forgewright v0.1.0
 ╱────╲   forge agents. wright code.
│ FW  │   ready · BYO keys · CLI
 └──┬──┘
 ═══╧═══
```
Reads as a stylized anvil (trapezoid with `FW` monogram, twin horns, base block). Renders cleanly in any monospaced terminal; no color or emoji required.

**Sources:** [aider](https://github.com/Aider-AI/aider), [OpenHands](https://github.com/All-Hands-AI/OpenHands), [smolagents](https://github.com/huggingface/smolagents), [plandex](https://github.com/plandex-ai/plandex), [Goose](https://github.com/block/goose), [crewAI](https://github.com/crewAIInc/crewAI), [PydanticAI](https://github.com/pydantic/pydantic-ai), [gpt-engineer](https://github.com/gpt-engineer-org/gpt-engineer), [Atomic Agents](https://github.com/BrainBlend-AI/atomic-agents). PyPI JSON API used to verify availability of all 19 candidate package names.

---

## 2. Competitive landscape

### Positioning opportunities

1. **CLI-first + BYOK + local-first with first-class persistence.** Every major open-source project (OpenManus, OpenHands, AutoGen, CrewAI, smolagents, Atomic Agents, PydanticAI, agency-swarm) is Python-library-shaped. None of them treat the terminal as a peer to a chat UI the way Claude Code or Gemini CLI do. Meanwhile, the loudest repeated complaint across repos is *no persistent memory* — OpenManus' #1087 and #1302 were both closed "Not planned"; OpenHands users want conversation branching (#8560); Atomic Agents wants graph memory (#151); AutoGen wants memory components for RAG (#4707).

2. **Multi-agent coordination that actually ships.** OpenManus' `run_flow.py` is labeled "unstable multi-agent version" in the README. AutoGen's "Multiple LLM working in sync" sits stale since May 2024 (#2075). CrewAI's `Crews` and `Flows` are clean but lack the type-safety of agency-swarm's directional `>` flows or PydanticAI's graph module. A framework that ships stable, type-safe, YAML-declarable agent communication is missing.

3. **Tool authorization / safe-by-default sandbox.** The loudest single issue class in smolagents — four of its top 12 issues are about memory poisoning (OWASP ASI06) and MCP server trust (#2332, #2305, #2303, #2290). OpenManus' #1331 is an RFC for a pre-tool-call authorization layer on `BaseTool`. CrewAI's #5888 asks for the same. A CLI tool with a default-deny, allowlist-driven, human-in-the-loop permission model would fill a clear gap.

4. **Provider-agnostic without non-ASCII / caching regressions.** AutoGen #6995 (MCP tool JSON serialization degrades Japanese text) and CrewAI #5886 (cache_breakpoint injected for non-Anthropic providers) are the kind of breakage that comes from "works on OpenAI, sometimes works elsewhere." A project that tests against the full LiteLLM matrix on every PR would be valuable.

5. **Observability of agent flow, not just LLM tokens.** Atomic Agents #20 (graphical representation of flow, open since Oct 2024) and #151 (graph memory), plus PydanticAI's tight Logfire integration, show users want flow-level traces. LangGraph's LangSmith coupling is the closest existing answer but is a paid commercial product.

### What to clone
- smolagents' `CodeAgent` — "agents that think in code," ~1,000-line core, 30% fewer steps than JSON tool calling.
- PydanticAI's capability/agent-spec ergonomics — composable capabilities, YAML/JSON spec option, durable execution.
- Atomic Agents' schema chaining and `atomic` CLI tool installer.
- agency-swarm's directional `communication_flows` (`>` operator for who-talks-to-whom).
- OpenHands' SDK + CLI + Local GUI separation.
- LangGraph's durable-execution model (Pregel/NetworkX-style state, human-in-the-loop pauses, time-travel debugging).
- v0/Lovable's "describe → build → refine → deploy" chat UX for the *human-facing* surface, while keeping the *agent* surface CLI-first and BYOK.

### What to avoid
- OpenManus' loose context/looping behavior (issues #757, #544, #969, #1267).
- OpenManus' "unstable multi-agent" tag on `run_flow.py` — don't ship a de facto broken tier.
- OpenManus' install hell — `uv` resolver failures with `crawl4ai`/`pillow` (#1360), Daytona SDK auth crash (#1361), Docker init failures (#1030), and 9-month-inactive bug reports.
- AutoGen's "maintenance mode" handoff to Microsoft Agent Framework.
- CrewAI's provider-specific bugs (DeepSeek/Anthropic-cache-leak/non-ASCII).
- smolagents' `DANGEROUS_FUNCTIONS` Windows bypass (#2232) — sandbox defaults must be secure-by-default.
- LangGraph's LangSmith coupling — users get nudged to a paid commercial product.
- Devin / Manus AI / Replit Agent closed-source model lock-in.
- v0/Bolt's vendor-locked deploy.

### Feature wishlist
1. Persistent/checkpointed memory with cross-session resume.
2. Default-deny tool authorization with allowlist + per-call approval.
3. Stable, type-safe multi-agent flows.
4. Provider-agnostic with full i18n + caching correctness.
5. Docker-less, single-binary, no-dependency-hell install.
6. MCP server trust verification + safe defaults.
7. CLI-native UX (slash-commands, `~/.config/<tool>/skills/`, GitHub-sync, `--non-interactive`).
8. Conversation fork/branch and model-switch mid-session.
9. Flow-level observability via OTel only.
10. Pluggable execution backends (local subprocess, Docker, Daytona, E2B, Modal).

**Sources:** [FoundationAgents/OpenManus](https://github.com/FoundationAgents/OpenManus), [OpenManus issues](https://github.com/FoundationAgents/OpenManus/issues), [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands), [microsoft/autogen](https://github.com/microsoft/autogen), [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI), [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph), [huggingface/smolagents](https://github.com/huggingface/smolagents), [BrainBlend-AI/atomic-agents](https://github.com/BrainBlend-AI/atomic-agents), [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai), [vrsen/agency-swarm](https://github.com/vrsen/agency-swarm), [Manus AI](https://manus.im), [Devin](https://devin.ai), [Lovable](https://lovable.dev), [Bolt.new](https://bolt.new), [v0](https://v0.app), [Replit Agent](https://replit.com/ai).

---

## 3. Tech stack

### Library decisions

| Library | Version | Role | Gotcha |
|---|---|---|---|
| pydantic | 2.13.4 | Message/config models | `extra="forbid"`; avoid shared mutable instances |
| pydantic-settings | 2.14.1 | TOML + env + dotenv + CLI | `env_nested_delimiter="__"`; CLI > env > TOML |
| mcp (official) | 1.27.2 | MCP client (stdio/SSE/StreamableHTTP) | Stdio for local; Streamable HTTP for remote |
| FastMCP | 3.3.1 | MCP server, auto-schema from type hints | `mcp.http_app(...).lifespan` required when mounting in FastAPI |
| Playwright | 1.55+ | Browser automation, persistent context | Can't automate default Chrome profile |
| LiteLLM | 1.86.2 | Unified LLM gateway (100+ providers) | Disable SDK's `max_retries` to avoid double-backoff with tenacity |
| openai | 2.40.0 | OpenAI/AsyncOpenAI | `openai[aiohttp]` for concurrency |
| anthropic | 0.105.2 | Claude | `client.messages.count_tokens` for token counting |
| boto3 | latest | AWS Bedrock Converse API | Use `bedrock-runtime` client |
| tiktoken | 0.13.0 | OpenAI token counts only | Not for Claude — use Anthropic's endpoint |
| tenacity | 9.1.4 | Retry with backoff + jitter | Distinguish via exception type; `reraise=True` |
| docker (docker-py) | 7.1.0 | Sandboxed code execution | `network_mode="none"`, `pids_limit`, `read_only=True` |
| crawl4ai | <0.8.7 | LLM-ready web extraction | Pin below 0.8.6 supply-chain incident |
| altair | 6.1.0 | Declarative charts, JSON spec | Validate LLM-emitted Vega-Lite spec before render |
| loguru | 0.7+ | Logging | `enqueue=True` for multi-proc; explicit `colorize=True` in CI |
| uv | 0.11.18 | Package/project manager | Replaces pip/poetry/pipx |
| rich | 14+ | Streaming display, syntax, panels | Aider's `mdstream.py` is the gold standard |
| prompt_toolkit | 3.0.51 | Input loop, history, completion | Pairs with rich for line-mode REPL |
| typer | 0.12+ | CLI framework on top of click | Type-hint-driven |
| httpx | 0.27+ | Async HTTP | Used by MCP client |
| keyring | latest | OS keyring for secrets | Preferred over env over file |

### Patterns and gotchas

- **Pydantic v2.** Use `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`. `model_validator(mode="after")` for cross-field invariants. Don't share mutable instances across threads.
- **MCP transport.** `stdio` for in-process; **Streamable HTTP** is the modern SSE replacement (HTTP POST + optional SSE response stream); legacy SSE server transport is superseded. Use stdio for our CLI subprocess and Streamable HTTP for the network-exposed MCP server.
- **Playwright persistent context.** `await playwright.chromium.launch_persistent_context(user_data_dir=..., headless=True)`. Can't automate the default Chrome profile — pass a dedicated `user_data_dir`. For DOM, `page.accessibility.snapshot()` returns a tree that doubles as an LLM-readable representation.
- **Multi-provider LLM.** LiteLLM is the right choice. Alternative: Pydantic AI (`Agent('anthropic:claude-sonnet-4-6')` syntax with native MCP) if you want batteries-included. Token counting: tiktoken is OpenAI-only; for Anthropic use `client.messages.count_tokens`; approximate with `len(text) / 4`.
- **Retry.** Tenacity with `wait_random_exponential(multiplier=1, min=2, max=60)`, `stop_after_attempt(7)`. Distinguish via exception type — 429/5xx/timeout retryable, `BadRequestError` not. Honor `Retry-After`. Disable SDK's built-in retries (`max_retries=0`) to avoid double-backoff.
- **Docker sandbox.** `mem_limit="512m"`, `cpu_quota=50000`, `pids_limit=256`, `network_mode="none"`, `read_only=True`, `user="nobody"`. gVisor (`runsc`) for stronger isolation; Firecracker for multi-tenant hostile.
- **Stuck-loop detection.** No off-the-shelf library. Sliding window over tool-call signatures (name + serialized args) — not raw text. Threshold of 2–3 identical consecutive calls → nudge prompt.
- **Loguru.** Thread-safe by default. `enqueue=True` for multi-proc/async safety. `serialize=True` for JSON. Explicit `colorize=True` in CI (Loguru disables color when stdout isn't a TTY).
- **TOML config.** `pydantic-settings` is the 2026 winner. `SettingsConfigDict(env_prefix="AGENT_", env_nested_delimiter="__", toml_file="config.toml", extra="forbid")`. Thread-safety: `model_config.frozen=True` + `lru_cache(maxsize=1)`.
- **Async vs sync.** Agent loop is `asyncio`; LLM streams and tool calls are I/O-bound. Sync escape via `asyncio.to_thread(...)`. Don't wrap sync SDK calls in an event loop.
- **Charts.** VMind is TypeScript-only. For a Python CLI, use **Vega-Altair 6.x** (declarative, JSON spec, LLM-friendly). LLM emits a JSON Vega-Lite spec, code validates and renders. Matplotlib as fallback only.
- **Crawl4AI.** Pin `<0.8.7` — the 0.8.6 release was a supply-chain incident (unclecode-litellm fork replacing litellm).

**Sources:** [Pydantic v2 docs](https://docs.pydantic.dev/latest/), [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), [Model Context Protocol](https://modelcontextprotocol.io/), [FastMCP](https://github.com/jlowin/fastmcp), [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk), [Playwright Python](https://playwright.dev/python/), [LiteLLM](https://github.com/BerriAI/litellm), [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python), [tenacity](https://github.com/jd/tenacity), [docker-py](https://github.com/docker/docker-py), [Crawl4AI](https://github.com/unclecode/crawl4ai), [Altair](https://altair-viz.github.io/), [loguru](https://github.com/Delgan/loguru), [uv](https://github.com/astral-sh/uv).

---

## 4. CLI / UX playbook

### Reference implementations

| Project | Stack | Best UX pattern to borrow |
|---|---|---|
| Claude Code | TS/Rust native binary | Permission-mode cycle, `PreToolUse`+`PostToolUse` hooks, four-tier `CLAUDE.md` discovery, settings precedence |
| Gemini CLI | TS + React/Ink | State-machine streaming, `StreamingState` enum, transient pending tool items with `borderTop`/`borderBottom` |
| Goose | Rust/TS | Recipe marketplace, MCP-first extension model, `~/.config/goose/` + `AGENTS.md` discovery |
| Aider | Python + rich + prompt_toolkit | `MarkdownStream` (20fps throttled live render with 6-line "unstable" window), `/add` `/drop` `/model` `/architect` `/tokens` |
| Plandex | Go (bubbletea/lipgloss) | Plan/diff sandbox, AI changes in review buffer separate from your files |
| OpenHands CLI | Python | `--always-approve` / `--yolo` / `--llm-approve` modes, `--resume [id\|--last]` |
| Codex CLI | Rust | Lightweight single-binary distribution, ChatGPT OAuth + API-key auth |

### Streaming + tool-call rendering
**Recommendation: `rich` 14.x + `prompt_toolkit` 3.0.51.** Aider's `mdstream.py` is the gold standard. Code snippet:

```python
import rich.live, rich.console
from rich.markdown import Markdown
console = rich.console.Console()
def stream_reply(chunks, live_window: int = 6):
    stable, buf = "", ""
    with rich.live.Live(console=console, refresh_per_second=20) as live:
        for ch in chunks:
            buf += ch
            *head, tail = buf.splitlines() or [""]
            stable, buf = "\n".join(head[:-live_window] + [""]), "\n".join(head[-live_window:])
            console.print(Markdown(stable), end=""); live.update(Markdown(buf))
        console.print(Markdown(buf))
```

Skip `textual` for v1 — overkill. Bring it in later if you need widgets/mouse.

### Must-have slash commands

| Category | Commands |
|---|---|
| **Session** | `/help`, `/clear`, `/exit`, `/resume [id]`, `/rename <name>`, `/fork` |
| **Model** | `/model [name]`, `/effort [low|med|high|max]` |
| **Context** | `/compact [hint]`, `/context`, `/tokens`, `/copy`, `/export` |
| **Files** | `/add <path>`, `/drop <path>`, `/read-only <path>`, `/ls` |
| **Modes** | `/plan`, `/ask` vs `/code`, `/architect` |
| **Approval** | `/permissions`, `/mcp`, `/sandbox` |
| **Self** | `/status`, `/cost`, `/doctor`, `/feedback`, `/debug` |
| **Config** | `/config`, `/theme`, `/init`, `/memory` |

### Session schema (JSON Schema draft)

Stored as `~/.local/share/forgewright/sessions/<uuid>.json` (XDG_STATE_HOME). One file per session; events appended; metadata header for fast listing. See full schema in [Appendix A](#appendix-a-session-schema).

### Interrupt + approval flow (state machine in prose)
States: `IDLE → STREAMING → AWAITING_APPROVAL → EXECUTING_TOOL → STREAMING → IDLE`.

- **IDLE:** prompt printed, waiting for Enter. Ctrl+C clears buffer, Ctrl+D exits.
- **STREAMING:** model tokens arrive. Ctrl+C sets `abort_flag`, cancels SSE, partial text preserved.
- **AWAITING_APPROVAL:** single-line prompt: `? Run `Bash(npm test)` [Y/n/a=always-allow-this-rule/A=allow-for-session/d=deny]`.
- **EXECUTING_TOOL:** same Ctrl+C semantics — SIGTERM + grace, persist partial output, return to IDLE.
- `Esc Esc` or `/stop` aborts the whole turn.
- Always-allow config: `[permissions.allow]` in project config, precedence managed > CLI > local > project > user (Claude Code model).

### TUI vs CLI decision
**Go CLI-with-bells, not full-TUI, for v1.** The spec says "no GUI, terminal + programmatic." A full-screen Textual app would break the pipe-friendly contract. Power users on headless boxes need every byte log-friendly. `rich.live.Live` + `prompt_toolkit.PromptSession` gives 95% of "TUI feel" while remaining a normal line-mode REPL.

### Three UX differentiators
1. **`/why <tool-call>` — rewind-and-explain.** Hotkey after any tool finishes; agent streams a one-paragraph "I did this because…" using the transcript as evidence. Pairs with a `--audit` flag.
2. **Native headless swarm mode.** `forgewright swarm plan.yaml` runs a plandex-style plan with branches, each a JSONL stream you can `tail -f | jq`. Checkpointed in SQLite, resumable.
3. **First-class headless Pi/SBC mode.** Auto-detect ARM/limited-RAM, default to a small model profile, surface a `--low-mem` flag, show `htop`-style live RSS in the status bar. None of the major CLIs are Pi-first.

**Sources:** [Claude Code docs](https://code.claude.com/docs), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Aider commands](https://aider.chat/docs/usage/commands.html), [Aider mdstream.py](https://github.com/Aider-AI/aider/blob/main/aider/mdstream.py), [Goose](https://github.com/block/goose), [Plandex](https://github.com/plandex-ai/plandex), [OpenHands CLI](https://github.com/All-Hands-AI/OpenHands-CLI), [Codex CLI](https://github.com/openai/codex), [Ink](https://github.com/vadimdemedes/ink).

---

## 5. Distribution & packaging

### Recommended stack
**uv + PyPI (OIDC trusted publishing) + Homebrew tap + multi-arch Docker.** Defer single-binary and apt until user demand proves it out.

`uv` is the 2026 default — replaces pip, pip-tools, pipx, poetry, pyenv, twine, virtualenv. Owns the full loop: `uv init → uv add → uv lock → uv sync → uv build → uv publish`. `uv tool install forgewright` mirrors `pipx` for free. `uv publish` supports PyPI trusted publishing (OIDC, no tokens) and PEP 740 attestations.

Aider's docs are the closest analogue: recommends `uv tool install --python python3.12 --with pip aider-chat@latest`, explicitly warns that system package managers "often install aider with incorrect dependencies." Treat that as a real warning.

### `pyproject.toml` template
See the [build plan's repo layout section](../BUILD_PLAN.md#2-repository-layout) for the full template. Key: `[project.scripts]` (not `gui-scripts`); `hatchling` build backend; `requires-python = ">=3.11,<3.14"`.

### CI matrix
- **ci.yml** — ruff + mypy + pytest, 3 OS × 3 Python (3.11/3.12/3.13), fail-fast off.
- **publish.yml** — triggered on tag `v*`, uses `pypa/gh-action-pypi-publish` with OIDC `id-token: write`.
- **docker.yml** — multi-arch buildx, push to `ghcr.io/forest/forgewright`.
- **homebrew.yml** — updates the tap formula on release.
- **security.yml** — gitleaks + trufflehog + pip-audit.

### Distribution matrix

| Channel | Supported | Install command | Maintenance |
|---|---|---|---|
| PyPI (uv/pipx) | **Yes (primary)** | `uv tool install forgewright` | Low — fully automated |
| Homebrew tap | **Yes** | `brew install forest/tap/forgewright` | Med — formula + bottle CI |
| Docker (multi-arch) | **Yes** | `docker run -it ghcr.io/forest/forgewright` | Low — single multi-stage Dockerfile |
| Standalone single binary | **Defer** | `curl -LsSf .../install.sh \| sh` | High — `pyapp` adds 30-80 MB; Playwright breaks bundling |
| apt (Debian/Ubuntu) | **No** | n/a | High — Aider warns against it |
| npm wrapper (`npx`) | **No** | n/a | Med — only worth it for JS dev audience |
| Scoop (Windows) | **Yes (v0.2)** | `scoop install forgewright` | Low — JSON manifest |

### Raspberry Pi / ARM64
`pydantic`, `litellm`, `fastmcp`, `altair`, and `httpx` all ship `manylinux aarch64` wheels. `playwright 1.60+` ships ARM64 wheels. `crawl4ai` is pure-Python. The risky part is Playwright's first-run browser binary download — bake it into the Docker image with `playwright install chromium`. Ship `linux/amd64,linux/arm64` Docker images, document the post-install step.

### Versioning: CalVer `YYYY.MM.PATCH`
Aider, Goose, and most of the fast-moving agent ecosystem use CalVer. SemVer is for libraries with API stability promises.

### First-run experience
Mirror `gh auth login` and `rustup`. On first invocation, `forgewright` detects no config, prints a one-line hint, and refuses to talk to a provider until keys are present. `forgewright init` runs an interactive wizard (Typer + Rich prompts): provider choice, API key (write to `~/.config/forgewright/credentials.toml` with `0600`), default model, MCP server list. Env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FORGEWRIGHT_TOKEN`) are read before disk so CI and headless servers work without prompts.

### Auto-update: defer to v0.2
`uv tool upgrade forgewright` and `brew upgrade` are 2-line upgrade paths. If users complain, add an opt-in `forgewright update` that shells out. `rustup self update` and `npm update -g` are the models.

### SBOM & supply chain
- `pip-audit --strict` in CI on every PR (PyPA-owned, Trail of Bits + Google supported).
- Sigstore/cosign signing of wheel and Docker image.
- PEP 740 in-toto attestations on PyPI.
- CycloneDX SBOM (`uv export --format cyclonedx1.5`) on each release.
- Target SLSA Build Level 2 — `provenance-gen` + hardened-runner.

### Three things NOT to do
1. Don't ship a PyInstaller single binary as the primary path. Bloats 80–200 MB, slow cold start, breaks Playwright/Crawl4AI.
2. Don't maintain apt/rpm/pacman packages yourself. Stale distros lag months; you'll burn cycles fixing distros. Homebrew core is the only system-PM channel worth submitting to.
3. Don't pin Python below 3.11 or above 3.13, and don't vendor dependencies. Pydantic v2, litellm, modern typing all want 3.11+.

**Sources:** [astral-sh/uv](https://github.com/astral-sh/uv), [uv docs](https://docs.astral.sh/uv/), [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/), [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish), [ofek/pyapp](https://github.com/ofek/pyapp), [pypa/cibuildwheel](https://github.com/pypa/cibuildwheel), [pip-audit](https://pypi.org/project/pip-audit/), [sigstore/cosign](https://github.com/sigstore/cosign), [Playwright PyPI](https://pypi.org/project/playwright/), [Aider install](https://aider.chat/docs/install.html), [Aider pyproject.toml](https://github.com/aider-ai/aider/blob/main/pyproject.toml), [Ruff installation](https://docs.astral.sh/ruff/installation/), [piwheels](https://www.piwheels.org/), [gh auth login](https://cli.github.com/manual/).

---

## 6. MCP integration

### Library decision
- **Server:** FastMCP 3.3.1 (standalone). Apache-2.0, Python-only, includes clients/servers/apps. FastMCP 1.0 was absorbed into the official SDK in 2024; standalone v3.x is the maintained successor. README claims "some version of FastMCP powers 70% of MCP servers."
- **Client:** official `mcp` Python SDK v1.x. `ClientSession` + `stdio_client(server_params)` for subprocess, `streamablehttp_client` for remote.

**Current spec version is `2025-06-18`.** Two normative transports: **stdio** and **Streamable HTTP**. SSE as standalone server transport is superseded. Use stdio for local subprocess, Streamable HTTP for network. SSE is acceptable only as the response-streaming mode of Streamable HTTP.

### Tool proxy pattern (remote MCP tool → local BaseTool)

```python
from typing import Any
from mcp import ClientSession, types as mcp_types
from forgewright.tool.base import BaseTool, ToolResult

class MCPToolProxy(BaseTool):
    def __init__(self, mcp_tool: mcp_types.Tool, session: ClientSession, server_id: str):
        self._mcp_tool = mcp_tool
        self._session = session
        self._server_id = server_id
        self.name = f"{server_id}__{mcp_tool.name}"   # namespace to defeat collisions
        self.description = mcp_tool.description or ""
        self.args_schema = mcp_tool.inputSchema

    async def _run(self, **kwargs: Any) -> ToolResult:
        async def _call(args: dict | None) -> mcp_types.CallToolResult:
            return await self._session.call_tool(self._mcp_tool.name, arguments=args or {})
        return await self._invoke_with_auth(_call, kwargs)
```

`name` is namespaced (`<serverId>__<toolName>`) to defeat tool-name collision attacks. `_invoke_with_auth` is the default-deny allowlist hook.

### MCP server skeleton (FastMCP + FastAPI)

```python
from fastapi import FastAPI
from fastmcp import FastMCP
from forgewright.tools import BashTool, FileEditorTool

mcp = FastMCP("forgewright-local", instructions="Local tools for forgewright.")
for tool in (BashTool(), FileEditorTool()):
    mcp.add_tool(tool.as_fastmcp_tool(), name=tool.name)

mcp_app = mcp.http_app(path="/")
api = FastAPI(lifespan=mcp_app.lifespan)
api.mount("/mcp", mcp_app)
# stdio: mcp.run(transport="stdio")
# network: uvicorn app:api --host 0.0.0.0 --port 8000
```

`lifespan` argument is required or the session manager fails on first request.

### Security checklist
1. Namespace every proxied tool (`<serverId>__<toolName>`).
2. Treat tool descriptions as untrusted input. Spec: "descriptions of tool behavior such as annotations should be considered untrusted, unless obtained from a trusted server."
3. Validate `inputSchema` server-side with `jsonschema`; reject non-conforming calls.
4. Default-deny allowlist at the BaseTool layer.
5. OAuth 2.1 with PKCE + `resource` parameter (RFC 8707) for every Streamable HTTP server. Reject tokens missing the `aud` claim.
6. No token passthrough — never forward a bearer token to a downstream API.
7. Elicitation & sampling require explicit user consent in the TUI.
8. Timeouts on every tool call (default 30s; configurable per-tool). Hung stdio servers must be SIGKILL'd.
9. Log structured `serverId`, `toolName`, `argsHash` (not raw args). Do not log secrets.
10. Pin MCP server versions; treat `notifications/tools/list_changed` as a re-authorization event.

### Five popular MCP servers to ship as one-click install
1. **Filesystem** (Anthropic, 252k visits/wk) — sandboxed local file ops.
2. **GitHub** (Anthropic, 106k) — PRs, issues, code search.
3. **PostgreSQL** (Anthropic, 140k) — read-only SQL.
4. **Fetch** (Anthropic, 181k) — HTML → markdown.
5. **Sequential Thinking** (MCP, 88.7k) — structured planning chain for sub-agents.

Discovery: `https://registry.modelcontextprotocol.io/v0/servers` (v0.1 frozen; v1 in dev). `forgewright mcp install <name>` resolves, downloads, writes to `~/.config/forgewright/mcp.json`.

### Testing patterns
- **Server in-process:** FastMCP `Client(transport=mcp)` → `await client.call_tool("bash", {"cmd": "echo hi"})`.
- **Client against mock server:** official SDK `Server` + `stdio_server` in a subprocess fixture.
- **OpenTelemetry:** `pip install opentelemetry-instrumentation-mcp`; `McpInstrumentor().instrument()`. Set `TRACELOOP_TRACE_CONTENT=false` in production.

### Sub-agent lifecycle
Share MCP **client sessions, not subprocesses**. One `ClientSession` per (server, transport) tuple. Sub-agents receive a reference; session lazy-initializes on first `list_tools`. On teardown, decrement refcount; kill subprocess only when count hits zero. Keeps the 11G RAM budget stable when several sub-agents run concurrently.

**Sources:** [MCP Architecture (2025-06-18)](https://modelcontextprotocol.io/docs/learn/architecture), [MCP Spec](https://modelcontextprotocol.io/specification/2025-06-18), [MCP Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization), [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk), [FastMCP v3](https://github.com/jlowin/fastmcp), [MCP Reference Servers](https://github.com/modelcontextprotocol/servers), [MCP Registry](https://github.com/modelcontextprotocol/registry), [mcpadapt](https://github.com/grll/mcpadapt), [opentelemetry-instrumentation-mcp](https://github.com/traceloop/openllmetry), [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents).

---

## 7. Security & sandboxing

### Default sandbox recommendation
**Layered sandbox; default to Docker with hard limits for untrusted Python.** Subprocess (5s timeout) gives CPU and time bounds but **no** memory, PID, FS, network, or syscall bounds — a single `numpy.empty(10**10)` from an LLM-written script OOMs the host. RestrictedPython is explicitly *not* a sandbox (its own docs say so). Pyodide is browser-shaped. PyPy's sandbox is deprecated.

Recommended Docker flags:

```yaml
mem_limit: 512m
pids_limit: 256
cpus: 1.0
read_only: true
tmpfs: { /tmp: "size=64m,noexec" }
cap_drop: [ALL]
security_opt: ["no-new-privileges:true", "seccomp=runtime/default"]
network_mode: "none"
user: "1000:1000"
ulimits: { nofile: { soft: 64, hard: 64 } }
```

For stronger isolation: gVisor (`runsc`) as default runtime; Firecracker for hostile multi-tenant. nsjail for self-hosted users who refuse Docker; bubblewrap for desktops on Linux.

### Dangerous-command denylist (top 20)

| # | Pattern | Regex |
|---|---|---|
| 1 | recursive force delete at root | `rm\s+(-[a-z]*f[a-z]*\s+)*-[a-z]*r[a-z]*\s+/\s*$` |
| 2 | recursive force delete home | `rm\s+-rf\s+(\~|\$HOME|/home|/workspace|/)` |
| 3 | format / wipe disk | `\b(mkfs\|wipefs\|dd\s+if=.*\s+of=/dev/)\b` |
| 4 | raw disk write | `dd\s+if=.+\s+of=/dev/(sd\|nvme\|hd\|vd\|xvd)` |
| 5 | shutdown / reboot | `\b(shutdown\|reboot\|halt\|poweroff\|init\s+0\|init\s+6)\b` |
| 6 | curl piped to shell | `(curl\|wget\|fetch).*\|\s*(sh\|bash\|zsh\|python\|perl\|ruby)\b` |
| 7 | sudo escalation | `\b(sudo\|doas\|pkexec)\b` |
| 8 | chmod 777 / chown recursive root | `chmod\s+(-R\s+)?777\b\|chown\s+-R\s+root` |
| 9 | disable firewall / SELinux | `\b(ufw\s+disable\|iptables\s+-F\|setenforce\s+0)\b` |
| 10 | history / credential dump | `\b(cat\|less\|head\|tail)\s+~?/?\.(bash_history\|ssh/id_\|netrc\|aws/credentials\|kube/config)\b` |
| 11 | git force-push to protected | `git\s+push.*(-f\|--force).*(origin\|upstream)\s+(main\|master\|prod)` |
| 12 | global install without lock | `(npm\s+-g\|pip\s+install).*--(no-deps\|pre)` |
| 13 | eval of remote payload | `\beval\s+"\$\(curl\|wget` |
| 14 | base64-decoded execution | `base64\s+-d.*\|\s*(sh\|bash\|python)` |
| 15 | network capture / sniffing | `\b(tcpdump\|wireshark\|nmap\|masscan)\b` |
| 16 | mount filesystem | `\bmount\s+(-\w+\s+)*/dev/` |
| 17 | cron / systemd persistence | `\b(crontab\s+-e\|systemctl\s+enable\|launchctl\s+load)\b` |
| 18 | container escape primitives | `nsenter\|unshare\s+(-m\|-u\|-p\|-n)\|chroot\s+/` |
| 19 | exfil over DNS / netcat | `\|\s*nc\s+.*\s+\d+\b` |
| 20 | kill -9 PID 1 | `kill\s+(-9\|-KILL)?\s*\b1\b` |

Pair the denylist with a small allowlist of safe builtins; reject everything else by default.

### Bash approval flow
Pre-parse → denylist check → hard-block on the 9 worst patterns → check trusted-tool cache → interactive Rich prompt (Y/n/a/A/d) → write decision to audit log. `forgewright trust <pattern> --scope=session|repo|machine` lifts commands into the allowlist. The cache is consulted *before* the prompt, never bypasses the audit log.

### Secret handling
Resolution precedence (highest wins, lowest leaked):
1. **OS keyring** via `keyring` (preferred, never written to disk).
2. **Environment variables** (read at startup, never logged, never serialized).
3. **`~/.config/forgewright/secrets.toml`** (chmod 0600, owner-only).
4. **`.forgewright.toml` in repo** — **forbidden for secrets**; lint rule blocks it.

LLM API keys are **never** logged, persisted, or echoed back. Pre-commit: `gitleaks` (Apache-2.0) with the standard rule pack. CI: `trufflehog` for diff scanning. Audit-log redaction layer (`secrets.Redact`) does Shannon-entropy + regex check before write.

### Audit log schema

```json
{
  "ts": "2026-06-02T10:42:13.481+10:00",
  "session_id": "01HXY...",
  "actor": {"type": "tool", "name": "Bash", "version": "0.1.0"},
  "user_consent": {"mode": "approve-each", "approver": "forest", "scope": "session"},
  "tool": "Bash",
  "args": {"cmd": "rm -rf ./build", "cwd": "/home/forest/proj", "timeout_s": 30},
  "env": {"container_id": "fw-9f3a", "sandbox": "docker:read-only"},
  "result": {"exit": 0, "stdout_sha256": "ab12...", "stderr_sha256": "cd34...", "duration_ms": 142},
  "redactions": ["ANTHROPIC_API_KEY", "GH_TOKEN"],
  "prev_hash": "f4e1...",
  "hash": "9c0a..."
}
```

Schema locked; logs written with `O_APPEND`; rotated nightly. `forgewright audit verify` recomputes the chain. `--format otel` for SIEM export.

### Threat model (STRIDE)

| Category | Threat | Mitigation |
|---|---|---|
| **S**poofing | MCP server pretends to be a trusted tool | Tool allowlist by canonical name; verify JSON-schema before invocation; pin server hashes |
| **T**ampering | Adversarial content in tool output poisons memory | Wrap every tool output in `agent-memory-guard` (OWASP ASI06) before appending |
| **R**epudiation | User denies running a destructive command | sha256-chained append-only audit log; signed checkpoints |
| **I**nformation disclosure | LLM API key leaks | Keyring-first secret resolution + redaction; pre-commit gitleaks |
| **D**enial of service | LLM-generated code OOMs or fork-bombs | Docker `mem_limit=512m`, `pids_limit=256`, `--network=none`, per-tool timeout |
| **E**levation of privilege | `rm -rf /`, `curl\|sh`, container escape | denylist + allowlist + plan mode; `--cap-drop=ALL`, `no-new-privileges` |

**In scope:** any code or text the LLM can influence. **Out of scope:** the user's terminal after `sudo forgewright run`; the host kernel; the LLM provider's training pipeline. **Assumptions:** Linux/macOS host, modern Docker, user reviews audit logs.

### Three security differentiators
1. **Default-deny with per-call approval that learns.** Out of the box, every shell command needs explicit user approval (one keystroke). The user builds the trust registry with `forgewright trust <pattern>`. No other open-source agent ships a coherent trust-elevation model.
2. **Tamper-evident audit log by default.** sha256-chained JSONL with a `forgewright audit verify` command.
3. **Layered sandbox: Docker → gVisor → Firecracker, chosen at install time.** A single `forgewright sandbox doctor` picks the strongest available primitive. Combined with OWASP Agent Memory Guard integration on every tool output, no other open-source framework ships comparable defense-in-depth out of the box.

**Sources:** [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/), [OWASP Agent Memory Guard](https://github.com/OWASP/www-project-agent-memory-guard), [smolagents #2290](https://github.com/huggingface/smolagents/issues/2290), [smolagents #2303](https://github.com/huggingface/smolagents/issues/2303), [smolagents #2305](https://github.com/huggingface/smolagents/issues/2305), [MCP Security and Trust & Safety](https://modelcontextprotocol.io/specification), [nsjail](https://github.com/google/nsjail), [bubblewrap](https://github.com/containers/bubblewrap), [gVisor](https://gvisor.dev/docs/), [Firecracker](https://firecracker-microvm.github.io/), [RestrictedPython](https://restrictedpython.readthedocs.io/en/latest/), [Docker Engine security](https://docs.docker.com/engine/security/), [E2B](https://e2b.dev/docs), [Daytona](https://www.daytona.io/docs), [Modal](https://modal.com/docs/guide/sandbox), [gitleaks](https://github.com/gitleaks/gitleaks).

---

## Appendix A — Session schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "session.v1.json",
  "type": "object",
  "required": ["id", "created_at", "model", "events"],
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "name": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" },
    "version": { "type": "integer", "const": 1 },
    "model": { "type": "string" },
    "provider": { "type": "string" },
    "cwd": { "type": "string" },
    "agent_md_paths": { "type": "array", "items": { "type": "string" } },
    "permission_mode": { "enum": ["default","acceptEdits","plan","auto","dontAsk","bypass"] },
    "totals": {
      "type": "object",
      "properties": {
        "input_tokens": {"type": "integer"},
        "output_tokens": {"type": "integer"},
        "cache_read_tokens": {"type": "integer"},
        "cache_write_tokens": {"type": "integer"},
        "cost_usd": {"type": "number"},
        "turns": {"type": "integer"}
      }
    },
    "events": {
      "type": "array",
      "items": {
        "oneOf": [
          { "type": "object", "required": ["type","ts"], "properties": { "type": {"const":"user"}, "ts": {"type":"string","format":"date-time"}, "content": {"type":"string"} } },
          { "type": "object", "required": ["type","ts"], "properties": { "type": {"const":"assistant"}, "ts": {"type":"string","format":"date-time"}, "content": {"type":"string"}, "tool_calls": {"type":"array"} } },
          { "type": "object", "required": ["type","ts","tool","status"], "properties": { "type": {"const":"tool"}, "ts": {"type":"string","format":"date-time"}, "tool": {"type":"string"}, "input": {"type":"object"}, "output": {"type":"string"}, "status": {"enum":["ok","error","denied","aborted"]} } },
          { "type": "object", "required": ["type","ts","mode"], "properties": { "type": {"const":"approval"}, "ts": {"type":"string","format":"date-time"}, "mode": {"enum":["prompted","auto","hook","deny"]}, "rule": {"type":"string"} } },
          { "type": "object", "required": ["type","ts"], "properties": { "type": {"const":"interrupt"}, "ts": {"type":"string","format":"date-time"}, "by": {"enum":["ctrl_c","ctrl_d","user_command"]} } }
        ]
      }
    }
  }
}
```

---

*Compiled 2026-06-02 from seven parallel research agents. All citations in-line. See `BUILD_PLAN.md` for the actionable plan that uses this research.*
