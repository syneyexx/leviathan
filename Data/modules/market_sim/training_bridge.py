"""Trading → Training bridge (Master Program T16).

Exports verified trading trajectories into existing LEVIATHAN Training / VerifiedExperience
without creating TradingTrainer2. No raw private chain-of-thought.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from Data.modules.cognition.experience import ExperienceStore, VerifiedExperience


def trading_decision_to_experience(
    decision: dict[str, Any],
    *,
    verified: bool = False,
    outcome: str = "pending",
) -> VerifiedExperience:
    """Map a shadow/paper decision record into a VerifiedExperience candidate."""
    exp = VerifiedExperience(
        experience_id=str(uuid.uuid4()),
        task_type="trading_decision",
        domain="trading",
        task_summary=(
            f"{decision.get('side')} {decision.get('qty')} {decision.get('symbol')} "
            f"@ expected={decision.get('expected_execution_price')}"
        ),
        strategy=str(decision.get("strategy_id") or "unbound"),
        outcome=outcome,
        verification_status="verified" if verified else "unverified",
        relevant_context_refs=[
            str(decision.get("session_id") or ""),
            str(decision.get("decision_id") or ""),
        ],
        action_sequence_summary=[
            f"decide:{decision.get('side')}",
            "no_broker" if decision.get("truth", {}).get("no_broker_order") else "broker_or_sim",
        ],
        evidence_refs=[str(decision.get("decision_id") or "")],
        reward=(decision.get("realized_outcome") or {}).get("shadow_pnl"),
        privacy_class="standard",
        metadata={
            "strategy_version": decision.get("strategy_version"),
            "feed_latency_ms": decision.get("feed_latency_ms"),
            "mode": decision.get("metadata", {}).get("mode")
            or ("SHADOW" if decision.get("truth", {}).get("shadow_live") else "UNKNOWN"),
            "no_raw_cot": True,
        },
    )
    if not verified:
        exp.admitted = False
        exp.admission_reason = "unverified_trading_outcome"
    return exp


def export_verified_trading_trajectories(
    decisions: Sequence[dict[str, Any]],
    *,
    store: ExperienceStore | None = None,
    require_outcome: bool = True,
) -> dict[str, Any]:
    """Admit only decisions with attached outcomes into ExperienceStore (T16)."""
    exp_store = store or ExperienceStore()
    admitted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for d in decisions:
        has_outcome = bool(d.get("realized_outcome") or d.get("outcome_attached_at"))
        if require_outcome and not has_outcome:
            skipped.append({"decision_id": d.get("decision_id"), "reason": "no_outcome"})
            continue
        exp = trading_decision_to_experience(
            d,
            verified=has_outcome,
            outcome="success" if has_outcome else "pending",
        )
        if has_outcome:
            admitted_exp = exp_store.admit(exp)
            admitted.append(admitted_exp.public_dict())
        else:
            skipped.append({"decision_id": d.get("decision_id"), "reason": "unverified"})
    # SFT-shaped export (no CoT): summary lines only.
    sft_lines = [
        json.dumps(
            {
                "text": f"Trading lesson: {a.get('task_summary')} → {a.get('outcome')}",
                "metadata": {
                    "domain": "trading",
                    "experience_id": a.get("experience_id"),
                    "no_raw_cot": True,
                },
            },
            sort_keys=True,
        )
        for a in admitted
    ]
    return {
        "admitted": len(admitted),
        "skipped": len(skipped),
        "experiences": admitted,
        "skipped_detail": skipped,
        "sft_lines": sft_lines,
        "truth": {
            "uses_existing_verified_experience": True,
            "no_trading_trainer_2": True,
            "no_raw_private_cot": True,
            "unverified_not_admitted": True,
        },
    }
