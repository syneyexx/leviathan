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
        # Fail closed: inventing pass-all thresholds fabricates wins==trials.
        return SealedEvaluationResult(
            passed=False,
            reason="NO_ACCEPTANCE_CRITERIA",
            run_id=run_id,
            sealed_attempt_id=sealed_attempt_id or meta.get("sealed_attempt_id"),
            metrics=metrics,
            acceptance_criteria={},
        )
    passed, reason = evaluate_acceptance(metrics, crit)
    return SealedEvaluationResult(
        passed=passed,
        reason=reason,
        run_id=run_id,
        sealed_attempt_id=sealed_attempt_id or meta.get("sealed_attempt_id"),
        metrics=metrics,
        acceptance_criteria=crit,
    )


# ---------------------------------------------------------------------------
# Wave 6 — actual fold evaluation structures (OOS runs via caller)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WfaPolicy:
    mode: str = "rolling"  # rolling | anchored | expanding
    train_size: int = 50
    validation_size: int = 0
    test_size: int = 10
    step: int = 10
    purge_bars: int = 0
    embargo_bars: int = 0
    min_folds: int = 3
    min_pass_ratio: float = 0.6
    max_worst_fold_drawdown_pct: float | None = None
    max_dispersion: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "train_size": self.train_size,
            "validation_size": self.validation_size,
            "test_size": self.test_size,
            "step": self.step,
            "purge_bars": self.purge_bars,
            "embargo_bars": self.embargo_bars,
            "min_folds": self.min_folds,
            "min_pass_ratio": self.min_pass_ratio,
            "max_worst_fold_drawdown_pct": self.max_worst_fold_drawdown_pct,
            "max_dispersion": self.max_dispersion,
        }


@dataclass
class WfaFoldResult:
    fold_index: int
    train_range: tuple[str, str]
    test_range: tuple[str, str]
    test_run_id: str
    frozen_strategy_version: int
    frozen_params: dict[str, Any]
    metrics: dict[str, Any]
    state: str
    passed: bool
    blockers: list[str] = field(default_factory=list)
    validation_range: tuple[str, str] | None = None
    train_run_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "train_range": list(self.train_range),
            "validation_range": list(self.validation_range) if self.validation_range else None,
            "test_range": list(self.test_range),
            "train_run_id": self.train_run_id,
            "test_run_id": self.test_run_id,
            "frozen_strategy_version": self.frozen_strategy_version,
            "frozen_params": dict(self.frozen_params),
            "metrics": dict(self.metrics),
            "state": self.state,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }


@dataclass
class WfaEvaluationResult:
    folds: list[WfaFoldResult]
    fold_count: int
    pass_count: int
    pass_ratio: float
    median_metrics: dict[str, Any]
    worst_fold: dict[str, Any]
    dispersion: dict[str, Any]
    state: str
    passed: bool
    blockers: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "folds": [f.public_dict() for f in self.folds],
            "fold_count": self.fold_count,
            "pass_count": self.pass_count,
            "pass_ratio": self.pass_ratio,
            "median_metrics": dict(self.median_metrics),
            "worst_fold": dict(self.worst_fold),
            "dispersion": dict(self.dispersion),
            "state": self.state,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "truth": {
                "test_metrics_never_fit": True,
                "plan_alone_is_not_wfa_complete": True,
            },
        }


def evaluate_wfa_folds(
    windows: Sequence[WfaWindow],
    *,
    policy: WfaPolicy,
    frozen_params: dict[str, Any],
    frozen_strategy_version: int,
    run_fold: Any,
    store: Any | None = None,
    qualification_id: str | None = None,
    strategy_id: str = "",
) -> WfaEvaluationResult:
    """Execute real OOS fold simulations via ``run_fold``.

    ``run_fold(fold_index, train_window, test_window, frozen_params)`` must return
    a dict with at least ``test_run_id``, ``metrics``, and optional ``passed``.
    TRAIN fitting is the caller's responsibility *before* freezing params —
    this function never feeds TEST metrics back into fitting.
    """
    from .institutional_core.status import MeasurementState

    folds: list[WfaFoldResult] = []
    blockers: list[str] = []
    if len(windows) < policy.min_folds:
        return WfaEvaluationResult(
            folds=[],
            fold_count=len(windows),
            pass_count=0,
            pass_ratio=0.0,
            median_metrics={},
            worst_fold={},
            dispersion={},
            state=MeasurementState.INSUFFICIENT_HISTORY.value,
            passed=False,
            blockers=["WFA_INSUFFICIENT"],
        )

    for win in windows:
        train_range = (win.train_start_ts, win.train_end_ts)
        test_range = (win.test_start_ts, win.test_end_ts)
        out = run_fold(
            fold_index=win.index,
            train_window=win,
            test_window=win,
            frozen_params=dict(frozen_params),
        )
        metrics = dict((out or {}).get("metrics") or {})
        test_run_id = str((out or {}).get("test_run_id") or "")
        train_run_id = (out or {}).get("train_run_id")
        passed = bool((out or {}).get("passed", False))
        fold_blockers = list((out or {}).get("blockers") or [])
        if not test_run_id:
            passed = False
            fold_blockers.append("MISSING_TEST_RUN_ID")
        state = (
            MeasurementState.PASS.value
            if passed
            else str((out or {}).get("state") or MeasurementState.FAIL.value)
        )
        fold = WfaFoldResult(
            fold_index=int(win.index),
            train_range=train_range,
            validation_range=None,
            test_range=test_range,
            train_run_id=str(train_run_id) if train_run_id else None,
            test_run_id=test_run_id,
            frozen_strategy_version=int(frozen_strategy_version),
            frozen_params=dict(frozen_params),
            metrics=metrics,
            state=state,
            passed=passed,
            blockers=fold_blockers,
        )
        folds.append(fold)
        if store is not None and qualification_id and hasattr(store, "upsert_wfa_fold"):
            store.upsert_wfa_fold(
                {
                    "fold_id": f"wfa_{qualification_id}_{win.index}",
                    "qualification_id": qualification_id,
                    "fold_index": int(win.index),
                    "train_start_ts": win.train_start_ts,
                    "train_end_ts": win.train_end_ts,
                    "test_start_ts": win.test_start_ts,
                    "test_end_ts": win.test_end_ts,
                    "purge_bars": int(policy.purge_bars),
                    "embargo_bars": int(policy.embargo_bars),
                    "train_run_id": fold.train_run_id,
                    "test_run_id": fold.test_run_id,
                    "strategy_id": strategy_id,
                    "strategy_version": frozen_strategy_version,
                    "frozen_params": frozen_params,
                    "metrics": metrics,
                    "state": state,
                    "passed": int(passed),
                    "created_at": win.test_end_ts,
                }
            )

    pass_count = sum(1 for f in folds if f.passed)
    fold_count = len(folds)
    pass_ratio = (pass_count / fold_count) if fold_count else 0.0
    # Median of numeric metric keys
    keys = set()
    for f in folds:
        keys.update(k for k, v in f.metrics.items() if isinstance(v, (int, float)))
    median_metrics: dict[str, Any] = {}
    dispersion: dict[str, Any] = {}
    for k in sorted(keys):
        vals = sorted(float(f.metrics[k]) for f in folds if isinstance(f.metrics.get(k), (int, float)))
        if not vals:
            continue
        mid = vals[len(vals) // 2]
        median_metrics[k] = mid
        dispersion[k] = (vals[-1] - vals[0]) if len(vals) > 1 else 0.0

    worst = min(folds, key=lambda f: float(f.metrics.get("total_return", f.metrics.get("sharpe", 0)) or 0), default=None)
    worst_fold = worst.public_dict() if worst else {}
    if policy.max_worst_fold_drawdown_pct is not None and worst:
        dd = float(worst.metrics.get("max_drawdown_pct") or 0)
        if dd > float(policy.max_worst_fold_drawdown_pct):
            blockers.append("WORST_FOLD_DRAWDOWN")
    if policy.max_dispersion is not None:
        for k, d in dispersion.items():
            if float(d) > float(policy.max_dispersion):
                blockers.append(f"DISPERSION:{k}")
                break

    ok = pass_ratio >= policy.min_pass_ratio and fold_count >= policy.min_folds and not blockers
    return WfaEvaluationResult(
        folds=folds,
        fold_count=fold_count,
        pass_count=pass_count,
        pass_ratio=pass_ratio,
        median_metrics=median_metrics,
        worst_fold=worst_fold,
        dispersion=dispersion,
        state=MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
        passed=ok,
        blockers=blockers if ok else (blockers or ["WFA_PASS_RATIO"]),
    )
