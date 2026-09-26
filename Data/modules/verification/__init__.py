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
    RequirementResult,
    VerificationOutcome,
    VerificationReport,
    VerificationRequirement,
    VerificationTier,
)

__all__ = [
    "ClaimAssessment",
    "ClaimExtractor",
    "ClaimKind",
    "ClaimSupportStatus",
    "ClaimVerifier",
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
    "build_system_capability_state",
]
