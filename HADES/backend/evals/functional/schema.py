"""Machine-readable benchmark result schema for the functional campaign.

Every model-dependent result must identify HADES + MODEL, never HADES alone.
Do not commit huge raw logs — write compact JSON/JSONL only.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BENCHMARK_SCHEMA_VERSION = "hades_functional_benchmark_v1"

Outcome = Literal["success", "partial", "failure", "blocked", "not_run"]
TaskSplit = Literal["dev", "regression", "held_out", "synthetic"]
EvalLayer = Literal["A_infrastructure", "B_deterministic", "C_real_model", "D_comparative"]


@dataclass
class ModelIdentity:
    """Required identity for model-dependent benchmarks."""

    model_id: str | None = None
    model_runtime: str | None = None  # e.g. lm_studio, mock, unavailable
    model_quantization: str | None = None
    context_size: int | None = None
    temperature: float | None = None
    tool_call_mode: str | None = None
    hardware: str | None = None

    def label(self) -> str:
        mid = self.model_id or "unknown"
        runtime = self.model_runtime or "unknown"
        return f"HADES + {mid} ({runtime})"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkRecord:
    """One task attempt — matches the campaign output contract."""

    benchmark_version: str = BENCHMARK_SCHEMA_VERSION
    timestamp: float = 0.0
    git_sha: str = "unavailable"
    task_id: str = ""
    task_family: str = ""
    task_split: TaskSplit = "dev"
    eval_layer: EvalLayer = "B_deterministic"
    synthetic: bool = False
    input: dict[str, Any] = field(default_factory=dict)
    ground_truth: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    verified_result: dict[str, Any] = field(default_factory=dict)
    outcome: Outcome = "not_run"
    success: bool = False
    partial: bool = False
    failure: bool = False
    latency_ms: float | None = None
    tokens: dict[str, Any] | None = None
    model_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    retrieval_stats: dict[str, Any] = field(default_factory=dict)
    verification_stats: dict[str, Any] = field(default_factory=dict)
    failure_class: str | None = None
    contributing_failure_classes: list[str] = field(default_factory=list)
    model: ModelIdentity = field(default_factory=ModelIdentity)
    notes: str = ""
    competitor: str | None = None  # for Layer D imports
    status: str = "NOT_RUN"  # PASS|FAIL|NOT_RUN|BLOCKED_EXTERNAL|UNVERIFIED_ON_HOST|BLOCKED_MODEL_UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_label"] = self.model.label()
        return payload


def new_record(
    *,
    task_id: str,
    task_family: str,
    git_sha: str = "unavailable",
    eval_layer: EvalLayer = "B_deterministic",
    task_split: TaskSplit = "dev",
    synthetic: bool = False,
    model: ModelIdentity | None = None,
    **kwargs: Any,
) -> BenchmarkRecord:
    return BenchmarkRecord(
        timestamp=time.time(),
        git_sha=git_sha,
        task_id=task_id,
        task_family=task_family,
        eval_layer=eval_layer,
        task_split=task_split,
        synthetic=synthetic,
        model=model or ModelIdentity(model_runtime="deterministic"),
        **kwargs,
    )


def finalize_outcome(record: BenchmarkRecord) -> BenchmarkRecord:
    """Normalize success/partial/failure flags from outcome."""
    if record.outcome == "success":
        record.success, record.partial, record.failure = True, False, False
        record.status = "PASS"
    elif record.outcome == "partial":
        record.success, record.partial, record.failure = False, True, False
        record.status = "FAIL"
    elif record.outcome == "failure":
        record.success, record.partial, record.failure = False, False, True
        record.status = "FAIL"
    elif record.outcome == "blocked":
        record.success = record.partial = record.failure = False
        if "MODEL" in (record.status or "") or "model" in (record.notes or "").lower():
            record.status = "BLOCKED_MODEL_UNAVAILABLE"
        elif record.status in {"NOT_RUN", "PASS", "FAIL"}:
            record.status = "BLOCKED_EXTERNAL"
    else:
        record.success = record.partial = record.failure = False
        if record.status in {"PASS", "FAIL"}:
            record.status = "NOT_RUN"
    return record
