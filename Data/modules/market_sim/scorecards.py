"""Agent scorecards, readiness ladder, and leaderboard FDR penalty (T8 / G27, G28)."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from .metrics import (
    _safe_sharpe,
    bootstrap_metric_cis,
    max_drawdown,
    periods_per_year_for_timeframe,
)
from .orchestra.types import AutonomyLevel
from .science import benjamini_hochberg
from .types import MarketSimError, MetricStatus


READINESS_LADDER: tuple[str, ...] = tuple(level.value for level in AutonomyLevel)
# A5 (live) does not exist — blocked by construction.
BLOCKED_READINESS = frozenset({"A5", "LIVE", "LIVE_ELIGIBLE"})


@dataclass
class AgentScorecard:
    scorecard_id: str
    agent_id: str
    agent_version: str
    regime: str
    year: int | None
    equity: list[float]
    sharpe: dict[str, Any]
    max_drawdown: dict[str, Any]
    bootstrap: dict[str, Any]
    violations: dict[str, int]
    token_cost: int
    latency_ms: float
    n_episodes: int
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "scorecard_id": self.scorecard_id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "regime": self.regime,
            "year": self.year,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "bootstrap": self.bootstrap,
            "violations": dict(self.violations),
            "token_cost": self.token_cost,
            "latency_ms": self.latency_ms,
            "n_episodes": self.n_episodes,
            "equity_points": len(self.equity),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "per_agent_evaluation": True,
                "cis_when_measured": True,
                "a5_blocked": True,
            },
        }


def build_agent_scorecard(
    *,
    agent_id: str,
    agent_version: str = "v1",
    equity: Sequence[float],
    regime: str = "all",
    year: int | None = None,
    violations: dict[str, int] | None = None,
    token_cost: int = 0,
    latency_ms: float = 0.0,
    n_episodes: int = 1,
    timeframe: str = "1h",
    created_at: str,
    bootstrap: bool = True,
) -> AgentScorecard:
    eq = [float(x) for x in equity]
    returns: list[float] = []
    for i in range(1, len(eq)):
        if eq[i - 1] > 0:
            returns.append((eq[i] - eq[i - 1]) / eq[i - 1])
    ppy = periods_per_year_for_timeframe(timeframe)
    sharpe = _safe_sharpe(returns, periods_per_year=ppy)
    dd = max_drawdown(eq)
    boot: dict[str, Any] = {"status": MetricStatus.UNMEASURED.value}
    if bootstrap and len(returns) >= 2:
        boot = bootstrap_metric_cis(returns, periods_per_year=ppy, n_boot=200, seed=42)
    return AgentScorecard(
        scorecard_id=str(uuid.uuid4()),
        agent_id=agent_id,
        agent_version=agent_version,
        regime=regime,
        year=year,
        equity=eq,
        sharpe=sharpe,
        max_drawdown=dd,
        bootstrap=boot,
        violations=dict(
            violations
            or {
                "risk_rejections": 0,
                "override_attempts": 0,
                "causality_attempts": 0,
            }
        ),
        token_cost=int(token_cost),
        latency_ms=float(latency_ms),
        n_episodes=int(n_episodes),
        created_at=created_at,
    )


def _sharpe_to_p_value(sharpe_value: float | None, n: int) -> float:
    """Approximate two-sided p-value under H0: Sharpe=0 (normal approx)."""
    if sharpe_value is None or n < 2:
        return 1.0
    # SE(Sharpe) ≈ sqrt((1 + 0.5*S^2) / n) for iid normal returns.
    se = math.sqrt((1.0 + 0.5 * sharpe_value * sharpe_value) / max(1, n))
    if se <= 0:
        return 1.0
    z = abs(sharpe_value) / se
    # erfc for two-sided normal p
    return float(math.erfc(z / math.sqrt(2.0)))


def leaderboard_with_penalty(
    rows: list[dict[str, Any]],
    *,
    q: float = 0.05,
) -> list[dict[str, Any]]:
    """Augment leaderboard rows with Sharpe/drawdown CIs and BH-FDR penalty (G27).

    Rows that fail FDR at level ``q`` receive ``multiple_testing_penalty=True`` and
    are demoted below discoveries while preserving measured metrics.
    """
    if not rows:
        return []
    p_values: list[float] = []
    labels: list[str] = []
    for i, row in enumerate(rows):
        sharpe = row.get("sharpe") or {}
        value = sharpe.get("value") if isinstance(sharpe, dict) else None
        n = int(row.get("equity_points") or row.get("n_returns") or 2)
        p_values.append(_sharpe_to_p_value(float(value) if value is not None else None, n))
        labels.append(str(row.get("agent_id") or f"row-{i}"))

    fdr = benjamini_hochberg(p_values, q=q, labels=labels)
    discoveries = {d["label"] for d in fdr.get("discoveries") or []}
    adjusted = list(fdr.get("adjusted_p") or [])

    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        item = dict(row)
        label = labels[i]
        item["adjusted_p"] = adjusted[i] if i < len(adjusted) else 1.0
        item["multiple_testing_penalty"] = label not in discoveries
        item["fdr_discovery"] = label in discoveries
        # Penalty: demote non-discoveries in sort key via flag (caller may re-sort).
        out.append(item)

    out.sort(
        key=lambda r: (
            0 if r.get("fdr_discovery") else 1,
            -float((r.get("sharpe") or {}).get("value") or (r.get("equity") or 0.0)),
        )
    )
    for rank, row in enumerate(out, start=1):
        row["rank"] = rank
        row["truth"] = {
            **dict(row.get("truth") or {}),
            "multiple_testing_penalty": True,
            "fdr_procedure": "benjamini_hochberg",
        }
    return out


def enrich_leaderboard_row(
    *,
    agent_id: str,
    equity: float,
    realized_pnl: float,
    fees_paid: float,
    trades: int,
    equity_curve: Sequence[float] | None = None,
    timeframe: str = "1h",
    violations: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a leaderboard row with per-agent Sharpe/drawdown when equity history exists."""
    curve = [float(x) for x in (equity_curve or [])]
    returns: list[float] = []
    for i in range(1, len(curve)):
        if curve[i - 1] > 0:
            returns.append((curve[i] - curve[i - 1]) / curve[i - 1])
    ppy = periods_per_year_for_timeframe(timeframe)
    sharpe = _safe_sharpe(returns, periods_per_year=ppy) if returns else {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "insufficient equity history",
    }
    dd = max_drawdown(curve) if len(curve) >= 2 else {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "insufficient equity history",
    }
    return {
        "agent_id": agent_id,
        "equity": float(equity),
        "realized_pnl": float(realized_pnl),
        "fees_paid": float(fees_paid),
        "trades": int(trades),
        "initial_comparable": True,
        "sharpe": sharpe,
        "max_drawdown": dd,
        "equity_points": len(curve),
        "n_returns": len(returns),
        "violations": dict(violations or {}),
        "confidence": {
            "sharpe_status": sharpe.get("status"),
            "drawdown_status": dd.get("status"),
        },
    }


# --- Readiness ladder (G28) ---

def parse_readiness_level(raw: Any) -> AutonomyLevel:
    text = str(raw or "").strip().upper()
    if text in BLOCKED_READINESS or text.startswith("A5"):
        raise MarketSimError(
            "READINESS_A5_BLOCKED",
            "A5/live readiness does not exist — live money is blocked by construction",
            http_status=403,
        )
    try:
        return AutonomyLevel.parse(text)
    except ValueError as exc:
        raise MarketSimError("INVALID_READINESS", str(exc), http_status=400) from exc


def can_advance_readiness(
    current: str | AutonomyLevel,
    target: str | AutonomyLevel,
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Policy: advance at most one rung; require MEASURED evidence; A5 blocked."""
    cur = current if isinstance(current, AutonomyLevel) else parse_readiness_level(current)
    # Target parse raises on A5.
    tgt = target if isinstance(target, AutonomyLevel) else parse_readiness_level(target)
    evidence = dict(evidence or {})
    measured = str(evidence.get("measurement") or evidence.get("state") or "").upper()
    reasons: list[str] = []
    allowed = True
    if tgt.rank < cur.rank:
        # Demotion always allowed.
        return {
            "allowed": True,
            "from": cur.value,
            "to": tgt.value,
            "reasons": ["demotion"],
            "truth": {"a5_blocked": True, "policy_enforced": True},
        }
    if tgt.rank > cur.rank + 1:
        allowed = False
        reasons.append("cannot_skip_rungs")
    if tgt.rank > cur.rank and measured not in {"MEASURED", "PASS"}:
        allowed = False
        reasons.append("UNMEASURED_blocks_advancement")
    if tgt.rank == cur.rank:
        reasons.append("same_level")
    return {
        "allowed": allowed,
        "from": cur.value,
        "to": tgt.value,
        "reasons": reasons or ["ok"],
        "truth": {"a5_blocked": True, "policy_enforced": True, "unmeasured_blocks": True},
    }


def readiness_public_dict(
    *,
    agent_id: str,
    level: str | AutonomyLevel,
    measurement: str = "UNMEASURED",
    reason: str = "",
    updated_at: str = "",
) -> dict[str, Any]:
    lvl = level if isinstance(level, AutonomyLevel) else parse_readiness_level(level)
    return {
        "agent_id": agent_id,
        "level": lvl.value,
        "measurement": measurement,
        "reason": reason,
        "updated_at": updated_at,
        "ladder": list(READINESS_LADDER),
        "truth": {
            "a5_blocked": True,
            "live_never_a_level": True,
            "policy_enforced": True,
        },
    }
