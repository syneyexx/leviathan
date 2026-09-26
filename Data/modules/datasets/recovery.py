"""Typed dataset recovery assessment — DB → sidecar → catalog → filesystem.

Brain readiness is never inferred from the derived catalog; callers must use
``DatasetLearningState``. Missing indexes surface as ``REINDEX_REQUIRED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RecoveryState(str, Enum):
    READY = "READY"
    METADATA_RESTORED = "METADATA_RESTORED"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"
    SOURCE_MISSING = "SOURCE_MISSING"
    HASH_MISMATCH = "HASH_MISMATCH"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"


# Precedence for evidence when restoring or assessing.
RECOVERY_PRECEDENCE = ("db", "sidecar", "catalog", "filesystem")


@dataclass
class DatasetRecoveryAssessment:
    dataset_id: str
    state: RecoveryState
    evidence_source: str | None = None
    source_present: bool = False
    metadata_restored: bool = False
    content_hash_ok: bool | None = None
    brain_learned: bool = False
    reindex_required: bool = False
    tombstoned: bool = False
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    learning_canonical_state: str | None = None
    display_name: str | None = None
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "recoveryState": self.state.value,
            "state": self.state.value,
            "evidenceSource": self.evidence_source,
            "sourcePresent": self.source_present,
            "metadataRestored": self.metadata_restored,
            "contentHashOk": self.content_hash_ok,
            "brainLearned": self.brain_learned,
            "reindexRequired": self.reindex_required,
            "tombstoned": self.tombstoned,
            "conflicts": list(self.conflicts),
            "detail": self.detail,
            "learningCanonicalState": self.learning_canonical_state,
            "displayName": self.display_name,
            "truth": {
                "recoveryPrecedence": list(RECOVERY_PRECEDENCE),
                "brainStateNotFromCatalog": True,
                "catalogIsDerived": True,
                "datasetStoreIsCanonical": True,
                "tombstonesBlockResurrection": True,
                "reindexRequiredIsNotLearned": True,
                **dict(self.truth or {}),
            },
        }


def default_recovery_truth() -> dict[str, Any]:
    return {
        "recoveryPrecedence": list(RECOVERY_PRECEDENCE),
        "brainStateNotFromCatalog": True,
        "catalogIsDerived": True,
        "datasetStoreIsCanonical": True,
        "tombstonesBlockResurrection": True,
        "reindexRequiredIsNotLearned": True,
    }


__all__ = [
    "RECOVERY_PRECEDENCE",
    "DatasetRecoveryAssessment",
    "RecoveryState",
    "default_recovery_truth",
]
