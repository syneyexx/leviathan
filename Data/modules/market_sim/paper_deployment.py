"""PaperDeployment — validated shadow/paper ops for StrategyAssets (W16).

Rejects incompatible deployments. Live remains BLOCKED. Paper never proves
live profitability. Uses existing RiskGuard / MarketState / DecisionRecord paths.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from .features import FEATURE_PIPELINE_VERSION
from .sim_to_paper_gap import measure_sim_to_paper_gap
from .strategy_asset import (
    CompatibilitySurface,
    ExecutionCompatibilityManifest,
    StrategyAsset,
)
from .types import MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FeedHealth:
    """Current-market feed health — gaps/staleness/reconnect/provenance."""

    feed_id: str
    status: str  # HEALTHY | STALE | GAP | DISCONNECTED | UNMEASURED
    last_tick_ts: str | None = None
    as_of: str | None = None
    staleness_seconds: float | None = None
    gap_count: int = 0
    reconnect_count: int = 0
    provenance: str = ""
    max_staleness_seconds: float = 120.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "status": self.status,
            "last_tick_ts": self.last_tick_ts,
            "as_of": self.as_of,
            "staleness_seconds": self.staleness_seconds,
            "gap_count": self.gap_count,
            "reconnect_count": self.reconnect_count,
            "provenance": self.provenance,
            "max_staleness_seconds": self.max_staleness_seconds,
            "metadata": dict(self.metadata),
            "truth": {
                "stale_feed_blocks_blind_orders": True,
                "unmeasured_is_not_healthy": self.status == "UNMEASURED",
            },
        }


def assess_feed_health(
    *,
    feed_id: str,
    last_tick_ts: str | None,
    as_of: str | None = None,
    gap_count: int = 0,
    reconnect_count: int = 0,
    provenance: str = "",
    max_staleness_seconds: float = 120.0,
) -> FeedHealth:
    if not last_tick_ts:
        return FeedHealth(
            feed_id=feed_id,
            status="UNMEASURED",
            last_tick_ts=None,
            as_of=as_of or utc_now(),
            gap_count=gap_count,
            reconnect_count=reconnect_count,
            provenance=provenance or "no_tick",
            max_staleness_seconds=max_staleness_seconds,
        )
    as_of_ts = as_of or utc_now()
    try:
        last = datetime.fromisoformat(last_tick_ts.replace("Z", "+00:00"))
        now = datetime.fromisoformat(as_of_ts.replace("Z", "+00:00"))
        stale = max(0.0, (now - last).total_seconds())
    except ValueError:
        return FeedHealth(
            feed_id=feed_id,
            status="UNMEASURED",
            last_tick_ts=last_tick_ts,
            as_of=as_of_ts,
            provenance=provenance or "unparseable_ts",
            max_staleness_seconds=max_staleness_seconds,
        )
    if gap_count > 0:
        status = "GAP"
    elif stale > max_staleness_seconds:
        status = "STALE"
    else:
        status = "HEALTHY"
    return FeedHealth(
        feed_id=feed_id,
        status=status,
        last_tick_ts=last_tick_ts,
        as_of=as_of_ts,
        staleness_seconds=stale,
        gap_count=gap_count,
        reconnect_count=reconnect_count,
        provenance=provenance,
        max_staleness_seconds=max_staleness_seconds,
    )


def environment_fingerprint(
    *,
    feature_pipeline_version: str = FEATURE_PIPELINE_VERSION,
    risk_model_version: str | None = None,
    sizing_model_version: str | None = None,
    cost_assumptions: dict[str, Any] | None = None,
    feed_id: str = "",
    cadence: str = "",
    extra: dict[str, Any] | None = None,
) -> str:
    blob = {
        "feature_pipeline_version": feature_pipeline_version,
        "risk_model_version": risk_model_version,
        "sizing_model_version": sizing_model_version,
        "cost_assumptions": cost_assumptions or {},
        "feed_id": feed_id,
        "cadence": cadence,
        "extra": extra or {},
        "live": False,
    }
    return hashlib.sha256(
        json.dumps(blob, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass
class PaperDeployment:
    deployment_id: str
    strategy_asset_id: str
    strategy_version: int
    compatibility: ExecutionCompatibilityManifest
    universe: list[str]
    feed_id: str
    risk_config: dict[str, Any]
    sizing_config: dict[str, Any]
    cadence: str
    env_fingerprint: str
    status: str = "CREATED"  # CREATED | VALIDATED | RUNNING | PAUSED | KILLED | FAILED | STOPPED
    kill_switch: bool = False
    feed_health: FeedHealth | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "strategy_asset_id": self.strategy_asset_id,
            "strategy_version": self.strategy_version,
            "compatibility": self.compatibility.public_dict(),
            "universe": list(self.universe),
            "feed_id": self.feed_id,
            "risk_config": dict(self.risk_config),
            "sizing_config": dict(self.sizing_config),
            "cadence": self.cadence,
            "env_fingerprint": self.env_fingerprint,
            "status": self.status,
            "kill_switch": self.kill_switch,
            "feed_health": self.feed_health.public_dict() if self.feed_health else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "paper_only": True,
                "live_trading": "BLOCKED",
                "a5": "IMPOSSIBLE",
                "paper_does_not_prove_live_profitability": True,
                "reject_incompatible_deployment": True,
            },
        }


def create_paper_deployment(
    *,
    asset: StrategyAsset,
    universe: Sequence[str],
    feed_id: str,
    risk_config: dict[str, Any] | None = None,
    sizing_config: dict[str, Any] | None = None,
    cadence: str = "every_n_bars",
    feature_pipeline_version: str = FEATURE_PIPELINE_VERSION,
    available_features: set[str] | None = None,
) -> PaperDeployment:
    """Validate compatibility then create a paper deployment. Live always rejected."""
    compat = asset.compatibility
    check = compat.validate_against_runtime(
        feature_pipeline_version=feature_pipeline_version,
        available_features=available_features,
        surface=CompatibilitySurface.PAPER,
    )
    if not check.get("ok"):
        raise MarketSimError(
            "INCOMPATIBLE_DEPLOYMENT",
            f"paper deployment rejected: {', '.join(check.get('reasons') or [])}",
            http_status=409,
        )
    if not universe:
        raise MarketSimError("EMPTY_UNIVERSE", "paper deployment requires non-empty universe", http_status=400)
    # Asset must be at least VALIDATED/CHAMPION/RESEARCH for reproducible deploy — DRAFT refused.
    if asset.status in {"DRAFT"}:
        raise MarketSimError(
            "ASSET_NOT_READY",
            "DRAFT strategy assets cannot deploy to paper; promote with evidence first",
            http_status=409,
        )
    fp = environment_fingerprint(
        feature_pipeline_version=feature_pipeline_version,
        risk_model_version=compat.risk_model_version,
        sizing_model_version=compat.sizing_model_version,
        cost_assumptions=compat.cost_model_assumptions,
        feed_id=feed_id,
        cadence=cadence,
        extra={"strategy_asset_id": asset.asset_id, "version": asset.version},
    )
    now = utc_now()
    return PaperDeployment(
        deployment_id=str(uuid.uuid4()),
        strategy_asset_id=asset.asset_id,
        strategy_version=asset.version,
        compatibility=compat,
        universe=[str(s).upper() for s in universe],
        feed_id=feed_id,
        risk_config=dict(risk_config or {}),
        sizing_config=dict(sizing_config or {}),
        cadence=cadence,
        env_fingerprint=fp,
        status="VALIDATED",
        created_at=now,
        updated_at=now,
        metadata={"compatibility_check": check},
    )


def refresh_deployment_feed(deployment: PaperDeployment, health: FeedHealth) -> PaperDeployment:
    deployment.feed_health = health
    deployment.updated_at = utc_now()
    if health.status in {"STALE", "GAP", "DISCONNECTED"} and deployment.status == "RUNNING":
        deployment.metadata = {
            **deployment.metadata,
            "feed_block": health.status,
            "orders_blocked_until_healthy": True,
        }
    return deployment


def arm_deployment_kill_switch(deployment: PaperDeployment, *, armed: bool = True, reason: str = "") -> PaperDeployment:
    deployment.kill_switch = bool(armed)
    deployment.status = "KILLED" if armed else ("PAUSED" if deployment.status == "KILLED" else deployment.status)
    deployment.updated_at = utc_now()
    deployment.metadata = {**deployment.metadata, "kill_reason": reason or ("armed" if armed else "disarmed")}
    return deployment


def assert_deployment_may_order(deployment: PaperDeployment) -> None:
    if deployment.kill_switch or deployment.status == "KILLED":
        raise MarketSimError("KILL_SWITCH", "paper deployment kill switch armed", http_status=409)
    if deployment.feed_health and deployment.feed_health.status in {"STALE", "GAP", "DISCONNECTED", "UNMEASURED"}:
        raise MarketSimError(
            "FEED_UNCERTAIN",
            f"refusing paper order under feed status={deployment.feed_health.status}",
            http_status=409,
        )
    if deployment.status not in {"VALIDATED", "RUNNING", "PAUSED"}:
        raise MarketSimError("DEPLOYMENT_NOT_ACTIVE", f"status={deployment.status}", http_status=409)


def compare_sim_shadow_paper(
    *,
    symbol: str,
    modelled_fills: Sequence[dict[str, Any]] | None = None,
    shadow_intents: Sequence[dict[str, Any]] | None = None,
    paper_observed: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Three-way honesty: modelled sim fill vs shadow intent vs paper observed."""
    gap = measure_sim_to_paper_gap(
        symbol=symbol,
        sim_fills=list(modelled_fills or []),
        paper_fills=list(paper_observed or []),
    )
    shadow = list(shadow_intents or [])
    observed = list(paper_observed or [])
    intent_vs_obs = None
    if shadow and observed:
        intent_vs_obs = measure_sim_to_paper_gap(
            symbol=symbol,
            sim_fills=shadow,
            paper_fills=observed,
        ).public_dict()
        intent_vs_obs["comparison"] = "shadow_intent_vs_paper_observed"
    return {
        "symbol": symbol,
        "modelled_vs_paper": gap.public_dict(),
        "shadow_vs_paper": intent_vs_obs,
        "shadow_intent_count": len(shadow),
        "paper_observed_count": len(observed),
        "modelled_fill_count": len(list(modelled_fills or [])),
        "truth": {
            "paper_does_not_prove_live_profitability": True,
            "unmeasured_gaps_stay_unmeasured": gap.status == "UNMEASURED",
            "live_trading": "BLOCKED",
        },
    }
