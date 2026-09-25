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
    """Promotion between A0–A4 only; never to live."""
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
    # Promotion requires measured acceptance evidence for A2+
    if tgt_i >= LEVEL_ORDER.index("A2") and not ev.get("accepted") and not ev.get("sealed_pass"):
        return {
            "allowed": False,
            "direction": "promote",
            "from": cur,
            "to": tgt,
            "reason": "PROMOTION_REQUIRES_KERNEL_ACCEPTANCE",
            "evidence": ev,
        }
    return {"allowed": True, "direction": "promote", "from": cur, "to": tgt, "evidence": ev}
