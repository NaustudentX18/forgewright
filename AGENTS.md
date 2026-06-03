# AGENTS.md

## Cursor Cloud specific instructions

### Repository layout

The git root is `/workspace`. The application lives in **`/workspace/forgewright`** (Python package `forgewright`, CLI-first AI agent framework). All dev commands below assume `cd /workspace/forgewright` first.

### Toolchain

- **Python:** 3.11–3.13 (CI matrix); dev env uses **3.12** via `uv python install 3.12`.
- **Package manager:** [uv](https://docs.astral.sh/uv/). Ensure `~/.local/bin` is on `PATH` (`source "$HOME/.local/bin/env"` in bash).
- **Node:** optional; only needed for MCP servers installed via `npx` (e.g. Postgres recipe).

### Dependency refresh (automatic)

The VM update script runs `uv sync --locked --all-extras` inside `forgewright/`. After it runs, use `uv run …` from that directory (activates `.venv` automatically).

### Lint, typecheck, tests

Match CI (see `forgewright/.github/workflows/ci.yml` and `forgewright/CONTRIBUTING.md`):

```bash
cd /workspace/forgewright
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

Default `pytest -q` uses the **stub LLM** and mocks; no API keys or Docker required. One test may be skipped (browser integration).

**Note:** As of setup verification, `ruff check` and `mypy src` can report pre-existing issues in the tree while `pytest -q` still passes (~739 tests). Fix lint/mypy only when your task requires it.

### Running the product

| Goal | Command |
|------|---------|
| CLI agent (offline) | `uv run forgewright build "<prompt>" --provider stub --max-steps 3` |
| Sandbox diagnostics | `uv run forgewright sandbox doctor` |
| Web chat UI | `uv run forgewright web --port 8787` → http://127.0.0.1:8787 |
| Web health | `curl http://127.0.0.1:8787/api/health` |

Start long-running servers in **tmux** (e.g. session `forgewright-web`), not as detached one-shot background shells.

### Services (what to run when)

| Service | Required for | Port |
|---------|----------------|------|
| forgewright process only | Unit tests, stub CLI/web | — |
| Real LLM (env / `~/.config/forgewright/config.toml`) | Real agent behavior | provider HTTPS |
| Docker | Docker sandbox, `PythonExecute` in containers | socket |
| Ollama | Local LLM | 11434 |
| Playwright Chromium | Browser tool E2E | `uv run playwright install chromium` |

For cloud-agent smoke tests, **stub provider** is enough to prove CLI + web + agent loop.

### Config

- `forgewright init` writes `~/.config/forgewright/config.toml` (defaults to stub).
- Override via `--provider` / `--model` or env vars documented in `forgewright/config.toml.example`.

### Pre-commit (optional locally)

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Hooks: ruff format/check, mypy, gitleaks (see `forgewright/.pre-commit-config.yaml`).
