---
name: Pull request
about: Submit a change to forgewright
title: ""
labels: []
assignees: []
---

<!--
  Thanks for taking the time to send a PR. The checklist below is here
  to help both of us — if any item is "no", leave a one-line
  explanation so the reviewer can decide whether to push through or
  ask for a change.
-->

## What

<!-- One or two sentences: what changed. -->

## Why

<!-- Link the issue or discussion. If there isn't one, say why not. -->

## How to test

<!-- Commands, prompts, or a recipe that the reviewer can copy-paste.
     A 5-line reproducer is worth a 50-line essay. -->

```bash
# 1.
# 2.
# 3.
```

## Checklist

<!-- Tick the boxes that apply. "n/a" with a one-liner is fine for
     any that don't. -->

- [ ] Tests added for new code (or "no behaviour change")
- [ ] Docs updated (`README.md`, `CHANGELOG.md`, or `docs/`)
- [ ] `uv run ruff check .` is clean
- [ ] `uv run mypy src` is clean
- [ ] `uv run pytest -q` passes locally
- [ ] Public-API changes are noted in `CHANGELOG.md` under `## [Unreleased]`
- [ ] Breaking changes are called out with a **BREAKING** marker in the
      commit message and a migration note in `CHANGELOG.md`
- [ ] No new dependencies without justification in the PR body
- [ ] No telemetry, no network calls outside the configured LLM
      provider, no new filesystem writes outside the working dir
      (unless explicitly intended)

## Screenshots / recordings

<!--
  For UI / REPL / streaming changes, an asciinema recording or a
  terminal screenshot is the fastest way to convey the change. Drop
  the file in this PR's comments, or paste a link.
-->

## Related issues / PRs

<!-- Closes #…  Fixes #…  Relates to #… -->

## Risks & rollback

<!--
  For non-trivial changes: what could go wrong, how would we notice,
  and how do we revert? For a tool addition, this is usually "merge
  forward"; for a sandbox / security change, this needs a real
  answer.
-->

## Notes for the reviewer

<!-- Anything you want flagged — a question, a doubt, an alternative
     you considered. -->
