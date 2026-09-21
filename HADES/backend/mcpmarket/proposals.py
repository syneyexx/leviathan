"""Missing-capability proposals. Operator controls connection."""

from __future__ import annotations

from typing import Any


def propose_missing(
    *,
    requirement: str,
    candidates: list[dict[str, Any]],
    market_status: str,
) -> dict[str, Any]:
    items = []
    for row in candidates:
        items.append(
            {
                "missing_capability": requirement,
                "candidate": row.get("name") or row.get("slug"),
                "slug": row.get("slug"),
                "why_relevant": row.get("why") or row.get("description") or "",
                "required_auth_setup": bool(row.get("requires_auth") or row.get("needs_setup", True)),
                "expected_side_effects": row.get("side_effect_class") or "network",
                "trust": "untrusted",
                "operator_controls": True,
            }
        )
    return {
        "status": market_status,
        "requirement": requirement,
        "candidates": items,
        "model_called": False,
        "auto_install": False,
        "resume_without_full_replan": True,
    }
