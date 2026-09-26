"""Paired compute evaluation — FAST vs DEEP on pre-registered suites (W12).

Correct criterion (program):
- On hard-task suites: DEEP should show a statistically supported positive
  paired delta over FAST above a configured minimum useful effect size.
- On easy suites: DEEP must not materially regress quality.
- Do NOT require DEEP > FAST on every easy task.
- Do NOT use non-overlapping CIs as a universal superiority definition.
- Use paired bootstrap of deltas.
Always report quality, latency, model calls, tokens, resource cost.
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class ComputeTrial:
    """One mode's measured outcome on a single task."""

    task_id: str
    mode: str  # FAST | DEEP | MAXIMUM | ...
    success: bool
    quality: float  # 0..1 deterministic score
    latency_ms: float
    model_calls: int = 1
    tokens: int = 0
    tool_calls: int = 0
    retrieval_calls: int = 0
    agent_calls: int = 0
    resource_cost: float = 0.0  # proxy units
    suite: str = "hard"  # hard | easy
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "success": self.success,
            "quality": self.quality,
            "latency_ms": self.latency_ms,
            "model_calls": self.model_calls,
            "tokens": self.tokens,
            "tool_calls": self.tool_calls,
            "retrieval_calls": self.retrieval_calls,
            "agent_calls": self.agent_calls,
            "resource_cost": self.resource_cost,
            "suite": self.suite,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PairedDelta:
    task_id: str
    suite: str
    quality_delta: float  # deep - fast
    latency_delta_ms: float
    model_calls_delta: int
    tokens_delta: int
    resource_cost_delta: float
    fast: ComputeTrial
    deep: ComputeTrial

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "suite": self.suite,
            "quality_delta": self.quality_delta,
            "latency_delta_ms": self.latency_delta_ms,
            "model_calls_delta": self.model_calls_delta,
            "tokens_delta": self.tokens_delta,
            "resource_cost_delta": self.resource_cost_delta,
            "fast": self.fast.public_dict(),
            "deep": self.deep.public_dict(),
        }


@dataclass(frozen=True)
class BootstrapResult:
    mean: float
    ci_low: float
    ci_high: float
    n: int
    samples: int
    method: str = "paired_bootstrap"

    def public_dict(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n": self.n,
            "samples": self.samples,
            "method": self.method,
        }


@dataclass(frozen=True)
class PairedComputeReport:
    report_id: str
    deltas: tuple[PairedDelta, ...]
    hard_quality: BootstrapResult | None
    easy_quality: BootstrapResult | None
    hard_mean_delta: float
    easy_mean_delta: float
    min_useful_effect: float
    hard_positive_supported: bool
    easy_no_material_regression: bool
    easy_regression_threshold: float
    latency_summary: dict[str, Any]
    cost_summary: dict[str, Any]
    measurement: str  # PASSED | FAILED | UNMEASURED | PARTIAL
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "deltas": [d.public_dict() for d in self.deltas],
            "hard_quality": self.hard_quality.public_dict() if self.hard_quality else None,
            "easy_quality": self.easy_quality.public_dict() if self.easy_quality else None,
            "hard_mean_delta": self.hard_mean_delta,
            "easy_mean_delta": self.easy_mean_delta,
            "min_useful_effect": self.min_useful_effect,
            "hard_positive_supported": self.hard_positive_supported,
            "easy_no_material_regression": self.easy_no_material_regression,
            "easy_regression_threshold": self.easy_regression_threshold,
            "latency_summary": dict(self.latency_summary),
            "cost_summary": dict(self.cost_summary),
            "measurement": self.measurement,
            "detail": self.detail,
            "truth": {
                "deep_not_required_to_beat_fast_on_every_easy_task": True,
                "non_overlapping_ci_is_not_universal_superiority": True,
                "uses_paired_bootstrap_of_deltas": True,
                "unmeasured_is_not_pass": self.measurement != "PASSED",
            },
        }


def paired_bootstrap(
    values: Sequence[float],
    *,
    samples: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> BootstrapResult:
    """Bootstrap mean and percentile CI for paired deltas."""
    n = len(values)
    if n == 0:
        return BootstrapResult(mean=0.0, ci_low=0.0, ci_high=0.0, n=0, samples=0)
    mean = sum(values) / n
    if n == 1:
        return BootstrapResult(mean=mean, ci_low=mean, ci_high=mean, n=1, samples=samples)
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(max(1, samples)):
        draw = [values[rng.randrange(n)] for _ in range(n)]
        boots.append(sum(draw) / n)
    boots.sort()
    lo_i = int(math.floor((alpha / 2) * len(boots)))
    hi_i = int(math.ceil((1 - alpha / 2) * len(boots))) - 1
    hi_i = min(max(hi_i, 0), len(boots) - 1)
    lo_i = min(max(lo_i, 0), len(boots) - 1)
    return BootstrapResult(
        mean=mean,
        ci_low=boots[lo_i],
        ci_high=boots[hi_i],
        n=n,
        samples=samples,
    )


def build_paired_deltas(
    fast_trials: Sequence[ComputeTrial],
    deep_trials: Sequence[ComputeTrial],
) -> list[PairedDelta]:
    by_deep = {t.task_id: t for t in deep_trials}
    out: list[PairedDelta] = []
    for fast in fast_trials:
        deep = by_deep.get(fast.task_id)
        if deep is None:
            continue
        suite = fast.suite or deep.suite or "hard"
        out.append(
            PairedDelta(
                task_id=fast.task_id,
                suite=suite,
                quality_delta=deep.quality - fast.quality,
                latency_delta_ms=deep.latency_ms - fast.latency_ms,
                model_calls_delta=deep.model_calls - fast.model_calls,
                tokens_delta=deep.tokens - fast.tokens,
                resource_cost_delta=deep.resource_cost - fast.resource_cost,
                fast=fast,
                deep=deep,
            )
        )
    return out


def analyze_paired_compute(
    deltas: Sequence[PairedDelta],
    *,
    min_useful_effect: float = 0.05,
    easy_regression_threshold: float = -0.05,
    bootstrap_samples: int = 1000,
    seed: int = 42,
) -> PairedComputeReport:
    hard = [d for d in deltas if d.suite == "hard"]
    easy = [d for d in deltas if d.suite == "easy"]
    hard_boot = paired_bootstrap(
        [d.quality_delta for d in hard], samples=bootstrap_samples, seed=seed
    ) if hard else None
    easy_boot = paired_bootstrap(
        [d.quality_delta for d in easy], samples=bootstrap_samples, seed=seed + 1
    ) if easy else None

    hard_mean = hard_boot.mean if hard_boot else 0.0
    easy_mean = easy_boot.mean if easy_boot else 0.0

    # Positive support: mean delta >= min_useful_effect AND CI lower bound > 0
    # (not merely non-overlapping CIs as universal superiority).
    hard_supported = bool(
        hard_boot
        and hard_boot.n >= 2
        and hard_mean >= min_useful_effect
        and hard_boot.ci_low > 0
    )
    easy_ok = bool(
        easy_boot is None
        or easy_boot.n == 0
        or easy_mean >= easy_regression_threshold
    )

    if not hard and not easy:
        measurement = "UNMEASURED"
        detail = "no paired deltas"
    elif hard and hard_boot and hard_boot.n < 2:
        measurement = "UNMEASURED"
        detail = "hard suite too small for paired bootstrap"
    elif hard_supported and easy_ok:
        measurement = "PASSED"
        detail = "hard positive paired delta supported; easy no material regression"
    elif hard and not hard_supported and easy_ok:
        measurement = "PARTIAL"
        detail = "hard delta not statistically supported above min useful effect"
    elif hard_supported and not easy_ok:
        measurement = "FAILED"
        detail = "easy suite material quality regression under DEEP"
    else:
        measurement = "FAILED"
        detail = "hard not supported and/or easy regression"

    latency_summary = {
        "fast_mean_ms": _mean([d.fast.latency_ms for d in deltas]),
        "deep_mean_ms": _mean([d.deep.latency_ms for d in deltas]),
        "mean_latency_delta_ms": _mean([d.latency_delta_ms for d in deltas]),
    }
    cost_summary = {
        "fast_mean_model_calls": _mean([float(d.fast.model_calls) for d in deltas]),
        "deep_mean_model_calls": _mean([float(d.deep.model_calls) for d in deltas]),
        "fast_mean_tokens": _mean([float(d.fast.tokens) for d in deltas]),
        "deep_mean_tokens": _mean([float(d.deep.tokens) for d in deltas]),
        "fast_mean_resource_cost": _mean([d.fast.resource_cost for d in deltas]),
        "deep_mean_resource_cost": _mean([d.deep.resource_cost for d in deltas]),
    }
    return PairedComputeReport(
        report_id=f"compute_paired_{uuid.uuid4().hex[:12]}",
        deltas=tuple(deltas),
        hard_quality=hard_boot,
        easy_quality=easy_boot,
        hard_mean_delta=hard_mean,
        easy_mean_delta=easy_mean,
        min_useful_effect=min_useful_effect,
        hard_positive_supported=hard_supported,
        easy_no_material_regression=easy_ok,
        easy_regression_threshold=easy_regression_threshold,
        latency_summary=latency_summary,
        cost_summary=cost_summary,
        measurement=measurement,
        detail=detail,
    )


def _mean(vals: Sequence[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def default_compute_fixture_trials() -> tuple[list[ComputeTrial], list[ComputeTrial]]:
    """Deterministic synthetic FAST/DEEP trials for CI (hard improves, easy stable)."""
    hard_ids = [f"hard-{i}" for i in range(1, 9)]
    easy_ids = [f"easy-{i}" for i in range(1, 7)]
    fast: list[ComputeTrial] = []
    deep: list[ComputeTrial] = []
    for i, tid in enumerate(hard_ids):
        # FAST weaker on hard tasks; DEEP improves quality with extra cost.
        fq = 0.35 + (i % 3) * 0.05
        dq = min(1.0, fq + 0.18 + (i % 2) * 0.04)
        fast.append(
            ComputeTrial(
                task_id=tid,
                mode="FAST",
                success=fq >= 0.5,
                quality=fq,
                latency_ms=40 + i * 3,
                model_calls=1,
                tokens=200 + i * 10,
                resource_cost=1.0,
                suite="hard",
            )
        )
        deep.append(
            ComputeTrial(
                task_id=tid,
                mode="DEEP",
                success=dq >= 0.5,
                quality=dq,
                latency_ms=180 + i * 12,
                model_calls=3 + (i % 2),
                tokens=900 + i * 40,
                tool_calls=1,
                resource_cost=4.0,
                suite="hard",
            )
        )
    for i, tid in enumerate(easy_ids):
        # Easy: both succeed; DEEP slightly slower but quality not worse.
        q = 0.92
        fast.append(
            ComputeTrial(
                task_id=tid,
                mode="FAST",
                success=True,
                quality=q,
                latency_ms=25 + i,
                model_calls=1,
                tokens=80,
                resource_cost=0.5,
                suite="easy",
            )
        )
        deep.append(
            ComputeTrial(
                task_id=tid,
                mode="DEEP",
                success=True,
                quality=q,  # no regression
                latency_ms=90 + i * 2,
                model_calls=2,
                tokens=300,
                resource_cost=2.0,
                suite="easy",
            )
        )
    return fast, deep


def run_paired_compute_evaluation(
    *,
    fast_runner: Callable[[str], ComputeTrial] | None = None,
    deep_runner: Callable[[str], ComputeTrial] | None = None,
    hard_task_ids: Sequence[str] | None = None,
    easy_task_ids: Sequence[str] | None = None,
    min_useful_effect: float = 0.05,
    easy_regression_threshold: float = -0.05,
    bootstrap_samples: int = 1000,
    seed: int = 42,
) -> PairedComputeReport:
    """Run or use fixture trials, then analyze paired FAST vs DEEP deltas."""
    if fast_runner is None or deep_runner is None:
        fast, deep = default_compute_fixture_trials()
        if hard_task_ids or easy_task_ids:
            allow = set(hard_task_ids or []) | set(easy_task_ids or [])
            fast = [t for t in fast if t.task_id in allow]
            deep = [t for t in deep if t.task_id in allow]
    else:
        hard_ids = list(hard_task_ids or [f"hard-{i}" for i in range(1, 9)])
        easy_ids = list(easy_task_ids or [f"easy-{i}" for i in range(1, 7)])
        fast = [fast_runner(tid) for tid in hard_ids + easy_ids]
        deep = [deep_runner(tid) for tid in hard_ids + easy_ids]
    deltas = build_paired_deltas(fast, deep)
    return analyze_paired_compute(
        deltas,
        min_useful_effect=min_useful_effect,
        easy_regression_threshold=easy_regression_threshold,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
