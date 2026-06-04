# forgewright — agent notes

## Cursor Cloud specific instructions

### Repository layout

All application code lives under `forgewright/`. Run commands from that directory unless noted otherwise.

### Dependency refresh (automatic)

The VM update script runs `uv sync --all-extras` inside `forgewright/`. See `forgewright/CONTRIBUTING.md` for the canonical dev setup.

### Lint, typecheck, and tests

From `forgewright/`:

| Check | Command |
|-------|---------|
| Lint | `uv run ruff check .` |
| Types | `uv run mypy src` |
| Tests | `uv run pytest -q` |

Unit tests use the **stub** LLM and need no API keys or Docker. Expect ~740 tests with one skip.

**Note:** At the pinned commit, `ruff check` and `mypy src` may report pre-existing issues in the tree; CI still runs them. `pytest -q` is the reliable green gate for environment verification.

### Running the CLI (no external services)

```bash
cd forgewright
FORGEWRIGHT_AUTO_APPROVE=1 uv run forgewright build "your prompt" --provider stub --model stub-model
```

Other useful commands: `uv run forgewright --help`, `uv run forgewright sandbox doctor`, `uv run forgewright audit verify`.

### Running the web chat

Requires the `[web]` extra (included in `--all-extras`):

```bash
cd forgewright
FORGEWRIGHT_LLM__PROVIDER=stub FORGEWRIGHT_LLM__MODEL=stub-model uv run forgewright web --port 8787 --host 127.0.0.1
```

- UI: `http://127.0.0.1:8787/`
- Create session: `POST /api/sessions` with `{}`
- Chat (SSE): `POST /api/sessions/{id}/messages` with `{"content":"..."}`

Use a tmux session for long-running `forgewright web` (see cloud agent tmux conventions).

### Optional tooling (not in update script)

- **Browser tool:** `uv run playwright install chromium` (large download; only needed for Browser-agent E2E).
- **Docker sandbox / Postgres recipes:** Docker daemon on the host; `sandbox doctor` shows docker as unavailable without it.
- **Real LLM E2E:** Configure `~/.config/forgewright/config.toml` or env vars (`FORGEWRIGHT_LLM__PROVIDER`, API keys). Ollama on port 11434 is documented in `forgewright/docs/MANUS-CLONE-STATUS.md`.

### Pre-commit

`uv run pre-commit install` then `uv run pre-commit run --all-files` — see `forgewright/CONTRIBUTING.md`.
