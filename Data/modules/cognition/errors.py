"""Structured cognition errors — follow repository error conventions."""

from __future__ import annotations

from typing import Any


class CognitionError(Exception):
    """Base cognitive runtime error."""

    code = "COGNITION_ERROR"
    http_status = 400

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})

    def public_dict(self) -> dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class CognitionBudgetExhausted(CognitionError):
    code = "COGNITION_BUDGET_EXHAUSTED"
    http_status = 429


class CognitionLoopDetected(CognitionError):
    code = "COGNITION_LOOP_DETECTED"
    http_status = 409


class CognitionPlanInvalid(CognitionError):
    code = "COGNITION_PLAN_INVALID"
    http_status = 400


class CognitionModelUnavailable(CognitionError):
    code = "COGNITION_MODEL_UNAVAILABLE"
    http_status = 503


class CognitionCapabilityUnavailable(CognitionError):
    code = "COGNITION_CAPABILITY_UNAVAILABLE"
    http_status = 503


class CognitionApprovalRequired(CognitionError):
    code = "COGNITION_APPROVAL_REQUIRED"
    http_status = 409


class CognitionDelegationFailed(CognitionError):
    code = "COGNITION_DELEGATION_FAILED"
    http_status = 502


class CognitionVerificationFailed(CognitionError):
    code = "COGNITION_VERIFICATION_FAILED"
    http_status = 422


class CognitionCancelled(CognitionError):
    code = "COGNITION_CANCELLED"
    http_status = 499


class CognitionResourceExhausted(CognitionError):
    code = "COGNITION_RESOURCE_EXHAUSTED"
    http_status = 429


class CognitionTransitionInvalid(CognitionError):
    code = "COGNITION_TRANSITION_INVALID"
    http_status = 409


class CognitionFeatureDisabled(CognitionError):
    code = "COGNITION_FEATURE_DISABLED"
    http_status = 404
