"""Approvals + Policy — gate WRITE+ capability execution."""

from .authority import (
    DEFAULT_AUTHORITY_PROFILE,
    ApprovalMode,
    AuthorityProfile,
    ResourceCeilings,
)
from .policy import AUTO_ALLOWED_EFFECTS, PolicyEngine
from .service import ApprovalService
from .store import ApprovalStore
from .types import ApprovalRecord, ApprovalStatus, PolicyDecision

__all__ = [
    "AUTO_ALLOWED_EFFECTS",
    "ApprovalMode",
    "ApprovalRecord",
    "ApprovalService",
    "ApprovalStatus",
    "ApprovalStore",
    "AuthorityProfile",
    "DEFAULT_AUTHORITY_PROFILE",
    "PolicyDecision",
    "PolicyEngine",
    "ResourceCeilings",
]
