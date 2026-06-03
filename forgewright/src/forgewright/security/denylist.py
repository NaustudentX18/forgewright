"""Dangerous-command denylist for the Bash tool.

Hard-coded regex patterns that, when matched against a shell command,
block execution. Phase 10 wires interactive approval; for now, the
denylist is the gate.

The full 20-pattern design lives in ``SECURITY.md`` §5. The first 9 are
the truly catastrophic operations (rm -rf /, curl|sh, kill 1, mkfs, dd to
disk, etc.); the remaining 11 are dangerous-but-sometimes-OK (sudo, ssh,
scp, wget, …). For Phase 4 we hard-block **all 20** — Phase 10 will move
the second group behind an interactive approval prompt.

The check is two-stage:
1. If the FIRST token of the command is a member of ``SAFE_BUILTINS``,
   the command is allowed through without a regex scan.
2. Otherwise, the full string is scanned with ``re.search`` against
   ``DANGEROUS_PATTERNS`` in order. The first hit is returned.

Notes on the regexes
--------------------
* They are intentionally coarse — we accept some false positives in
  exchange for catching the family. The sandbox is the real security
  boundary; this denylist is a UX shortcut (see ``SECURITY.md`` §5
  "Limitations").
* Whitespace runs (``\\s+``) tolerate ``rm  -rf   /`` style abuse.
* Word boundaries (``\\b``) prevent ``nuke`` from matching the ``nu``
  fragment of ``mkfs`` or similar.
* None of the patterns look for *only* the start of the string; payloads
  like ``cd /tmp && rm -rf /`` must still trip the denylist.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

__all__ = ["DANGEROUS_PATTERNS", "SAFE_BUILTINS", "DenylistMatch", "check_command"]


@dataclass(frozen=True)
class DenylistMatch:
    """A single dangerous-pattern hit.

    Attributes:
        pattern: The regex source that matched (for audit logging).
        description: A short human-readable description of the rule.
        matched_text: The substring that triggered the match.
    """

    pattern: str
    description: str
    matched_text: str


# 20 patterns, each (regex, human-readable description).
# Ordered roughly by severity (catastrophic first, dangerous-but-sometimes-OK last).
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # --- Tier 1: catastrophic, near-irreversible ---
    (
        r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+/\S*",
        "recursive force-delete targeting the root filesystem (rm -rf /…)",
    ),
    (
        r"\brm\s+-[a-zA-Z]*[rRfF][a-zA-Z]*\s+(\$\{?HOME\}?|[/~](home|workspace)\S*|~/?)",
        "recursive force-delete targeting the user's home directory (rm -rf ~, $HOME, /home/…)",
    ),
    (
        r":\(\)\s*\{[^}]*\|[^}]*&[^}]*\}\s*;?\s*:",
        "classic bash fork bomb",
    ),
    (
        r"(curl|wget|fetch)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|fish|csh|tcsh|ksh|dash|ash|python|python3|perl|ruby|node)\b",
        "piping a downloaded payload directly into a shell or interpreter (curl|sh)",
    ),
    (
        r"\bdd\s+[^|;&]*\bof\s*=\s*/dev/(sd|hd|nvme|vd|xvd|mmcblk|loop)",
        "raw disk write to a block device (dd of=/dev/…)",
    ),
    (
        r"\bmkfs(\.\w+)?\b[^|;&]*\s+/dev/(sd|hd|nvme|vd|xvd|mmcblk|loop|zd|nbd)",
        "formatting a filesystem on a block device (mkfs /dev/…)",
    ),
    (
        r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?(?:0?777|[a-zA-Z\-=]*7[RxWrXtT]{3,}|a=rwx[a-zA-Z]*)\s+/\s*($|&|;|\|)",
        "making the root filesystem world-writable (chmod 777 /)",
    ),
    (
        r"(?<![\w/])(>|>>)\s*/dev/(sd|hd|nvme|vd|xvd|mmcblk|loop|zd|nbd)",
        "shell redirection overwriting a block device (>/dev/sda)",
    ),
    (
        r"\bkill\s+(?:-9\s+|-KILL\s+|-s\s+9\s+|-s\s+KILL\s+)?1\b",
        "sending a signal to PID 1 (init / systemd)",
    ),
    # --- Tier 2: dangerous but legitimate in some workflows ---
    (
        r"\bmkfs(\.\w+)?\b",
        "filesystem format (mkfs.*); not always destructive but irreversible",
    ),
    (
        r"\bchown\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)[^\s|;&]+\s+/\s*($|&|;|\|)",
        "recursive chown of the root filesystem",
    ),
    (
        r"\bmv\s+/\S+\s+/dev/null\b",
        "moving an absolute path into /dev/null (destructive redirection via mv)",
    ),
    (
        r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|networking|network|firewalld|ufw|systemd-[\w-]+)\b",
        "disabling a critical system service (ssh, firewall, systemd-…)",
    ),
    (
        r"\biptables\s+-F\b",
        "flushing iptables rules (drops all firewall rules)",
    ),
    (
        r"\bpasswd\s+root\b",
        "changing the root password",
    ),
    (
        r"\buserdel\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)*root\b",
        "deleting the root user account",
    ),
    (
        r"\b(shutdown|poweroff|halt|reboot)\b(\s+(-[rRhHfc]+\s+)?(now|-?\s*\d+\s*|\"[^\"]*\"|'[^\']*'))?",
        "immediate shutdown / reboot / poweroff",
    ),
    (
        r"\bcrontab\s+-[rR]\b",
        "wiping the current crontab (crontab -r)",
    ),
    (
        r"\beval\s+[\"']?\$\(\s*(curl|wget|fetch)\b",
        "evaluating the result of a remote command (eval $(curl …))",
    ),
    (
        r"\bbase64\s+(-d|--decode)\b[^|;&]*\|\s*(sh|bash|zsh|fish|csh|tcsh|ksh|dash|ash|python|python3|perl|ruby|node)\b",
        "decoding base64 and piping into a shell (base64 -d | sh)",
    ),
]


# A small allowlist of safe builtins that NEVER trigger the denylist.
# Tokenization is via shlex.split, so quoting/leading whitespace are
# handled. Multi-token commands (e.g. "git status") use the first token.
#
# Note: ``echo`` and ``mv`` are deliberately EXCLUDED. ``echo`` accepts
# shell redirects (``echo x > /etc/passwd``) when invoked through
# ``asyncio.create_subprocess_shell``; ``mv`` can move sensitive paths
# to /dev/null. Both are checked against the regex denylist like any
# other command.
SAFE_BUILTINS: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "find",
        "tree",
        "printf",
        "pwd",
        "cd",
        "which",
        "whoami",
        "date",
        "git",
        "pytest",
        "python",
        "python3",
        "uv",
        "pip",
        "node",
        "mkdir",
        "touch",
        "cp",
    }
)


def check_command(cmd: str) -> DenylistMatch | None:
    """Return the first dangerous-pattern match, or None if the command is safe.

    The check is two-stage:

    1. Tokenize ``cmd`` with :func:`shlex.split`. If the first token is a
       member of :data:`SAFE_BUILTINS`, the command is allowed through
       without a regex scan. Tokenization errors fall through to stage 2.
    2. Otherwise, scan the full command string against
       :data:`DANGEROUS_PATTERNS` in order. Return the first match.

    Returns ``None`` when no pattern matches.
    """
    if not cmd:
        return None

    # Stage 1: SAFE_BUILTINS short-circuit.
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = []  # unbalanced quotes — let the denylist do the work
    if tokens:
        first = tokens[0]
        # Strip any path prefix (e.g. "/usr/bin/git" -> "git").
        bare = first.rsplit("/", 1)[-1]
        if bare in SAFE_BUILTINS:
            return None

    # Stage 2: full-string regex scan.
    for pattern, description in DANGEROUS_PATTERNS:
        match = re.search(pattern, cmd)
        if match is not None:
            return DenylistMatch(
                pattern=pattern,
                description=description,
                matched_text=match.group(0),
            )
    return None
