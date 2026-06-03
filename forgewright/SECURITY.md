# Security Policy

> **TL;DR:** Default-deny, opt-in trust, tamper-evident audit log, sandboxed code execution, secrets in your OS keyring. Report vulnerabilities to **security@forgewright.dev** (private). We aim to acknowledge within 48 hours and triage within 7 days.

---

## 1. Supported versions

| Version | Supported |
|---|---|
| Latest release (`main` branch tip) | ✓ |
| Previous minor release | ✓ (security fixes backported for 90 days) |
| Anything older | ✗ |

forgewright follows **CalVer** (`YYYY.MM.PATCH`). Each release is signed with Sigstore/cosign and published to PyPI with PEP 740 attestations.

---

## 2. Reporting a vulnerability

**Please do not file a public GitHub issue for security bugs.**

Pick whichever channel is most comfortable for you:

1. **Email:** **security@forgewright.dev** (PGP encrypted preferred).
   - PGP key fingerprint: `B6A1 0C2D 7E4F 9A8B 3C5D  2E1F 4A7B 9C0D 6E3F 2A1B`
   - Public key: <https://forgewright.dev/pgp/security.asc>
2. **GitHub Security Advisories:** open a
   [private security advisory](https://github.com/forest/forgewright/security/advisories/new)
   on this repository. Use this if you prefer to keep the report entirely
   inside GitHub's coordinated-disclosure workflow.
3. **Signal / Matrix:** see the contact page at <https://forgewright.dev/contact>
   for time-limited, end-to-end-encrypted channels.

Whichever channel you use, please include:

- A clear description of the vulnerability
- A reproducer (commands, prompt, or code snippet)
- The affected version (commit SHA if possible)
- Your assessment of impact (RCE, data leak, sandbox escape, …)
- Whether you intend to disclose publicly, and on what timeline

### What to expect

| Stage | Time |
|---|---|
| Acknowledgement | within 48 hours |
| Triage and severity assessment | within 7 days |
| Patch development | varies by severity (see below) |
| Public disclosure | coordinated with you, after the fix ships |

### Severity targets (from triage to fix)

| Severity | Example | Target fix time |
|---|---|---|
| Critical | RCE via a tool, sandbox escape | 7 days |
| High | Secret leak to logs, auth bypass | 30 days |
| Medium | Limited info disclosure, DoS | 90 days |
| Low | UX issues with security implications | next release |

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We'll credit you in the release notes and CVE description unless you ask to remain anonymous.

---

## 3. Threat model

### What's in scope

- **Any code or text the LLM can influence** — tool outputs, fetched URLs, file contents, MCP server responses, agent memory.
- **The local subprocess the agent spawns** for tool execution.
- **The audit log** and any tampering attempts.
- **Sandbox escapes** from any of the four backends.
- **MCP server trust** — a malicious or compromised server returning deceptive tool definitions.

### What's out of scope

- The user's terminal after they `sudo forgewright run`.
- The host kernel or container runtime.
- The LLM provider's training pipeline and API.
- Prompt injection that succeeds *only* against the model itself (we treat all model output as low-trust regardless).
- Third-party MCP servers not in our recommended set.

### Assumptions

- The user runs on Linux/macOS/Windows with a modern Docker.
- The user does not paste raw user input into a privileged shell.
- The user reviews audit logs after incidents.
- The user does not disable the default-deny sandbox without understanding the implications.

---

## 4. Sandboxing

The `PythonExecute` tool runs user-supplied code in one of four backends. The default is **DockerSandbox** with hard limits:

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

Recommended upgrade: **GVisorSandbox** (`--runtime=runsc`) for stronger syscall isolation. For multi-tenant hostile workloads, **FirecrackerSandbox** (v0.2) provides microVM-grade isolation.

| Backend | Strengths | Weaknesses |
|---|---|---|
| `SubprocessSandbox` | Zero install, fast | No memory/FS/network limits; trusted code only |
| `DockerSandbox` | Hard limits, ubiquitous | Kernel shared; escape possible if Docker misconfigured |
| `GVisorSandbox` | Userspace kernel, syscall filter | Requires gVisor install; small perf hit |
| `FirecrackerSandbox` | microVM, strong isolation | v0.2; complex setup |

`forgewright sandbox doctor` reports which backends are available and recommends the strongest.

---

## 5. The dangerous-command denylist

The `Bash` tool applies a 20-pattern denylist before any command reaches the shell. **9 patterns hard-block** (no prompt, no override). The rest prompt for approval unless allowlisted.

### Hard-block (no override without `--i-understand-the-risks`)

| # | Pattern | Regex |
|---|---|---|
| 1 | `rm -rf /` and variants | `rm\s+(-[a-z]*f[a-z]*\s+)*-[a-z]*r[a-z]*\s+/\s*$` |
| 2 | `rm -rf ~` and similar | `rm\s+-rf\s+(\~\|\$HOME\|/home\|/workspace\|/)` |
| 3 | Format/wipe disk | `\b(mkfs\|wipefs)\b` |
| 4 | Raw disk write | `dd\s+if=.+\s+of=/dev/(sd\|nvme\|hd\|vd\|xvd)` |
| 5 | Shutdown/reboot | `\b(shutdown\|reboot\|halt\|poweroff\|init\s+0\|init\s+6)\b` |
| 6 | curl\|sh, wget\|sh | `(curl\|wget\|fetch).*\|\s*(sh\|bash\|zsh\|python\|perl\|ruby)\b` |
| 7 | Sudo escalation | `\b(sudo\|doas\|pkexec)\b` |
| 8 | Kill PID 1 | `kill\s+(-9\|-KILL)?\s*\b1\b` |
| 9 | base64\|sh | `base64\s+-d.*\|\s*(sh\|bash\|python)` |

### Prompt (allowlistable)

| # | Pattern | Regex |
|---|---|---|
| 10 | chmod 777 / chown -R root | `chmod\s+(-R\s+)?777\b\|chown\s+-R\s+root` |
| 11 | Disable firewall | `\b(ufw\s+disable\|iptables\s+-F\|setenforce\s+0)\b` |
| 12 | Credential dump | `\b(cat\|less\|head\|tail)\s+~?/?\.(bash_history\|ssh/id_\|netrc\|aws/credentials\|kube/config)\b` |
| 13 | Force-push to main | `git\s+push.*(-f\|--force).*(origin\|upstream)\s+(main\|master\|prod)` |
| 14 | Network capture | `\b(tcpdump\|wireshark\|nmap\|masscan)\b` |
| 15 | Container escape | `nsenter\|unshare\s+(-m\|-u\|-p\|-n)\|chroot\s+/` |
| 16 | Persistence | `\b(crontab\s+-e\|systemctl\s+enable\|launchctl\s+load)\b` |
| 17 | DNS exfil | `\|\s*nc\s+.*\s+\d+\b` |
| 18 | Mount filesystem | `\bmount\s+(-\w+\s+)*/dev/` |
| 19 | Eval of remote | `\beval\s+"\$\(curl\|wget` |
| 20 | Unlocked global install | `(npm\s+-g\|pip\s+install).*--(no-deps\|pre)` |

The denylist is paired with a small allowlist of safe builtins (`ls`, `cat`, `grep`, `pytest`, `git status`, `uv run`, …). Anything not on either list is prompted by default. The full source lives in `src/forgewright/security/denylist.py`.

### Limitations

The denylist is **defense in depth, not a security boundary**. A determined attacker (or a sufficiently creative model) can:

- Encode payloads (base64, hex, unicode escapes).
- Chain through symlinks or `LD_PRELOAD` (mitigated by `read_only=true` and `no-new-privileges`).
- Exploit race conditions in multi-tool interactions.

The real security boundary is the **sandbox**. The denylist is a UX shortcut to catch the obvious cases without bothering the user.

---

## 6. Tool authorization model

The default mode is **approve-each**: every tool call goes through an interactive prompt. The user can opt-in to:

- **Session allowlist** — `a` at the prompt. Cleared on exit.
- **Repo allowlist** — `A` at the prompt. Persists to `./.forgewright/trust.toml`, gitignored.
- **Machine allowlist** — `forgewright trust <pattern> --scope=machine`. Persists to `~/.config/forgewright/trust.toml`.

### Modes

| Mode | Behavior |
|---|---|
| `default` | Approve-each, except for the small safe-builtin allowlist. |
| `acceptEdits` | `str_replace_editor` is auto-approved; everything else prompts. |
| `plan` | No execution. The agent describes what it would do, the user approves the whole plan. |
| `auto` | Skip the prompt for any tool on the machine allowlist. |
| `dontAsk` | Like `auto` but also skips for repo-allowlisted tools. |
| `bypass` | **No prompts. No audit gate. Use only in CI.** |

`bypass` is for trusted CI jobs that have already passed the equivalent review in their pipeline config. It is not a "convenience mode" for interactive use.

### Cycle the mode

Press `Shift+Tab` in the REPL to cycle: `default → acceptEdits → plan → auto → dontAsk → bypass → default`. The current mode is shown in the status bar.

---

## 7. Secret handling

API keys and tokens resolve in this order (highest wins, **lowest leaked**):

1. **OS keyring** via the `keyring` package. Set with `forgewright secrets set anthropic`. Never written to disk in plain text.
2. **Environment variables** (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `FORGEWRIGHT_TOKEN`). Read at startup, never logged, never serialized.
3. **`~/.config/forgewright/secrets.toml`** — chmod 0600, owner-only. Used as fallback when neither keyring nor env is set.
4. **`.forgewright.toml` in the repo** — **forbidden for secrets**. The `forbid-secrets-in-toml` lint rule blocks any attempt.

The audit log records `keyring_source` (`env` / `keyring` / `file`) but never the value. LLM API keys are never logged, echoed, or included in error messages.

### Pre-commit

- `gitleaks` with the standard rule pack.
- `trufflehog` in CI for diff scanning (catches uncommitted staged changes that gitleaks sometimes misses).
- `pip-audit --strict` on every PR.

---

## 8. MCP server trust

MCP is the riskiest integration surface. The 2025-06-18 spec calls out the following threats:

- **Spoofing** — a server pretends to be a trusted tool. Mitigated by namespacing (`<server_id>__<tool_name>`) and the allowlist.
- **Tampering** — adversarial content in tool descriptions or outputs. Mitigated by treating all tool output as untrusted input and wrapping in the `agent-memory-guard` (OWASP ASI06) before appending to memory.
- **Elevation of privilege** — a server's tool asks for more than the user granted. Mitigated by per-tool scopes in the allowlist.

### Hardening checklist

1. **Pin MCP server versions** in `mcp.json`. A `^1.2.0` pin is a recipe for trouble.
2. **Treat `notifications/tools/list_changed` as a re-authorization event.** When a server signals a tool change, re-trust before continuing.
3. **Validate `inputSchema` server-side** with `jsonschema` before calling. A buggy or malicious server can return a schema that doesn't match the actual behavior.
4. **Refuse OAuth passthrough.** Each hop gets its own token; we never forward a bearer token to a downstream API.
5. **Timeouts on every tool call.** Default 30s; configurable per-tool. Hung stdio servers are SIGKILL'd.
6. **Log structured `serverId`, `toolName`, `argsHash` (not raw args).** Don't leak credentials into the audit log.

---

## 9. The audit log

Every action lands in `audit.jsonl`, sha256-chained. The chain makes tampering detectable: `forgewright audit verify` recomputes the chain and reports any gap.

### Schema (excerpt)

```json
{
  "ts": "2026-06-02T11:30:13.481+10:00",
  "session_id": "01HXY...",
  "type": "tool",
  "actor": {"type": "tool", "name": "Bash", "version": "0.1.0"},
  "user_consent": {"mode": "approve-each", "approver": "forest", "scope": "session"},
  "tool": "Bash",
  "args": {"cmd": "rm -rf ./build", "cwd": "..."},
  "result": {"exit": 0, "stdout_sha256": "ab12...", "stderr_sha256": "cd34..."},
  "redactions": ["ANTHROPIC_API_KEY", "GH_TOKEN"],
  "prev_hash": "f4e1...",
  "hash": "9c0a..."
}
```

### Properties

- **Append-only.** Files are opened with `O_APPEND`. The directory is 0700.
- **Tamper-evident.** `prev_hash` and `hash` form a chain. `audit verify` validates it.
- **Redacted.** Secret-looking strings are detected by Shannon-entropy + regex and replaced with `<redacted>` before write.
- **Rotated.** Nightly rotation, 30-day retention by default.
- **Exportable.** `--format otel` emits OpenTelemetry-compatible spans for SIEM ingestion.

### What the audit log does NOT do

- It does not prevent an attack in progress. It's a forensic record, not a WAF.
- It does not protect against a compromised kernel or a user with `root` on the host.
- It does not catch prompt injection that succeeds against the model itself. The model can choose to ignore anything the agent says.

---

## 10. Known limitations

We try to be honest about what the framework does **not** protect against.

| Limitation | Why it exists | Workaround |
|---|---|---|
| A buggy MCP server can return deceptive tool descriptions | MCP spec treats descriptions as untrusted | Validate `inputSchema`; re-trust on `list_changed` |
| The model can choose to ignore a tool's safety warning | LLMs are not perfectly obedient | The user is the last line of defense; the audit log records what happened |
| `SubprocessSandbox` has no memory/FS/network limits | It's a fast iteration mode | Use `DockerSandbox` for anything untrusted |
| A user in `bypass` mode skips all prompts | The mode is intentional for CI | Use `default` or `plan` for interactive work |
| A determined attacker with code execution in the sandbox can sometimes exfiltrate via timing channels | Out of scope for v0.1 | Future: gVisor + seccomp + eBPF-based channel mitigation |
| The `Bash` denylist can be bypassed by encoded payloads | Regexes are not Turing-complete | Pair the denylist with the sandbox as the real boundary |

---

## 11. Hardening checklist for users

A pre-flight checklist for production or sensitive environments:

- [ ] Set `mode = "default"` (don't use `bypass` outside CI)
- [ ] Run `forgewright sandbox doctor`; use the strongest backend available
- [ ] Set secrets via `forgewright secrets set` (keyring) rather than env vars
- [ ] Install `gitleaks` and `trufflehog` as pre-commit hooks
- [ ] Configure audit log shipping to your SIEM
- [ ] Pin MCP server versions in `mcp.json`
- [ ] Review `forgewright trust ls` weekly; revoke stale rules
- [ ] Verify the audit chain with `forgewright audit verify` in a cron
- [ ] Subscribe to GitHub security advisories for this repo
- [ ] Set `TRACELOOP_TRACE_CONTENT=false` in production

---

## 12. Security-relevant references

- [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/)
- [OWASP Agent Memory Guard (ASI06 mitigation)](https://github.com/OWASP/www-project-agent-memory-guard)
- [Model Context Protocol — Security and Trust & Safety](https://modelcontextprotocol.io/specification)
- [gVisor — application kernel for containers](https://gvisor.dev/docs/)
- [Firecracker microVM](https://firecracker-microvm.github.io/)
- [PyInstaller security considerations](https://pyinstaller.org/en/stable/security.html)
- [Sigstore / cosign](https://github.com/sigstore/cosign)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)

---

*This document is a living artifact. Open a PR if you'd like to add a section or correct a limitation.*
