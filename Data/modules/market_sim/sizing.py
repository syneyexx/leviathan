"""Explicit position sizing models — no hidden multipliers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SizingModel:
    """Canonical sizing configuration persisted on SimRun."""

    kind: str = "risk_pct"  # risk_pct | fixed_qty | fixed_notional | all_in_cap
    per_trade_risk_pct: float = 1.0
    max_position_pct: float = 25.0
    fixed_qty: float | None = None
    fixed_notional: float | None = None
    max_notional: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "perTradeRiskPct": self.per_trade_risk_pct,
            "maxPositionPct": self.max_position_pct,
            "fixedQty": self.fixed_qty,
            "fixedNotional": self.fixed_notional,
            "maxNotional": self.max_notional,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None, *, defaults: dict[str, Any] | None = None) -> "SizingModel":
        d = dict(defaults or {})
        if raw:
            d.update(raw)
        kind = str(d.get("kind") or d.get("sizingKind") or "risk_pct")
        return cls(
            kind=kind,
            per_trade_risk_pct=float(
                d.get("per_trade_risk_pct", d.get("perTradeRiskPct", 1.0))
            ),
            max_position_pct=float(
                d.get("max_position_pct", d.get("maxPositionPct", 25.0))
            ),
            fixed_qty=(
                None
                if d.get("fixed_qty", d.get("fixedQty")) is None
                else float(d.get("fixed_qty", d.get("fixedQty")))
            ),
            fixed_notional=(
                None
                if d.get("fixed_notional", d.get("fixedNotional")) is None
                else float(d.get("fixed_notional", d.get("fixedNotional")))
            ),
            max_notional=(
                None
                if d.get("max_notional", d.get("maxNotional")) is None
                else float(d.get("max_notional", d.get("maxNotional")))
            ),
        )

    def target_qty(
        self,
        *,
        price: float,
        equity: float,
        available_cash: float,
        requested_qty: float | None,
    ) -> tuple[float, str]:
        """Return (qty, reason). Never applies undocumented multipliers."""
        if price <= 0 or equity <= 0:
            return 0.0, "invalid price/equity"
        max_pos_notional = equity * (self.max_position_pct / 100.0)
        if self.max_notional is not None:
            max_pos_notional = min(max_pos_notional, float(self.max_notional))
        cap_qty = max_pos_notional / price
        affordable = available_cash / price

        kind = (self.kind or "risk_pct").lower()
        if kind == "fixed_qty":
            base = self.fixed_qty if self.fixed_qty is not None else requested_qty
            if base is None:
                return 0.0, "fixed_qty requires fixedQty or requested qty"
            qty = max(0.0, min(float(base), cap_qty, affordable))
            return qty, "fixed_qty"
        if kind == "fixed_notional":
            notional = self.fixed_notional
            if notional is None and requested_qty is not None:
                notional = float(requested_qty) * price
            if notional is None:
                return 0.0, "fixed_notional requires fixedNotional"
            qty = max(0.0, min(float(notional) / price, cap_qty, affordable))
            return qty, "fixed_notional"
        if kind == "all_in_cap":
            qty = max(0.0, min(cap_qty, affordable))
            if requested_qty is not None:
                qty = min(qty, float(requested_qty))
            return qty, "all_in_cap"

        # risk_pct (default): size to per_trade_risk_pct of equity, capped by max position
        risk_notional = equity * (self.per_trade_risk_pct / 100.0)
        risk_qty = risk_notional / price
        if requested_qty is not None:
            qty = max(0.0, min(float(requested_qty), cap_qty, affordable, risk_qty))
            return qty, "risk_pct_requested"
        qty = max(0.0, min(cap_qty, affordable, risk_qty))
        return qty, "risk_pct"
