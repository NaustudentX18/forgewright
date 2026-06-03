"""ApprovalFlow — the interactive prompt that gates Bash commands.

The Bash tool checks the denylist first; if that passes, it consults
the :class:`TrustRegistry` (this is the "skip the prompt" path); only
then does it call :meth:`ApprovalFlow.request_approval` (the "ask
the user" path).

The flow is intentionally simple in v0.1:

* **y** — yes, this once.
* **n** — no, deny this once (the default).
* **a** — yes, and add a MACHINE-scoped trust rule (persists to
  ``~/.config/forgewright/trust.toml``).
* **A** — yes, and add a SESSION-scoped rule (in-memory only).
* **d** — deny and add a MACHINE-scoped deny rule. Not implemented in
  v0.1; treated as ``n`` for now. The deny-rule machinery is
  deferred to v0.2 alongside the wider policy system.

Non-interactive mode (CI, non-TTY, ``--bypass`` in some cases) skips
the prompt: safe builtins auto-approve, everything else auto-denies.
The exact safe-builtin list comes from
:data:`forgewright.security.denylist.SAFE_BUILTINS`, so the two
layers stay in lockstep.
"""

from __future__ import annotations

import enum
import shlex
from collections.abc import Callable
from dataclasses import dataclass

from forgewright.logger import logger
from forgewright.security.denylist import SAFE_BUILTINS, check_command
from forgewright.security.trust import TrustRegistry, TrustRule, TrustScope, derive_pattern

__all__ = ["ApprovalDecision", "ApprovalFlow", "ApprovalResult"]


class ApprovalDecision(enum.StrEnum):
    """The user's choice at the approval prompt.

    The string values are the single-character keys shown in the
    prompt (``[y/n/a/A/d]``). Stable on disk; do not rename.
    """

    YES = "y"
    NO = "n"
    ALWAYS = "a"
    SESSION = "A"
    DENY = "d"


@dataclass(frozen=True)
class ApprovalResult:
    """The outcome of :meth:`ApprovalFlow.request_approval`.

    Attributes:
        decision: The user's choice (or the auto-decision in
            non-interactive mode).
        rule_added: The :class:`TrustRule` that was added to the
            registry as a side effect of the user choosing ``a`` or
            ``A``. ``None`` for plain ``y`` / ``n`` / ``d`` / auto.
    """

    decision: ApprovalDecision
    rule_added: TrustRule | None = None


class ApprovalFlow:
    """Gatekeeper for the Bash tool's "ask the user" path.

    The flow is stateless beyond the injected :class:`TrustRegistry`
    and the optional :attr:`prompt_callback`. Tests inject a callback
    that returns a deterministic string (``"y"`` / ``"n"`` / etc.)
    instead of a real TTY prompt.
    """

    def __init__(
        self,
        trust: TrustRegistry,
        *,
        interactive: bool = True,
        prompt_callback: Callable[[str], str] | None = None,
    ) -> None:
        self.trust = trust
        self.interactive = interactive
        self.prompt_callback = prompt_callback

    # ------------------------------------------------------------------ #
    # Pre-check
    # ------------------------------------------------------------------ #

    def should_approve(self, command: str) -> bool:
        """Return True if ``command`` is already on the trust allowlist.

        The Bash tool calls this BEFORE :meth:`request_approval` so
        the common case ("the user trusts ``ls`` and we run it 50
        times a session") never wakes the prompt.
        """
        return self.trust.is_allowed(command)

    # ------------------------------------------------------------------ #
    # The prompt
    # ------------------------------------------------------------------ #

    async def request_approval(self, command: str) -> ApprovalResult:
        """Ask the user whether to run ``command``.

        Returns an :class:`ApprovalResult`. The flow:

        1. If the denylist rejects ``command`` outright, return
           ``NO`` — there is no prompt for a hard-block.
        2. If :attr:`interactive` is False (CI / non-TTY), return
           ``YES`` for safe builtins, ``NO`` otherwise.
        3. Otherwise, render the prompt and let the user pick
           ``y / n / a / A / d``.

        The two side effects of choosing ``a`` or ``A`` (adding a
        MACHINE or SESSION rule) are performed inline so the
        resulting :class:`ApprovalResult` carries the rule.
        """
        # 1. Hard-blocked commands never prompt.
        if check_command(command) is not None:
            logger.warning("approval.denied_by_denylist cmd={}", command[:120])
            return ApprovalResult(decision=ApprovalDecision.NO)

        # 2. Non-interactive: auto-decide based on safe-builtin membership.
        if not self.interactive:
            return self._auto_decide(command)

        # 3. Interactive: ask the user.
        return self._ask_user(command)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _auto_decide(self, command: str) -> ApprovalResult:
        """Pick a decision for non-interactive runs.

        Safe builtins auto-approve; everything else auto-denies. We
        inspect the first token (stripped of any path prefix) so a
        call to ``/usr/bin/git`` is recognized as ``git``.
        """
        first = _first_token(command)
        if first and first in SAFE_BUILTINS:
            return ApprovalResult(decision=ApprovalDecision.YES)
        return ApprovalResult(decision=ApprovalDecision.NO)

    def _ask_user(self, command: str) -> ApprovalResult:
        """Render the prompt and act on the user's response.

        The default answer is ``n`` (deny) — explicit opt-in is the
        spec. We accept empty input as ``n`` so a stray Enter doesn't
        auto-approve.
        """
        prompt_text = f"? Run `{command[:80]}` [y/n/a/A/d]"
        raw = self._render_prompt(prompt_text)
        # Preserve case: lowercase 'a' = ALWAYS (machine rule), uppercase
        # 'A' = SESSION rule. We strip whitespace only.
        choice = raw.strip()
        return self._handle_choice(command, choice)

    def _render_prompt(self, prompt_text: str) -> str:
        """Render the prompt via the injected callback or rich.

        Tests inject :attr:`prompt_callback` to drive the flow
        without a TTY. The default is :class:`rich.prompt.Prompt`,
        which honors ``--no-color`` and non-TTY environments.
        """
        if self.prompt_callback is not None:
            return self.prompt_callback(prompt_text)

        # Imported lazily so a missing rich at install time doesn't
        # block the rest of the security layer (the flow is
        # importable without rich; rich is only needed at the actual
        # prompt).
        from rich.prompt import Prompt

        response: str = Prompt.ask(prompt_text, default="n", show_default=False)
        return response

    def _handle_choice(self, command: str, choice: str) -> ApprovalResult:
        """Map the user's input to an :class:`ApprovalResult`."""
        if choice == "a":
            pattern = derive_pattern(command)
            rule = self.trust.add(
                pattern, scope=TrustScope.MACHINE, reason="user typed 'a' at prompt"
            )
            return ApprovalResult(decision=ApprovalDecision.ALWAYS, rule_added=rule)
        if choice == "A":
            pattern = derive_pattern(command)
            rule = self.trust.add(
                pattern, scope=TrustScope.SESSION, reason="user typed 'A' at prompt"
            )
            return ApprovalResult(decision=ApprovalDecision.SESSION, rule_added=rule)
        if choice == "y" or choice == "Y":
            return ApprovalResult(decision=ApprovalDecision.YES)
        if choice == "n" or choice == "N" or choice == "":
            return ApprovalResult(decision=ApprovalDecision.NO)
        if choice == "d" or choice == "D":
            # Deny-rule machinery lands in v0.2; for v0.1 treat as plain NO.
            logger.debug("approval.deny_rule_v02 cmd={}", command[:80])
            return ApprovalResult(decision=ApprovalDecision.NO)

        # Unknown input: deny, and warn so noisy mis-keypresses show up in the log.
        logger.warning("approval.unknown_choice choice={} cmd={}", choice, command[:80])
        return ApprovalResult(decision=ApprovalDecision.NO)


def _first_token(command: str) -> str | None:
    """Return the first whitespace-delimited token of ``command``.

    Path prefixes are stripped (``/usr/bin/git`` → ``git``) so the
    check matches the denylist's behavior. Returns ``None`` for an
    empty command or one that fails to tokenize.
    """
    if not command or not command.strip():
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Fall back to plain split so e.g. an unbalanced quote doesn't
        # deny a clearly-safe command.
        tokens = command.split()
    if not tokens:
        return None
    return tokens[0].rsplit("/", 1)[-1]
