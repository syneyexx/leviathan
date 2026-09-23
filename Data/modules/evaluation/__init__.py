"""Evaluation harness — honest PASSED/FAILED/UNMEASURED outcomes + Wave 2 platform."""

from .harness import EvaluationHarness
from .platform import EvaluationPlatform
from .scorecard import build_scorecard, scorecard_from_report_dicts
from .store import EvaluationStore, seed_default_regressions
from .types import (
    EvalCase,
    EvalCaseResult,
    EvalOutcome,
    EvalReport,
    JudgmentKind,
    MeasurementState,
    RegressionCase,
    Scorecard,
    ScorecardEntry,
    measurement_is_pass,
    outcome_to_measurement,
)

__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalOutcome",
    "EvalReport",
    "EvaluationHarness",
    "EvaluationPlatform",
    "EvaluationStore",
    "JudgmentKind",
    "MeasurementState",
    "RegressionCase",
    "Scorecard",
    "ScorecardEntry",
    "build_scorecard",
    "measurement_is_pass",
    "outcome_to_measurement",
    "scorecard_from_report_dicts",
    "seed_default_regressions",
]
