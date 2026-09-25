"""User steering classification — preserve valid constraints; don't flatten intents.

Invalidation scopes make mid-turn corrections surgical: corrections do not wipe
goals/constraints; goal replacement does not wipe hard constraints; status
requests mutate nothing.
"""

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
class InvalidationScope:
    """What a steering event may invalidate — explicit, not blind wipe."""

    plan: bool = False
    current_action: bool = False
    open_hypotheses: bool = False
    response_draft: bool = False
    pending_worker: bool = False
    goal: bool = False
    constraints: bool = False  # almost never true
    beliefs: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "current_action": self.current_action,
            "open_hypotheses": self.open_hypotheses,
            "response_draft": self.response_draft,
            "pending_worker": self.pending_worker,
            "goal": self.goal,
            "constraints": self.constraints,
            "beliefs": self.beliefs,
            "truth": {
                "invalidation_is_scoped": True,
                "not_blind_full_reset": True,
                "valid_constraints_preserved_unless_scoped": not self.constraints,
            },
        }


# Per-kind default scopes (program: mid-turn corrections are scoped).
_SCOPES: dict[SteerKind, InvalidationScope] = {
    SteerKind.STATUS_REQUEST: InvalidationScope(),
    SteerKind.CLARIFICATION: InvalidationScope(
        response_draft=True,
    ),
    SteerKind.NEW_CONSTRAINT: InvalidationScope(
        plan=True,
        current_action=True,
        pending_worker=True,
    ),
    SteerKind.CORRECTION: InvalidationScope(
        plan=True,
        current_action=True,
        response_draft=True,
        pending_worker=True,
        open_hypotheses=False,  # corrections refine; do not wipe hypotheses
        beliefs=False,
    ),
    SteerKind.GOAL_REPLACEMENT: InvalidationScope(
        plan=True,
        current_action=True,
        response_draft=True,
        pending_worker=True,
        open_hypotheses=True,
        goal=True,
        # constraints stay unless explicitly superseded elsewhere
    ),
    SteerKind.UNKNOWN: InvalidationScope(
        plan=True,
        pending_worker=True,
    ),
}


@dataclass(frozen=True)
class SteerClassification:
    kind: SteerKind
    text: str
    preserves_existing_constraints: bool
    replaces_goal: bool
    detail: str
    invalidation: InvalidationScope = InvalidationScope()

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "preserves_existing_constraints": self.preserves_existing_constraints,
            "replaces_goal": self.replaces_goal,
            "detail": self.detail,
            "invalidation": self.invalidation.public_dict(),
            "truth": {
                "steering_is_not_blind_append": True,
                "valid_constraints_are_preserved": self.preserves_existing_constraints,
                "invalidation_is_scoped": True,
            },
        }


def invalidation_scope_for(kind: SteerKind) -> InvalidationScope:
    return _SCOPES.get(kind, InvalidationScope(plan=True))


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
            invalidation=InvalidationScope(),
        )
    if _STATUS.search(text):
        kind = SteerKind.STATUS_REQUEST
        return SteerClassification(
            kind=kind,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="status inquiry — no plan mutation required",
            invalidation=invalidation_scope_for(kind),
        )
    if _GOAL_REPLACE.search(text):
        kind = SteerKind.GOAL_REPLACEMENT
        return SteerClassification(
            kind=kind,
            text=text,
            preserves_existing_constraints=True,  # constraints still bind unless contradicted
            replaces_goal=True,
            detail="goal replacement — preserve prior constraints unless superseded",
            invalidation=invalidation_scope_for(kind),
        )
    if _CORRECTION.search(text):
        kind = SteerKind.CORRECTION
        return SteerClassification(
            kind=kind,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="correction of prior approach",
            invalidation=invalidation_scope_for(kind),
        )
    if _CONSTRAINT.search(text):
        kind = SteerKind.NEW_CONSTRAINT
        return SteerClassification(
            kind=kind,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="additional hard/soft constraint",
            invalidation=invalidation_scope_for(kind),
        )
    if _CLARIFICATION.search(text) or text.endswith("?"):
        kind = SteerKind.CLARIFICATION
        return SteerClassification(
            kind=kind,
            text=text,
            preserves_existing_constraints=True,
            replaces_goal=False,
            detail="clarification request",
            invalidation=invalidation_scope_for(kind),
        )
    kind = SteerKind.UNKNOWN
    return SteerClassification(
        kind=kind,
        text=text,
        preserves_existing_constraints=True,
        replaces_goal=False,
        detail="generic steering note",
        invalidation=invalidation_scope_for(kind),
    )
