"""Verification Engine — completion authority from Evidence, not model text."""

from .engine import VerificationEngine
from .store import VerificationReportStore
from .types import (
    RequirementResult,
    VerificationOutcome,
    VerificationReport,
    VerificationRequirement,
)

__all__ = [
    "RequirementResult",
    "VerificationEngine",
    "VerificationOutcome",
    "VerificationReport",
    "VerificationReportStore",
    "VerificationRequirement",
]
