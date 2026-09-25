"""Evaluation harness — honest PASSED/FAILED/UNMEASURED outcomes + Wave 2/5 platform."""

from .ablations import ABLATION_FEATURES, AblationReport, run_all_ablations, run_feature_ablation
from .assistant_benchmark import (
    AssistantBenchmarkRunner,
    AssistantTask,
    TaskFamily,
    TaskRunMetrics,
    TaskRunResult,
    default_assistant_tasks,
)
from .frontier_reasoning import (
    FRONTIER_ABLATION_FEATURES,
    FRONTIER_SUITE_ID,
    frontier_ablation_public_bundle,
    frontier_reasoning_suite,
    run_all_frontier_ablations,
    run_frontier_feature_ablation,
    run_frontier_probe,
    run_frontier_reasoning_suite,
)
from .harness import EvaluationHarness
from .paired import PairedEvaluationReport, run_paired_evaluation
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
    "ABLATION_FEATURES",
    "AblationReport",
    "AssistantBenchmarkRunner",
    "AssistantTask",
    "EvalCase",
    "EvalCaseResult",
    "EvalOutcome",
    "EvalReport",
    "EvaluationHarness",
    "EvaluationPlatform",
    "EvaluationStore",
    "FRONTIER_ABLATION_FEATURES",
    "FRONTIER_SUITE_ID",
    "JudgmentKind",
    "MeasurementState",
    "PairedEvaluationReport",
    "RegressionCase",
    "Scorecard",
    "ScorecardEntry",
    "TaskFamily",
    "TaskRunMetrics",
    "TaskRunResult",
    "build_scorecard",
    "default_assistant_tasks",
    "frontier_ablation_public_bundle",
    "frontier_reasoning_suite",
    "measurement_is_pass",
    "outcome_to_measurement",
    "run_all_ablations",
    "run_all_frontier_ablations",
    "run_feature_ablation",
    "run_frontier_feature_ablation",
    "run_frontier_probe",
    "run_frontier_reasoning_suite",
    "run_paired_evaluation",
    "scorecard_from_report_dicts",
    "seed_default_regressions",
]
