"""Walk-forward analysis + sealed evaluation helpers (P2B).

Rolling chronological windows only — never shuffle financial time.
Acceptance metrics are read from kernel ``compute_metrics`` / run results,
never from request payloads or agent claims.

Wave 6: actual fold evaluation (train-fit / test-run) lives here.
Background qualification orchestration uses the registered
``market_sim.qualification_run`` worker capability (execution builtins +
jobs allowlist + workers entrypoint). This module does not register that
capability — fold evaluation is callable/orchestrated by
QualificationAuthority once the background job resumes a qualification run.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .experiments import evaluate_acceptance, walk_forward_splits
from .institutional_core.status import MeasurementState
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
# Wave 6 — typed WFA policy + actual fold evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WfaPolicy:
    """Frozen walk-forward geometry + pass thresholds.

    ``mode`` is one of ``rolling`` | ``anchored`` | ``expanding``.
    TRAIN/VALIDATION may fit and select; TEST metrics never feed fitting.
    """

    mode: str  # rolling | anchored | expanding
    train_size: int
    validation_size: int
    test_size: int
    step: int
    purge_bars: int
    embargo_bars: int
    min_folds: int
    min_pass_ratio: float
    max_worst_fold_drawdown_pct: float | None
    max_dispersion: float | None


@dataclass
class WfaFoldResult:
    fold_index: int
    train_range: tuple[str, str]
    validation_range: tuple[str, str] | None
    test_range: tuple[str, str]
    train_run_id: str | None
    test_run_id: str
    frozen_strategy_version: int
    frozen_params: dict[str, Any]
    metrics: dict[str, Any]
    state: MeasurementState
    passed: bool
    blockers: list[str] = field(default_factory=list)

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
            "state": self.state.value if isinstance(self.state, MeasurementState) else str(self.state),
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
    state: MeasurementState
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
            "state": self.state.value if isinstance(self.state, MeasurementState) else str(self.state),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "truth": {
                "chronological_only": True,
                "no_shuffle": True,
                "test_metrics_never_fit": True,
                "fills_from_run_fold_only": True,
            },
        }


def _metric_scalar(metrics: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        raw = metrics.get(name)
        if isinstance(raw, dict):
            if raw.get("value") is None:
                continue
            try:
                return float(raw["value"])
            except (TypeError, ValueError):
                continue
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _fold_geometry(
    bars: Sequence[Bar],
    policy: WfaPolicy,
) -> list[dict[str, Any]]:
    """Build chronological train[/validation]/test folds with purge+embargo gaps."""
    n = len(bars)
    mode = str(policy.mode or "rolling").lower()
    train_size = int(policy.train_size)
    validation_size = max(0, int(policy.validation_size))
    test_size = int(policy.test_size)
    step = max(1, int(policy.step))
    purge = max(0, int(policy.purge_bars))
    embargo = max(0, int(policy.embargo_bars))
    if train_size < 5 or test_size < 1:
        raise MarketSimError("WFA_INVALID", "train_size>=5 and test_size>=1 required")

    folds: list[dict[str, Any]] = []
    if mode == "anchored":
        train_start = 0
        train_end = train_size - 1
        cursor = train_end + 1 + purge
        validation_range = None
        if validation_size > 0:
            val_end = cursor + validation_size - 1
            if val_end >= n:
                return folds
            validation_range = (cursor, val_end)
            cursor = val_end + 1 + embargo
        else:
            cursor = cursor + embargo
        test_start = cursor
        test_end = test_start + test_size - 1
        if test_end >= n:
            return folds
        folds.append(
            {
                "fold_index": 0,
                "train": (train_start, train_end),
                "validation": validation_range,
                "test": (test_start, test_end),
            }
        )
        return folds

    start = 0
    idx = 0
    while True:
        if mode == "expanding":
            train_start = 0
            train_end = start + train_size - 1
        else:
            train_start = start
            train_end = train_start + train_size - 1
        if train_end >= n:
            break
        cursor = train_end + 1 + purge
        validation_range = None
        if validation_size > 0:
            val_end = cursor + validation_size - 1
            if val_end >= n:
                break
            validation_range = (cursor, val_end)
            cursor = val_end + 1 + embargo
        else:
            cursor = cursor + embargo
        test_start = cursor
        test_end = test_start + test_size - 1
        if test_end >= n:
            break
        folds.append(
            {
                "fold_index": idx,
                "train": (train_start, train_end),
                "validation": validation_range,
                "test": (test_start, test_end),
            }
        )
        idx += 1
        start += step
    return folds


def _ts_range(bars: Sequence[Bar], lo_hi: tuple[int, int] | None) -> tuple[str, str] | None:
    if lo_hi is None:
        return None
    lo, hi = lo_hi
    return (bars[lo].ts, bars[hi].ts)


FitFoldFn = Callable[..., Mapping[str, Any]]
RunFoldFn = Callable[..., Mapping[str, Any]]


def evaluate_wfa_folds(
    bars: Sequence[Bar],
    *,
    policy: WfaPolicy,
    run_fold: RunFoldFn,
    fit_fold: FitFoldFn | None = None,
    store: Any | None = None,
    qualification_id: str | None = None,
    strategy_id: str = "",
    frozen_strategy_version: int = 0,
    acceptance_criteria: Mapping[str, Any] | None = None,
    initial_params: Mapping[str, Any] | None = None,
) -> WfaEvaluationResult:
    """Execute chronological WFA folds with strict train-fit / test-eval separation.

    ``fit_fold`` (optional) may inspect TRAIN (and VALIDATION) ranges only and
    must return frozen params. ``run_fold`` executes the TEST region with those
    frozen params and returns metrics / run ids — this module never invents fills.

    TEST metrics are never passed back into ``fit_fold``.
    """
    geometry = _fold_geometry(bars, policy)
    blockers: list[str] = []
    if len(geometry) < int(policy.min_folds):
        return WfaEvaluationResult(
            folds=[],
            fold_count=len(geometry),
            pass_count=0,
            pass_ratio=0.0,
            median_metrics={},
            worst_fold={},
            dispersion={},
            state=MeasurementState.INSUFFICIENT_HISTORY,
            passed=False,
            blockers=["INSUFFICIENT_HISTORY", f"folds={len(geometry)} < min_folds={policy.min_folds}"],
        )

    criteria = dict(acceptance_criteria or {})
    fold_results: list[WfaFoldResult] = []
    pass_count = 0
    drawdowns: list[float] = []
    returns: list[float] = []

    for geo in geometry:
        fold_index = int(geo["fold_index"])
        train_idx = geo["train"]
        val_idx = geo["validation"]
        test_idx = geo["test"]
        train_range = _ts_range(bars, train_idx)
        validation_range = _ts_range(bars, val_idx)
        test_range = _ts_range(bars, test_idx)
        assert train_range is not None and test_range is not None

        frozen_params: dict[str, Any] = dict(initial_params or {})
        train_run_id: str | None = None
        fold_blockers: list[str] = []

        if fit_fold is not None:
            fit_out = dict(
                fit_fold(
                    fold_index=fold_index,
                    train_range=train_range,
                    validation_range=validation_range,
                    train_indices=train_idx,
                    validation_indices=val_idx,
                    bars_train=list(bars[train_idx[0] : train_idx[1] + 1]),
                    bars_validation=(
                        list(bars[val_idx[0] : val_idx[1] + 1]) if val_idx is not None else None
                    ),
                    params=dict(frozen_params),
                )
                or {}
            )
            if "frozen_params" in fit_out:
                frozen_params = dict(fit_out["frozen_params"] or {})
            elif "params" in fit_out:
                frozen_params = dict(fit_out["params"] or {})
            train_run_id = fit_out.get("train_run_id") or fit_out.get("run_id")
            if fit_out.get("test_metrics") is not None:
                fold_blockers.append("FIT_SAW_TEST_METRICS")

        test_out = dict(
            run_fold(
                fold_index=fold_index,
                test_range=test_range,
                test_indices=test_idx,
                bars_test=list(bars[test_idx[0] : test_idx[1] + 1]),
                frozen_params=dict(frozen_params),
                frozen_strategy_version=int(frozen_strategy_version),
                train_range=train_range,
                validation_range=validation_range,
            )
            or {}
        )
        metrics = dict(test_out.get("metrics") or {})
        test_run_id = str(test_out.get("test_run_id") or test_out.get("run_id") or "")
        if not test_run_id:
            fold_blockers.append("MISSING_TEST_RUN_ID")

        passed = False
        state = MeasurementState.FAIL
        if criteria:
            ok, reason = evaluate_acceptance(metrics, criteria)
            passed = bool(ok)
            if not ok:
                fold_blockers.append(str(reason))
            state = MeasurementState.PASS if ok else MeasurementState.FAIL
        elif test_out.get("passed") is True and metrics:
            passed = True
            state = MeasurementState.PASS
        elif metrics:
            state = MeasurementState.MEASURED
            passed = False
            fold_blockers.append("NO_ACCEPTANCE_CRITERIA")
        else:
            state = MeasurementState.UNMEASURED
            fold_blockers.append("NO_TEST_METRICS")

        if fold_blockers and "FIT_SAW_TEST_METRICS" in fold_blockers:
            passed = False
            state = MeasurementState.FAIL

        dd = _metric_scalar(metrics, "max_drawdown_pct", "max_drawdown")
        if dd is not None:
            if abs(dd) <= 1.0 and "max_drawdown_pct" not in metrics:
                dd = dd * 100.0
            drawdowns.append(float(dd))
            if (
                policy.max_worst_fold_drawdown_pct is not None
                and float(dd) > float(policy.max_worst_fold_drawdown_pct)
            ):
                fold_blockers.append("WORST_FOLD_DRAWDOWN")
                passed = False
                state = MeasurementState.FAIL

        ret = _metric_scalar(metrics, "total_return_pct", "total_return")
        if ret is not None:
            returns.append(float(ret))

        if passed:
            pass_count += 1

        fold_result = WfaFoldResult(
            fold_index=fold_index,
            train_range=train_range,
            validation_range=validation_range,
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
        fold_results.append(fold_result)

        if store is not None and hasattr(store, "upsert_wfa_fold"):
            try:
                store.upsert_wfa_fold(
                    {
                        "qualification_id": qualification_id or "",
                        "fold_index": fold_index,
                        "train_start_ts": train_range[0],
                        "train_end_ts": train_range[1],
                        "validation_start_ts": validation_range[0] if validation_range else None,
                        "validation_end_ts": validation_range[1] if validation_range else None,
                        "test_start_ts": test_range[0],
                        "test_end_ts": test_range[1],
                        "purge_bars": int(policy.purge_bars),
                        "embargo_bars": int(policy.embargo_bars),
                        "train_run_id": fold_result.train_run_id,
                        "test_run_id": fold_result.test_run_id,
                        "strategy_id": strategy_id,
                        "strategy_version": int(frozen_strategy_version),
                        "frozen_params": dict(frozen_params),
                        "metrics": metrics,
                        "state": state.value,
                    }
                )
            except Exception:  # noqa: BLE001 — persistence is best-effort evidence
                fold_result.blockers.append("WFA_FOLD_PERSIST_FAILED")

    fold_count = len(fold_results)
    pass_ratio = (pass_count / fold_count) if fold_count else 0.0

    median_metrics: dict[str, Any] = {}
    if returns:
        median_metrics["total_return_pct"] = float(statistics.median(returns))
    if drawdowns:
        median_metrics["max_drawdown_pct"] = float(statistics.median(drawdowns))

    worst_fold: dict[str, Any] = {}
    if drawdowns:
        worst_i = max(range(len(drawdowns)), key=lambda i: drawdowns[i])
        dd_folds = [
            f
            for f in fold_results
            if _metric_scalar(f.metrics, "max_drawdown_pct", "max_drawdown") is not None
        ]
        if dd_folds:
            wf = dd_folds[worst_i] if worst_i < len(dd_folds) else dd_folds[-1]
            worst_fold = {
                "fold_index": wf.fold_index,
                "max_drawdown_pct": drawdowns[worst_i],
                "passed": wf.passed,
                "test_run_id": wf.test_run_id,
            }

    dispersion: dict[str, Any] = {}
    if len(returns) >= 2:
        dispersion["return_stdev"] = float(statistics.pstdev(returns))
        dispersion["return_range"] = float(max(returns) - min(returns))
    elif returns:
        dispersion["return_stdev"] = 0.0
        dispersion["return_range"] = 0.0

    if pass_ratio < float(policy.min_pass_ratio):
        blockers.append("MIN_PASS_RATIO")
    if (
        policy.max_dispersion is not None
        and dispersion.get("return_stdev") is not None
        and float(dispersion["return_stdev"]) > float(policy.max_dispersion)
    ):
        blockers.append("MAX_DISPERSION")
    if any("WORST_FOLD_DRAWDOWN" in f.blockers for f in fold_results):
        if "WORST_FOLD_DRAWDOWN" not in blockers:
            blockers.append("WORST_FOLD_DRAWDOWN")

    passed = (
        not blockers
        and pass_ratio >= float(policy.min_pass_ratio)
        and fold_count >= int(policy.min_folds)
    )
    state = MeasurementState.PASS if passed else MeasurementState.FAIL
    if fold_count < int(policy.min_folds):
        state = MeasurementState.INSUFFICIENT_HISTORY
        passed = False

    return WfaEvaluationResult(
        folds=fold_results,
        fold_count=fold_count,
        pass_count=pass_count,
        pass_ratio=pass_ratio,
        median_metrics=median_metrics,
        worst_fold=worst_fold,
        dispersion=dispersion,
        state=state,
        passed=passed,
        blockers=blockers,
    )
