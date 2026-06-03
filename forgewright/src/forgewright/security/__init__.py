"""Security layer: command denylist, approval flow, trust registry, audit log."""

from __future__ import annotations

from forgewright.security.approval import ApprovalDecision, ApprovalFlow, ApprovalResult
from forgewright.security.audit import AuditEvent, AuditLog, AuditVerifyResult
from forgewright.security.denylist import (
    DANGEROUS_PATTERNS,
    SAFE_BUILTINS,
    DenylistMatch,
    check_command,
)
from forgewright.security.trust import TrustRegistry, TrustRule, TrustScope

__all__ = [
    "DANGEROUS_PATTERNS",
    "SAFE_BUILTINS",
    "ApprovalDecision",
    "ApprovalFlow",
    "ApprovalResult",
    "AuditEvent",
    "AuditLog",
    "AuditVerifyResult",
    "DenylistMatch",
    "TrustRegistry",
    "TrustRule",
    "TrustScope",
    "check_command",
]
