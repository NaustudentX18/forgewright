"""Provider-aware token counting for context budgeting and cost hints.

* **OpenAI / Azure** — ``tiktoken`` when installed (OpenAI tokenizer).
* **Anthropic** — ``client.messages.count_tokens`` when the SDK and API key
  are available.
* **All other providers** — characters ÷ 4 heuristic (no tiktoken on Claude).

Falls back to the heuristic whenever a provider-specific path is unavailable
(missing dependency, missing credentials, or API error).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forgewright.logger import logger

if TYPE_CHECKING:
    from forgewright.schema import ChatMessage

__all__ = [
    "character_heuristic_token_count",
    "count_for_provider",
    "count_tokens_anthropic",
    "count_tokens_openai",
    "messages_for_anthropic_count",
]


def character_heuristic_token_count(messages: list[ChatMessage]) -> int:
    """Approximate token count as ``sum(len(content) // 4)`` per message."""
    total = 0
    for m in messages:
        total += len(m.content) // 4
        if m.tool_call_id:
            total += len(m.tool_call_id) // 4
        if m.name:
            total += len(m.name) // 4
    return total


def messages_for_anthropic_count(
    messages: list[ChatMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split system prompts and map forgewright messages to Anthropic params.

    Tool results are folded into synthetic user turns so the count API
    still sees their text without requiring a live tool-use block shape.
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
        elif m.role in ("user", "assistant"):
            out.append({"role": m.role, "content": m.content})
        elif m.role == "tool":
            label = m.name or "tool"
            out.append(
                {
                    "role": "user",
                    "content": f"[tool result: {label}]\n{m.content}",
                }
            )
    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def count_tokens_openai(messages: list[ChatMessage], model: str) -> int:
    """Count tokens with tiktoken; fall back to the char heuristic."""
    try:
        import tiktoken
    except ImportError:
        logger.debug("tiktoken not installed; using character heuristic for OpenAI")
        return character_heuristic_token_count(messages)

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    total = 0
    for m in messages:
        total += len(encoding.encode(m.content))
        if m.tool_call_id:
            total += len(encoding.encode(m.tool_call_id))
        if m.name:
            total += len(encoding.encode(m.name))
    return total


def count_tokens_anthropic(
    messages: list[ChatMessage],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> int | None:
    """Return Anthropic's token count, or ``None`` to signal fallback."""
    try:
        import anthropic
    except ImportError:
        logger.debug("anthropic SDK not installed; using character heuristic")
        return None

    key = api_key
    if not key:
        import os

        key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None

    system, anthropic_messages = messages_for_anthropic_count(messages)
    if not anthropic_messages:
        return character_heuristic_token_count(messages)

    client_kwargs: dict[str, Any] = {"api_key": key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**client_kwargs)

    params: dict[str, Any] = {"model": model, "messages": anthropic_messages}
    if system:
        params["system"] = system

    try:
        result = client.messages.count_tokens(**params)
        return int(result.input_tokens)
    except Exception as exc:
        logger.debug("anthropic.messages.count_tokens failed: {}", exc)
        return None


def count_for_provider(
    provider: str,
    model: str,
    messages: list[ChatMessage],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> int:
    """Dispatch to the best counter for ``provider``, else heuristic."""
    if provider in ("openai", "azure"):
        return count_tokens_openai(messages, model)
    if provider == "anthropic":
        precise = count_tokens_anthropic(
            messages,
            model,
            api_key=api_key,
            base_url=base_url,
        )
        if precise is not None:
            return precise
    return character_heuristic_token_count(messages)
