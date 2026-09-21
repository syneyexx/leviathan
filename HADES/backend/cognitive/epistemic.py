"""Pillar 3 — Epistemic Engine.

Typed uncertainty classes with deterministic recovery actions.
Confidence never outranks evidence. Prefer autonomous recovery over
unnecessary user questions.
"""

from __future__ import annotations

from typing import Any

from .contracts import AdaptiveDecision, UNCERTAINTY_CLASSES, UncertaintyState
from .modes import CognitiveMode, mode_allows_influence


# Deterministic recovery policy — uncertainty class → action.
RECOVERY_POLICY: dict[str, dict[str, Any]] = {
    "missing_information": {
        "action": "retrieve",
        "ask_user": False,
        "reason_code": "EPISTEMIC_RETRIEVE",
    },
    "conflicting_evidence": {
        "action": "compare_sources",
        "ask_user": False,
        "reason_code": "EPISTEMIC_COMPARE",
    },
    "stale_evidence": {
        "action": "refresh",
        "ask_user": False,
        "reason_code": "EPISTEMIC_REFRESH",
    },
    "ambiguous_goal": {
        "action": "clarify_goal",
        "ask_user": True,  # only when independent resolution is impossible
        "reason_code": "EPISTEMIC_CLARIFY",
    },
    "low_model_confidence": {
        "action": "escalate_verifier",
        "ask_user": False,
        "reason_code": "EPISTEMIC_VERIFY",
    },
    "unknown_runtime_state": {
        "action": "inspect_self_model",
        "ask_user": False,
        "reason_code": "EPISTEMIC_SELF_MODEL",
    },
    "unverified_assumption": {
        "action": "test_assumption",
        "ask_user": False,
        "reason_code": "EPISTEMIC_TEST",
    },
    "out_of_distribution": {
        "action": "stronger_model_or_specialist",
        "ask_user": False,
        "reason_code": "EPISTEMIC_ESCALATE",
    },
    "simulation_gap": {
        "action": "run_controlled_simulation",
        "ask_user": False,
        "reason_code": "EPISTEMIC_SIMULATE",
    },
    "tool_failure": {
        "action": "retry_or_fallback",
        "ask_user": False,
        "reason_code": "EPISTEMIC_TOOL_FALLBACK",
    },
    "insufficient_coverage": {
        "action": "expand_targeted_coverage",
        "ask_user": False,
        "reason_code": "EPISTEMIC_COVERAGE",
    },
}


def classify_uncertainty(
    *,
    signals: dict[str, Any] | None = None,
) -> list[UncertaintyState]:
    """Map observable signals to typed uncertainty states."""
    signals = signals or {}
    states: list[UncertaintyState] = []

    def _add(cls: str, detail: str, *, severity: str = "medium", refs: list[str] | None = None) -> None:
        policy = RECOVERY_POLICY[cls]
        # Ask user only for ambiguous_goal when no independent resolution path exists.
        ask = bool(policy["ask_user"])
        if cls == "ambiguous_goal" and signals.get("can_resolve_independently"):
            ask = False
        states.append(
            UncertaintyState(
                uncertainty_class=cls,
                detail=detail,
                evidence_refs=list(refs or []),
                recovery_action=str(policy["action"]),
                severity=severity,
                ask_user=ask,
            )
        )

    if signals.get("missing_fields") or signals.get("open_questions"):
        _add(
            "missing_information",
            detail=str(signals.get("missing_fields") or signals.get("open_questions")),
            refs=["signals.missing"],
        )
    if signals.get("contradictions") or signals.get("conflicting_evidence"):
        _add(
            "conflicting_evidence",
            detail=str(signals.get("contradictions") or signals.get("conflicting_evidence")),
            severity="high",
            refs=["signals.contradictions"],
        )
    if signals.get("stale") or signals.get("stale_evidence"):
        _add(
            "stale_evidence",
            detail=str(signals.get("stale") or signals.get("stale_evidence")),
            refs=["signals.freshness"],
        )
    if signals.get("ambiguous_goal") or signals.get("goal_unclear"):
        _add(
            "ambiguous_goal",
            detail=str(signals.get("ambiguous_goal") or "goal unclear"),
            severity="high",
            refs=["signals.goal"],
        )
    if signals.get("low_model_confidence") or (
        isinstance(signals.get("model_confidence"), (int, float))
        and float(signals["model_confidence"]) < 0.35
    ):
        _add(
            "low_model_confidence",
            detail="model confidence below threshold",
            refs=["signals.model_confidence"],
        )
    if signals.get("unknown_runtime_state") or signals.get("runtime_unknown"):
        _add(
            "unknown_runtime_state",
            detail=str(signals.get("unknown_runtime_state") or "runtime state unknown"),
            severity="high",
            refs=["signals.runtime"],
        )
    if signals.get("unverified_assumption") or signals.get("assumptions_unverified"):
        _add(
            "unverified_assumption",
            detail=str(signals.get("unverified_assumption") or signals.get("assumptions_unverified")),
            refs=["signals.assumptions"],
        )
    if signals.get("out_of_distribution") or signals.get("ood"):
        _add(
            "out_of_distribution",
            detail=str(signals.get("out_of_distribution") or "ood"),
            severity="high",
            refs=["signals.ood"],
        )
    if signals.get("simulation_gap"):
        _add(
            "simulation_gap",
            detail=str(signals.get("simulation_gap")),
            refs=["signals.simulation"],
        )
    if signals.get("tool_failure") or signals.get("tool_error"):
        _add(
            "tool_failure",
            detail=str(signals.get("tool_failure") or signals.get("tool_error")),
            severity="high",
            refs=["signals.tools"],
        )
    if signals.get("insufficient_coverage") or signals.get("coverage_gap"):
        _add(
            "insufficient_coverage",
            detail=str(signals.get("insufficient_coverage") or signals.get("coverage_gap")),
            refs=["signals.coverage"],
        )

    # Explicit class passthrough for tests / callers
    explicit = signals.get("uncertainty_class")
    if explicit and str(explicit) in UNCERTAINTY_CLASSES:
        if not any(s.uncertainty_class == explicit for s in states):
            _add(str(explicit), detail=str(signals.get("detail") or explicit))

    return states


def recovery_plan(
    states: list[UncertaintyState],
    *,
    mode: CognitiveMode = CognitiveMode.SHADOW,
    evidence_confidence: float | None = None,
    claimed_confidence: float | None = None,
) -> dict[str, Any]:
    """Build an ordered recovery plan. Evidence outranks claimed confidence."""
    ordered = sorted(
        states,
        key=lambda s: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(s.severity, 2),
    )
    actions = []
    ask_user = False
    for state in ordered:
        policy = RECOVERY_POLICY.get(state.uncertainty_class, RECOVERY_POLICY["missing_information"])
        actions.append(
            {
                "uncertainty_class": state.uncertainty_class,
                "action": state.recovery_action or policy["action"],
                "reason_code": policy["reason_code"],
                "ask_user": state.ask_user,
                "severity": state.severity,
                "detail": state.detail,
            }
        )
        if state.ask_user:
            ask_user = True

    # Confidence may never outrank evidence.
    confidence_blocked = False
    if (
        claimed_confidence is not None
        and evidence_confidence is not None
        and float(claimed_confidence) > float(evidence_confidence)
    ):
        confidence_blocked = True
        actions.insert(
            0,
            {
                "uncertainty_class": "unverified_assumption",
                "action": "defer_to_evidence",
                "reason_code": "EVIDENCE_OUTRANKS_CONFIDENCE",
                "ask_user": False,
                "severity": "high",
                "detail": f"claimed={claimed_confidence} evidence={evidence_confidence}",
            },
        )

    primary = actions[0] if actions else None
    influence = mode_allows_influence(mode)
    decision = AdaptiveDecision(
        controller="cognitive.epistemic",
        decision=primary["action"] if primary and influence else "observe_only",
        reason_code=primary["reason_code"] if primary else "NO_UNCERTAINTY",
        mode=mode.value,
        confidence=evidence_confidence,
        fallback="continue_with_verification" if not influence else None,
        verification_result="confidence_blocked" if confidence_blocked else None,
    )
    return {
        "states": [s.to_dict() for s in ordered],
        "actions": actions,
        "primary_action": primary,
        "ask_user": ask_user and influence,
        "influence": influence,
        "confidence_blocked": confidence_blocked,
        "decision": decision.to_dict(),
    }


def epistemic_step(signals: dict[str, Any], *, mode: CognitiveMode = CognitiveMode.SHADOW) -> dict[str, Any]:
    states = classify_uncertainty(signals=signals)
    return recovery_plan(
        states,
        mode=mode,
        evidence_confidence=signals.get("evidence_confidence"),
        claimed_confidence=signals.get("claimed_confidence"),
    )
