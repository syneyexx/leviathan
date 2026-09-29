"""Canonical MarketSim operating profiles.

Profiles configure existing MarketSim / paper / RiskGuard paths.
They are not a second trading engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


AUTONOMOUS_PAPER_REAL_DATA = "AUTONOMOUS_PAPER_REAL_DATA"
RESEARCH_GYM = "RESEARCH_GYM"
PAPER_SHADOW = "PAPER_SHADOW"


@dataclass(frozen=True)
class OperatingProfile:
    """Declared operating envelope for paper / research execution."""

    profile_id: str
    real_market_data: bool
    paper_only: bool
    live_money_allowed: bool
    deterministic_risk_guard: bool
    point_in_time: bool
    durable_receipts: bool
    reconciliation_required: bool
    strategy_memory_feedback: bool
    description: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "real_market_data": self.real_market_data,
            "paper_only": self.paper_only,
            "live_money_allowed": self.live_money_allowed,
            "deterministic_risk_guard": self.deterministic_risk_guard,
            "point_in_time": self.point_in_time,
            "durable_receipts": self.durable_receipts,
            "reconciliation_required": self.reconciliation_required,
            "strategy_memory_feedback": self.strategy_memory_feedback,
            "description": self.description,
            "truth": {
                "not_a_second_engine": True,
                "live_money": "BLOCKED" if not self.live_money_allowed else "FORBIDDEN_IN_PROFILE",
            },
        }


_PROFILES: dict[str, OperatingProfile] = {
    AUTONOMOUS_PAPER_REAL_DATA: OperatingProfile(
        profile_id=AUTONOMOUS_PAPER_REAL_DATA,
        real_market_data=True,
        paper_only=True,
        live_money_allowed=False,
        deterministic_risk_guard=True,
        point_in_time=True,
        durable_receipts=True,
        reconciliation_required=True,
        strategy_memory_feedback=True,
        description=(
            "Real provider market data with actual timestamps and PIT rules; "
            "simulated capital; paper-only orders; deterministic RiskGuard; "
            "complete receipts; persistent portfolio accounting; reconciliation; "
            "postmortem; StrategyMemory feedback; real-money execution impossible."
        ),
    ),
    RESEARCH_GYM: OperatingProfile(
        profile_id=RESEARCH_GYM,
        real_market_data=False,
        paper_only=True,
        live_money_allowed=False,
        deterministic_risk_guard=True,
        point_in_time=True,
        durable_receipts=True,
        reconciliation_required=False,
        strategy_memory_feedback=True,
        description="Historical gym / research replay under RiskGuard.",
    ),
    PAPER_SHADOW: OperatingProfile(
        profile_id=PAPER_SHADOW,
        real_market_data=True,
        paper_only=True,
        live_money_allowed=False,
        deterministic_risk_guard=True,
        point_in_time=True,
        durable_receipts=True,
        reconciliation_required=True,
        strategy_memory_feedback=False,
        description="Observe-only shadow paper — no capital authority.",
    ),
}


def resolve_operating_profile(profile_id: str | None) -> OperatingProfile:
    key = str(profile_id or AUTONOMOUS_PAPER_REAL_DATA).strip().upper()
    if key not in _PROFILES:
        raise KeyError(f"unknown operating profile: {profile_id}")
    return _PROFILES[key]


def list_operating_profiles() -> list[dict[str, Any]]:
    return [p.public_dict() for p in _PROFILES.values()]


__all__ = [
    "AUTONOMOUS_PAPER_REAL_DATA",
    "RESEARCH_GYM",
    "PAPER_SHADOW",
    "OperatingProfile",
    "resolve_operating_profile",
    "list_operating_profiles",
]
