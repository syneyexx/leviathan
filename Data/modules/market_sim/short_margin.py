"""Short margin policy — supports_short alone is never enough."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShortMarginPolicy:
    """Required before opening/increasing a short in simulation."""

    initial_margin_pct: float
    maintenance_margin_pct: float
    short_proceeds_policy: str = "reserved"  # reserved | free_with_margin
    buying_power_rule: str = "initial_margin_only"
    borrow_fee_bps_per_day: float | None = None  # None => borrow_cost UNMEASURED

    def public_dict(self) -> dict[str, Any]:
        return {
            "initialMarginPct": self.initial_margin_pct,
            "maintenanceMarginPct": self.maintenance_margin_pct,
            "shortProceedsPolicy": self.short_proceeds_policy,
            "buyingPowerRule": self.buying_power_rule,
            "borrowFeeBpsPerDay": self.borrow_fee_bps_per_day,
            "borrowCost": (
                "MEASURED"
                if self.borrow_fee_bps_per_day is not None
                else "UNMEASURED"
            ),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ShortMarginPolicy | None":
        if not raw:
            return None
        try:
            return cls(
                initial_margin_pct=float(
                    raw.get("initial_margin_pct", raw.get("initialMarginPct"))
                ),
                maintenance_margin_pct=float(
                    raw.get("maintenance_margin_pct", raw.get("maintenanceMarginPct"))
                ),
                short_proceeds_policy=str(
                    raw.get("short_proceeds_policy", raw.get("shortProceedsPolicy", "reserved"))
                ),
                buying_power_rule=str(
                    raw.get("buying_power_rule", raw.get("buyingPowerRule", "initial_margin_only"))
                ),
                borrow_fee_bps_per_day=(
                    None
                    if raw.get("borrow_fee_bps_per_day", raw.get("borrowFeeBpsPerDay")) is None
                    else float(raw.get("borrow_fee_bps_per_day", raw.get("borrowFeeBpsPerDay")))
                ),
            )
        except (TypeError, ValueError, KeyError):
            return None


def short_open_allowed(
    *,
    supports_short: bool,
    margin_policy: ShortMarginPolicy | None,
) -> tuple[bool, str]:
    if not supports_short:
        return False, "INSTRUMENT_RULE: short not supported for instrument"
    if margin_policy is None:
        return False, "MARGIN_POLICY_REQUIRED: short blocked without ShortMarginPolicy"
    if margin_policy.initial_margin_pct <= 0 or margin_policy.maintenance_margin_pct <= 0:
        return False, "MARGIN_POLICY_REQUIRED: invalid margin percentages"
    return True, "short_allowed"
