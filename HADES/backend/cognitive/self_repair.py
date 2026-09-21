"""Pillar 8 — Self-Diagnosis & Controlled Self-Repair.

Investigate degradation and produce reviewable repair proposals.
Reuses Coding Agent investigation/worktrees — never a hidden self-edit loop.
Production application remains policy-gated.
"""

from __future__ import annotations

from typing import Any, Callable

from .contracts import AdaptiveDecision, new_id, utc_now
from .modes import CognitiveMode, mode_allows_influence


def diagnose(
    *,
    trigger: str,
    metrics: dict[str, Any] | None = None,
    symptoms: list[str] | None = None,
    self_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bounded diagnosis from observable signals — no unrestricted self-modification."""
    metrics = metrics or {}
    symptoms = list(symptoms or [])
    candidates: list[dict[str, Any]] = []

    trigger_l = str(trigger or "").lower()
    if "retrieval" in trigger_l or metrics.get("retrieval_precision_drop"):
        candidates.append(
            {
                "cause": "retrieval_index_degradation",
                "reproduction": "run_retrieval_eval_suite",
                "confidence": 0.7,
            }
        )
    if "latency" in trigger_l or metrics.get("latency_regression"):
        candidates.append(
            {
                "cause": "model_or_tool_latency_regression",
                "reproduction": "compare_flight_recorder_runs",
                "confidence": 0.65,
            }
        )
    if "neural" in trigger_l or metrics.get("neural_interference"):
        candidates.append(
            {
                "cause": "neural_interference_or_corrupt_checkpoint",
                "reproduction": "disable_neural_fallback_and_compare",
                "confidence": 0.75,
            }
        )
    if "memory" in trigger_l or "corrupt" in trigger_l:
        candidates.append(
            {
                "cause": "memory_corruption_or_poison",
                "reproduction": "immune_scan_plus_quarantine_audit",
                "confidence": 0.8,
            }
        )
    if "exception" in trigger_l or metrics.get("repeated_exceptions"):
        candidates.append(
            {
                "cause": "subsystem_exception_regression",
                "reproduction": "sandbox_repro_with_coding_investigate",
                "confidence": 0.7,
            }
        )
    for s in symptoms:
        if s and not any(s in c["cause"] for c in candidates):
            candidates.append({"cause": s, "reproduction": "targeted_fixture", "confidence": 0.4})

    # Cross-check self-model for degraded components
    if self_model:
        for cap in self_model.get("capabilities") or []:
            if isinstance(cap, dict) and (cap.get("degraded") or cap.get("status") == "degraded"):
                candidates.append(
                    {
                        "cause": f"degraded:{cap.get('component')}:{cap.get('capability')}",
                        "reproduction": "self_model_reprobe",
                        "confidence": 0.6,
                    }
                )

    candidates.sort(key=lambda c: -float(c.get("confidence") or 0))
    return {
        "trigger": trigger,
        "candidate_causes": candidates,
        "primary": candidates[0] if candidates else None,
        "decision": AdaptiveDecision(
            controller="cognitive.self_repair",
            decision="diagnose",
            reason_code="REGRESSION_SIGNAL",
            mode=CognitiveMode.SHADOW.value,
            input_refs=[trigger],
        ).to_dict(),
    }


def propose_repair(
    store: Any,
    *,
    trigger: str,
    diagnosis: dict[str, Any],
    mode: CognitiveMode = CognitiveMode.OFF,
    coding_investigate: Callable[..., dict[str, Any]] | None = None,
    fixture_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a reviewable repair proposal. Never auto-applies to production."""
    if mode is CognitiveMode.OFF:
        return {
            "status": "disabled",
            "reason": "self_repair_mode_off",
            "decision": AdaptiveDecision(
                controller="cognitive.self_repair",
                decision="noop",
                reason_code="MODE_OFF",
                mode=mode.value,
            ).to_dict(),
        }

    primary = diagnosis.get("primary") or {}
    investigation = None
    if coding_investigate is not None:
        try:
            investigation = coding_investigate(trigger=trigger, cause=primary.get("cause"))
        except Exception as exc:
            investigation = {"error": type(exc).__name__, "note": "coding_investigate_failed"}

    # Controlled fixture path for acceptance without live coding agent
    if fixture_result is not None:
        investigation = {
            "fixture": True,
            "worktree": fixture_result.get("worktree", "sandbox/worktree_repair_fixture"),
            "patch": fixture_result.get("patch"),
            "tests": fixture_result.get("tests") or [],
            "benchmark": fixture_result.get("benchmark"),
            "verified": bool(fixture_result.get("verified")),
        }

    proposal = {
        "id": new_id("repair"),
        "trigger": trigger,
        "status": "proposed",
        "diagnosis": diagnosis,
        "candidate_cause": primary.get("cause"),
        "reproduction": primary.get("reproduction"),
        "investigation": investigation,
        "sandbox_only": True,
        "production_apply": False,  # always gated
        "requires_human_or_policy_approval": True,
        "created_at": utc_now(),
    }

    # Promotion gate: only mark ready_for_review when tests/benchmark present
    inv = investigation or {}
    if inv.get("verified") and inv.get("tests") is not None:
        proposal["status"] = "ready_for_review"
    elif inv.get("error"):
        proposal["status"] = "investigation_failed"

    if mode_allows_influence(mode) and store is not None:
        proposal = store.upsert_repair_proposal(proposal)
    elif store is not None and mode is CognitiveMode.SHADOW:
        # Shadow still persists proposal for observability
        proposal = store.upsert_repair_proposal(proposal)

    return {
        "status": proposal["status"],
        "proposal": proposal,
        "decision": AdaptiveDecision(
            controller="cognitive.self_repair",
            decision="propose_sandbox_repair",
            reason_code="CONTROLLED_REPAIR_PROPOSAL",
            mode=mode.value,
            verification_result=str(inv.get("verified")),
            fallback="no_production_apply",
        ).to_dict(),
    }


def run_controlled_repair_fixture(store: Any, *, mode: CognitiveMode = CognitiveMode.SHADOW) -> dict[str, Any]:
    """Safe end-to-end repair scenario using a controlled fixture (no live repo edits)."""
    diag = diagnose(
        trigger="retrieval_precision_drop",
        metrics={"retrieval_precision_drop": 0.2},
        symptoms=["retrieval_precision_drop"],
    )
    fixture = {
        "worktree": "sandbox/worktree_repair_fixture",
        "patch": {
            "files": ["backend/reasoning/retrieval.py"],
            "summary": "Bound retrieval fanout under homeostasis signal",
        },
        "tests": [{"name": "test_perception_bounds_retrieval", "passed": True}],
        "benchmark": {"retrieval_calls": {"before": 40, "after": 8}},
        "verified": True,
    }
    return propose_repair(
        store,
        trigger="retrieval_precision_drop",
        diagnosis=diag,
        mode=mode,
        fixture_result=fixture,
    )
