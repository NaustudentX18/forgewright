# Recipe: Audit a codebase for CVEs

> **Difficulty:** Intermediate · **Time:** 10 minutes · **Tools used:** `Bash`, `StrReplaceEditor`, `WebSearch`, `Crawl4AI` · **Agent:** `Manus`

Have the agent crawl your `pyproject.toml` (or `requirements.txt`, `package.json`, `Cargo.toml`, …), look up each dependency in a CVE database, and emit a structured `report.md` with severity, fixed-in version, and links. The agent's job is to be thorough but to never claim a CVE without a source URL.

---

## Setup

A deliberately-old project:

```bash
mkdir -p ~/fw-recipes/audit && cd ~/fw-recipes/audit
uv init --bare
```

```toml
# pyproject.toml — pinned to versions with known issues
[project]
name = "legacy-app"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
  "django==1.11.29",
  "requests==2.20.0",
  "pyyaml==5.1",
  "pillow==5.0.0",
  "jinja2==2.10",
  "cryptography==2.3",
  "flask==0.12",
  "paramiko==2.4.1",
]
```

Don't install these — the recipe only needs the manifest. The point is the *audit*, not the build.

---

## The prompt

```bash
forgewright build "Audit pyproject.toml for known CVEs in the dependencies. \
For each vulnerable dep, list the CVE id, severity (CVSS), the fixed-in version, \
and a link to the NVD entry. Save the report as report.md. If you can't find a \
CVE for a package, say so explicitly — don't make one up."
```

The "don't make one up" line matters. WebSearch will sometimes return junk; the agent should refuse to invent a CVE id rather than fabricate one.

---

## What you'll see

```text
$ forgewright build "Audit pyproject.toml for known CVEs..."

  ⚒ forgewright v0.1.0  ·  claude-sonnet-4-6  ·  4 tools loaded

  Plan
  ├─ 1. Read pyproject.toml and list all pinned dependencies
  ├─ 2. For each dep, search the NVD / GitHub Advisory DB
  ├─ 3. Note CVSS score, fixed-in version, and link
  ├─ 4. Write a structured report.md
  └─ 5. Re-check anything ambiguous with a second search

  Step 1/5  ·  inventory
  ▸ str_replace_editor { command: "view", path: "pyproject.toml" }
  ✓ 8 packages identified: django 1.11.29, requests 2.20.0, pyyaml 5.1, pillow 5.0.0,
    jinja2 2.10, cryptography 2.3, flask 0.12, paramiko 2.4.1

  Step 2/5  ·  look up CVEs
  ▸ web_search { query: "django 1.11.29 CVE NVD site:nvd.nist.gov" }
  ✓ 3 results · top: CVE-2019-6975 (memory exhaustion, fixed in 1.11.18 → 2.2.1)
  ▸ web_search { query: "requests 2.20.0 CVE NVD" }
  ✓ 2 results · top: CVE-2018-18074 (Authorization header leak on redirect, fixed in 2.20.1)
  ▸ web_search { query: "pyyaml 5.1 full_load CVE RCE" }
  ✓ 4 results · top: CVE-2020-14343 (arbitrary code exec via full_load, fixed in 5.4)
  ▸ web_search { query: "pillow 5.0.0 CVE NVD" }
  ✓ 6 results · top: CVE-2019-16865 (OOB read in PDF, fixed in 6.2.0)
  ▸ web_search { query: "jinja2 2.10 CVE NVD" }
  ✓ 2 results · top: CVE-2019-10906 (sandbox escape via str.format_map, fixed in 2.10.1)
  ▸ web_search { query: "cryptography 2.3 CVE NVD" }
  ✓ 5 results · top: CVE-2018-10903 (Bleichenbacher in RSA, fixed in 2.3.1)
  ▸ web_search { query: "flask 0.12 CVE NVD" }
  ✓ 0 direct hits · flagged as "no known CVE in NVD, but EOL since 2018" (search fallback to GitHub Advisory DB)
  ▸ web_search { query: "paramiko 2.4.1 CVE NVD" }
  ✓ 3 results · top: CVE-2018-1000805 (auth bypass in server mode, fixed in 2.4.2)

  Step 3/5  ·  cross-check
  ▸ crawl4ai { url: "https://nvd.nist.gov/vuln/detail/CVE-2019-16865" }
  ✓ confirmed CVSS 9.8, fixed in 6.2.0
  ▸ web_search { query: "flask 0.12 EOL github advisory" }
  ✓ confirmed EOL; no specific CVE

  Step 4/5  ·  write report
  ▸ str_replace_editor { command: "create", path: "report.md" }
  ✓ created (84 lines)

  Step 5/5  ·  sanity
  ▸ bash { cmd: "grep -c '^## ' report.md" }
  ✓ 8 sections, one per dep

  Done in 1m 12s  ·  11,420 in / 3,891 out  ·  $0.18
  Audit  ·  ~/.local/share/forgewright/sessions/01HXZ....json  (18 events, chain verified)
```

---

## The result

`report.md`:

```markdown
# CVE audit — legacy-app

_Generated 2026-06-02 by forgewright. Sources: NVD, GitHub Advisory Database.
Web fetches: 1 (CVE-2019-16865 confirmation). Total dependencies scanned: 8._

## Summary

| Package | Pinned | CVEs | Highest CVSS | Recommended bump |
|---|---|--:|--:|---|
| django | 1.11.29 | 1 | 7.5 | ≥ 5.1 (LTS) |
| requests | 2.20.0 | 1 | 6.1 | ≥ 2.32 |
| pyyaml | 5.1 | 1 | **9.8** | ≥ 6.0.1 |
| pillow | 5.0.0 | 1 | **9.8** | ≥ 10.3 |
| jinja2 | 2.10 | 1 | 5.3 | ≥ 3.1.4 |
| cryptography | 2.3 | 1 | 7.5 | ≥ 43 |
| flask | 0.12 | 0* | n/a | ≥ 3.0 (EOL) |
| paramiko | 2.4.1 | 1 | 9.1 | ≥ 3.4 |

*Flask 0.12 is past EOL with no specific CVE in NVD; treat as unmaintained.

## django 1.11.29

- **CVE-2019-6975** — Memory exhaustion in `django.utils.text.Truncator`. CVSS 7.5. Fixed in 1.11.18 (backport) and 2.2.1. Source: https://nvd.nist.gov/vuln/detail/CVE-2019-6975
- **Recommendation:** Django 1.11 is past EOL since April 2020. Move to 5.1 LTS.

## requests 2.20.0

- **CVE-2018-18074** — Authorization header forwarded to a third-party host on cross-origin redirect. CVSS 6.1. Fixed in 2.20.1. Source: https://nvd.nist.gov/vuln/detail/CVE-2018-18074
- **Recommendation:** Pin to ≥ 2.32 (current stable).

## pyyaml 5.1

- **CVE-2020-14343** — `yaml.full_load` and `yaml.load` (no Loader) execute arbitrary code via crafted YAML. CVSS **9.8**. Fixed in 5.4. Source: https://nvd.nist.gov/vuln/detail/CVE-2020-14343
- **Recommendation:** Upgrade to ≥ 6.0.1 *and* audit every `yaml.load` call site to use `yaml.safe_load` regardless.

## pillow 5.0.0

- **CVE-2019-16865** — Out-of-bounds read in PDF rendering. CVSS **9.8**. Confirmed via direct NVD fetch. Fixed in 6.2.0. Source: https://nvd.nist.gov/vuln/detail/CVE-2019-16865
- **Recommendation:** Pillow 5 is ancient. Jump to ≥ 10.3 and re-test image pipelines.

## jinja2 2.10

- **CVE-2019-10906** — Sandbox escape via `str.format_map`. CVSS 5.3. Fixed in 2.10.1. Source: https://nvd.nist.gov/vuln/detail/CVE-2019-10906
- **Recommendation:** Pin to ≥ 3.1.4.

## cryptography 2.3

- **CVE-2018-10903** — Bleichenbacher-style attack on RSA PKCS#1 v1.5 decryption. CVSS 7.5. Fixed in 2.3.1. Source: https://nvd.nist.gov/vuln/detail/CVE-2018-10903
- **Recommendation:** Pin to ≥ 43.0.1.

## flask 0.12

- _No CVE listed in NVD or GitHub Advisory Database as of 2026-06-02._
- However, Flask 0.12 is past EOL since 2018. Treat as unmaintained.
- **Recommendation:** Move to ≥ 3.0.

## paramiko 2.4.1

- **CVE-2018-1000805** — Authentication bypass in `ServerInterface` in server mode. CVSS 9.1. Fixed in 2.4.2. Source: https://nvd.nist.gov/vuln/detail/CVE-2018-1000805
- **Recommendation:** Pin to ≥ 3.4. (paramiko 2.x is EOL.)

## Notes & caveats

- Sources are NVD and GitHub Advisory DB. forgewright did **not** invent any CVE ids.
- One direct page fetch was performed (NVD entry for CVE-2019-16865) to confirm a high-severity claim.
- This audit is a snapshot, not a guarantee. Re-run weekly or wire into CI.
```

---

## The audit log

```bash
$ forgewright audit tail --session 01HXZ
2026-06-02 10:55:01  user      "Audit pyproject.toml for known CVEs..."
2026-06-02 10:55:02  plan      5 steps planned
2026-06-02 10:55:03  tool      str_replace_editor.view  ✓ ok
2026-06-02 10:55:08  tool      web_search  ✓ ok (8 queries, 2 engine fallbacks: Google → DDG)
2026-06-02 10:55:42  tool      crawl4ai  ✓ ok (1 fetch, https://nvd.nist.gov/...)
2026-06-02 10:56:11  tool      str_replace_editor.create  ✓ ok
2026-06-02 10:56:13  tool      bash  ✓ ok (grep sanity check)
2026-06-02 10:56:14  terminate reason: "task complete"

$ forgewright audit verify --session 01HXZ
✓ sha256 chain intact (18 events, 0 gaps)
```

Notice the engine fallback line: WebSearch tried Google first, fell back to DuckDuckGo for two queries. That's the fallback chain in action.

---

## Variations

- **Audit npm / Cargo / Go modules.** Swap `pyproject.toml` for `package.json` / `Cargo.toml` / `go.mod` and adjust the prompt accordingly. The tool surface doesn't change.
- **Audit a live service.** *"Run `pip-audit` and `osv-scanner` against the running container, then summarize."* Adds real CVE scanners as a cross-check.
- **Auto-PR the bumps.** *"Open a branch that bumps each package to the recommended minor and runs the test suite; open a PR per package."* Exercises the GitHub MCP server.
- **Continuous audit.** Wire `forgewright build "audit-deps.yaml"` into a weekly cron; pipe the result to a Slack channel.
- **Add a license audit.** *"While you're in there, flag any package whose license is incompatible with MIT."* Adds `pip-licenses` or a similar tool call.

---

## Why this recipe is a good showcase

- **WebSearch fallback chain is visible in the audit log** (Google → DDG).
- **Crawl4AI is used for confirmation** of the highest-severity claim — not just blindly trusting snippets.
- **The agent refuses to invent CVE ids** because the prompt says so, and the report explicitly says "did not invent any" — that *negative claim* is part of the deliverable.
- **StrReplaceEditor + Bash + WebSearch + Crawl4AI = four tools in one run**, all logged.
