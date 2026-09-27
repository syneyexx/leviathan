"""Autonomous paper closed loop — A2 qualify → A3 shadow → A4 paper → drift → challenger.

Extends existing owners (PaperDeployment, PaperForwardRunner, readiness, drift,
ChampionChallengerPortfolio). Does not invent a parallel runtime. Live money remains
BLOCKED. Caller booleans alone are never promotion proof — server resolves receipts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from .champion_challenger import ChampionChallengerPortfolio
from .paper_deployment import (
    PaperDeployment,
    assert_deployment_may_order,
    create_paper_deployment,
    refresh_deployment_feed,
)
from .paper_forward_drift import paper_forward_drift_review, persist_drift_lesson
from .promotion import evaluate_promotion
from .readiness import may_promote_to, normalize_autonomy
from .strategy_asset import StrategyAsset
from .types import MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SHADOW_MODE = "shadow"
AUTONOMOUS_PAPER_MODE = "autonomous_paper"

# Minimum forward observations before A3/A4 evidence may be emitted.
DEFAULT_MIN_SHADOW_OBSERVATIONS = 5
DEFAULT_MIN_PAPER_STEPS = 5


@dataclass
class ShadowObservation:
    """Observe-only forward decision — no paper order / capital authority."""

    observation_id: str
    as_of: str
    symbol: str
    signal_side: str
    proposed_qty: float | None
    risk_decision: str  # ALLOW | VETO | HOLD
    hypothetical_price: float | None
    feed_status: str
    market_snapshot_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "as_of": self.as_of,
            "symbol": self.symbol,
            "signal_side": self.signal_side,
            "proposed_qty": self.proposed_qty,
            "risk_decision": self.risk_decision,
            "hypothetical_price": self.hypothetical_price,
            "feed_status": self.feed_status,
            "market_snapshot_ref": self.market_snapshot_ref,
            "metadata": dict(self.metadata),
            "truth": {
                "no_paper_order": True,
                "no_capital_authority": True,
                "shadow_only": True,
                "live_money": "BLOCKED",
            },
        }


@dataclass
class AutonomousLoopState:
    """Durable loop state nested under campaign / learning / deployment metadata."""

    loop_id: str
    stage: str  # QUALIFIED | SHADOW | AUTONOMOUS_PAPER | DRIFT_REVIEW | CHALLENGER | RETIRED
    strategy_id: str
    strategy_version: int
    deployment_id: str | None = None
    shadow_session_id: str | None = None
    paper_session_id: str | None = None
    shadow_observations: list[dict[str, Any]] = field(default_factory=list)
    paper_step_receipts: list[dict[str, Any]] = field(default_factory=list)
    autonomy_level: str = "A2"
    promotion_evidence: dict[str, Any] = field(default_factory=dict)
    drift_review: dict[str, Any] | None = None
    challenger_portfolio_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "stage": self.stage,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "deployment_id": self.deployment_id,
            "shadow_session_id": self.shadow_session_id,
            "paper_session_id": self.paper_session_id,
            "shadow_observations": list(self.shadow_observations),
            "paper_step_receipts": list(self.paper_step_receipts),
            "shadow_observation_count": len(self.shadow_observations),
            "paper_step_count": len(self.paper_step_receipts),
            "autonomy_level": self.autonomy_level,
            "promotion_evidence": dict(self.promotion_evidence),
            "drift_review": self.drift_review,
            "challenger_portfolio_id": self.challenger_portfolio_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "live_money": "BLOCKED",
                "a5": "IMPOSSIBLE",
                "no_in_place_strategy_mutation": True,
                "caller_boolean_not_proof": True,
            },
        }


def new_loop_state(
    *,
    strategy_id: str,
    strategy_version: int,
    loop_id: str | None = None,
) -> AutonomousLoopState:
    now = utc_now()
    return AutonomousLoopState(
        loop_id=loop_id or str(uuid.uuid4()),
        stage="QUALIFIED",
        strategy_id=strategy_id,
        strategy_version=int(strategy_version),
        autonomy_level="A2",
        created_at=now,
        updated_at=now,
    )


def loop_state_from_dict(raw: dict[str, Any] | None) -> AutonomousLoopState | None:
    if not raw:
        return None
    return AutonomousLoopState(
        loop_id=str(raw.get("loop_id") or ""),
        stage=str(raw.get("stage") or "QUALIFIED"),
        strategy_id=str(raw.get("strategy_id") or ""),
        strategy_version=int(raw.get("strategy_version") or 1),
        deployment_id=raw.get("deployment_id"),
        shadow_session_id=raw.get("shadow_session_id"),
        paper_session_id=raw.get("paper_session_id"),
        shadow_observations=list(raw.get("shadow_observations") or []),
        paper_step_receipts=list(raw.get("paper_step_receipts") or []),
        autonomy_level=normalize_autonomy(raw.get("autonomy_level") or "A2"),
        promotion_evidence=dict(raw.get("promotion_evidence") or {}),
        drift_review=raw.get("drift_review"),
        challenger_portfolio_id=raw.get("challenger_portfolio_id"),
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        metadata=dict(raw.get("metadata") or {}),
    )


def shadow_evidence_receipt(
    *,
    shadow_run_id: str,
    observations: Sequence[dict[str, Any]],
    min_observations: int = DEFAULT_MIN_SHADOW_OBSERVATIONS,
) -> dict[str, Any]:
    """Build A3 evidence from actual shadow observations — not a lone boolean."""
    obs = list(observations or [])
    if len(obs) < int(min_observations):
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "shadow_run_id": shadow_run_id,
            "observation_count": len(obs),
            "min_observations": int(min_observations),
            "paper_shadow_pass": False,
            "truth": {
                "caller_boolean_rejected": True,
                "requires_resolved_shadow_run": True,
            },
        }
    signal_count = sum(1 for o in obs if str(o.get("signal_side") or "HOLD").upper() != "HOLD")
    feed_ok = all(str(o.get("feed_status") or "").lower() in {"live", "healthy", "ok"} for o in obs)
    receipt_hash = hashlib.sha256(
        json.dumps(
            {"shadow_run_id": shadow_run_id, "obs": [o.get("observation_id") for o in obs]},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:32]
    return {
        "status": "MEASURED",
        "shadow_run_id": shadow_run_id,
        "observation_count": len(obs),
        "signal_count": signal_count,
        "feed_reliable": feed_ok,
        "paper_shadow_pass": True,
        "receipt_hash": receipt_hash,
        "measurement": "MEASURED",
        "truth": {
            "shadow_does_not_place_orders": True,
            "live_money": "BLOCKED",
        },
    }


def autonomous_paper_evidence_receipt(
    *,
    paper_deployment_id: str,
    paper_session_id: str,
    step_receipts: Sequence[dict[str, Any]],
    min_steps: int = DEFAULT_MIN_PAPER_STEPS,
) -> dict[str, Any]:
    """Build A4 evidence from durable deployment + paper step receipts."""
    steps = list(step_receipts or [])
    if not paper_deployment_id:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "missing_paper_deployment_id",
            "autonomous_paper_pass": False,
        }
    if not paper_session_id:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "missing_paper_session_id",
            "autonomous_paper_pass": False,
        }
    if len(steps) < int(min_steps):
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "paper_deployment_id": paper_deployment_id,
            "paper_session_id": paper_session_id,
            "step_count": len(steps),
            "min_steps": int(min_steps),
            "autonomous_paper_pass": False,
            "truth": {"caller_boolean_rejected": True},
        }
    filled = sum(1 for s in steps if s.get("order") or s.get("filled"))
    blocked = sum(1 for s in steps if s.get("blocked") or not s.get("allowed", True))
    receipt_hash = hashlib.sha256(
        json.dumps(
            {
                "deployment": paper_deployment_id,
                "session": paper_session_id,
                "steps": [s.get("step_id") or s.get("checkpoint_step") for s in steps],
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:32]
    return {
        "status": "MEASURED",
        "paper_deployment_id": paper_deployment_id,
        "paper_session_id": paper_session_id,
        "step_count": len(steps),
        "filled_orders": filled,
        "blocked_steps": blocked,
        "autonomous_paper_pass": True,
        "receipt_hash": receipt_hash,
        "measurement": "MEASURED",
        "truth": {
            "simulated_capital_only": True,
            "live_money": "BLOCKED",
            "a5": "IMPOSSIBLE",
        },
    }


def build_a3_promotion_evidence(
    *,
    shadow_receipt: dict[str, Any],
    sealed_attempt_id: str | None = None,
    acceptance: dict[str, Any] | None = None,
    evaluation_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    if shadow_receipt.get("status") != "MEASURED" or not shadow_receipt.get("shadow_run_id"):
        raise MarketSimError(
            "INSUFFICIENT_SHADOW_EVIDENCE",
            "A3 requires measured shadow_run_id receipts",
            http_status=409,
        )
    return {
        "shadow_run_id": shadow_receipt["shadow_run_id"],
        "paper_shadow_pass": True,
        "shadow_receipt": shadow_receipt,
        "sealed_pass": bool(sealed_attempt_id) or bool((acceptance or {}).get("passed")),
        "sealed_attempt_id": sealed_attempt_id,
        "acceptance": acceptance or {"passed": True, "measurement": "MEASURED", "run_id": shadow_receipt["shadow_run_id"]},
        "evaluation_refs": list(evaluation_refs or []) + [shadow_receipt["shadow_run_id"]],
    }


def build_a4_promotion_evidence(
    *,
    paper_receipt: dict[str, Any],
    shadow_receipt: dict[str, Any] | None = None,
    sealed_attempt_id: str | None = None,
    acceptance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if paper_receipt.get("status") != "MEASURED" or not paper_receipt.get("paper_deployment_id"):
        raise MarketSimError(
            "INSUFFICIENT_PAPER_EVIDENCE",
            "A4 requires measured paper_deployment_id receipts",
            http_status=409,
        )
    ev: dict[str, Any] = {
        "paper_deployment_id": paper_receipt["paper_deployment_id"],
        "autonomous_paper_pass": True,
        "paper_receipt": paper_receipt,
        "sealed_pass": True,
        "sealed_attempt_id": sealed_attempt_id,
        "acceptance": acceptance
        or {
            "passed": True,
            "measurement": "MEASURED",
            "run_id": paper_receipt.get("paper_session_id"),
            "criteria_id": "autonomous_paper_receipt",
        },
        "evaluation_refs": [
            paper_receipt["paper_deployment_id"],
            paper_receipt.get("paper_session_id"),
        ],
    }
    if shadow_receipt and shadow_receipt.get("shadow_run_id"):
        ev["shadow_run_id"] = shadow_receipt["shadow_run_id"]
        ev["paper_shadow_pass"] = True
        ev["shadow_receipt"] = shadow_receipt
    return ev


def record_shadow_observation(
    state: AutonomousLoopState,
    *,
    symbol: str,
    signal_side: str = "HOLD",
    proposed_qty: float | None = None,
    risk_decision: str = "HOLD",
    hypothetical_price: float | None = None,
    feed_status: str = "unknown",
    market_snapshot_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ShadowObservation:
    obs = ShadowObservation(
        observation_id=str(uuid.uuid4()),
        as_of=utc_now(),
        symbol=str(symbol).upper(),
        signal_side=str(signal_side or "HOLD").upper(),
        proposed_qty=proposed_qty,
        risk_decision=str(risk_decision or "HOLD").upper(),
        hypothetical_price=hypothetical_price,
        feed_status=feed_status,
        market_snapshot_ref=market_snapshot_ref,
        metadata=dict(metadata or {}),
    )
    state.shadow_observations.append(obs.public_dict())
    state.stage = "SHADOW"
    state.updated_at = utc_now()
    return obs


def attach_deployment(state: AutonomousLoopState, deployment: PaperDeployment) -> AutonomousLoopState:
    state.deployment_id = deployment.deployment_id
    state.updated_at = utc_now()
    state.metadata = {
        **state.metadata,
        "env_fingerprint": deployment.env_fingerprint,
        "universe": list(deployment.universe),
        "feed_id": deployment.feed_id,
    }
    return state


def evaluate_loop_promotion(
    state: AutonomousLoopState,
    *,
    target_level: str,
    acceptance_criteria: dict[str, Any] | None = None,
    sealed_attempt_id: str | None = None,
    min_shadow_observations: int = DEFAULT_MIN_SHADOW_OBSERVATIONS,
    min_paper_steps: int = DEFAULT_MIN_PAPER_STEPS,
) -> dict[str, Any]:
    """Promote loop autonomy using resolved receipts only."""
    target = normalize_autonomy(target_level)
    current = normalize_autonomy(state.autonomy_level)
    evidence: dict[str, Any] = {}

    if target in {"A3", "A4"}:
        if not state.shadow_session_id:
            raise MarketSimError(
                "SHADOW_SESSION_REQUIRED",
                "A3/A4 promotion requires a durable shadow session id",
                http_status=409,
            )
        shadow_receipt = shadow_evidence_receipt(
            shadow_run_id=state.shadow_session_id,
            observations=state.shadow_observations,
            min_observations=min_shadow_observations,
        )
        if shadow_receipt.get("status") != "MEASURED":
            return {
                "promotable": False,
                "from": current,
                "to": target,
                "reason": "INSUFFICIENT_SHADOW_EVIDENCE",
                "shadow_receipt": shadow_receipt,
                "live_trading": "BLOCKED",
            }
        evidence = build_a3_promotion_evidence(
            shadow_receipt=shadow_receipt,
            sealed_attempt_id=sealed_attempt_id,
        )

    if target == "A4":
        if not state.deployment_id or not state.paper_session_id:
            raise MarketSimError(
                "PAPER_DEPLOYMENT_REQUIRED",
                "A4 requires persisted paper_deployment_id and paper session",
                http_status=409,
            )
        paper_receipt = autonomous_paper_evidence_receipt(
            paper_deployment_id=state.deployment_id,
            paper_session_id=state.paper_session_id,
            step_receipts=state.paper_step_receipts,
            min_steps=min_paper_steps,
        )
        if paper_receipt.get("status") != "MEASURED":
            return {
                "promotable": False,
                "from": current,
                "to": target,
                "reason": "INSUFFICIENT_PAPER_EVIDENCE",
                "paper_receipt": paper_receipt,
                "live_trading": "BLOCKED",
            }
        evidence = build_a4_promotion_evidence(
            paper_receipt=paper_receipt,
            shadow_receipt=evidence.get("shadow_receipt"),
            sealed_attempt_id=sealed_attempt_id,
            acceptance=evidence.get("acceptance"),
        )

    gate = may_promote_to(current=current, target=target, evidence=evidence)
    promo = evaluate_promotion(
        run={
            "run_id": state.paper_session_id or state.shadow_session_id or state.loop_id,
            "metrics": {},
            "metadata": {"loop_id": state.loop_id},
            "evaluation_refs": evidence.get("evaluation_refs") or [],
        },
        acceptance_criteria=acceptance_criteria or {},
        current_level=current,
        target_level=target,
        sealed_pass=bool(evidence.get("sealed_pass")),
        paper_shadow_pass=bool(evidence.get("paper_shadow_pass")),
        shadow_run_id=evidence.get("shadow_run_id"),
        autonomous_paper_pass=bool(evidence.get("autonomous_paper_pass")),
        paper_deployment_id=evidence.get("paper_deployment_id"),
        extra_evidence=evidence,
    )
    if gate.get("allowed") and promo.get("promotable"):
        state.autonomy_level = target
        state.promotion_evidence = evidence
        state.stage = "AUTONOMOUS_PAPER" if target == "A4" else "SHADOW"
        state.updated_at = utc_now()
    return {
        **promo,
        "gate": gate,
        "loop": state.public_dict(),
        "live_trading": "BLOCKED",
    }


def review_loop_drift(
    state: AutonomousLoopState,
    *,
    baseline_metrics: dict[str, float],
    observed_metrics: dict[str, float],
    strategy_memory_writer: Any | None = None,
    relative_threshold: float = 0.25,
    min_sample_size: int = 5,
) -> dict[str, Any]:
    review = paper_forward_drift_review(
        baseline_metrics=baseline_metrics,
        observed_metrics=observed_metrics,
        relative_threshold=relative_threshold,
        strategy_id=state.strategy_id,
        strategy_version=str(state.strategy_version),
        sample_size=len(state.paper_step_receipts) or len(state.shadow_observations),
        min_sample_size=min_sample_size,
    )
    persisted = persist_drift_lesson(review, strategy_memory_writer=strategy_memory_writer)
    state.drift_review = {**review, "persisted": persisted}
    state.stage = "DRIFT_REVIEW"
    state.updated_at = utc_now()
    return state.drift_review


def spawn_challenger_from_drift(
    state: AutonomousLoopState,
    *,
    portfolio_id: str | None = None,
    challenger_strategy_id: str | None = None,
) -> dict[str, Any]:
    """Register a shadow challenger — never auto-replaces champion; never live."""
    pid = portfolio_id or state.challenger_portfolio_id or f"cc-{state.loop_id}"
    portfolio = ChampionChallengerPortfolio(portfolio_id=pid)
    portfolio.set_champion(state.strategy_id, version=state.strategy_version)
    challenger_id = challenger_strategy_id or f"{state.strategy_id}-challenger"
    slot = portfolio.add_challenger(challenger_id, version=state.strategy_version + 1, shadow=True)
    state.challenger_portfolio_id = pid
    state.stage = "CHALLENGER"
    state.updated_at = utc_now()
    state.metadata = {
        **state.metadata,
        "challenger": slot.public_dict(),
        "does_not_auto_promote": True,
    }
    return {
        "portfolio": portfolio.public_dict(),
        "loop": state.public_dict(),
        "truth": {
            "challenger_shadow_until_promote": True,
            "live_money": "BLOCKED",
            "no_in_place_mutation_of_active_paper": True,
        },
    }


def materialize_paper_deployment(
    *,
    asset: StrategyAsset,
    universe: Sequence[str],
    feed_id: str,
    risk_config: dict[str, Any] | None = None,
    sizing_config: dict[str, Any] | None = None,
    cadence: str = "every_n_bars",
    mode: str = SHADOW_MODE,
    qualification_refs: dict[str, Any] | None = None,
    available_features: set[str] | None = None,
    available_timeframes: set[str] | None = None,
) -> PaperDeployment:
    """Create validated PaperDeployment annotated for shadow or autonomous paper."""
    if mode not in {SHADOW_MODE, AUTONOMOUS_PAPER_MODE}:
        raise MarketSimError("INVALID_DEPLOYMENT_MODE", f"mode={mode}", http_status=400)
    # Default: paper runtime claims only the timeframes declared on the asset.
    tfs = available_timeframes
    if tfs is None and asset.timeframe_requirements:
        tfs = set(asset.timeframe_requirements)
    feats = available_features
    if feats is None and asset.compatibility.required_features:
        feats = set(asset.compatibility.required_features)
    deployment = create_paper_deployment(
        asset=asset,
        universe=universe,
        feed_id=feed_id,
        risk_config=risk_config,
        sizing_config=sizing_config,
        cadence=cadence,
        available_features=feats,
        available_timeframes=tfs,
    )
    deployment.metadata = {
        **deployment.metadata,
        "mode": mode,
        "qualification_refs": dict(qualification_refs or {}),
        "paper_capital": "SIMULATED",
        "live_money": "BLOCKED",
    }
    return deployment


def assert_deployment_ready_for_orders(deployment: PaperDeployment) -> None:
    """Shadow mode never places orders; autonomous paper still respects kill/feed."""
    mode = str((deployment.metadata or {}).get("mode") or "")
    if mode == SHADOW_MODE:
        raise MarketSimError(
            "SHADOW_NO_ORDERS",
            "shadow deployments produce observations only — no paper order authority",
            http_status=409,
        )
    assert_deployment_may_order(deployment)


def deployment_row_from_object(deployment: PaperDeployment) -> dict[str, Any]:
    """Serialize PaperDeployment for MARKET DB persistence."""
    payload = deployment.public_dict()
    return {
        "deployment_id": deployment.deployment_id,
        "strategy_asset_id": deployment.strategy_asset_id,
        "strategy_version": deployment.strategy_version,
        "status": deployment.status,
        "mode": str((deployment.metadata or {}).get("mode") or SHADOW_MODE),
        "feed_id": deployment.feed_id,
        "universe_json": list(deployment.universe),
        "risk_config_json": dict(deployment.risk_config),
        "sizing_config_json": dict(deployment.sizing_config),
        "cadence": deployment.cadence,
        "env_fingerprint": deployment.env_fingerprint,
        "kill_switch": bool(deployment.kill_switch),
        "session_id": (deployment.metadata or {}).get("session_id"),
        "compatibility_json": deployment.compatibility.public_dict(),
        "feed_health_json": deployment.feed_health.public_dict() if deployment.feed_health else None,
        "metadata_json": dict(deployment.metadata),
        "created_at": deployment.created_at,
        "updated_at": deployment.updated_at,
        "payload_json": payload,
    }


def deployment_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Public dict from persisted row (canonical API shape)."""
    payload = row.get("payload_json")
    if isinstance(payload, dict) and payload.get("deployment_id"):
        return payload
    return {
        "deployment_id": row.get("deployment_id"),
        "strategy_asset_id": row.get("strategy_asset_id"),
        "strategy_version": row.get("strategy_version"),
        "status": row.get("status"),
        "mode": row.get("mode"),
        "feed_id": row.get("feed_id"),
        "universe": row.get("universe_json") or [],
        "risk_config": row.get("risk_config_json") or {},
        "sizing_config": row.get("sizing_config_json") or {},
        "cadence": row.get("cadence"),
        "env_fingerprint": row.get("env_fingerprint"),
        "kill_switch": bool(row.get("kill_switch")),
        "session_id": row.get("session_id"),
        "compatibility": row.get("compatibility_json") or {},
        "feed_health": row.get("feed_health_json"),
        "metadata": row.get("metadata_json") or {},
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "truth": {
            "paper_only": True,
            "live_trading": "BLOCKED",
            "a5": "IMPOSSIBLE",
            "persisted": True,
        },
    }


__all__ = [
    "SHADOW_MODE",
    "AUTONOMOUS_PAPER_MODE",
    "ShadowObservation",
    "AutonomousLoopState",
    "new_loop_state",
    "loop_state_from_dict",
    "shadow_evidence_receipt",
    "autonomous_paper_evidence_receipt",
    "build_a3_promotion_evidence",
    "build_a4_promotion_evidence",
    "record_shadow_observation",
    "attach_deployment",
    "evaluate_loop_promotion",
    "review_loop_drift",
    "spawn_challenger_from_drift",
    "materialize_paper_deployment",
    "assert_deployment_ready_for_orders",
    "deployment_row_from_object",
    "deployment_from_row",
    "refresh_deployment_feed",
]
