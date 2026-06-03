"""Tests for :mod:`forgewright.security.approval`."""

from __future__ import annotations

from pathlib import Path

import pytest
from forgewright.security.approval import (
    ApprovalDecision,
    ApprovalFlow,
    ApprovalResult,
)
from forgewright.security.trust import TrustRegistry, TrustRule, TrustScope


@pytest.fixture
def trust(tmp_path: Path) -> TrustRegistry:
    return TrustRegistry(machine_path=tmp_path / "trust.toml")


# ---------------------------------------------------------------------------
# should_approve (trust short-circuit)
# ---------------------------------------------------------------------------


def test_should_approve_when_on_trust(trust: TrustRegistry) -> None:
    trust.add("ls")
    af = ApprovalFlow(trust, interactive=True)
    assert af.should_approve("ls") is True
    assert af.should_approve("ls -la") is True


def test_should_approve_false_for_untrusted(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=True)
    assert af.should_approve("rm -rf /") is False
    assert af.should_approve("curl https://x") is False


# ---------------------------------------------------------------------------
# request_approval — non-interactive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_interactive_safe_builtin_is_yes(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=False)
    result = await af.request_approval("ls /tmp")
    assert result.decision == ApprovalDecision.YES
    assert result.rule_added is None


@pytest.mark.asyncio
async def test_non_interactive_unknown_command_is_no(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=False)
    result = await af.request_approval("curl https://evil.example")
    assert result.decision == ApprovalDecision.NO


# ---------------------------------------------------------------------------
# request_approval — denylist short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denylist_blocks_even_when_user_says_yes(
    trust: TrustRegistry,
) -> None:
    """Hard-blocked commands never prompt; callback is ignored."""
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "y")
    result = await af.request_approval("rm -rf /")
    assert result.decision == ApprovalDecision.NO


@pytest.mark.asyncio
async def test_denylist_blocks_when_user_says_a(trust: TrustRegistry) -> None:
    """A dangerous command must not be allowlisted via the prompt."""
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "a")
    result = await af.request_approval("rm -rf /tmp")
    assert result.decision == ApprovalDecision.NO
    # No rule was added.
    assert all(rule.pattern != "rm *" for rule in trust.list_rules())


# ---------------------------------------------------------------------------
# request_approval — prompt_callback driven
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_y_returns_yes(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "y")
    result = await af.request_approval("ls")
    assert result.decision == ApprovalDecision.YES
    assert result.rule_added is None


@pytest.mark.asyncio
async def test_callback_n_returns_no(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "n")
    result = await af.request_approval("ls")
    assert result.decision == ApprovalDecision.NO


@pytest.mark.asyncio
async def test_callback_a_returns_always_and_adds_machine_rule(
    trust: TrustRegistry,
) -> None:
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "a")
    result = await af.request_approval("ls -la /tmp")
    assert result.decision == ApprovalDecision.ALWAYS
    assert isinstance(result.rule_added, TrustRule)
    assert result.rule_added.scope == TrustScope.MACHINE
    # The trust registry now contains the new rule.
    assert trust.is_allowed("ls -la") is True
    # The pattern is derived from the first word.
    assert result.rule_added.pattern == "ls *"


@pytest.mark.asyncio
async def test_callback_A_returns_session_and_adds_session_rule(
    trust: TrustRegistry,
) -> None:
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "A")
    result = await af.request_approval("pytest -x tests/")
    assert result.decision == ApprovalDecision.SESSION
    assert isinstance(result.rule_added, TrustRule)
    assert result.rule_added.scope == TrustScope.SESSION
    assert trust.is_allowed("pytest -x tests/") is True


@pytest.mark.asyncio
async def test_callback_d_treated_as_no(trust: TrustRegistry) -> None:
    """``d`` (deny-rule) is not implemented in v0.1; falls back to ``n``."""
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "d")
    result = await af.request_approval("ls")
    assert result.decision == ApprovalDecision.NO
    assert result.rule_added is None


@pytest.mark.asyncio
async def test_empty_input_defaults_to_no(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=True, prompt_callback=lambda _: "")
    result = await af.request_approval("ls")
    assert result.decision == ApprovalDecision.NO


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_command_is_denied(trust: TrustRegistry) -> None:
    af = ApprovalFlow(trust, interactive=False)
    result = await af.request_approval("")
    assert result.decision == ApprovalDecision.NO


@pytest.mark.asyncio
async def test_non_interactive_path_prefix_safe_builtin(
    trust: TrustRegistry,
) -> None:
    """``/usr/bin/git`` is recognized as ``git`` (a safe builtin)."""
    af = ApprovalFlow(trust, interactive=False)
    result = await af.request_approval("/usr/bin/git status")
    assert result.decision == ApprovalDecision.YES


@pytest.mark.asyncio
async def test_approval_result_is_frozen(trust: TrustRegistry) -> None:
    """ApprovalResult is a frozen dataclass."""
    result = ApprovalResult(decision=ApprovalDecision.YES)
    with pytest.raises((AttributeError, Exception)):
        result.decision = ApprovalDecision.NO  # type: ignore[misc]
