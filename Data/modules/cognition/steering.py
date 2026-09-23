"""User steering classification — preserve valid constraints; don't flatten intents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SteerKind(str, Enum):
    CORRECTION = "correction"
    NEW_CONSTRAINT = "new_constraint"
    GOAL_REPLACEMENT = "goal_replacement"
    CLARIFICATION = "clarification"
    STATUS_REQUEST = "status_request"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SteerClassification:
    kind: SteerKind
    text: str
    preserves_existing_constraints: bool
    replaces_goal: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "preserves_existing_constraints": self.preserves_existing_constraints,
            "replaces_goal": self.replaces_goal,
            "detail": self.detail,
            "truth": {
                "steering_is_not_blind_append": True,
                "valid_constraints_are_preserved": self.preserves_existing_constraints,
            },
        }


_STATUS = re.compile(
    r"\b(status|voortgang|progress|where\s+are\s+we|hoe\s+ver|wat\s+is\s+de\s+stand)\b",
    re.I,
)
_CORRECTION = re.compile(
    r"\b(fout|wrong|incorrect|nee[, ]|no[, ]|corrigeer|correct(?:ion)?|fix\s+that|"
    r"dat\s+klopt\s+niet|that's\s+wrong)\b",
    re.I,
)
_CONSTRAINT = re.compile(
    r"\b(moet|moeten|nooit|altijd|uitsluitend|never|always|must|don't|do not|"
    r"constraint|regel|voorwaarde)\b",
    re.I,
)
_GOAL_REPLACE = re.compile(
    r"\b(in\s+plaats\s+van|instead|new\s+goal|ander\s+doel|vergeet\s+het\s+vorige|"
    r"forget\s+(?:the\s+)?(?:previous|old)\s+goal|replace\s+the\s+goal|"
    r"stop\s+and\s+(?:do|make)|nu\s+wil\s+ik)\b",
    re.I,
)
_CLARIFICATION = re.compile(
    r"\b(bedoel|mean(?:ing)?|clarif|toelicht|leg\s+uit|wat\s+bedoel|"
    r"can\s+you\s+explain|precieser)\b",
    re.I,
)


def classify_steer(instruction: str) -> SteerClassification:
    text = (instruction or "").strip()
    if not text:
        return SteerClassification(
            kind=SteerKind.UNKNOWN,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="empty",
        )
    if _STATUS.search(text):
        return SteerClassification(
            kind=SteerKind.STATUS_REQUEST,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="status inquiry — no plan mutation required",
        )
    if _GOAL_REPLACE.search(text):
        return SteerClassification(
            kind=SteerKind.GOAL_REPLACEMENT,
            text=text,
            preserves_existing_constraints=True,  # constraints still bind unless contradicted
            replaces_goal=True,
            detail="goal replacement — preserve prior constraints unless superseded",
        )
    if _CORRECTION.search(text):
        return SteerClassification(
            kind=SteerKind.CORRECTION,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="correction of prior approach",
        )
    if _CONSTRAINT.search(text):
        return SteerClassification(
            kind=SteerKind.NEW_CONSTRAINT,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="additional hard/soft constraint",
        )
    if _CLARIFICATION.search(text) or text.endswith("?"):
        return SteerClassification(
            kind=SteerKind.CLARIFICATION,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="clarification request",
        )
    return SteerClassification(
        kind=SteerKind.UNKNOWN,
        text=text,
        preserves_existing_constraints=True,
        replaces_goal=False,
        detail="generic steering note",
    )
