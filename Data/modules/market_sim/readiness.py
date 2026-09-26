"""Readiness ladder A0–A4; A5 / live impossible (P3B / G28)."""

from __future__ import annotations

from typing import Any

from .orchestra.types import AutonomyLevel
from .types import MarketSimError

LEVEL_ORDER = ("A0", "A1", "A2", "A3", "A4")


def normalize_autonomy(raw: Any, *, default: str = "A0") -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return AutonomyLevel.parse(default).value
    if text in {"A5", "LIVE", "LIVE_TRADING", "PRODUCTION"}:
        raise MarketSimError(
            "A5_IMPOSSIBLE",
            "A5 / live trading is not a readiness level; ladder stops at A4 (autonomous paper).",
            http_status=422,
        )
    try:
        return AutonomyLevel.parse(text).value
    except ValueError as exc:
        raise MarketSimError("INVALID_AUTONOMY_LEVEL", str(exc), http_status=422) from exc


def assert_not_live_level(level: str) -> None:
    text = str(level or "").strip().upper()
    if text in {"A5", "LIVE", "LIVE_TRADING"}:
        raise MarketSimError(
            "A5_IMPOSSIBLE",
            "A5 / live trading cannot be enabled",
            http_status=422,
        )


def readiness_ladder() -> dict[str, Any]:
    return {
        "levels": [
            {"level": "A0", "name": "Gym", "description": "TradingGym / historical research"},
            {"level": "A1", "name": "Validation", "description": "WFA / validation metrics"},
            {"level": "A2", "name": "Sealed once", "description": "Single-use SEALED evaluation"},
            {"level": "A3", "name": "Shadow paper", "description": "Paper shadow without capital authority"},
            {"level": "A4", "name": "Autonomous paper", "description": "Autonomous paper loop only"},
        ],
        "ceiling": "A4",
        "A5": "IMPOSSIBLE",
        "live_trading": "BLOCKED",
        "truth": {
            "a5_does_not_exist": True,
            "live_never_a_level": True,
            "paper_only": True,
        },
    }


def may_promote_to(*, current: str, target: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Promotion between A0–A4 only; never to live.

    Caller-supplied booleans are not proof. Server resolves trusted evaluation
    records via evidence refs / acceptance payloads produced by the kernel.
    Stage prerequisites are enforced — arbitrary A0→A4 jumps require an
    explicit validated policy, not a lone ``accepted=True``.
    """
    cur = normalize_autonomy(current)
    tgt = normalize_autonomy(target)
    assert_not_live_level(tgt)
    cur_i = LEVEL_ORDER.index(cur)
    tgt_i = LEVEL_ORDER.index(tgt)
    ev = dict(evidence or {})
    if tgt_i < cur_i:
        return {"allowed": True, "direction": "demote", "from": cur, "to": tgt, "evidence": ev}
    if tgt_i == cur_i:
        return {"allowed": True, "direction": "noop", "from": cur, "to": tgt, "evidence": ev}

    # Resolve trusted acceptance — reject bare caller booleans.
    acceptance = ev.get("acceptance")
    accepted = False
    if isinstance(acceptance, dict):
        # Kernel-shaped acceptance from evaluate_acceptance_from_run / AcceptanceCriteria.
        if acceptance.get("passed") is True and (
            acceptance.get("run_id")
            or acceptance.get("criteria_id")
            or acceptance.get("metrics")
            or acceptance.get("measurement") == "MEASURED"
        ):
            accepted = True
        elif acceptance.get("passed") is True and not (
            acceptance.get("run_id") or acceptance.get("criteria_id") or acceptance.get("metrics")
        ):
            return {
                "allowed": False,
                "direction": "promote",
                "from": cur,
                "to": tgt,
                "reason": "PROMOTION_REQUIRES_RESOLVED_ACCEPTANCE",
                "evidence": ev,
            }
    sealed_pass = bool(ev.get("sealed_pass"))
    sealed_attempt_id = ev.get("sealed_attempt_id") or (
        acceptance.get("sealed_attempt_id") if isinstance(acceptance, dict) else None
    )
    evaluation_refs = list(ev.get("evaluation_refs") or [])
    policy = dict(ev.get("policy") or {})
    allow_jump = bool(policy.get("allow_level_jump")) and bool(policy.get("policy_version"))

    # Stage prerequisites: each step up requires corresponding evidence class.
    # A1: validation metrics; A2: sealed; A3: paper/shadow evidence; A4: autonomous paper evidence.
    required_gaps: list[str] = []
    for level_i in range(cur_i + 1, tgt_i + 1):
        level = LEVEL_ORDER[level_i]
        if level == "A1":
            if not accepted and not evaluation_refs:
                required_gaps.append("A1_requires_validation_acceptance_or_evaluation_refs")
        elif level == "A2":
            if not (accepted and (sealed_pass or sealed_attempt_id)) and not (
                sealed_pass and sealed_attempt_id
            ):
                required_gaps.append("A2_requires_sealed_kernel_acceptance")
        elif level == "A3":
            if not (ev.get("paper_shadow_pass") or ev.get("shadow_run_id")):
                required_gaps.append("A3_requires_paper_shadow_evidence")
        elif level == "A4":
            if not (ev.get("autonomous_paper_pass") or ev.get("paper_deployment_id")):
                required_gaps.append("A4_requires_autonomous_paper_evidence")

    if required_gaps and not allow_jump:
        return {
            "allowed": False,
            "direction": "promote",
            "from": cur,
            "to": tgt,
            "reason": "PROMOTION_STAGE_PREREQUISITES",
            "missing": required_gaps,
            "evidence": ev,
        }
    if required_gaps and allow_jump:
        # Explicit validated policy may permit a jump, but still needs kernel acceptance for A2+.
        if tgt_i >= LEVEL_ORDER.index("A2") and not accepted and not sealed_pass:
            return {
                "allowed": False,
                "direction": "promote",
                "from": cur,
                "to": tgt,
                "reason": "PROMOTION_REQUIRES_KERNEL_ACCEPTANCE",
                "evidence": ev,
            }
    # Reject lone accepted=True without structured acceptance / refs.
    if ev.get("accepted") is True and not accepted and not evaluation_refs and not sealed_pass:
        return {
            "allowed": False,
            "direction": "promote",
            "from": cur,
            "to": tgt,
            "reason": "PROMOTION_REJECTS_CALLER_BOOLEAN",
            "evidence": ev,
        }
    return {"allowed": True, "direction": "promote", "from": cur, "to": tgt, "evidence": ev}
