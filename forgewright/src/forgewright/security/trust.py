"""TrustRegistry — the persistent allowlist of approved command patterns.

Lives at ``~/.config/forgewright/trust.toml`` (overridable via
``Settings.security.trust``). The :class:`TrustRegistry` is the source
of truth for the Bash tool's "skip the prompt" short-circuit; it is
read on every command and updated whenever the user picks ``a`` or
``A`` at the approval prompt (see :mod:`forgewright.security.approval`).

The on-disk format is a list of ``[[rule]]`` entries. The schema is
defined by :class:`TrustRule`; see its docstring for field semantics.

Scoping model
-------------

Three scopes, in increasing order of blast-radius:

* ``session`` — in-memory only. Cleared on process exit (or by
  ``TrustRegistry.clear_session()``).
* ``repo``     — checked into ``.forgewright/trust.toml`` in the
  working directory. Not implemented in v0.1 (the architecture calls
  for it; the wiring lives in Phase 10A). Treated as in-memory here.
* ``machine``  — persisted to the user-level ``trust.toml`` under
  ``~/.config/forgewright/``. Survives across sessions.

Matching model
--------------

Patterns are matched against the full command string. Two strategies,
in order:

1. If the pattern contains a wildcard (``*``, ``?``, ``[``), treat it
   as an :mod:`fnmatch` glob.
2. Otherwise, the command must either equal the pattern, or start
   with ``"<pattern> "`` (a literal space). This is what the user
   means by "trust ``ls``": they want ``ls`` and ``ls -la`` to
   succeed, not ``lsass`` or ``lsof`` to get a free pass.
"""

from __future__ import annotations

import enum
import fnmatch
import shlex
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from forgewright.logger import logger

__all__ = ["DenyRule", "TrustRegistry", "TrustRule", "TrustScope"]


class TrustScope(enum.StrEnum):
    """Where a :class:`TrustRule` lives and how long it persists.

    Values are stable on disk; do not rename them.
    """

    SESSION = "session"  # in-memory only
    REPO = "repo"  # .forgewright/trust.toml (v0.1: in-memory fallback)
    MACHINE = "machine"  # ~/.config/forgewright/trust.toml


@dataclass(frozen=True)
class TrustRule:
    """A single allowlist entry.

    Attributes:
        pattern: The match pattern. Wildcards (``*``, ``?``, ``[``)
            make it a :mod:`fnmatch` glob; otherwise the command must
            equal the pattern or start with ``"<pattern> "``.
        scope: Where the rule lives; see :class:`TrustScope`.
        added_at: ISO-8601 timestamp of when the rule was created.
        reason: Free-form human note ("user typed 'a' at prompt", etc.).
    """

    pattern: str
    scope: TrustScope
    added_at: str
    reason: str = ""

    def to_toml_dict(self) -> dict[str, str]:
        """Render as a dict suitable for ``[[rule]]`` in TOML."""
        return {
            "pattern": self.pattern,
            "scope": self.scope.value,
            "added_at": self.added_at,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DenyRule:
    """A single denylist entry.

    A pattern in this list is *forbidden* — even if the same pattern
    (or a more permissive one) is in the trust allowlist, the deny
    rule wins. This matches the principle of least surprise: the
    user can say "never run ``rm -rf *`` again" with one keypress and
    it sticks across sessions.

    Attributes:
        pattern: The match pattern. Same matching rules as
            :class:`TrustRule` (fnmatch glob if it contains ``*``,
            ``?``, or ``[``; otherwise exact-or-prefix-with-space).
        added_at: ISO-8601 timestamp of when the rule was created.
        reason: Free-form human note ("user typed 'd' at prompt").
    """

    pattern: str
    added_at: str
    reason: str = ""

    def to_toml_dict(self) -> dict[str, str]:
        """Render as a dict suitable for ``[[deny]]`` in TOML."""
        return {
            "pattern": self.pattern,
            "added_at": self.added_at,
            "reason": self.reason,
        }


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 with a ``Z`` suffix (matches audit log)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _rule_matches(command: str, pattern: str) -> bool:
    """Return True if ``command`` is allowed by ``pattern``.

    A wildcard in ``pattern`` switches to :mod:`fnmatch`; otherwise the
    match is exact-or-prefix-with-a-single-space (so ``ls`` matches
    ``ls`` and ``ls -la`` but not ``lsof``).
    """
    if not command or not pattern:
        return False
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(command, pattern)
    return command == pattern or command.startswith(pattern + " ")


class TrustRegistry:
    """Persistent + in-memory allowlist of command patterns.

    The :class:`TrustRegistry` keeps an in-memory list of :class:`TrustRule`s
    that the Bash tool consults on every call. The machine-scoped
    subset is mirrored to ``self._path`` (defaulting to
    ``Settings.security.trust``) on every mutation so the registry is
    crash-safe and easy to edit by hand.

    Session and repo rules are never written to disk in v0.1.
    """

    _DEFAULT_PATH: ClassVar[str] = str(Path.home() / ".config" / "forgewright" / "trust.toml")

    def __init__(
        self,
        machine_path: str | Path | None = None,
        *,
        repo_path: str | Path | None = None,
        load_repo_trust: bool = True,
    ) -> None:
        """Build a TrustRegistry.

        Args:
            machine_path: Override the on-disk path for MACHINE rules.
                Defaults to ``~/.config/forgewright/trust.toml``.
            repo_path: Directory to start the upward search from when
                looking for a project-scoped ``.forgewright/trust.toml``.
                Defaults to the current working directory at construction
                time. Pass an explicit value to make this testable.
            load_repo_trust: When ``False`` (e.g. for tests that do not
                want to pick up a stray ``.forgewright/trust.toml`` in
                ``cwd``), skip the REPO scope load entirely.
        """
        self._path: Path = Path(machine_path) if machine_path else Path(self._DEFAULT_PATH)
        # Rules in memory. MACHINE rules that came from disk are loaded
        # at init; SESSION/REPO rules accumulate over the process
        # lifetime. Deny rules live in their own map for O(1) lookup
        # precedence (deny always wins over allow).
        self._rules: dict[str, TrustRule] = {}
        self._deny_rules: dict[str, DenyRule] = {}
        self._load_from_disk()
        if load_repo_trust:
            start = Path(repo_path) if repo_path else Path.cwd()
            self._load_repo_trust(start)

    # ------------------------------------------------------------------ #
    # Disk I/O
    # ------------------------------------------------------------------ #

    def _load_from_disk(self) -> None:
        """Load MACHINE rules and deny rules from disk; ignore schema errors."""
        if not self._path.exists():
            return
        try:
            with self._path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            logger.warning("trust.load: failed to parse {}: {}", self._path, exc)
            return

        for entry in data.get("rule", []) or []:
            try:
                rule = TrustRule(
                    pattern=str(entry["pattern"]),
                    scope=TrustScope(str(entry.get("scope", "machine"))),
                    added_at=str(entry.get("added_at", "")),
                    reason=str(entry.get("reason", "")),
                )
            except (KeyError, ValueError) as exc:
                logger.warning("trust.load: skipping malformed rule {}: {}", entry, exc)
                continue
            # De-dupe: in-memory wins if it has the same pattern.
            if rule.pattern not in self._rules:
                self._rules[rule.pattern] = rule

        for entry in data.get("deny", []) or []:
            try:
                rule = DenyRule(
                    pattern=str(entry["pattern"]),
                    added_at=str(entry.get("added_at", "")),
                    reason=str(entry.get("reason", "")),
                )
            except (KeyError, ValueError) as exc:
                logger.warning("trust.load: skipping malformed deny rule {}: {}", entry, exc)
                continue
            if rule.pattern not in self._deny_rules:
                self._deny_rules[rule.pattern] = rule

    def _load_repo_trust(self, start: Path) -> None:
        """Walk up from ``start`` looking for ``.forgewright/trust.toml``.

        REPO rules are loaded into the in-memory registry but are never
        written back to disk by :meth:`_persist` (that path only handles
        MACHINE rules). Adding a REPO rule via the API mutates the
        in-memory list only — the file on disk must be edited by hand
        or by ``forgewright trust add --scope repo``.

        Search stops at the first hit or at the filesystem root,
        whichever comes first.
        """
        cur = start.resolve() if start.exists() else start
        for directory in (cur, *cur.parents):
            candidate = directory / ".forgewright" / "trust.toml"
            if not candidate.exists():
                continue
            try:
                with candidate.open("rb") as f:
                    data = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                logger.warning("trust.repo_load: failed to parse {}: {}", candidate, exc)
                return
            for entry in data.get("rule", []) or []:
                try:
                    rule = TrustRule(
                        pattern=str(entry["pattern"]),
                        scope=TrustScope.REPO,
                        added_at=str(entry.get("added_at", "")),
                        reason=str(entry.get("reason", "")),
                    )
                except (KeyError, ValueError) as exc:
                    logger.warning(
                        "trust.repo_load: skipping malformed rule {}: {}", entry, exc
                    )
                    continue
                # REPO rules lose to MACHINE rules on a pattern collision
                # (machine > repo > session is the resolution order).
                existing = self._rules.get(rule.pattern)
                if existing and existing.scope == TrustScope.MACHINE:
                    continue
                self._rules[rule.pattern] = rule
            # First hit wins; do not walk past it.
            return

    def _persist(self) -> None:
        """Write all MACHINE-scoped rules + deny rules back to disk as TOML.

        We do the write manually (no third-party TOML writer) so the
        registry has no new dep. The format is the same as
        :meth:`__init__` expects to read back.
        """
        machine_rules = [r for r in self._rules.values() if r.scope == TrustScope.MACHINE]
        deny_rules = list(self._deny_rules.values())
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                f.write("# forgewright trust registry — managed by `forgewright trust`.\n")
                f.write("# Hand-edits are preserved; broken entries are skipped on load.\n")
                for rule in machine_rules:
                    f.write("\n[[rule]]\n")
                    f.write(f"pattern = {toml_quote(rule.pattern)}\n")
                    f.write(f"scope = {toml_quote(rule.scope.value)}\n")
                    f.write(f"added_at = {toml_quote(rule.added_at)}\n")
                    f.write(f"reason = {toml_quote(rule.reason)}\n")
                for rule in deny_rules:
                    f.write("\n[[deny]]\n")
                    f.write(f"pattern = {toml_quote(rule.pattern)}\n")
                    f.write(f"added_at = {toml_quote(rule.added_at)}\n")
                    f.write(f"reason = {toml_quote(rule.reason)}\n")
        except OSError as exc:
            logger.warning("trust.persist: failed to write {}: {}", self._path, exc)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def is_allowed(self, command: str) -> bool:
        """Return True if ``command`` is allowed by at least one rule.

        A rule with pattern ``ls`` matches ``ls`` and ``ls -la`` but
        not ``lsof``. A rule with pattern ``git *`` matches anything
        starting with ``git`` (see :func:`_rule_matches`).

        **Deny rules always win.** A command matched by a deny rule
        returns ``False`` even if an allow rule also matches it.
        This is the principle of least surprise: the user can say
        "never run ``rm -rf *``" and trust that nothing in the
        allowlist will override that.
        """
        if any(_rule_matches(command, d.pattern) for d in self._deny_rules.values()):
            return False
        return any(_rule_matches(command, r.pattern) for r in self._rules.values())

    def is_denied(self, command: str) -> bool:
        """Return True if ``command`` matches a deny rule."""
        return any(_rule_matches(command, d.pattern) for d in self._deny_rules.values())

    def add(
        self,
        pattern: str,
        scope: TrustScope = TrustScope.MACHINE,
        reason: str = "",
    ) -> TrustRule:
        """Add (or replace) a rule.

        Returns the :class:`TrustRule` that ended up in the registry.
        MACHINE-scoped rules are persisted immediately; SESSION and
        REPO rules live only in memory.
        """
        rule = TrustRule(
            pattern=pattern,
            scope=scope,
            added_at=_now_iso(),
            reason=reason,
        )
        # Replace any existing rule with the same pattern. The new
        # scope / reason win — this matches what the user expects when
        # they run `forgewright trust add "git *"` after a session
        # rule for the same pattern.
        self._rules[pattern] = rule
        if scope == TrustScope.MACHINE:
            self._persist()
        else:
            logger.debug("trust.add: in-memory rule pattern={} scope={}", pattern, scope.value)
        return rule

    def remove(self, pattern: str) -> bool:
        """Remove a rule. Returns True if a rule was removed.

        MACHINE rules are persisted immediately; the in-memory list is
        always updated.
        """
        rule = self._rules.pop(pattern, None)
        if rule is None:
            return False
        if rule.scope == TrustScope.MACHINE:
            self._persist()
        return True

    def list_rules(self) -> list[TrustRule]:
        """Return a copy of all rules, in insertion order."""
        return list(self._rules.values())

    # ------------------------------------------------------------------ #
    # Deny rules
    # ------------------------------------------------------------------ #

    def add_deny(self, pattern: str, reason: str = "") -> DenyRule:
        """Add (or replace) a deny rule. Persists to the on-disk registry.

        The on-disk format is ``[[deny]]``; deny rules are kept in the
        same file as allow rules for simplicity. The in-memory map is
        always updated, then the file is rewritten.
        """
        rule = DenyRule(pattern=pattern, added_at=_now_iso(), reason=reason)
        self._deny_rules[pattern] = rule
        self._persist()
        return rule

    def remove_deny(self, pattern: str) -> bool:
        """Remove a deny rule. Returns True if a rule was removed."""
        rule = self._deny_rules.pop(pattern, None)
        if rule is None:
            return False
        self._persist()
        return True

    def list_deny_rules(self) -> list[DenyRule]:
        """Return a copy of all deny rules, in insertion order."""
        return list(self._deny_rules.values())

    def clear_session(self) -> None:
        """Drop all SESSION-scoped rules (no-op for MACHINE / REPO)."""
        self._rules = {p: r for p, r in self._rules.items() if r.scope != TrustScope.SESSION}

    @property
    def path(self) -> Path:
        """The on-disk path used for MACHINE rules."""
        return self._path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def toml_quote(value: str) -> str:
    """Quote a string for the basic-string TOML form (double-quote delimited).

    We only emit ASCII identifiers in the trust file, but the quote
    logic is conservative: backslashes and double-quotes are escaped.
    Multi-line values would need a triple-quoted TOML basic string;
    the registry does not produce those, so we keep this simple.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def derive_pattern(command: str) -> str:
    """Pick a sensible ``fnmatch`` pattern for an approval "always" rule.

    The Bash tool's interactive prompt derives the pattern from the
    command's first word so a rule added for ``git status`` does not
    silently cover ``git push --force`` too. A trailing space + ``*``
    is appended (e.g. ``"ls *"``) so the pattern matches the common
    case where the user wants arguments to also pass.

    Edge cases:
      * Empty / whitespace-only command → returns ``""``.
      * Tokenization failure (e.g. unbalanced quotes) → returns the
        stripped first whitespace-delimited word.
    """
    if not command or not command.strip():
        return ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command.split()[0] if command.split() else ""
    if not tokens:
        return ""
    first = tokens[0].rsplit("/", 1)[-1]  # strip /usr/bin/git prefix
    return f"{first} *"
