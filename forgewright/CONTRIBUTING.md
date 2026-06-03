# Contributing to forgewright

> **forgewright** is an open-source project and we welcome contributions of all kinds: code, docs, recipes, bug reports, feature discussions, and security reviews. This guide covers the practical "how to get a PR merged" path.

---

## Code of conduct

This project follows the [Contributor Covenant](./CODE_OF_CONDUCT.md). By participating, you agree to its terms. Be kind, be patient, assume good faith.

---

## Quick start

```bash
# 1. Fork and clone
git clone https://github.com/<you>/forgewright
cd forgewright

# 2. Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Set up the dev environment
uv sync --all-extras
uv run playwright install chromium

# 4. Verify everything works
uv run ruff check .
uv run mypy src
uv run pytest -q
```

You should see green on all three. If not, see the troubleshooting section below.

---

## Project layout

```
src/forgewright/
├── agent/        # BaseAgent, ReActAgent, ToolCallAgent, Manus, sub-agents
├── tool/         # BaseTool, ToolCollection, 8 concrete tools
├── llm/          # LLM Protocol, LiteLLM backend, stub backend
├── mcp/          # MCP client (proxy) and server (FastMCP)
├── flow/         # PlanningFlow, PlanningTool
├── sandbox/      # Sandbox Protocol, 4 backends
├── security/     # denylist, approval, secrets, audit
├── cli/          # typer subcommands
├── config.py     # pydantic-settings
├── schema.py     # Pydantic models
├── memory.py     # bounded deque + LoopGuard
└── logger.py     # loguru setup

tests/
├── unit/         # mirrors src/ tree, fast
└── integration/  # slower, exercises real LLM / MCP / Docker

docs/
├── ARCHITECTURE.md
├── RESEARCH.md
├── SECURITY.md
└── recipes/
```

---

## Development workflow

### 1. Pick something to work on

- **Good first issues** are tagged [`good first issue`](https://github.com/forest/forgewright/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
- **Help wanted** is tagged [`help wanted`](https://github.com/forest/forgewright/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22).
- **Discussions** are a good place to float ideas before opening a PR.

For larger changes, **open a discussion first**. We'd rather align on the approach than rework a 2,000-line PR.

### 2. Branch and commit

```bash
git checkout -b feat/my-tool
# make changes
git add src/forgewright/tool/my_tool.py tests/unit/tool/test_my_tool.py
git commit -m "feat(tool): add my_tool for X"
```

We follow [Conventional Commits](https://www.conventionalcommits.org/). The type prefix is required:

| Prefix | Use for |
|---|---|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Docs only |
| `refactor:` | No behavior change |
| `test:` | Add or fix tests |
| `chore:` | Build, CI, deps |
| `perf:` | Performance |
| `security:` | Security fix |

The scope is the layer (`agent`, `tool`, `mcp`, `llm`, `cli`, `sandbox`, `security`).

### 3. Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

The hooks run `ruff format`, `ruff check`, `mypy`, `gitleaks`, and a few `forgewright`-specific lint rules. They'll fail the CI if skipped.

### 4. Tests

```bash
# Fast unit tests
uv run pytest tests/unit -q

# Integration tests (slower, may hit network)
uv run pytest tests/integration -q

# With coverage
uv run pytest --cov=forgewright --cov-report=term-missing
```

Every PR must:

- Add tests for new code.
- Keep or improve coverage (target 80%+ for `src/forgewright/agent/`, `tool/`, `llm/`, `mcp/`).
- Pass the existing tests.

The integration suite is opt-in for PRs but required for `main`. Mark integration tests with `@pytest.mark.integration` and they'll run nightly + on merge.

### 5. Open the PR

Use the [PR template](./.github/PULL_REQUEST_TEMPLATE.md). Include:

- **What** changed (one or two sentences).
- **Why** the change is needed (link an issue or discussion).
- **How** to test it (commands, screenshots, or a recorded `forgewright` run).
- **Risks** and rollback plan (if non-trivial).

The CI matrix runs ruff + mypy + pytest on 3 OS × 3 Python versions. A green check on all of them is required to merge.

---

## Code style

### Python

- **Target:** 3.11, 3.12, 3.13. Don't use 3.10-only or 3.14-only syntax.
- **Formatter:** `ruff format` (the project's `line-length = 100`).
- **Linter:** `ruff check` (E, F, W, I, B, UP, SIM, RUF rules).
- **Type checker:** `mypy --strict` on `src/forgewright/`.
- **Docstrings:** Google style. One-line summary + extended description for public functions.
- **Comments:** Default to writing none. Add a comment only when the *why* is non-obvious.

### Pydantic

- `model_config = ConfigDict(extra="forbid")` on every model. We want to catch provider drift.
- `Field(min_length=..., max_length=..., description=...)` for user-facing fields.
- `model_validator(mode="after")` for cross-field invariants, not `@validator`.
- Never share mutable instances across threads. Use `model_copy(update=...)`.

### Async

- The agent loop is `asyncio`. Don't introduce sync I/O in the hot path.
- For sync tools, use `asyncio.to_thread(...)` (not `loop.run_in_executor`, which is older and less ergonomic).
- For concurrent tool calls, use `asyncio.gather(*[tool(arg) for arg in args], return_exceptions=True)`.

### Logging

- `from loguru import logger` and use the `logger` directly. No `getLogger(__name__)`.
- `logger.bind(session_id=..., tool=...)` for context.
- `logger.opt(exception=True).error(...)` for exception traceback capture.
- Never `print()`. Use `console.print()` from `rich` if you must write to stdout.

---

## Documentation

- **Public API** — every public function, class, and module has a docstring. CI fails on `interrogate --fail-under=80`.
- **Architecture decisions** — significant changes get a short ADR in `docs/adr/`. Use Michael Nygard's template.
- **Recipes** — for new use-cases, add a `docs/recipes/<use-case>.md` following the existing format.
- **README** — keep the comparison table current. If you add a feature, add a row.

---

## Recipes

Recipes are the easiest contribution and the most visible. To add a recipe:

1. Create `docs/recipes/<your-recipe>.md` following the [refactor recipe](./docs/recipes/refactor.md) as a template.
2. The five required sections: **Setup · Prompt · What you'll see · The result · Audit log**. Optional: **Variations · Why it's a good showcase**.
3. Keep the demo realistic — real tool calls, real output, real numbers. No "… (output elided)".
4. Add a one-line entry in the [README's Recipes section](./README.md#recipes).

If your recipe shows off a feature, end with a "Why this recipe is a good showcase" section. We use those when writing release notes.

---

## Reporting bugs

Open a [GitHub issue](https://github.com/forest/forgewright/issues/new?template=bug_report.md) with:

- The version (`forgewright --version` or `git rev-parse HEAD`).
- The OS and Python version.
- The exact command you ran.
- The exact output (or a screenshot for the REPL).
- A minimal reproducer (a tiny `pyproject.toml` + a prompt is ideal).

For security bugs, see [SECURITY.md](./SECURITY.md) — **do not** open a public issue.

---

## Feature requests

Open a [GitHub discussion](https://github.com/forest/forgewright/discussions/new?category=ideas) first, not an issue. We use discussions to align on the approach before opening a tracking issue.

A good feature request explains:

- The problem you're trying to solve.
- The user story ("as a developer running forgewright on a Pi, I want …").
- The alternatives you considered.
- Whether you're willing to send a PR.

---

## Reviewing PRs

Anyone can review. We use a "two-approvers" rule for `main`:

- The author cannot be a reviewer.
- At least one approval from a maintainer.
- At least one approval from someone who has *run* the change locally (not just read the diff).

Reviews should be specific and actionable. "I would do this differently" without a suggestion is a discussion, not a review.

---

## Release process

Releases are cut from `main` by a maintainer. The high-level loop is:

- **Bump the version** in `src/forgewright/__init__.py` *and* `pyproject.toml`
  (both must agree). Use the next `0.X.Y` SemVer for compatibility-breaking
  changes; CalVer `YYYY.MM.PATCH` for routine releases.
- **Update `CHANGELOG.md`.** Move everything under `## [Unreleased]` into a
  new `## [0.2.0] - YYYY-MM-DD` (or appropriate version) section, leave a
  fresh empty `## [Unreleased]` stub at the top.
- **Commit and tag** with the format `v0.X.Y` (or `vYYYY.MM.PATCH` for CalVer
  releases), e.g. `git tag -s v0.2.0 -m "Release 0.2.0"`.
- **Push the tag.** GitHub Actions (`.github/workflows/release.yml`) handles
  the rest: it builds the multi-arch wheel, publishes to PyPI via OIDC,
  builds and pushes the Docker image, updates the Homebrew tap, signs
  everything with Sigstore/cosign, generates the CycloneDX SBOM, and posts
  the GitHub release with release notes.
- **Verify the pipeline ran cleanly.** Confirm the GitHub release appeared,
  the PyPI upload succeeded (the `twine check` step), the Docker push to
  `ghcr.io/forest/forgewright` finished, and the Homebrew tap PR was merged.
  Re-run any failed step manually before announcing.
- **Announce.** Post a short note in `#releases` on
  [Discord](https://discord.gg/forgewright) and, if the release is notable,
  on the relevant subreddits (r/LocalLLaMA, r/MachineLearning,
  r/opensource).

A release is blocked until the following are all green:

- The full CI matrix (lint, types, unit, integration).
- `pip-audit --strict` reports no unfixed vulnerabilities.
- `forgewright audit verify` confirms a clean audit chain on `main`.
- At least one maintainer signs off in the tracking discussion / PR.

For the day-to-day checklist, hotfixes, and rollback procedure see
[`docs/RELEASE.md`](./docs/RELEASE.md).

---

## Distribution

Each release ships to four channels. **Maintainers do not run these
manually** — they are triggered by the `release.yml` workflow on tag push —
but it helps to know how each one works in case you need to debug a failure
or unblock a pipeline.

- **PyPI** — Built as a binary wheel and sdist by
  [`cibuildwheel`](https://cibuildwheel.readthedocs.io/) on
  `linux/amd64`, `linux/arm64`, `macos x86_64`, and `macos arm64`. Uploaded
  via [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
  (OIDC) — no long-lived API token, no manual `twine upload`. The
  `publish-pypi` job is the source of truth; if it fails, the whole release
  is held.
- **Docker** — `Dockerfile` is a multi-stage build: a `python:3.12-slim`
  builder installs the package and Playwright Chromium, and a slim runtime
  layer copies the venv. Pushed as a multi-arch manifest
  (`ghcr.io/forest/forgewright:VERSION` plus `:latest` and `:v0.X.Y`).
  Signing: `cosign sign --yes ghcr.io/forest/forgewright@sha256:...` runs
  in the same job.
- **Homebrew** — A separate repo, [`forest/homebrew-tap`](https://github.com/forest/homebrew-tap),
  holds the `forgewright.rb` formula. The `homebrew-tap-bump` workflow opens
  a PR with the new `url` and `sha256` on every release tag; merging the PR
  publishes the bump. The tap PR is opened automatically — if it doesn't
  appear, check the `homebrew-tap-bump` job's logs first.
- **Scoop (Windows)** — Targeted for v0.2. The manifest lives in
  `packaging/scoop/forgewright.json`; the v0.2 release will add a CI job to
  submit the manifest to
  [ScoopEx](https://github.com/ScoopInstaller/Extras).

To verify a release end-to-end (typically the maintainer who cut the
release does this):

```bash
# 1. PyPI is reachable
pip download forgewright==0.1.0 --no-deps --dest /tmp/fw-check
python -m zipfile -e /tmp/fw-check/forgewright-0.1.0-py3-none-any.whl /tmp/fw-check/wheel
test -f /tmp/fw-check/wheel/forgewright-0.1.0.dist-info/RECORD

# 2. Docker image runs
docker run --rm ghcr.io/forest/forgewright:0.1.0 --version

# 3. Homebrew bottle resolves
brew install forest/tap/forgewright
forgewright --version

# 4. Cosign signatures are valid
cosign verify ghcr.io/forest/forgewright:0.1.0 \
  --certificate-identity-regexp 'https://github.com/forest/forgewright' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com'
```

If any of those fail, follow the rollback procedure in
[`docs/RELEASE.md`](./docs/RELEASE.md#rollback) before announcing.

---

## Community

- **Discord:** [discord.gg/forgewright](https://discord.gg/forgewright) — for help, design chat, and pairing.
- **GitHub Discussions:** for feature requests, design proposals, and "how do I" questions.
- **GitHub Issues:** for actionable bugs and tracked work.
- **X/Twitter:** [@forgewright](https://twitter.com/forgewright) (TBD) — release announcements only.

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE). The documentation is CC-BY-4.0 — see [docs/LICENSE](./docs/LICENSE).

---

## A note on scope

forgewright is deliberately small in v0.1. We will say "no" to features that:

- Require a SaaS component (telemetry, hosted UI, account system).
- Couple tightly to a single LLM provider.
- Bloat the dependency footprint for marginal capability.
- Add a feature flag matrix that the user has to learn.

If your PR falls into one of these buckets, expect a discussion. The reasoning is in [ARCHITECTURE.md §1](./ARCHITECTURE.md#1-design-principles) and [README §"Philosophy"](./README.md#philosophy).

---

Thanks for reading. Thanks even more for sending a PR.
