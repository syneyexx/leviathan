from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvalOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNMEASURED = "UNMEASURED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    description: str
    check: str  # capability_exists | evidence_verified | always_unmeasured
    params: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "description": self.description,
            "check": self.check,
            "params": self.params,
        }


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    outcome: EvalOutcome
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class EvalReport:
    suite_id: str
    name: str
    results: tuple[EvalCaseResult, ...]
    summary: dict[str, int]

    def public_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "results": [item.public_dict() for item in self.results],
            "summary": self.summary,
            "truth": {
                "unmeasured_is_not_passed": True,
                "evaluation_is_not_production_proof": True,
            },
        }
