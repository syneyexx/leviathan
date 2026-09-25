"""Walk-forward analysis + sealed evaluation helpers (P2B).

Rolling chronological windows only — never shuffle financial time.
Acceptance metrics are read from kernel ``compute_metrics`` / run results,
never from request payloads or agent claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .experiments import evaluate_acceptance, walk_forward_splits
from .types import Bar, MarketSimError


@dataclass
class WfaWindow:
    index: int
    train_start_index: int
    train_end_index: int
    test_start_index: int
    test_end_index: int
    train_start_ts: str
    train_end_ts: str
    test_start_ts: str
    test_end_ts: str
    purge_bars: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_start_index": self.train_start_index,
            "train_end_index": self.train_end_index,
            "test_start_index": self.test_start_index,
            "test_end_index": self.test_end_index,
            "train_start_ts": self.train_start_ts,
            "train_end_ts": self.train_end_ts,
            "test_start_ts": self.test_start_ts,
            "test_end_ts": self.test_end_ts,
            "purge_bars": self.purge_bars,
        }


def rolling_wfa_windows(
    bars: Sequence[Bar],
    *,
    train_size: int,
    test_size: int,
    step: int | None = None,
    purge_bars: int = 0,
) -> list[WfaWindow]:
    """Build rolling train→test windows with optional purge gap."""
    n = len(bars)
    if train_size < 5 or test_size < 1:
        raise MarketSimError("WFA_INVALID", "train_size>=5 and test_size>=1 required")
    if purge_bars < 0:
        raise MarketSimError("WFA_INVALID", "purge_bars must be >= 0")
    step = int(step) if step is not None else int(test_size)
    if step < 1:
        raise MarketSimError("WFA_INVALID", "step must be >= 1")
    windows: list[WfaWindow] = []
    start = 0
    idx = 0
    while True:
        train_start = start
        train_end = train_start + train_size - 1
        test_start = train_end + 1 + purge_bars
        test_end = test_start + test_size - 1
        if test_end >= n:
            break
        windows.append(
            WfaWindow(
                index=idx,
                train_start_index=train_start,
                train_end_index=train_end,
                test_start_index=test_start,
                test_end_index=test_end,
                train_start_ts=bars[train_start].ts,
                train_end_ts=bars[train_end].ts,
                test_start_ts=bars[test_start].ts,
                test_end_ts=bars[test_end].ts,
                purge_bars=purge_bars,
            )
        )
        idx += 1
        start += step
    return windows


def walk_forward_plan(
    bars: Sequence[Bar],
    *,
    mode: str = "anchored",
    train_size: int | None = None,
    test_size: int | None = None,
    step: int | None = None,
    purge_bars: int = 0,
    design_frac: float = 0.5,
    validation_frac: float = 0.25,
) -> dict[str, Any]:
    """Unified WFA plan: anchored single split or rolling windows."""
    mode = str(mode or "anchored").lower()
    if mode == "rolling":
        if train_size is None or test_size is None:
            n = len(bars)
            train_size = train_size or max(20, n // 3)
            test_size = test_size or max(5, n // 10)
        windows = rolling_wfa_windows(
            bars,
            train_size=int(train_size),
            test_size=int(test_size),
            step=step,
            purge_bars=purge_bars,
        )
        return {
            "mode": "rolling",
            "windows": [w.public_dict() for w in windows],
            "window_count": len(windows),
            "train_size": int(train_size),
            "test_size": int(test_size),
            "step": int(step) if step is not None else int(test_size),
            "purge_bars": purge_bars,
            "truth": {"chronological_only": True, "no_shuffle": True},
        }
    # Default: anchored design/validation/test (existing helper)
    if not bars:
        raise MarketSimError("WFA_EMPTY", "no bars for walk-forward plan")
    split = walk_forward_splits(
        bars[0].ts,
        bars[-1].ts,
        list(bars),
        design_frac=design_frac,
        validation_frac=validation_frac,
    )
    split["mode"] = "anchored"
    return split


@dataclass
class SealedEvaluationResult:
    passed: bool
    reason: str
    run_id: str
    sealed_attempt_id: str | None
    metrics: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "run_id": self.run_id,
            "sealed_attempt_id": self.sealed_attempt_id,
            "metrics": self.metrics,
            "acceptance_criteria": self.acceptance_criteria,
            "truth": {
                "acceptance_from_run_metrics": True,
                "never_from_request_payload": True,
                "kernel_owned": True,
            },
        }


def evaluate_acceptance_from_run(
    run: dict[str, Any] | Any,
    *,
    criteria: dict[str, Any] | None = None,
    sealed_attempt_id: str | None = None,
) -> SealedEvaluationResult:
    """Kernel-owned acceptance: read metrics from the run, not the caller body."""
    if hasattr(run, "public_dict"):
        payload = run.public_dict()
    else:
        payload = dict(run)
    run_id = str(payload.get("run_id") or "")
    metrics = dict(payload.get("metrics") or {})
    meta = dict(payload.get("metadata") or {})
    crit = dict(criteria or meta.get("acceptance_criteria") or payload.get("acceptance_criteria") or {})
    if not crit:
        crit = {"min_trades": 1, "max_drawdown_pct": 100.0, "min_total_return_pct": -100.0}
    passed, reason = evaluate_acceptance(metrics, crit)
    return SealedEvaluationResult(
        passed=passed,
        reason=reason,
        run_id=run_id,
        sealed_attempt_id=sealed_attempt_id or meta.get("sealed_attempt_id"),
        metrics=metrics,
        acceptance_criteria=crit,
    )
