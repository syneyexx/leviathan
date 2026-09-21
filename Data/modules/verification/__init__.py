"""Verification Engine — completion authority from Evidence, not model text."""

from .engine import VerificationEngine
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
    "VerificationRequirement",
]
