"""Research curriculum — logged, reproducible stage progression (W14).

synthetic easy → synthetic hostile → historical train → validation →
robustness → sealed → paper. Curriculum itself is an auditable artifact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CurriculumStage(str, Enum):
    SYNTHETIC_EASY = "synthetic_easy"
    SYNTHETIC_HOSTILE = "synthetic_hostile"
    HISTORICAL_TRAIN = "historical_train"
    VALIDATION = "validation"
    ROBUSTNESS = "robustness"
    SEALED = "sealed"
    PAPER = "paper"


STAGE_ORDER = (
    CurriculumStage.SYNTHETIC_EASY,
    CurriculumStage.SYNTHETIC_HOSTILE,
    CurriculumStage.HISTORICAL_TRAIN,
    CurriculumStage.VALIDATION,
    CurriculumStage.ROBUSTNESS,
    CurriculumStage.SEALED,
    CurriculumStage.PAPER,
)


@dataclass
class CurriculumStepResult:
    stage: CurriculumStage
    passed: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "passed": self.passed,
            "evidence": dict(self.evidence),
            "notes": self.notes,
        }


@dataclass
class ResearchCurriculum:
    curriculum_id: str
    seed: int = 42
    current_index: int = 0
    results: list[CurriculumStepResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def current_stage(self) -> CurriculumStage | None:
        if self.current_index < 0 or self.current_index >= len(STAGE_ORDER):
            return None
        return STAGE_ORDER[self.current_index]

    def content_hash(self) -> str:
        blob = json.dumps(
            {
                "curriculum_id": self.curriculum_id,
                "seed": self.seed,
                "stages": [s.value for s in STAGE_ORDER],
                "results": [r.public_dict() for r in self.results],
                "current_index": self.current_index,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def advance(self, *, passed: bool, evidence: dict[str, Any] | None = None, notes: str = "") -> CurriculumStage | None:
        stage = self.current_stage
        if stage is None:
            return None
        self.results.append(
            CurriculumStepResult(stage=stage, passed=passed, evidence=dict(evidence or {}), notes=notes)
        )
        if passed:
            self.current_index += 1
        return self.current_stage

    def public_dict(self) -> dict[str, Any]:
        return {
            "curriculum_id": self.curriculum_id,
            "seed": self.seed,
            "current_index": self.current_index,
            "current_stage": self.current_stage.value if self.current_stage else None,
            "stages": [s.value for s in STAGE_ORDER],
            "results": [r.public_dict() for r in self.results],
            "content_hash": self.content_hash(),
            "metadata": dict(self.metadata),
            "truth": {
                "logged_and_reproducible": True,
                "sealed_is_late_stage": True,
                "no_skip_without_record": True,
            },
        }


def new_curriculum(*, curriculum_id: str, seed: int = 42, metadata: dict[str, Any] | None = None) -> ResearchCurriculum:
    return ResearchCurriculum(
        curriculum_id=curriculum_id,
        seed=seed,
        metadata=dict(metadata or {}),
    )
