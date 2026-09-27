"""Futures / FX paper execution semantics — extend historical owners; no equity fill assumptions.

Paper support is AVAILABLE only where multiplier/currency/session semantics are enforced.
Continuous research symbols are refused as tradable paper contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .futures_contracts import FuturesContractSpec
from .fx import CurrencyPair, fx_notional
from .types import MarketSimError


@dataclass(frozen=True)
class FuturesPaperContract:
    """Actual contract identity for paper — not a continuous research series."""

    spec: FuturesContractSpec
    contract_month: str  # YYYYMM
    expiry: str
    last_trade: str
    settlement: str = "cash"
    session: str = "RTH"
    roll_policy: str = "UNMEASURED"
    continuous_map: str | None = None  # research symbol mapping, not tradable
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            **self.spec.public_dict(),
            "contractMonth": self.contract_month,
            "expiry": self.expiry,
            "lastTrade": self.last_trade,
            "settlement": self.settlement,
            "session": self.session,
            "rollPolicy": self.roll_policy,
            "continuousMap": self.continuous_map,
            "tickValue": str(
                Decimal(str(self.spec.tick_size)) * Decimal(str(self.spec.multiplier))
            ),
            "metadata": dict(self.metadata),
            "truth": {
                "continuous_series_not_tradable_paper_contract": True,
                "variation_margin_required": True,
                "live_money": "BLOCKED",
            },
        }


def refuse_continuous_as_paper(symbol: str, *, continuous_tokens: tuple[str, ...] = ("_CONT", "@C", "CONTINUOUS")) -> None:
    upper = str(symbol or "").upper()
    if any(tok in upper for tok in continuous_tokens):
        raise MarketSimError(
            "CONTINUOUS_NOT_PAPER_CONTRACT",
            f"continuous research symbol {symbol!r} cannot be paper-traded; use actual contract month",
            http_status=409,
        )


def futures_paper_fill_notional(contract: FuturesPaperContract, qty: Any, price: Any) -> dict[str, Any]:
    refuse_continuous_as_paper(contract.spec.symbol)
    notional = contract.spec.notional(qty, price)
    return {
        "notional": str(notional),
        "multiplier": contract.spec.multiplier,
        "currency": contract.spec.quote_currency,
        "status": "MEASURED",
        "truth": {"no_silent_equity_fill": True},
    }


def futures_paper_capability() -> dict[str, Any]:
    return {
        "HISTORICAL_RESEARCH": "AVAILABLE",
        "SHADOW": "NOT_IMPLEMENTED",
        "AUTONOMOUS_PAPER": "NOT_IMPLEMENTED",
        "reason": "paper_path_requires_actual_contract_month_session_roll_policy",
        "foundation": "FuturesPaperContract + variation_margin",
        "truth": {
            "historical_vm_available": True,
            "continuous_not_paper": True,
            "live_money": "BLOCKED",
        },
    }


@dataclass(frozen=True)
class FxPaperPair:
    pair: CurrencyPair
    lot_size: str = "100000"
    session: str = "OTC_24_5"
    rollover_swap_status: str = "UNMEASURED"
    weekend_closed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            **self.pair.public_dict(),
            "lotSize": self.lot_size,
            "session": self.session,
            "rolloverSwapStatus": self.rollover_swap_status,
            "weekendClosed": self.weekend_closed,
            "pipSize": str(self.pair.pip_size()),
            "tickSize": self.pair.default_tick_size(),
            "metadata": dict(self.metadata),
            "truth": {
                "missing_fx_rate_is_not_1": True,
                "live_money": "BLOCKED",
            },
        }


def fx_convert(
    *,
    amount: Any,
    rate: Any | None,
    pair: CurrencyPair | None = None,
) -> dict[str, Any]:
    """FX conversion — missing rate is UNMEASURED / refused, never 1.0."""
    if rate is None:
        return {
            "converted": None,
            "rate": None,
            "status": "UNMEASURED",
            "reason": "missing_fx_rate_not_1",
            "pair": pair.public_dict() if pair else None,
            "truth": {"missing_fx_rate_is_not_1": True},
        }
    try:
        converted = Decimal(str(amount)) * Decimal(str(rate))
    except Exception as exc:  # noqa: BLE001
        return {
            "converted": None,
            "rate": str(rate),
            "status": "UNMEASURED",
            "reason": f"fx_convert_error:{exc}",
            "truth": {"missing_fx_rate_is_not_1": True},
        }
    return {
        "converted": str(converted),
        "rate": str(rate),
        "status": "MEASURED",
        "notional_quote": str(fx_notional(amount, rate, pair=pair)),
        "pair": pair.public_dict() if pair else None,
    }


def fx_paper_capability() -> dict[str, Any]:
    return {
        "HISTORICAL_RESEARCH": "AVAILABLE",
        "SHADOW": "NOT_IMPLEMENTED",
        "AUTONOMOUS_PAPER": "NOT_IMPLEMENTED",
        "reason": "paper_requires_rollover_swap_and_session_semantics",
        "foundation": "FxPaperPair + fx_convert fail-closed",
        "truth": {
            "missing_fx_rate_is_not_1": True,
            "live_money": "BLOCKED",
        },
    }
