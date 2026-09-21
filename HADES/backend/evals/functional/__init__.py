"""HADES Functional Hardening Campaign — measurement-first eval layer.

Extends Eval Lab / existing suites. Does not replace them.
Separates Layer A (infra), B (deterministic), C (real-model), D (comparative).

Principle: architecture is not capability until measured.
"""

from __future__ import annotations

from evals.functional.schema import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkRecord,
    ModelIdentity,
    new_record,
)
from evals.functional.taxonomy import (
    CAMPAIGN_FAILURE_CLASSES,
    CAMPAIGN_TAXONOMY_VERSION,
    classify_campaign_failure,
    map_to_legacy_failure_class,
)
from evals.functional.scoreboard import QualityScoreboard, ScoreLayer, build_scoreboard

__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "BenchmarkRecord",
    "ModelIdentity",
    "new_record",
    "CAMPAIGN_FAILURE_CLASSES",
    "CAMPAIGN_TAXONOMY_VERSION",
    "classify_campaign_failure",
    "map_to_legacy_failure_class",
    "QualityScoreboard",
    "ScoreLayer",
    "build_scoreboard",
]
