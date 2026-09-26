"""Verification Engine — completion authority from Evidence, not model text."""

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
    "VerificationEngine",
    "VerificationOutcome",
    "VerificationPool",
    "VerificationReport",
    "VerificationReportStore",
    "VerificationRequirement",
]
