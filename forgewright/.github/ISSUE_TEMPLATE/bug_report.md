---
name: Bug report
about: Report something that is broken, wrong, or surprising
title: "[bug] "
labels: ["bug", "needs-triage"]
assignees: []
---

> **Security issues are not bugs.** If you found a vulnerability, please
> follow [`SECURITY.md`](../../SECURITY.md) and email
> **security@forgewright.dev** or open a
> [private security advisory](https://github.com/forest/forgewright/security/advisories/new).
> Do not file a public issue.

<!--
  Please fill in every section below. "N/A" is fine for sections that
  don't apply, but blank sections slow triage. Thanks!
-->

## Summary

<!-- One sentence: what broke, and what you were trying to do. -->

## Environment

- **forgewright version:** <!-- output of `forgewright --version` or `git rev-parse HEAD` -->
- **OS:** <!-- e.g. Ubuntu 24.04, macOS 15.4, Windows 11 -->
- **Python version:** <!-- output of `python --version` -->
- **Install method:** <!-- uv / pipx / Homebrew / Docker / from source -->
- **LLM provider & model:** <!-- e.g. anthropic / claude-sonnet-4-6 -->
- **Sandbox backend:** <!-- subprocess / docker / gvisor / firecracker; `forgewright sandbox doctor` -->
- **MCP servers in use:** <!-- from `forgewright mcp ls`, or "none" -->

## Steps to reproduce

<!-- The smallest possible set of steps that triggers the bug. Include the
     exact prompt / command / config snippet. A 5-line reproducer is worth
     a 50-line essay. -->

1.
2.
3.

## Expected behaviour

<!-- What you expected to happen. -->

## Actual behaviour

<!-- What actually happened. Include the full error message, the stack
     trace, and a screenshot or copy-paste of the relevant output. -->

## Logs

<!--
  If you have logs, paste them here. Otherwise, run with
  `forgewright --log-level DEBUG …` and re-run, then paste the relevant
  block. Trim aggressively; we don't need the full transcript.
-->

```text
PASTE LOGS HERE
```

## Audit log excerpt

<!--
  forgewright writes a sha256-chained audit log. The path is printed
  at the end of every run, and you can pretty-print the last few
  events with `forgewright audit tail -n 5`.
-->

```json
PASTE EVENTS HERE
```

## Possible cause

<!-- Optional. If you have a guess at the root cause, or a pointer to the
     likely file, this dramatically speeds up triage. -->

## Workaround

<!-- Optional. If you found a way to make it work, share it. -->

## Additional context

<!-- Anything else that might help — links, screenshots, related issues,
     the recipe you were following, the model card, etc. -->
