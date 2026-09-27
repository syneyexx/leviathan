"""Strategy promotion adapter — consumes QualificationAuthority evidence (Wave 12).

Promotion never enables live money. A5 remains impossible.

Scientific promotion toward shadow/paper requires a persisted
QualificationDecision with qualified=True. Caller booleans and
extra_evidence["acceptance"]["passed"]=true cannot override a failed or
missing qualification for institutional targets.
"""

from __future__ import annotations

from typing import Any

from .readiness import assert_not_live_level, may_promote_to, normalize_autonomy
from .wfa import evaluate_acceptance_from_run

_INSTITUTIONAL_TARGETS = frozenset({"A2", "A3", "A4"})


def _resolve_qualification(
    *,
    qualification_decision_id: str | None,
    qualification_decision: Any | None,
    store: Any | None,
    extra: dict[str, Any],
) -> tuple[str | None, str | None, bool | None, list[str]]:
    blockers: list[str] = []
    if qualification_decision is not None:
        qid = str(
            getattr(qualification_decision, "qualification_id", None)
            or (qualification_decision.get("qualification_id") if isinstance(qualification_decision, dict) else None)
            or ""
        ) or None
        state = str(
            getattr(qualification_decision, "state", None)
            or (qualification_decision.get("state") if isinstance(qualification_decision, dict) else None)
            or ""
        ) or None
        qualified = bool(
            getattr(qualification_decision, "qualified", None)
            if not isinstance(qualification_decision, dict)
            else qualification_decision.get("qualified")
        )
        raw_blockers = (
            getattr(qualification_decision, "blockers", None)
            if not isinstance(qualification_decision, dict)
            else qualification_decision.get("blockers")
        )
        blockers = list(raw_blockers or [])
        return qid, state, qualified, blockers

    qid = qualification_decision_id or extra.get("qualification_decision_id") or extra.get("qualification_id")
    if not qid:
        return None, None, None, ["QUALIFICATION_REQUIRED"]
    if store is not None and hasattr(store, "get_qualification_run"):
        row = store.get_qualification_run(str(qid))
        if row is None:
            return str(qid), None, False, ["QUALIFICATION_NOT_FOUND"]
        decision = str(row.get("decision") or row.get("status") or "").upper()
        qualified = decision == "QUALIFIED"
        return (
            str(qid),
            str(row.get("status") or decision),
            qualified,
            list(row.get("blockers") or ([] if qualified else ["QUALIFICATION_NOT_QUALIFIED"])),
        )
    return str(qid), None, None, ["QUALIFICATION_STORE_UNAVAILABLE"]


def evaluate_promotion(
    *,
    run: Any | None = None,
    metrics: dict[str, Any] | None = None,
    acceptance_criteria: dict[str, Any] | None = None,
    current_level: str = "A0",
    target_level: str = "A1",
    sealed_pass: bool = False,
    paper_shadow_pass: bool = False,
    shadow_run_id: str | None = None,
    autonomous_paper_pass: bool = False,
    paper_deployment_id: str | None = None,
    extra_evidence: dict[str, Any] | None = None,
    qualification_decision_id: str | None = None,
    qualification_decision: Any | None = None,
    store: Any | None = None,
    legacy_demo: bool = False,
) -> dict[str, Any]:
    assert_not_live_level(target_level)
    current = normalize_autonomy(current_level)
    target = normalize_autonomy(target_level)
    extra = dict(extra_evidence or {})

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

    caller_passed = isinstance(extra.get("acceptance"), dict) and extra["acceptance"].get("passed") is True
    if caller_passed:
        acceptance = {
            **dict(extra["acceptance"]),
            "caller_boolean_ignored_for_institutional": True,
        }

    qid, qstate, qqualified, qblockers = _resolve_qualification(
        qualification_decision_id=qualification_decision_id,
        qualification_decision=qualification_decision,
        store=store,
        extra=extra,
    )

    institutional = target in _INSTITUTIONAL_TARGETS and not legacy_demo
    qualification_ok = bool(qqualified) if institutional else True
    if institutional and qqualified is None:
        qualification_ok = False
        if "QUALIFICATION_REQUIRED" not in qblockers:
            qblockers = list(qblockers) + ["QUALIFICATION_REQUIRED"]
    elif institutional and qqualified is False:
        qualification_ok = False
        if "QUALIFICATION_REQUIRED" not in qblockers:
            qblockers = ["QUALIFICATION_REQUIRED"] + list(qblockers)

    evidence: dict[str, Any] = {
        "accepted": bool(qualification_ok) if institutional else accepted,
        "sealed_pass": sealed_pass or bool(extra.get("sealed_pass")),
        "acceptance": acceptance,
        "evaluation_refs": list(
            (acceptance.get("evaluation_refs") if isinstance(acceptance, dict) else None)
            or (payload or {}).get("evaluation_refs")
            or extra.get("evaluation_refs")
            or []
        ),
        "sealed_attempt_id": (
            extra.get("sealed_attempt_id")
            or (acceptance.get("sealed_attempt_id") if isinstance(acceptance, dict) else None)
        ),
        "run_id": (payload or {}).get("run_id"),
        "qualification_id": qid,
        "qualification_qualified": qqualified,
    }
    if shadow_run_id or extra.get("shadow_run_id"):
        evidence["shadow_run_id"] = shadow_run_id or extra.get("shadow_run_id")
    if paper_shadow_pass or extra.get("paper_shadow_pass"):
        evidence["paper_shadow_pass"] = True
    if paper_deployment_id or extra.get("paper_deployment_id"):
        evidence["paper_deployment_id"] = paper_deployment_id or extra.get("paper_deployment_id")
    if autonomous_paper_pass or extra.get("autonomous_paper_pass"):
        evidence["autonomous_paper_pass"] = True
    if extra.get("shadow_receipt"):
        evidence["shadow_receipt"] = extra["shadow_receipt"]
    if extra.get("paper_receipt"):
        evidence["paper_receipt"] = extra["paper_receipt"]

    gate = may_promote_to(current=current, target=target, evidence=evidence)
    promotable = bool(gate.get("allowed"))
    if institutional and not qualification_ok:
        promotable = False
        gate = {
            **gate,
            "allowed": False,
            "reason": qblockers[0] if qblockers else "QUALIFICATION_REQUIRED",
            "qualification_blockers": qblockers,
        }

    reason = None
    if institutional and not qualification_ok:
        reason = qblockers[0] if qblockers else "QUALIFICATION_REQUIRED"
    elif not promotable:
        reason = str(gate.get("reason") or "PROMOTION_DENIED")
    # Institutional path only when target requires qualification AND it passed.
    path = "institutional" if (institutional and qualification_ok) else "legacy_non_institutional"
    if legacy_demo:
        path = "legacy_non_institutional"

    return {
        "promotable": promotable,
        "from": current,
        "to": target,
        "accepted": accepted,
        "acceptance": acceptance,
        "gate": gate,
        "qualification_id": qid,
        "qualification_state": qstate,
        "qualification_blockers": qblockers,
        "reason": reason,
        "path": path,
        "live_trading": "BLOCKED",
        "truth": {
            "kernel_owned_metrics": True,
            "a5_impossible": True,
            "no_frontend_authority": True,
            "caller_boolean_not_proof": True,
            "qualification_required_for_institutional": target in _INSTITUTIONAL_TARGETS,
            "caller_acceptance_cannot_override_qualification": True,
            "legacy_demo": bool(legacy_demo),
            "non_institutional_path": path != "institutional",
            "institutional_lifecycle_write": path == "institutional" and promotable,
        },
    }
