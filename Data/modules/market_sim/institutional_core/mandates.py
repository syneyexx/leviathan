"""W51 — Mandates as policy-as-code: pre/post trade checks.

Extends orchestra.types.Mandate — does not duplicate mandate authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str  # BUY | SELL | SHORT | COVER
    qty: float
    order_type: str = "MARKET"
    family: str = "equity"
    notional: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "orderType": self.order_type,
            "family": self.family,
            "notional": self.notional,
        }


@dataclass
class PolicyViolation:
    code: str
    severity: str  # BLOCK | WARN
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass
class PolicyDecision:
    phase: str  # PRE_TRADE | POST_TRADE
    allowed: bool
    violations: list[PolicyViolation] = field(default_factory=list)
    mandate_fingerprint: str | None = None
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "allowed": self.allowed,
            "violations": [v.public_dict() for v in self.violations],
            "mandateFingerprint": self.mandate_fingerprint,
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_orchestra_mandate": True,
                "live_trading_never_granted_by_mandate": True,
            },
        }


def _mandate_view(mandate: Any) -> dict[str, Any]:
    if mandate is None:
        return {}
    if hasattr(mandate, "public_dict"):
        return dict(mandate.public_dict())
    if isinstance(mandate, Mapping):
        return dict(mandate)
    return {}


def mandate_fingerprint(mandate: Any) -> str:
    import hashlib
    import json

    view = _mandate_view(mandate)
    raw = json.dumps(view, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pre_trade_check(
    intent: OrderIntent | Mapping[str, Any],
    mandate: Any,
    *,
    current_symbol_exposure_pct: float = 0.0,
    current_gross_exposure_pct: float = 0.0,
    orders_today: int = 0,
) -> PolicyDecision:
    if isinstance(intent, Mapping):
        intent = OrderIntent(
            symbol=str(intent.get("symbol") or "").upper(),
            side=str(intent.get("side") or "BUY").upper(),
            qty=float(intent.get("qty") or 0),
            order_type=str(intent.get("order_type") or intent.get("orderType") or "MARKET").upper(),
            family=str(intent.get("family") or "equity").lower(),
            notional=(
                None
                if intent.get("notional") is None
                else float(intent.get("notional"))
            ),
        )
    view = _mandate_view(mandate)
    violations: list[PolicyViolation] = []

    # Mandates can never enable live trading.
    if view.get("cannotEnableLive") is False:
        violations.append(
            PolicyViolation("LIVE_TRADING_FORBIDDEN", "BLOCK", "mandate cannot enable live")
        )

    universe = {str(s).upper() for s in (view.get("universe") or [])}
    if universe and intent.symbol.upper() not in universe:
        violations.append(
            PolicyViolation("UNIVERSE", "BLOCK", f"{intent.symbol} not in mandate universe")
        )

    allowed_types = {str(t).upper() for t in (view.get("allowedOrderTypes") or ["MARKET"])}
    if intent.order_type.upper() not in allowed_types:
        violations.append(
            PolicyViolation("ORDER_TYPE", "BLOCK", f"{intent.order_type} not allowed")
        )

    allowed_families = {str(f).lower() for f in (view.get("allowedFamilies") or [])}
    if allowed_families and intent.family.lower() not in allowed_families:
        violations.append(
            PolicyViolation("FAMILY", "BLOCK", f"{intent.family} not allowed")
        )

    max_orders = int(view.get("maxOrdersPerDay") or 0)
    if max_orders and orders_today >= max_orders:
        violations.append(
            PolicyViolation("MAX_ORDERS", "BLOCK", f"orders_today={orders_today} >= {max_orders}")
        )

    max_sym = float(view.get("maxSymbolExposurePct") or 100.0)
    if current_symbol_exposure_pct > max_sym:
        violations.append(
            PolicyViolation(
                "SYMBOL_EXPOSURE",
                "BLOCK",
                f"symbol exposure {current_symbol_exposure_pct} > {max_sym}",
            )
        )

    max_gross = float(view.get("maxGrossExposurePct") or 100.0)
    if current_gross_exposure_pct > max_gross:
        violations.append(
            PolicyViolation(
                "GROSS_EXPOSURE",
                "BLOCK",
                f"gross exposure {current_gross_exposure_pct} > {max_gross}",
            )
        )

    if intent.qty <= 0:
        violations.append(PolicyViolation("QTY", "BLOCK", "qty must be positive"))

    blocked = [v for v in violations if v.severity == "BLOCK"]
    return PolicyDecision(
        phase="PRE_TRADE",
        allowed=not blocked,
        violations=violations,
        mandate_fingerprint=mandate_fingerprint(mandate) if view else None,
    )


def post_trade_check(
    *,
    mandate: Any,
    realized_drawdown_pct: float,
    gross_exposure_pct: float,
) -> PolicyDecision:
    view = _mandate_view(mandate)
    violations: list[PolicyViolation] = []
    max_dd = float(view.get("maxDrawdownPct") or 100.0)
    if realized_drawdown_pct > max_dd:
        violations.append(
            PolicyViolation(
                "DRAWDOWN",
                "BLOCK",
                f"drawdown {realized_drawdown_pct} > {max_dd}",
            )
        )
    max_gross = float(view.get("maxGrossExposurePct") or 100.0)
    if gross_exposure_pct > max_gross:
        violations.append(
            PolicyViolation(
                "GROSS_EXPOSURE",
                "BLOCK",
                f"post gross {gross_exposure_pct} > {max_gross}",
            )
        )
    blocked = [v for v in violations if v.severity == "BLOCK"]
    return PolicyDecision(
        phase="POST_TRADE",
        allowed=not blocked,
        violations=violations,
        mandate_fingerprint=mandate_fingerprint(mandate) if view else None,
    )


def load_mandate(raw: Mapping[str, Any] | None) -> Any:
    """Prefer orchestra Mandate when importable."""
    try:
        from ..orchestra.types import Mandate

        return Mandate.from_dict(dict(raw or {}))
    except Exception:  # noqa: BLE001
        return dict(raw or {})
