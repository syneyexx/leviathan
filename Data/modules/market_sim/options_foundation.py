"""Options research foundation — contract chain, IV/Greeks honesty, lifecycle stubs.

Trading/paper remains NOT_IMPLEMENTED until full lifecycle is proven.
Undefined Greeks are UNMEASURED — never silently zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .options_contracts import OptionContractSpec, parse_option_right


@dataclass(frozen=True)
class OptionChainSnapshot:
    underlying: str
    as_of: str
    contracts: tuple[OptionContractSpec, ...]
    source: str = "UNMEASURED"
    provenance_hash: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "as_of": self.as_of,
            "contract_count": len(self.contracts),
            "contracts": [c.public_dict() for c in self.contracts],
            "source": self.source,
            "provenance_hash": self.provenance_hash,
            "truth": {
                "greeks_unset_is_UNMEASURED": True,
                "options_trading": "NOT_IMPLEMENTED",
                "paper_support": "NOT_IMPLEMENTED",
                "live_money": "BLOCKED",
            },
        }


@dataclass
class OptionLifecycleEvent:
    event_id: str
    kind: str  # exercise | assignment | expiration | corporate_action
    contract_symbol: str
    as_of: str
    status: str = "RECORDED"  # RECORDED | UNMEASURED | BLOCKED
    quantity: float | None = None
    cash_amount: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "contract_symbol": self.contract_symbol,
            "as_of": self.as_of,
            "status": self.status,
            "quantity": self.quantity,
            "cash_amount": self.cash_amount,
            "metadata": dict(self.metadata),
            "truth": {
                "options_paper": "NOT_IMPLEMENTED",
                "undefined_not_zero": True,
            },
        }


def build_option_chain(
    *,
    underlying: str,
    as_of: str,
    strikes: Sequence[float | str],
    expiry: str,
    rights: Sequence[str] = ("call", "put"),
    style: str = "american",
    multiplier: str = "100",
    venue: str = "UNKNOWN",
    quotes: dict[str, dict[str, Any]] | None = None,
) -> OptionChainSnapshot:
    """Build a typed option chain. Missing bid/ask/IV/Greeks stay UNMEASURED."""
    quotes = quotes or {}
    contracts: list[OptionContractSpec] = []
    for strike in strikes:
        for right_raw in rights:
            right = parse_option_right(str(right_raw))
            sym = f"{underlying.upper()}{expiry.replace('-', '')}{right[0].upper()}{strike}"
            q = quotes.get(sym) or {}
            contracts.append(
                OptionContractSpec(
                    symbol=sym,
                    underlying=underlying.upper(),
                    right=right,
                    strike=str(strike),
                    expiry=expiry,
                    venue=venue,
                    multiplier=multiplier,
                    style=style,
                    implied_vol=q.get("implied_vol"),
                    delta=q.get("delta"),
                    gamma=q.get("gamma"),
                    theta=q.get("theta"),
                    vega=q.get("vega"),
                    metadata={
                        "bid": q.get("bid"),
                        "ask": q.get("ask"),
                        "bid_ask_status": (
                            "MEASURED"
                            if q.get("bid") is not None and q.get("ask") is not None
                            else "UNMEASURED"
                        ),
                    },
                )
            )
    return OptionChainSnapshot(
        underlying=underlying.upper(),
        as_of=as_of,
        contracts=tuple(contracts),
        source="constructed",
    )


def options_paper_capability() -> dict[str, Any]:
    return {
        "HISTORICAL_RESEARCH": "NOT_IMPLEMENTED",
        "SHADOW": "NOT_IMPLEMENTED",
        "AUTONOMOUS_PAPER": "NOT_IMPLEMENTED",
        "reason": "full_options_lifecycle_not_proven",
        "truth": {
            "identity_exists": True,
            "greeks_default_UNMEASURED": True,
            "no_fake_paper_support": True,
            "live_money": "BLOCKED",
        },
    }
