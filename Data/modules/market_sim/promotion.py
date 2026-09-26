"""Strategy promotion from kernel acceptance evidence (P3B).

Promotion never enables live money. A5 remains impossible.
"""

from __future__ import annotations

from typing import Any

from .readiness import assert_not_live_level, may_promote_to, normalize_autonomy
from .wfa import evaluate_acceptance_from_run


def evaluate_promotion(
    *,
    run: Any | None = None,
    metrics: dict[str, Any] | None = None,
    acceptance_criteria: dict[str, Any] | None = None,
    current_level: str = "A0",
    target_level: str = "A1",
    sealed_pass: bool = False,
) -> dict[str, Any]:
    assert_not_live_level(target_level)
    current = normalize_autonomy(current_level)
    target = normalize_autonomy(target_level)

    accepted = False
    acceptance: dict[str, Any] = {"status": "UNMEASURED"}
    payload: dict[str, Any] | None = None
    if run is not None:
        payload = run.public_dict() if hasattr(run, "public_dict") else dict(run)
    elif metrics is not None:
        payload = {"run_id": "promo-metrics", "metrics": dict(metrics), "metadata": {}}
    if payload is not None:
        result = evaluate_acceptance_from_run(payload, criteria=acceptance_criteria or {})
        acceptance = result.public_dict() if hasattr(result, "public_dict") else dict(result)
        accepted = bool(getattr(result, "passed", acceptance.get("passed")))

    gate = may_promote_to(
        current=current,
        target=target,
        evidence={
            "accepted": accepted,
            "sealed_pass": sealed_pass,
            "acceptance": acceptance,
            "evaluation_refs": list(
                (acceptance.get("evaluation_refs") if isinstance(acceptance, dict) else None)
                or (payload or {}).get("evaluation_refs")
                or []
            ),
            "sealed_attempt_id": (
                acceptance.get("sealed_attempt_id") if isinstance(acceptance, dict) else None
            ),
            "run_id": (payload or {}).get("run_id"),
        },
    )
    return {
        "promotable": bool(gate.get("allowed")),
        "from": current,
        "to": target,
        "accepted": accepted,
        "acceptance": acceptance,
        "gate": gate,
        "live_trading": "BLOCKED",
        "truth": {
            "kernel_owned_metrics": True,
            "a5_impossible": True,
            "no_frontend_authority": True,
        },
    }
