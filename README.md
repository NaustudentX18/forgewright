<p align="center">
  <img src="docs/logo-mark-512.png" alt="forgewright" width="180">
</p>

<h1 align="center">forgewright</h1>

<p align="center"><strong>The open-source, CLI-first AI agent framework for builders who'd rather own their stack than rent someone else's.</strong></p>

<p align="center">
  <a href="forgewright/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="https://pypi.org/project/forgewright/"><img src="https://img.shields.io/pypi/v/forgewright.svg" alt="PyPI"></a>
  <a href="https://github.com/NaustudentX18/forgewright/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/NaustudentX18/forgewright/ci.yml?branch=master" alt="CI"></a>
  <a href="https://calver.org/"><img src="https://img.shields.io/badge/calver-YYYY.MM.PATCH-orange.svg" alt="CalVer"></a>
</p>

---

## Install

```bash
# uv (recommended)
uv tool install forgewright
```

```bash
# pipx
pipx install forgewright
```

```bash
# brew
brew install forest/tap/forgewright
```

That's the whole pitch. One command, one binary, no SaaS signup. If you want
optional extras (browser, sandbox, viz, web, tui), see
[`docs/INSTALL.md`](forgewright/docs/INSTALL.md).

---

## What it does

**forgewright** is a command-line AI agent framework. Give it a task — "add
JWT auth to the /api routes", "audit this repo for CVEs", "summarize the
files in ./src" — and it plans the work, picks the right tools, runs them in a
sandbox, and reports back. Multi-step. Streaming. Verifiable.

Bring your own keys. **Anthropic, OpenAI, Google, Azure, AWS Bedrock,
Ollama, or OpenRouter** through LiteLLM. Secrets resolve from the OS keyring,
then env vars, then a chmod-0600 `secrets.toml` — never logged, never echoed.
Sandboxing is **default-deny** with a 20-pattern dangerous-command denylist,
per-call approval, and four pluggable backends (`subprocess` → `docker` →
`gvisor` → `firecracker`). Every tool call, every approval, every secret
redaction lands in a **sha256-chained JSONL audit log** that you can verify
with `forgewright audit verify`. No telemetry. No token markup. No pro tier.

It's the open-source answer to **Manus AI** and **Lovable** for developers
who want the agent on *their* machine, using *their* keys, doing *their*
bidding.

---

## Quickstart

```bash
forgewright init                          # bootstrap config
$EDITOR ~/.config/forgewright/config.toml # add your keys
forgewright build "summarize ./src"       # run a task
forgewright audit verify                  # verify the audit chain
```

The 5-minute tour lives in
[`docs/QUICKSTART.md`](forgewright/docs/QUICKSTART.md). The
[`docs/recipes/`](forgewright/docs/recipes/) directory has copy-pasteable
end-to-end examples — refactor a module, audit for CVEs, build a dashboard,
wire an agent to Postgres.

> TUI + PWA screenshots coming with v0.2.1. For now, `forgewright --help`
> is the prettiest screenshot we've got.

---

## Why forgewright?

| | forgewright | Manus AI | Lovable | OpenHands | smolagents | crewAI |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| **Open source (MIT)** | yes | — | — | yes | yes | yes |
| **CLI-first, pipe-friendly** | yes | — | — | partial | — | — |
| **BYO keys, no markup** | yes | — | — | yes | yes | yes |
| **Default-deny sandbox** | yes | — | — | — | — | — |
| **Tamper-evident audit log** | yes | — | — | — | — | — |
| **Per-call approval that learns** | yes | — | — | — | — | — |
| **MCP client *and* server** | yes | — | — | client | — | — |
| **Works on a Raspberry Pi** | yes | — | — | yes | yes | yes |
| **Resumable sessions** | yes | — | — | yes | — | — |
| **CalVer, signed releases** | yes | n/a | n/a | yes | yes | yes |

The cloud-locked competitors are fine for demos. They're a bad bet for the
thing you're actually building. forgewright assumes you want the agent on
your box, your CI, your customer's VPC.

---

## Feature highlights

- **8 tools out of the box** — `Bash`, `StrReplaceEditor`, `PythonExecute`,
  `WebSearch`, `Browser` (Playwright), `Crawl4AI`, `AskHuman`, `Terminate`.
  All namespaced, versioned, and registered in a single `ToolCollection`.
- **7 LLM providers, one config field.** Switch with `provider = "..."`.
  Stub backend for tests and offline demos.
- **Layered agents.** `BaseAgent` → `ReActAgent` → `ToolCallAgent` →
  `Manus` (general-purpose), plus `DataAnalysis`, `BrowserAgent`, and
  `MCPAgent` sub-agents. Each layer adds capability without bolting on
  hacks.
- **MCP, both ways.** Ship a server exposing your tools to other agents;
  consume any registry server (`filesystem`, `github`, `postgres`, …) as
  if it were local. `forgewright mcp install <name>` one-shots a popular
  server from the registry.
- **Sandbox ladder.** `subprocess` for speed, `docker` for isolation
  (mem/CPU/PID/network limits, `read_only`, `cap_drop=ALL`), `gvisor` and
  `firecracker` when installed. `forgewright sandbox doctor` picks the
  strongest one available.
- **TUI + PWA.** `forgewright` opens a `textual` REPL with slash commands,
  sessions, and a cost tracker. `forgewright web` ships a FastAPI chat
  with SSE streaming that installs as a home-screen app on iOS and
  Android — offline shell, native install card, the lot.
- **Pi-friendly.** Built and tested on a Raspberry Pi 5 (Pironman / Naspi).
  No cloud account, no telemetry, no compile-from-source on ARM64.

---

## Architecture

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  LLM layer   │────▶│  Agent stack │────▶│ ToolCollect. │
│  (LiteLLM,   │     │ Base→ReAct→  │     │ Bash, Edit,  │
│   7 provs +  │     │ ToolCall→    │     │ Python, Web, │
│   Stub)      │     │ Manus+subs   │     │ Browser, MCP │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                                          ┌─────▼─────┐
                                          │  Sandbox  │
                                          │ sub→docker│
                                          │ →gvisor→  │
                                          │ firecracker│
                                          └─────┬─────┘
                                                │
                                          ┌─────▼─────┐
                                          │   State   │
                                          │ JSONL aud.│
                                          │ + sessions│
                                          │ + cost    │
                                          └───────────┘
```

Full deep-dive, with the Mermaid diagram and module-by-module walkthrough,
lives in [`docs/ARCHITECTURE.md`](forgewright/docs/ARCHITECTURE.md). The
rationale for the design is in
[`docs/RESEARCH.md`](forgewright/docs/RESEARCH.md); the build plan that
took us from zero to v0.1 is in [`BUILD_PLAN.md`](forgewright/BUILD_PLAN.md).

---

## Documentation

| | |
|---|---|
| Quickstart | [`docs/QUICKSTART.md`](forgewright/docs/QUICKSTART.md) |
| Install | [`docs/INSTALL.md`](forgewright/docs/INSTALL.md) |
| Architecture | [`docs/ARCHITECTURE.md`](forgewright/docs/ARCHITECTURE.md) |
| Recipes | [`docs/recipes/`](forgewright/docs/recipes/) |
| Mobile / PWA | [`docs/MOBILE.md`](forgewright/docs/MOBILE.md) |
| Security | [`SECURITY.md`](forgewright/SECURITY.md) |
| Roadmap | [`ROADMAP.md`](forgewright/ROADMAP.md) |
| Changelog | [`CHANGELOG.md`](forgewright/CHANGELOG.md) |

The deep reference — install matrix, all CLI commands, every config knob,
the full feature list, the BYOK provider table, the MCP extension section,
and the long Acknowledgments — is in the
[`forgewright/README.md`](forgewright/README.md) of this repo. This file is
the landing page; that one is the manual.

---

## Contributing

We welcome PRs. Open a discussion first if the change is non-trivial — the
project is moving fast and we'd rather steer than revert.

- [`CONTRIBUTING.md`](forgewright/CONTRIBUTING.md) — style, commit format,
  the PR template, and the test/lint/type gates.
- [`CODE_OF_CONDUCT.md`](forgewright/CODE_OF_CONDUCT.md) — the short,
  serious version.
- **GitHub Discussions** — open soon, for "is this a good idea" threads
  and recipe sharing.

Looking for first-issue-friendly work? The current wants are: Playwright
tooling, FastMCP integrations, the planning flow, ARM64 build verification,
and more [`docs/recipes/`](forgewright/docs/recipes/).

---

## License

MIT. See [`LICENSE`](forgewright/LICENSE). Docs in `docs/` are dual-licensed
under CC-BY-4.0. Cite v0.1.0 with [`CITATION.cff`](forgewright/CITATION.cff).

forgewright stands on the shoulders of giants — with gratitude to
**[LiteLLM](https://github.com/BerriAI/litellm)** (one interface to every
LLM), **[Pydantic](https://docs.pydantic.dev/)** (config that doesn't lie),
**[Rich](https://github.com/Textualize/rich)** (terminals that feel like
terminals), **[FastAPI](https://fastapi.tiangolo.com/)** (the web chat
that streams), and **[Textual](https://textual.textualize.io/)** (the TUI
that doesn't suck). The full acknowledgment list — OpenHands, OpenManus,
smolagents, crewAI, Playwright, Sigstore, Astral, and the rest of the
ecosystem — is in the [deep README](forgewright/README.md#acknowledgments).

---

<p align="center"><i>Forge agents. Wright code. In your terminal, with your keys.</i></p>
<p align="center">
  <a href="https://github.com/NaustudentX18/forgewright"><img src="https://img.shields.io/github/stars/NaustudentX18/forgewright?style=social" alt="GitHub stars"></a>
</p>
