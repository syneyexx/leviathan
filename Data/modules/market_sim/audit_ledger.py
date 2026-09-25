"""Hash-chained trading audit ledger (T9 / G36)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence


GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_link(prev_hash: str, payload: dict[str, Any]) -> str:
    body = f"{prev_hash}|{_canonical(payload)}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def append_audit_event(
    events: list[dict[str, Any]],
    *,
    kind: str,
    payload: dict[str, Any],
    created_at: str,
    session_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Append intent→risk→broker→fill→reconcile event with hash chain."""
    prev = events[-1]["entry_hash"] if events else GENESIS_HASH
    entry = {
        "event_id": str(uuid.uuid4()),
        "kind": kind,
        "session_id": session_id,
        "run_id": run_id,
        "payload": dict(payload),
        "prev_hash": prev,
        "created_at": created_at,
    }
    entry["entry_hash"] = _hash_link(prev, {
        "kind": kind,
        "session_id": session_id,
        "run_id": run_id,
        "payload": entry["payload"],
        "created_at": created_at,
        "prev_hash": prev,
    })
    events.append(entry)
    return entry


def verify_audit_chain(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Return ok=False if any link is tampered or broken."""
    prev = GENESIS_HASH
    for i, ev in enumerate(events):
        expected_prev = ev.get("prev_hash")
        if expected_prev != prev:
            return {
                "ok": False,
                "broken_at": i,
                "reason": "prev_hash_mismatch",
                "truth": {"tamper_detectable": True},
            }
        recomputed = _hash_link(prev, {
            "kind": ev.get("kind"),
            "session_id": ev.get("session_id"),
            "run_id": ev.get("run_id"),
            "payload": ev.get("payload") or {},
            "created_at": ev.get("created_at"),
            "prev_hash": prev,
        })
        if recomputed != ev.get("entry_hash"):
            return {
                "ok": False,
                "broken_at": i,
                "reason": "entry_hash_mismatch",
                "truth": {"tamper_detectable": True},
            }
        prev = ev["entry_hash"]
    return {
        "ok": True,
        "length": len(events),
        "tip_hash": prev if events else GENESIS_HASH,
        "truth": {"tamper_detectable": True, "hash_chained": True},
    }


AUDIT_KINDS = (
    "intent",
    "risk_decision",
    "broker_call",
    "fill",
    "reconciliation",
    "kill_switch",
    "failure_injection",
)
