# Quickstart

> **Time:** 5 minutes · **What you'll have:** a working `forgewright` install
> running real tasks against a real LLM, plus the REPL and an MCP server you
> can wire into another agent.

This is the fastest path from a clean machine to a working `forgewright`. If
you want more detail on any step, jump to [`INSTALL.md`](./INSTALL.md).

---

## 1. Install (`30 seconds`)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install forgewright
```

(Use `pipx install forgewright`, `brew install forest/tap/forgewright`, or
`docker run --rm ghcr.io/forest/forgewright` if you prefer — see
[`INSTALL.md`](./INSTALL.md#choose-your-install-method).)

Verify:

```bash
forgewright --version
# forgewright 0.1.0
```

---

## 2. Configure your provider (`60 seconds`)

Run the init wizard:

```bash
forgewright init
```

It writes a starter config to `~/.config/forgewright/config.toml`. Open it:

```bash
$EDITOR ~/.config/forgewright/config.toml
```

A minimal Anthropic config:

```toml
[llm]
provider = "anthropic"
model    = "claude-sonnet-4-6"

[security]
mode = "default"
```

Set the API key (pick one):

```bash
# A. OS keyring (recommended)
forgewright secrets set anthropic
# paste key, press enter

# B. Environment variable
export ANTHROPIC_API_KEY="sk-ant-..."

# C. secrets.toml fallback
echo 'ANTHROPIC_API_KEY = "sk-ant-..."' >> ~/.config/forgewright/secrets.toml
chmod 0600 ~/.config/forgewright/secrets.toml
```

Other providers: see the [provider table](../README.md#bring-your-own-model)
in the README.

---

## 3. Run a single task (`60 seconds`)

Try the lightest possible agent task:

```bash
forgewright build "list the files in the current directory"
```

You'll see a streaming plan, one or two tool calls (probably `Bash` running
`ls`), and a short final answer. At the end, forgewright prints a session ID
and a path to the audit log:

```
Done in 1.7s  ·  412 in / 89 out  ·  $0.002
Audit  ·  ~/.local/share/forgewright/sessions/01HXY....json  (2 events, chain verified)
```

---

## 4. Open the REPL (`60 seconds`)

```bash
forgewright
```

You'll get a streaming prompt:

```
forgewright v0.1.0 · claude-sonnet-4-6 · 8 tools · mode=default
Type /help for slash commands. Ctrl+C aborts, Ctrl+D exits.

>
```

Try the built-in slash commands:

```text
> /help
> /status
> /cost
> /exit
```

`/status` shows the current session, model, sandbox, and the running
token / cost totals. `/cost` prints the per-session spend. The first time
you press `Shift+Tab` you'll cycle the permission mode (`default →
acceptEdits → plan → auto → dontAsk → bypass → default`).

---

## 5. A real task that uses the web (`60 seconds`)

```bash
forgewright build "what's the weather in Tokyo right now?"
```

The agent will:
1. Plan: `1. Search for Tokyo weather  2. Extract the temperature`.
2. Call the `WebSearch` tool (DuckDuckGo by default; the chain falls back
   to SerpAPI / Brave if configured).
3. Optionally call the `Browser` tool to follow a link.
4. Return a short summary plus a citation.

The first call may prompt for approval (it's outside the safe-builtin
allowlist). Press `a` to allow for the session, `A` for the repo, or `m`
for the machine allowlist.

---

## 6. Try the MCP server (`60 seconds`)

forgewright is both an MCP **client** (can call other agents' tools) and
an MCP **server** (exposes its tools to other agents). In one terminal,
start the server:

```bash
forgewright mcp serve
# forgewright mcp server listening on stdio
#   tools: bash, browser, str_replace_editor, terminate, ask_human
#   version: 0.1.0
```

In a second terminal, point any MCP-compatible client (Claude Desktop,
Cursor, Cline, another `forgewright` instance) at it:

```json
// Claude Desktop config: ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "forgewright": {
      "command": "forgewright",
      "args": ["mcp", "serve"],
      "transport": "stdio"
    }
  }
}
```

Now the client can call `bash`, `browser`, etc. through your local
forgewright. Useful patterns: chain a planning LLM to your shell, give
your editor's agent a real browser, or wire `forgewright` into a CI
pipeline.

To **call** an MCP server from forgewright instead of exposing it, add
one to your config:

```toml
[mcp.servers.filesystem]
transport = "stdio"
command   = "npx"
args      = ["-y", "@modelcontextprotocol/server-filesystem", "/home/you/projects"]
```

Then `forgewright mcp ls` lists what was discovered and
`forgewright mcp trust filesystem__read_file` adds it to the allowlist.

---

## Where to next?

- **Install details:** [`INSTALL.md`](./INSTALL.md) — every install method,
  every optional extra, and a troubleshooting section.
- **The agent stack:** [`ARCHITECTURE.md`](./ARCHITECTURE.md) — the layered
  design (BaseAgent → ReActAgent → ToolCallAgent → Manus).
- **Security model:** [`SECURITY.md`](../SECURITY.md) — denylist, sandboxes,
  audit log, threat model.
- **Recipes:** [`recipes/`](./recipes/) — five-minute end-to-end examples
  for refactoring, CVE auditing, dashboards, and Postgres.
- **Research notes:** [`RESEARCH.md`](./RESEARCH.md) — the design
  decisions behind the framework.

Welcome aboard. `forge agents. wright code.`
