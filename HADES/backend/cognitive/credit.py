"""Pillar 10 — Long-Term Credit Assignment / Responsibility Engine.

Evidence-backed attribution. Temporal precedence alone is not causality.
"""

from __future__ import annotations

from typing import Any

from .contracts import AdaptiveDecision, CAUSAL_EVIDENCE_TIERS, new_id, utc_now
from .modes import CognitiveMode, mode_allows_influence


def assign_credit(
    store: Any,
    *,
    outcome_ref: str,
    attributions: list[dict[str, Any]],
    mode: CognitiveMode = CognitiveMode.SHADOW,
) -> dict[str, Any]:
    """Record credit only when causal evidence tier justifies it."""
    recorded: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in attributions:
        decision_ref = str(raw.get("decision_ref") or "")
        tier = str(raw.get("causal_evidence_level") or "coincidental").lower()
        if tier not in CAUSAL_EVIDENCE_TIERS:
            tier = "coincidental"
        polarity = str(raw.get("polarity") or "neutral").lower()
        if polarity not in {"positive", "negative", "neutral"}:
            polarity = "neutral"

        # Coincidental earlier actions receive no credit.
        if tier == "coincidental":
            rejected.append(
                {
                    **raw,
                    "reject_reason": "temporal_precedence_is_not_causality",
                    "causal_evidence_level": tier,
                }
            )
            continue

        confidence = raw.get("confidence")
        if confidence is None:
            confidence = {
                "correlated": 0.35,
                "intervened": 0.7,
                "verified_cause": 0.95,
                "counterfactual": 0.85,
            }.get(tier, 0.2)

        record = {
            "id": new_id("credit"),
            "outcome_ref": outcome_ref,
            "decision_ref": decision_ref,
            "actor_ref": raw.get("actor_ref"),
            "contribution_type": str(raw.get("contribution_type") or "decision"),
            "polarity": polarity,
            "confidence": float(confidence),
            "causal_evidence_level": tier,
            "evidence_refs": list(raw.get("evidence_refs") or []),
            "counterfactual_evidence": raw.get("counterfactual_evidence"),
            "timestamp": utc_now(),
        }
        if mode_allows_influence(mode) and store is not None:
            store.append_credit(record)
            record["persisted"] = True
        else:
            record["persisted"] = False
        recorded.append(record)

    decision = AdaptiveDecision(
        controller="cognitive.credit",
        decision="assign" if recorded else "reject_all_coincidental",
        reason_code="EVIDENCE_BACKED_ATTRIBUTION" if recorded else "NO_CAUSAL_EVIDENCE",
        mode=mode.value,
        input_refs=[outcome_ref],
        confidence=max((r["confidence"] for r in recorded), default=None),
    )
    return {
        "outcome_ref": outcome_ref,
        "recorded": recorded,
        "rejected": rejected,
        "decision": decision.to_dict(),
    }


def aggregate_actor_credit(
    store: Any,
    *,
    actor_ref: str,
    decay: float = 0.85,
    limit: int = 50,
) -> dict[str, Any]:
    """Decayed aggregate — one failure must not permanently poison an actor."""
    rows = store.list_credit(limit=limit) if store else []
    score = 0.0
    weight = 0.0
    relevant = []
    for index, row in enumerate(rows):
        if row.get("actor_ref") != actor_ref:
            continue
        w = decay ** index
        conf = float(row.get("confidence") or 0.0)
        polar = row.get("polarity")
        sign = 1.0 if polar == "positive" else (-1.0 if polar == "negative" else 0.0)
        # Down-weight weak tiers
        tier_w = {
            "verified_cause": 1.0,
            "counterfactual": 0.9,
            "intervened": 0.75,
            "correlated": 0.4,
        }.get(str(row.get("causal_evidence_level")), 0.2)
        score += sign * conf * w * tier_w
        weight += w * tier_w
        relevant.append(row)
    return {
        "actor_ref": actor_ref,
        "aggregate_score": round(score / weight, 4) if weight else 0.0,
        "n": len(relevant),
        "note": "Decayed aggregate; single failure does not permanently poison.",
    }


def scenario_credit_demo() -> dict[str, Any]:
    """Deterministic fixture scenarios for acceptance tests (no I/O)."""
    outcome = "run_failure_migration"
    attributions = [
        {
            "decision_ref": "opened_editor",
            "actor_ref": "user",
            "contribution_type": "incidental",
            "polarity": "neutral",
            "causal_evidence_level": "coincidental",
            "evidence_refs": ["timeline:earlier"],
        },
        {
            "decision_ref": "assumed_schema_v2",
            "actor_ref": "agent.coding",
            "contribution_type": "assumption",
            "polarity": "negative",
            "causal_evidence_level": "verified_cause",
            "evidence_refs": ["test:migration_failed", "fix:schema_mismatch"],
        },
        {
            "decision_ref": "selected_stale_belief",
            "actor_ref": "memory.retrieval",
            "contribution_type": "belief_selection",
            "polarity": "negative",
            "causal_evidence_level": "correlated",
            "evidence_refs": ["belief:schema_valid_time_expired"],
        },
    ]
    # Use in-memory path via assign without store for pure logic
    return assign_credit(None, outcome_ref=outcome, attributions=attributions, mode=CognitiveMode.SHADOW)
