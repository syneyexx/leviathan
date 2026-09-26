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
from .compute_paired import (
    BootstrapResult,
    ComputeTrial,
    PairedComputeReport,
    analyze_paired_compute,
    paired_bootstrap,
    run_paired_compute_evaluation,
)
from .harness import EvaluationHarness
from .judge_calibration import (
    JudgeCalibrationReport,
    LabeledJudgeExample,
    calibrate_judge,
    judge_or_unmeasured,
)
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
    "BootstrapResult",
    "ComputeTrial",
    "EvalCase",
    "EvalCaseResult",
    "EvalOutcome",
    "EvalReport",
    "EvaluationHarness",
    "EvaluationPlatform",
    "EvaluationStore",
    "JudgeCalibrationReport",
    "JudgmentKind",
    "LabeledJudgeExample",
    "MeasurementState",
    "PairedComputeReport",
    "PairedEvaluationReport",
    "RegressionCase",
    "Scorecard",
    "ScorecardEntry",
    "TaskFamily",
    "TaskRunMetrics",
    "TaskRunResult",
    "analyze_paired_compute",
    "build_scorecard",
    "calibrate_judge",
    "default_assistant_tasks",
    "judge_or_unmeasured",
    "measurement_is_pass",
    "outcome_to_measurement",
    "paired_bootstrap",
    "run_all_ablations",
    "run_feature_ablation",
    "run_paired_compute_evaluation",
    "run_paired_evaluation",
    "scorecard_from_report_dicts",
    "seed_default_regressions",
]
