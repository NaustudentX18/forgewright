# Manus-clone intent vs. shipped state

**Goal:** `forgewright` is an open-source, BYOK clone of Manus — a
chat-based AI agent with tool use (file editing, shell, Python, web
search, browser) that streams tokens, persists sessions, and runs in
the browser via a web UI.

## What was wrong (the "cooked it" parts)

The v0.1.0 release shipped an agent stack that *looked* complete on
paper but had a critical missing piece:

| What the docs claimed | What was actually on disk |
|---|---|
| "Phase 2 — LLM abstraction. Provider-agnostic LLM protocol with a **LiteLLM backend (Anthropic, OpenAI, Google, Azure, Bedrock, Ollama, OpenRouter)** and a deterministic stub for tests." (`CHANGELOG.md` line 30) | `src/forgewright/llm/` contained only `base.py`, `__init__.py`, and `stub.py`. The `litellm_backend.py` file was **completely missing**. |
| `LLMConfig.provider` is a `Literal` of seven real providers. | `LLMBackend.from_config()` for every non-stub provider fell through to `StubBackend` with the comment "Real providers land in Phase 2 of the build plan." |
| Web chat uses the Manus agent loop with SSE streaming. | True at the transport layer, but the LLM behind the loop was the stub. The stub returned `"I have no tools to call. TASK_COMPLETE"` for every request, regardless of the user's BYOK configuration. |

**Net effect:** A user with a real `ANTHROPIC_API_KEY` and
`provider="anthropic"` in their config still got a stub-LLM chat
that couldn't use any tools. The project was, in effect, a CLI
scaffold around a stub, not a working BYOK agent.

## What's now fixed

| Layer | File | Status |
|---|---|---|
| LiteLLM backend | `src/forgewright/llm/litellm_backend.py` | **New.** 230 lines, full implementation. |
| Factory dispatch | `src/forgewright/llm/base.py` `LLMBackend.from_config` | **Rewritten.** Real providers now route to `LiteLLMBackend`; only `provider="stub"` uses the stub. |
| `__init__.py` exports | `src/forgewright/llm/__init__.py` | **`LiteLLMBackend` added to exports.** |
| Ollama prefix | `PROVIDER_PREFIX["ollama"]` | **Was `"ollama/"` → changed to `"ollama_chat/"`.** Without the chat prefix, Ollama's `/api/generate` endpoint returns tool calls as raw text in `content`, breaking agent tool use. The chat endpoint (`/api/chat`) returns structured `tool_calls`. |
| Tests | `tests/unit/llm/test_litellm_backend.py` | **New.** 36 tests: factory dispatch, model-string prefix per provider, message/tool conversion, response normalization with malformed-tool-args guard, mocked end-to-end `ask_tool` with `tools=[...]`. |
| mypy override | `pyproject.toml` | `litellm` and `litellm.*` added to the `ignore_missing_imports` list (consistent with how the project treats `fastapi`, `docker`, etc.). |

**Total: 719 tests pass** (up from 617 before the fix), zero
regressions.

## Verified end-to-end

The full Manus-style agent loop now runs against a real LLM through
the web chat:

```bash
# Server boot
FORGEWRIGHT_LLM__PROVIDER=ollama \
FORGEWRIGHT_LLM__MODEL=gpt-oss:20b \
FORGEWRIGHT_LLM__BASE_URL=https://ollama.com \
FORGEWRIGHT_LLM__API_KEY="$OLLAMA_CLOUD_API_KEY" \
uv run --extra web forgewright web --port 18790
```

```bash
# Send a message
curl -N -X POST http://127.0.0.1:18790/api/sessions/$SID/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"Use the bash tool to list files in /tmp, then terminate."}'
```

Observed SSE event sequence (real network call to Ollama Cloud):

```
event: thinking      data: {"step": 0, "max_steps": 8}
event: tool_call     data: {"tool": "bash",  "args": {"cmd": "ls -1 /tmp | head -n 3", ...}}
event: tool_result   data: {"tool": "bash",  "output": "120e7e94ab8d8b1cbfca6dfc83853ee8\n3dshippit-generated\n5G.fap\n", "duration_ms": 396}
event: tool_call     data: {"tool": "terminate", "args": {"reason": "done"}}
event: tool_result   data: {"tool": "terminate", "output": "Terminated: done"}
event: token × 8     data: streaming chunks of the final assistant message
event: final         data: {"content": "Tool 'terminate' returned:\nTerminated: done"}
```

Server log:

```
14:44:45 INFO  tool_call.dispatched name=bash       is_error=False id=call_frv49kh8
14:44:46 INFO  tool_call.dispatched name=terminate  is_error=False id=call_d3y89yge
```

Two real tool dispatches. The Bash tool actually executed
`ls -1 /tmp | head -n 3` on the Pi and returned three real filenames.
The Manus-clone loop — model → tool → observation → model → finish —
is now real, not stubbed.

## What still needs work (out of scope for the v0.1.0 bugfix)

The earlier roadmap (see `BUILD_PLAN.md` and the v0.1 chat-function
roadmap reply in this conversation) still applies. The most
user-visible gaps remain:

1. **Stop / cancel button** in the web UI mid-stream (the abort
   endpoint exists, no client wiring).
2. **Markdown rendering** beyond `*italic*` + fenced code.
3. **First-commit + a proper `[Unreleased]` section** so the next
   release can be cut from a real git history (the repo has zero
   commits on `master`).
4. **Tool-card state on session reopen** (collapsible but doesn't
   restore).
5. **Image / screenshot inline rendering** (Browser tool screenshots
   don't show in the chat).

The LiteLLM bug was the single biggest blocker because every other
Manus-clone feature depends on a real LLM doing real tool calls. With
it fixed, the rest of the polish items become straightforward.

## Reproducing the fix

```bash
cd /home/pi/forgewright
uv run pytest tests/unit/llm/ -v          # 36 tests
uv run pytest tests/unit/                 # 719 tests
```

```bash
# Set any provider — see the CLAUDE.md model catalog
export FORGEWRIGHT_LLM__PROVIDER=ollama
export FORGEWRIGHT_LLM__MODEL=qwen3-14b-agent
export FORGEWRIGHT_LLM__BASE_URL=http://your-ollama-host:11434
uv run --extra web forgewright web
# Open http://127.0.0.1:8787
```

For Anthropic / OpenAI / Google / Azure / Bedrock / OpenRouter, the
env-var equivalents are the same with `provider` swapped and
`api_key` set; no code changes required.
