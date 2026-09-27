"""Strategy promotion adapter — consumes QualificationAuthority evidence (Wave 12).

Promotion never enables live money. A5 remains impossible.

Scientific promotion from research/backtest into shadow (A2) requires a
persisted QualificationDecision with qualified=True. Caller booleans and
extra_evidence["acceptance"]["passed"]=true cannot override a failed or
missing qualification for that institutional entry.

A3/A4 may proceed as operational paper-track promotions when shadow/paper
receipts exist (Wave 23), but remain non-institutional lifecycle writes
unless a QUALIFIED decision is also present. CHALLENGER→CHAMPION still
requires forward-evidence policy elsewhere.
"""

from __future__ import annotations

from typing import Any

from .readiness import assert_not_live_level, may_promote_to, normalize_autonomy
from .wfa import evaluate_acceptance_from_run

# Scientific entry into the paper track (research → shadow).
_SCIENTIFIC_ENTRY_TARGETS = frozenset({"A2"})
# Operational paper-track steps — receipts required; qualification preferred.
_OPERATIONAL_TARGETS = frozenset({"A3", "A4"})
_INSTITUTIONAL_TARGETS = _SCIENTIFIC_ENTRY_TARGETS | _OPERATIONAL_TARGETS


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

    scientific_entry = target in _SCIENTIFIC_ENTRY_TARGETS and not legacy_demo
    operational = target in _OPERATIONAL_TARGETS and not legacy_demo

    # A2 scientific entry: qualification mandatory.
    # A3/A4: operational receipts may allow promotion without institutional lifecycle write;
    # explicit failed qualification still blocks; QUALIFIED upgrades path to institutional.
    qualification_ok = True
    if scientific_entry:
        if qqualified is True:
            qualification_ok = True
        else:
            qualification_ok = False
            if "QUALIFICATION_REQUIRED" not in qblockers:
                qblockers = list(qblockers) + ["QUALIFICATION_REQUIRED"]
    elif operational and qqualified is False:
        qualification_ok = False
        if "QUALIFICATION_REQUIRED" not in qblockers:
            qblockers = ["QUALIFICATION_REQUIRED"] + list(qblockers)

    evidence: dict[str, Any] = {
        "accepted": bool(qualification_ok) if scientific_entry else (accepted or bool(qqualified)),
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
    if scientific_entry and not qualification_ok:
        promotable = False
        gate = {
            **gate,
            "allowed": False,
            "reason": qblockers[0] if qblockers else "QUALIFICATION_REQUIRED",
            "qualification_blockers": qblockers,
        }
    elif operational and qqualified is False:
        promotable = False
        gate = {
            **gate,
            "allowed": False,
            "reason": qblockers[0] if qblockers else "QUALIFICATION_REQUIRED",
            "qualification_blockers": qblockers,
        }

    reason = None
    if scientific_entry and not qualification_ok:
        reason = qblockers[0] if qblockers else "QUALIFICATION_REQUIRED"
    elif operational and qqualified is False:
        reason = qblockers[0] if qblockers else "QUALIFICATION_REQUIRED"
    elif not promotable:
        reason = str(gate.get("reason") or "PROMOTION_DENIED")

    if legacy_demo:
        path = "legacy_non_institutional"
    elif scientific_entry and qualification_ok:
        path = "institutional"
    elif operational and qqualified:
        path = "institutional"
    elif operational:
        path = "operational_paper"
    else:
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
            "qualification_required_for_scientific_entry": True,
            "caller_acceptance_cannot_override_qualification": True,
            "legacy_demo": bool(legacy_demo),
            "operational_paper_path": path == "operational_paper",
            "non_institutional_path": path != "institutional",
            "institutional_lifecycle_write": path == "institutional" and promotable,
        },
    }
