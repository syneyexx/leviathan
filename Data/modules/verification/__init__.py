"""Verification Engine — completion authority from Evidence, not model text."""

from .capability_state import SystemCapabilityState, build_system_capability_state
from .claims import (
    ClaimAssessment,
    ClaimExtractor,
    ClaimKind,
    ClaimSupportStatus,
    ClaimVerifier,
    FactualityGate,
    FactualityMode,
    FactualityResult,
    VerificationPool,
)
from .engine import VerificationEngine
from .store import VerificationReportStore
from .types import (
    CriterionVerificationStatus,
    RequirementResult,
    VerificationOutcome,
    VerificationReport,
    VerificationRequirement,
    VerificationTier,
    VerifierKind,
)

__all__ = [
    "ClaimAssessment",
    "ClaimExtractor",
    "ClaimKind",
    "ClaimSupportStatus",
    "ClaimVerifier",
    "CriterionVerificationStatus",
    "FactualityGate",
    "FactualityMode",
    "FactualityResult",
    "RequirementResult",
    "SystemCapabilityState",
    "VerificationEngine",
    "VerificationOutcome",
    "VerificationPool",
    "VerificationReport",
    "VerificationReportStore",
    "VerificationRequirement",
    "VerificationTier",
    "VerifierKind",
    "build_system_capability_state",
]
