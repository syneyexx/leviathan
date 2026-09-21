"""Fault / decision timeline from existing coding events and investigate artifacts."""

from __future__ import annotations

from typing import Any


def build_fault_timeline(
    *,
    events: list[dict[str, Any]] | None = None,
    investigate: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    instructions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Link observations → decisions → actions → tests → instructions → evidence.

    Does not duplicate full run storage; references existing structures.
    """
    items: list[dict[str, Any]] = []
    inv = dict(investigate or {})
    for obs in inv.get("observations") or []:
        action = obs.get("action") or {}
        items.append(
            {
                "kind": "observation",
                "action": action.get("kind"),
                "rationale": action.get("rationale"),
                "status": obs.get("status"),
                "led_to": "next_action_or_hypothesis",
            }
        )
    for hyp in inv.get("hypotheses") or []:
        items.append(
            {
                "kind": "hypothesis",
                "id": hyp.get("id"),
                "cause": hyp.get("cause"),
                "status": hyp.get("status"),
                "check": hyp.get("discriminating_check"),
            }
        )
    for instr in instructions or []:
        items.append(
            {
                "kind": "instruction",
                "version": instr.get("version"),
                "note": instr.get("note"),
                "status": instr.get("status"),
                "effective_from_action": instr.get("effective_from_action"),
                "changed_plan": True,
            }
        )
    for ev in events or []:
        items.append(
            {
                "kind": "event",
                "event_kind": ev.get("kind"),
                "seq": ev.get("seq"),
                "ts": ev.get("ts"),
                "data_keys": sorted((ev.get("data") or {}).keys()),
            }
        )
    if review:
        items.append(
            {
                "kind": "review",
                "status": review.get("status"),
                "defects": len(review.get("defects") or []),
                "extra_checks": review.get("extra_checks") or [],
            }
        )
    if evidence:
        items.append(
            {
                "kind": "evidence",
                "run_id": evidence.get("run_id"),
                "change_hash": evidence.get("change_hash"),
                "result_status": evidence.get("result_status"),
                "supports": evidence.get("result_status"),
            }
        )
    return {
        "items": items,
        "summary": inv.get("investigate_summary") or {},
        "stop_reason": inv.get("stop_reason"),
        "note": "Timeline references existing events/artifacts; not a second full run log.",
    }
