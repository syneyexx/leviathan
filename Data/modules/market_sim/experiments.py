"""Strategy research experiments — hypothesis → test → learn → version (or reject)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from .causality import compare_ts
from .types import MetricStatus


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
    start_ts: str,
    end_ts: str,
    bars: list[Any],
    *,
    design_frac: float = 0.5,
    validation_frac: float = 0.25,
) -> dict[str, Any]:
    """Chronological design / validation / holdout test — no shuffling."""
    n = len(bars)
    if n < 30:
        return {
            "design": {"start_ts": start_ts, "end_ts": end_ts, "bar_count": n},
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


def evaluate_acceptance(
    metrics: dict[str, Any],
    criteria: dict[str, Any],
) -> tuple[bool, str]:
    """Return (passed, reason). Conservative defaults."""
    min_trades = int(criteria.get("min_trades", 5))
    max_dd = float(criteria.get("max_drawdown_pct", 25.0))
    min_return = float(criteria.get("min_total_return_pct", 0.0))
    require_beat_benchmark = bool(criteria.get("beat_benchmark", False))

    trades = int(metrics.get("trade_count") or metrics.get("fills") or 0)
    if isinstance(metrics.get("trade_count"), dict):
        trades = int(metrics["trade_count"].get("value") or 0)

    def _metric(name: str, default: float = 0.0) -> float:
        raw = metrics.get(name)
        if isinstance(raw, dict):
            if raw.get("status") == MetricStatus.UNMEASURED.value:
                return default
            return float(raw.get("value") or default)
        if raw is None:
            return default
        return float(raw)

    total_return = _metric("total_return_pct", 0.0)
    max_drawdown = _metric("max_drawdown_pct", 100.0)
    vs_bench = _metric("excess_return_pct", 0.0)

    if trades < min_trades:
        return False, f"insufficient trades ({trades} < {min_trades}) — small sample"
    if max_drawdown > max_dd:
        return False, f"drawdown {max_drawdown:.2f}% exceeds {max_dd}%"
    if total_return < min_return:
        return False, f"return {total_return:.2f}% below minimum {min_return}%"
    if require_beat_benchmark and vs_bench <= 0:
        return False, "did not beat buy-and-hold benchmark after costs"
    return True, "acceptance criteria met on held-out split"


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
            if compare_ts(e.available_at, as_of_ts) > 0:
                continue
            score = 0
            for k, v in feats.items():
                if e.features.get(k) == v or e.applicability.get(k) == v:
                    score += 1
            hits.append((score, e))
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
