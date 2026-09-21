"""Pillar 9 — Autonomous Scientific Method.

Formal hypothesis → experiment → measurement → verdict loop.
Reuses Eval Lab A/B machinery; records negative results.
"""

from __future__ import annotations

from typing import Any, Callable

from .contracts import AdaptiveDecision, new_id, utc_now
from .modes import CognitiveMode


def create_hypothesis(
    store: Any,
    *,
    claim: str,
    scope: str,
    predicted_outcome: str,
    falsification_criterion: str,
    required_evidence: list[str] | None = None,
    experiment: dict[str, Any] | None = None,
    confounders: list[str] | None = None,
    mode: CognitiveMode = CognitiveMode.SHADOW,
) -> dict[str, Any]:
    if not claim.strip() or not falsification_criterion.strip():
        return {
            "status": "rejected",
            "reason": "claim_and_falsification_required",
        }
    hypothesis = {
        "id": new_id("hyp"),
        "claim": claim.strip(),
        "scope": scope.strip() or "general",
        "predicted_outcome": predicted_outcome.strip(),
        "falsification_criterion": falsification_criterion.strip(),
        "required_evidence": list(required_evidence or []),
        "experiment": dict(experiment or {}),
        "confounders": list(confounders or []),
        "result": None,
        "verdict": "open",
        "status": "open",
        "measurements": [],
        "created_at": utc_now(),
    }
    # Persist whenever a store exists and mode is not OFF (SHADOW retained for observability).
    if store is not None and mode is not CognitiveMode.OFF:
        hypothesis = store.upsert_hypothesis(hypothesis)
    return {
        "status": "created",
        "hypothesis": hypothesis,
        "decision": AdaptiveDecision(
            controller="cognitive.scientific_method",
            decision="create_hypothesis",
            reason_code="FORMAL_CLAIM",
            mode=mode.value,
        ).to_dict(),
    }


def record_measurement(
    store: Any,
    *,
    hypothesis_id: str,
    metrics: dict[str, Any],
    arm: str = "treatment",
    notes: str = "",
    hypothesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hyp = hypothesis
    if hyp is None and store is not None:
        hyp = store.get_hypothesis(hypothesis_id)
    if not hyp:
        return {"status": "missing"}
    measurements = list(hyp.get("measurements") or [])
    measurements.append(
        {
            "arm": arm,
            "metrics": dict(metrics),
            "notes": notes,
            "at": utc_now(),
        }
    )
    hyp["measurements"] = measurements
    hyp["updated_at"] = utc_now()
    if store is not None and store.get_hypothesis(hypothesis_id) is not None:
        hyp = store.upsert_hypothesis(hyp)
    return {"status": "recorded", "hypothesis": hyp}


def analyze_hypothesis(
    store: Any,
    *,
    hypothesis_id: str,
    primary_metric: str,
    higher_is_better: bool = True,
    min_effect: float = 0.0,
    mode: CognitiveMode = CognitiveMode.SHADOW,
    hypothesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require measurements — reject 'seems better'."""
    hyp = hypothesis
    if hyp is None and store is not None:
        hyp = store.get_hypothesis(hypothesis_id)
    if not hyp:
        return {"status": "missing"}
    measurements = list(hyp.get("measurements") or [])
    if len(measurements) < 2:
        return {
            "status": "insufficient_measurements",
            "hypothesis": hyp,
            "decision": AdaptiveDecision(
                controller="cognitive.scientific_method",
                decision="hold",
                reason_code="NEED_MEASUREMENTS",
                mode=mode.value,
            ).to_dict(),
        }

    by_arm: dict[str, list[float]] = {}
    for m in measurements:
        arm = str(m.get("arm") or "treatment")
        metrics = m.get("metrics") or {}
        if primary_metric not in metrics:
            continue
        try:
            by_arm.setdefault(arm, []).append(float(metrics[primary_metric]))
        except (TypeError, ValueError):
            continue

    if "control" not in by_arm or "treatment" not in by_arm:
        # Allow A/B naming
        arms = list(by_arm.keys())
        if len(arms) < 2:
            return {"status": "need_two_arms", "arms": arms, "hypothesis": hyp}
        control_vals = by_arm[arms[0]]
        treatment_vals = by_arm[arms[1]]
        control_name, treatment_name = arms[0], arms[1]
    else:
        control_vals = by_arm["control"]
        treatment_vals = by_arm["treatment"]
        control_name, treatment_name = "control", "treatment"

    control_mean = sum(control_vals) / len(control_vals)
    treatment_mean = sum(treatment_vals) / len(treatment_vals)
    delta = treatment_mean - control_mean
    improved = delta >= min_effect if higher_is_better else delta <= -min_effect
    falsified = (delta <= -min_effect) if higher_is_better else (delta >= min_effect)

    if falsified:
        verdict = "rejected"
    elif improved:
        verdict = "supported"
    else:
        verdict = "inconclusive"

    hyp["result"] = {
        "primary_metric": primary_metric,
        "control_arm": control_name,
        "treatment_arm": treatment_name,
        "control_mean": control_mean,
        "treatment_mean": treatment_mean,
        "delta": delta,
        "higher_is_better": higher_is_better,
        "min_effect": min_effect,
    }
    hyp["verdict"] = verdict
    hyp["status"] = verdict
    hyp["updated_at"] = utc_now()
    # Negative results are first-class
    hyp["negative_result_preserved"] = verdict == "rejected"

    if store is not None and mode is not CognitiveMode.OFF and store.get_hypothesis(hypothesis_id) is not None:
        hyp = store.upsert_hypothesis(hyp)
    elif store is not None and mode is not CognitiveMode.OFF:
        hyp = store.upsert_hypothesis(hyp)

    return {
        "status": "analyzed",
        "verdict": verdict,
        "hypothesis": hyp,
        "decision": AdaptiveDecision(
            controller="cognitive.scientific_method",
            decision=verdict,
            reason_code="MEASURED_VERDICT",
            mode=mode.value,
            verification_result=verdict,
        ).to_dict(),
    }


def run_controlled_ab(
    store: Any,
    *,
    claim: str,
    scope: str,
    falsification_criterion: str,
    control_metrics: dict[str, float],
    treatment_metrics: dict[str, float],
    primary_metric: str,
    higher_is_better: bool = True,
    mode: CognitiveMode = CognitiveMode.ACTIVE,
    eval_lab_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convenience: create hypothesis, record control/treatment, analyze.

    Optional eval_lab_runner may wrap gen2.eval_lab.run_ab_experiment.
    """
    created = create_hypothesis(
        store,
        claim=claim,
        scope=scope,
        predicted_outcome=f"treatment improves {primary_metric}",
        falsification_criterion=falsification_criterion,
        experiment={"type": "ab", "primary_metric": primary_metric},
        mode=mode,
    )
    if created.get("status") != "created":
        return created
    hyp = created["hypothesis"]
    hid = hyp["id"]

    eval_meta = None
    if eval_lab_runner is not None:
        try:
            eval_meta = eval_lab_runner(control_metrics=control_metrics, treatment_metrics=treatment_metrics)
        except Exception as exc:
            eval_meta = {"error": type(exc).__name__}

    m1 = record_measurement(
        store, hypothesis_id=hid, metrics=control_metrics, arm="control", hypothesis=hyp
    )
    hyp = m1.get("hypothesis") or hyp
    m2 = record_measurement(
        store, hypothesis_id=hid, metrics=treatment_metrics, arm="treatment", hypothesis=hyp
    )
    hyp = m2.get("hypothesis") or hyp
    analyzed = analyze_hypothesis(
        store,
        hypothesis_id=hid,
        primary_metric=primary_metric,
        higher_is_better=higher_is_better,
        mode=mode,
        hypothesis=hyp,
    )
    analyzed["eval_lab"] = eval_meta
    return analyzed
