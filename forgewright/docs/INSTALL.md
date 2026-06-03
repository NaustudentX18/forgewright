# Install

> **TL;DR:** `uv tool install forgewright` is the recommended one-shot. Pick
> another method below if `uv` isn't your style, or you want a sandboxed
> container.

forgewright ships to four channels: **uv** (recommended), **pipx**, **Homebrew**
(macOS / Linuxbrew), and **Docker** (any platform). All four produce the same
`forgewright` binary with the same behaviour.

## Choose your install method

### 1. `uv` (recommended)

`uv` is a single Rust binary that handles Python version selection, virtual
environments, and the global `PATH` install in one tool. If you don't already
have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install forgewright:

```bash
uv tool install forgewright
```

`uv` will pick a compatible Python (3.11, 3.12, or 3.13), create an isolated
environment, and drop a `forgewright` shim into `~/.local/bin`. To upgrade
later: `uv tool upgrade forgewright`.

### 2. `pipx`

`pipx` is the classic "install Python CLI tools in their own venv" tool.
Equivalent to `uv tool`, with a slightly slower cold install.

```bash
pipx install forgewright
```

If you don't have `pipx` yet: `pip install --user pipx && pipx ensurepath`.

### 3. Homebrew (macOS / Linuxbrew)

```bash
brew install forest/tap/forgewright
```

The tap is auto-updated by a bot on every release tag, so `brew upgrade` is
all you need to track new versions.

### 4. Docker (any platform)

```bash
docker run --rm ghcr.io/forest/forgewright --help
```

For interactive use, mount your working directory and API keys:

```bash
docker run --rm -it \
  -v "$PWD":/work \
  -w /work \
  -e ANTHROPIC_API_KEY \
  ghcr.io/forgewright/forest/forgewright \
  build "summarise the files in ./src"
```

The image is multi-arch (`linux/amd64` and `linux/arm64`) and ships with
Playwright Chromium pre-installed for the browser tool.

---

## Verify the install

In a fresh shell (so `PATH` updates are picked up):

```bash
forgewright --version
# forgewright 0.1.0

forgewright doctor
# forgewright doctor
#   ✓ python  3.12.13  (>= 3.11, < 3.14)
#   ✓ config  /home/you/.config/forgewright/config.toml (exists)
#   ✓ keys    anthropic via env  ANTHROPIC_API_KEY
#   ✓ cache   /home/you/.cache/forgewright
#   ! sandbox subprocess  (run `forgewright sandbox doctor` to upgrade)

forgewright sandbox doctor
# forgewright sandbox doctor
#   ✓ subprocess   available   (no isolation; trusted code only)
#   ✓ docker       available   (mem 512m, pids 256, no network)
#   ✗ gvisor       missing     (install with: https://gvisor.dev/docs/user_guide/install/)
#   ✗ firecracker  missing     (planned for v0.2)
```

A green `sandbox doctor` is not required — `subprocess` is the default and
fine for day-to-day work — but it's the recommended upgrade path for
running untrusted code.

---

## Configure the provider

forgewright needs an LLM provider. Pick one (Anthropic, OpenAI, Google,
Azure, Bedrock, Ollama, OpenRouter) and set the API key.

### 1. Create the config file

```bash
forgewright init
```

This writes a starter config to `~/.config/forgewright/config.toml` and
prints a summary. Re-run safely — it never overwrites without prompting.

### 2. Edit the config

```bash
$EDITOR ~/.config/forgewright/config.toml
```

A minimal Anthropic config:

```toml
[llm]
provider = "anthropic"
model    = "claude-sonnet-4-6"

[security]
mode = "default"   # default | acceptEdits | plan | auto | dontAsk | bypass
```

A minimal local Ollama config:

```toml
[llm]
provider   = "ollama"
model      = "llama3.1:70b"
base_url   = "http://localhost:11434"
```

### 3. Set the API key

Pick one of three sources. **Highest security first** (only the first is
considered secret-safe):

```bash
# A. OS keyring (recommended; never written to disk in plain text)
forgewright secrets set anthropic
# > Prompt: paste your Anthropic API key

# B. Environment variable
export ANTHROPIC_API_KEY="sk-ant-..."

# C. secrets.toml fallback (chmod 0600)
mkdir -p ~/.config/forgewright
echo 'ANTHROPIC_API_KEY = "sk-ant-..."' >> ~/.config/forgewright/secrets.toml
chmod 0600 ~/.config/forgewright/secrets.toml
```

Keys are resolved in that order (keyring → env → file). The audit log
records the *source* of each key, never the value.

---

## Optional dependencies

forgewright has three optional extras. They're installed automatically when
relevant, but you can pull them in by hand:

```bash
# LLM providers (anthropic, openai, google, …)
uv tool install 'forgewright[llm]'

# MCP client + server
uv tool install 'forgewright[mcp]'

# Playwright browser tool (downloads Chromium the first time)
uv tool install 'forgewright[browser]'
uv tool run --from playwright playwright install chromium
```

---

## Upgrading

```bash
uv tool upgrade forgewright
# or
pipx upgrade forgewright
# or
brew upgrade forgewright
# or
docker pull ghcr.io/forest/forgewright:latest
```

`uv` and `pipx` will reinstall the matching optional extras. `brew` will
re-run the formula's install hook.

---

## Uninstalling

```bash
uv tool uninstall forgewright
# or
pipx uninstall forgewright
# or
brew uninstall forgewright
# (no uninstall needed for Docker — the image just stops running)
```

User data (config, sessions, audit log) is kept in
`~/.config/forgewright/` and `~/.local/share/forgewright/`. Remove those
directories if you want a clean slate.

---

## Troubleshooting

### "command not found: forgewright"

`uv` and `pipx` install the binary to `~/.local/bin` (or
`~/Library/Python/X.Y/bin` on macOS with `pipx`). Make sure that directory
is on your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
# or, for fish / zsh / nushell, the equivalent in your rc file
```

Restart the shell, or `source` the rc file in the current session.

### "playwright browsers not installed"

The browser tool needs Chromium. Install it once:

```bash
uv tool run --from playwright playwright install chromium
```

If you're using the Docker image, Chromium is already pre-installed.

### "docker socket not available" / "cannot connect to docker daemon"

`PythonExecute`'s Docker mode needs `/var/run/docker.sock`. Fixes:

- **Linux:** add yourself to the `docker` group and re-login:
  `sudo usermod -aG docker $USER`.
- **macOS / Windows:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  and make sure it's running.
- **CI:** mount the socket explicitly: `-v /var/run/docker.sock:/var/run/docker.sock`.
- **Workaround:** set `mode = "subprocess"` in the sandbox section of the
  config to skip Docker entirely. Only do this for trusted code.

### "mcp: command not found" / "fastmcp not installed"

Reinstall with the `mcp` extra:

```bash
uv tool install 'forgewright[mcp]' --force
```

### "Provider 'X' is not supported"

Check the [supported providers table](../README.md#bring-your-own-model) in
the README. If your provider is OpenAI-compatible (OpenRouter, vLLM,
Together, Fireworks, etc.) set `provider = "openai"` and override
`base_url`.

### "Permission denied" writing to `~/.config/forgewright/`

`HOME` may be set to a different directory in your environment. Check
with `echo $HOME`. If you've intentionally moved it, set `XDG_CONFIG_HOME`
to the correct path.

### "TLS / certificate verify failed" talking to an LLM provider

Most often caused by corporate proxies. Set `SSL_CERT_FILE` to your
organisation's CA bundle, or set `provider_https_verify = false` in
`[llm]` to skip verification (not recommended).

### Still stuck?

Open a [discussion](https://github.com/forest/forgewright/discussions) or
[file an issue](https://github.com/forest/forgewright/issues/new/choose)
with the output of `forgewright doctor` and `forgewright --version`.

For security issues, see [`SECURITY.md`](../SECURITY.md) — **do not** file
a public bug.
