"""Strategy research experiments — hypothesis → test → learn → version (or reject)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from .types import MetricStatus
from .epistemic import is_available


@dataclass
class ExperimentTrial:
    trial_id: str
    strategy_id: str
    strategy_version: int | None
    hypothesis: str
    proposer_agent_id: str
    data_hash: str
    config: dict[str, Any]
    split: dict[str, Any]  # design / validation / test windows
    seed: int
    status: str  # proposed | running | passed | rejected | archived
    results: dict[str, Any] = field(default_factory=dict)
    rejection_reason: str = ""
    acceptance_criteria: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    finished_at: str | None = None
    code_version: str = "market_sim-1"
    cost_model: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "hypothesis": self.hypothesis,
            "proposer_agent_id": self.proposer_agent_id,
            "data_hash": self.data_hash,
            "config": self.config,
            "split": self.split,
            "seed": self.seed,
            "status": self.status,
            "results": self.results,
            "rejection_reason": self.rejection_reason,
            "acceptance_criteria": self.acceptance_criteria,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "code_version": self.code_version,
            "cost_model": self.cost_model,
            "truth": {
                "failed_trials_retained": True,
                "learning_requires_new_version": True,
                "paper_never_auto_approves_live": True,
            },
        }


def walk_forward_splits(
    start_ts: str | int,
    end_ts: str | int | None = None,
    bars: list[Any] | None = None,
    *,
    design_frac: float = 0.5,
    validation_frac: float = 0.25,
    window: int | None = None,
    step: int | None = None,
) -> dict[str, Any]:
    """Chronological design / validation / holdout — optional rolling windows.

    Legacy: ``walk_forward_splits(start_ts, end_ts, bars)``.
    Rolling: ``walk_forward_splits(n_bars, window=20, step=10)`` → ``windows`` list.
    """
    # Rolling-window API (D13 / G20 early)
    if isinstance(start_ts, int) and window is not None:
        n = int(start_ts)
        win = max(2, int(window))
        stp = max(1, int(step or max(1, win // 2)))
        windows: list[dict[str, Any]] = []
        start = 0
        while start + win <= n:
            windows.append(
                {
                    "start_index": start,
                    "end_index": start + win - 1,
                    "bar_count": win,
                    "design": {"start_index": start, "end_index": start + win // 2 - 1},
                    "validation": {
                        "start_index": start + win // 2,
                        "end_index": start + (3 * win) // 4 - 1,
                    },
                    "test": {"start_index": start + (3 * win) // 4, "end_index": start + win - 1},
                }
            )
            start += stp
        return {
            "windows": windows,
            "window": win,
            "step": stp,
            "bar_count": n,
            "truth": {"chronological_only": True, "no_shuffle": True, "rolling": True},
        }

    bars = list(bars or [])
    start_s = str(start_ts or "")
    end_s = str(end_ts or "")
    n = len(bars)
    if n < 30:
        return {
            "design": {"start_ts": start_s, "end_ts": end_s, "bar_count": n},
            "validation": None,
            "test": None,
            "warning": "insufficient bars for walk-forward; single window only",
        }
    d_end = int(n * design_frac)
    v_end = int(n * (design_frac + validation_frac))
    d_end = max(10, min(d_end, n - 10))
    v_end = max(d_end + 5, min(v_end, n - 5))
    return {
        "design": {
            "start_ts": bars[0].ts,
            "end_ts": bars[d_end - 1].ts,
            "bar_count": d_end,
            "end_index": d_end - 1,
        },
        "validation": {
            "start_ts": bars[d_end].ts,
            "end_ts": bars[v_end - 1].ts,
            "bar_count": v_end - d_end,
            "start_index": d_end,
            "end_index": v_end - 1,
        },
        "test": {
            "start_ts": bars[v_end].ts,
            "end_ts": bars[-1].ts,
            "bar_count": n - v_end,
            "start_index": v_end,
            "end_index": n - 1,
        },
        "truth": {"chronological_only": True, "no_shuffle": True},
    }


def purged_cv_splits(
    n_bars: int,
    *,
    n_folds: int = 5,
    purge: int = 5,
    embargo: int = 5,
) -> dict[str, Any]:
    """Purged K-fold CV over a chronological bar index (G20 / Lopez de Prado).

    Test folds are contiguous blocks. Train excludes a purge gap around the
    test block plus an embargo after the test end to limit leakage.
    """
    n = int(n_bars)
    k = max(2, int(n_folds))
    purge_n = max(0, int(purge))
    embargo_n = max(0, int(embargo))
    if n < k * 4:
        return {
            "folds": [],
            "warning": "insufficient bars for purged CV",
            "bar_count": n,
            "n_folds": k,
        }
    fold_size = n // k
    folds: list[dict[str, Any]] = []
    for i in range(k):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size - 1 if i < k - 1 else n - 1
        left_cut = max(0, test_start - purge_n)
        right_cut = min(n - 1, test_end + purge_n + embargo_n)
        train_idx = [j for j in range(n) if j < left_cut or j > right_cut]
        test_idx = list(range(test_start, test_end + 1))
        folds.append(
            {
                "fold": i,
                "train_indices": train_idx,
                "test_indices": test_idx,
                "purge": purge_n,
                "embargo": embargo_n,
                "train_count": len(train_idx),
                "test_count": len(test_idx),
            }
        )
    return {
        "folds": folds,
        "n_folds": k,
        "bar_count": n,
        "purge": purge_n,
        "embargo": embargo_n,
        "truth": {
            "chronological_only": True,
            "no_shuffle": True,
            "purged": True,
            "embargoed": True,
        },
    }


def cpcv_splits(
    n_bars: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    purge: int = 5,
    embargo: int = 5,
) -> dict[str, Any]:
    """Combinatorial Purged Cross-Validation paths (G20).

    Splits the timeline into ``n_groups`` contiguous groups and enumerates
    combinations of ``n_test_groups`` as the test set; remaining groups form
    train after purge/embargo around each test group.
    """
    from itertools import combinations

    n = int(n_bars)
    g = max(3, int(n_groups))
    t = max(1, min(int(n_test_groups), g - 1))
    purge_n = max(0, int(purge))
    embargo_n = max(0, int(embargo))
    if n < g * 3:
        return {
            "paths": [],
            "warning": "insufficient bars for CPCV",
            "bar_count": n,
            "n_groups": g,
        }
    group_size = n // g
    groups: list[list[int]] = []
    for i in range(g):
        start = i * group_size
        end = (i + 1) * group_size - 1 if i < g - 1 else n - 1
        groups.append(list(range(start, end + 1)))

    paths: list[dict[str, Any]] = []
    for test_combo in combinations(range(g), t):
        test_set: set[int] = set()
        blocked: set[int] = set()
        for gi in test_combo:
            idxs = groups[gi]
            test_set.update(idxs)
            lo = max(0, idxs[0] - purge_n)
            hi = min(n - 1, idxs[-1] + purge_n + embargo_n)
            blocked.update(range(lo, hi + 1))
        train_idx = [j for j in range(n) if j not in blocked]
        test_idx = sorted(test_set)
        paths.append(
            {
                "test_groups": list(test_combo),
                "train_indices": train_idx,
                "test_indices": test_idx,
                "train_count": len(train_idx),
                "test_count": len(test_idx),
            }
        )
    return {
        "paths": paths,
        "n_groups": g,
        "n_test_groups": t,
        "n_paths": len(paths),
        "bar_count": n,
        "purge": purge_n,
        "embargo": embargo_n,
        "truth": {
            "chronological_only": True,
            "combinatorial_purged_cv": True,
            "no_shuffle": True,
        },
    }


def robustness_report(
    window_metrics: list[dict[str, Any]],
    *,
    key: str = "total_return",
) -> dict[str, Any]:
    """Summarize stability of a metric across WFA/CV windows (G20)."""

    def _val(m: dict[str, Any]) -> float | None:
        raw = m.get(key)
        if isinstance(raw, dict):
            if raw.get("status") == MetricStatus.UNMEASURED.value:
                return None
            if raw.get("value") is None:
                return None
            return float(raw["value"])
        if raw is None:
            return None
        return float(raw)

    values = [v for v in (_val(m) for m in window_metrics) if v is not None]
    if len(values) < 2:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "need >=2 measured windows",
            "n_windows": len(window_metrics),
            "n_measured": len(values),
        }
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    std = var ** 0.5
    positives = sum(1 for v in values if v > 0)
    return {
        "status": MetricStatus.MEASURED.value,
        "key": key,
        "n_windows": len(window_metrics),
        "n_measured": len(values),
        "mean": mean,
        "std": std,
        "min": min(values),
        "max": max(values),
        "positive_share": positives / len(values),
        "stable": std <= abs(mean) + 1e-12 if mean != 0 else std == 0,
        "truth": {"cross_window_only": True, "not_a_live_guarantee": True},
    }


def evaluate_acceptance(
    metrics: dict[str, Any],
    criteria: dict[str, Any],
    *,
    run_id: str | None = None,
    run_ids: list[str] | None = None,
    require_run_ids: bool = True,
) -> tuple[bool, str]:
    """Return (passed, reason). Conservative defaults.

    Accepts both hand-typed percent keys (``total_return_pct``) and
    ``compute_metrics`` shapes (``total_return`` as fraction status/value).

    G21: by default requires ``run_id`` / ``run_ids`` so caller-fabricated
    metrics alone cannot pass acceptance. Pass ``require_run_ids=False`` only
    for offline unit checks of the numeric criteria themselves.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for candidate in ([str(run_id)] if run_id else []) + [str(r) for r in (run_ids or []) if r]:
        if candidate and candidate not in seen:
            seen.add(candidate)
            ids.append(candidate)

    if require_run_ids and not ids:
        return False, "acceptance requires run-derived evidence (run_id/run_ids)"

    min_trades = int(criteria.get("min_trades", 5))
    max_dd = float(criteria.get("max_drawdown_pct", 25.0))
    min_return = float(criteria.get("min_total_return_pct", 0.0))
    require_beat_benchmark = bool(criteria.get("beat_benchmark", False))

    trades = 0
    tc = metrics.get("trade_count")
    if isinstance(tc, dict):
        trades = int(tc.get("value") or 0)
    elif tc is not None:
        trades = int(tc)
    elif metrics.get("fills") is not None:
        fills_raw = metrics.get("fills")
        trades = int(fills_raw) if not isinstance(fills_raw, dict) else int(fills_raw.get("value") or 0)

    def _raw(name: str) -> Any:
        return metrics.get(name)

    def _as_float(raw: Any, default: float = 0.0) -> float:
        if isinstance(raw, dict):
            if raw.get("status") == MetricStatus.UNMEASURED.value:
                return default
            return float(raw.get("value") if raw.get("value") is not None else default)
        if raw is None:
            return default
        return float(raw)

    def _pct_from_fraction_or_pct(primary: str, alias: str, *, default: float = 0.0) -> float:
        if primary in metrics:
            return _as_float(_raw(primary), default)
        if alias in metrics:
            val = _as_float(_raw(alias), default)
            # Heuristic: absolute values <= 5 treated as fraction (0.2 → 20%).
            if abs(val) <= 5.0:
                return val * 100.0
            return val
        return default

    total_return = _pct_from_fraction_or_pct("total_return_pct", "total_return", default=0.0)
    max_drawdown = _pct_from_fraction_or_pct("max_drawdown_pct", "max_drawdown", default=100.0)
    max_drawdown = abs(max_drawdown)
    vs_bench = _pct_from_fraction_or_pct("excess_return_pct", "excess_return", default=0.0)

    if trades < min_trades:
        return False, f"insufficient trades ({trades} < {min_trades}) — small sample"
    if max_drawdown > max_dd:
        return False, f"drawdown {max_drawdown:.2f}% exceeds {max_dd}%"
    if total_return < min_return:
        return False, f"return {total_return:.2f}% below minimum {min_return}%"
    if require_beat_benchmark and vs_bench <= 0:
        return False, "did not beat buy-and-hold benchmark after costs"
    evidence = f" on runs {ids}" if ids else ""
    return True, f"acceptance criteria met on held-out split{evidence}"


def trial_fingerprint(trial: ExperimentTrial) -> str:
    payload = {
        "strategy_id": trial.strategy_id,
        "hypothesis": trial.hypothesis,
        "data_hash": trial.data_hash,
        "config": trial.config,
        "seed": trial.seed,
        "cost_model": trial.cost_model,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


@dataclass
class StrategyMemoryEntry:
    """Version-bound searchable memory — causal: only past trials visible at decision time."""

    memory_id: str
    strategy_id: str
    strategy_version: int
    features: dict[str, Any]
    applicability: dict[str, Any]
    outcome_summary: str
    trial_id: str | None
    created_at: str
    available_at: str  # causality: not visible before this ts
    rejected: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "features": self.features,
            "applicability": self.applicability,
            "outcome_summary": self.outcome_summary,
            "trial_id": self.trial_id,
            "created_at": self.created_at,
            "available_at": self.available_at,
            "rejected": self.rejected,
        }


class StrategyMemoryIndex:
    def __init__(self) -> None:
        self._entries: list[StrategyMemoryEntry] = []

    def add(self, entry: StrategyMemoryEntry) -> None:
        self._entries.append(entry)

    def search(
        self,
        *,
        as_of_ts: str,
        features: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[StrategyMemoryEntry]:
        """Only return memories with available_at <= as_of_ts (no future leakage)."""
        feats = features or {}
        hits = []
        for e in self._entries:
            if not is_available(available_at=e.available_at, as_of=as_of_ts):
                continue
            score = 0
            for k, v in feats.items():
                if e.features.get(k) == v or e.applicability.get(k) == v:
                    score += 1
            hits.append((score, e))
        hits.sort(key=lambda x: (-x[0], x[1].available_at), reverse=False)
        hits.sort(key=lambda x: -x[0])
        return [e for _, e in hits[:limit]]


def market_features_from_closes(closes: list[float]) -> dict[str, Any]:
    if len(closes) < 5:
        return {"regime": "unknown", "trend": "flat", "volatility": "low"}
    window = closes[-20:] if len(closes) >= 20 else closes
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    std = var ** 0.5
    ret = (closes[-1] - closes[0]) / closes[0] if closes[0] else 0.0
    vol_pct = (std / mean * 100.0) if mean else 0.0
    trend = "up" if ret > 0.02 else ("down" if ret < -0.02 else "flat")
    vol = "high" if vol_pct > 3 else ("medium" if vol_pct > 1 else "low")
    return {
        "regime": f"{trend}_{vol}",
        "trend": trend,
        "volatility": vol,
        "return_pct": round(ret * 100, 3),
        "vol_pct": round(vol_pct, 3),
    }


def strategy_matches_regime(
    applicability: dict[str, Any],
    features: dict[str, Any],
) -> dict[str, Any]:
    """Concrete condition match — not Brain association as a trade signal."""
    required_trends = set(applicability.get("trends") or [])
    required_vols = set(applicability.get("volatilities") or [])
    min_similarity = float(applicability.get("min_feature_overlap", 1))
    matched = []
    if required_trends:
        if features.get("trend") in required_trends:
            matched.append("trend")
        else:
            return {
                "matched": False,
                "reason": f"trend {features.get('trend')} not in {sorted(required_trends)}",
                "similarity": 0.0,
            }
    if required_vols:
        if features.get("volatility") in required_vols:
            matched.append("volatility")
        else:
            return {
                "matched": False,
                "reason": f"volatility {features.get('volatility')} not in {sorted(required_vols)}",
                "similarity": 0.0,
            }
    regimes = set(applicability.get("regimes") or [])
    if regimes and features.get("regime") in regimes:
        matched.append("regime")
    similarity = float(len(matched))
    ok = similarity >= min_similarity if (required_trends or required_vols or regimes) else False
    if not (required_trends or required_vols or regimes):
        return {
            "matched": False,
            "reason": "no applicability conditions defined — cannot claim recognition",
            "similarity": 0.0,
        }
    return {
        "matched": ok,
        "reason": "conditions matched" if ok else "insufficient feature overlap",
        "matched_keys": matched,
        "similarity": similarity,
        "features": features,
    }


def new_trial(
    *,
    strategy_id: str,
    hypothesis: str,
    proposer_agent_id: str,
    data_hash: str,
    config: dict[str, Any],
    split: dict[str, Any],
    seed: int,
    acceptance_criteria: dict[str, Any] | None = None,
    cost_model: dict[str, Any] | None = None,
    created_at: str,
    strategy_version: int | None = None,
) -> ExperimentTrial:
    return ExperimentTrial(
        trial_id=str(uuid.uuid4()),
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        hypothesis=hypothesis,
        proposer_agent_id=proposer_agent_id,
        data_hash=data_hash,
        config=config,
        split=split,
        seed=seed,
        status="proposed",
        acceptance_criteria=dict(acceptance_criteria or {"min_trades": 5, "max_drawdown_pct": 25}),
        created_at=created_at,
        cost_model=dict(cost_model or {}),
    )
