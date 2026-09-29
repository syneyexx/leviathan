"""Paper-trading causal quote fence (Wave 4).

Refuse future / poison quotes relative to decision as_of. Extends existing
causality helpers — does not invent a second market clock.
"""

from __future__ import annotations

from typing import Any, Mapping

from .epistemic import compare_ts
from .types import MarketSimError


def refuse_future_quote(
    *,
    quote_ts: str | None,
    as_of: str,
    symbol: str = "",
    price: float | None = None,
) -> dict[str, Any]:
    """Return ALLOW or raise MarketSimError on lookahead / future quote.

    Callers must pass the decision as_of. Missing quote_ts is UNMEASURED — not
    silently treated as causal.
    """
    if not as_of:
        raise MarketSimError(
            "AS_OF_REQUIRED",
            "Paper decision requires as_of for causal quote fencing",
            http_status=422,
        )
    if not quote_ts:
        return {
            "status": "UNMEASURED",
            "allowed": False,
            "reason": "missing_quote_ts",
            "as_of": as_of,
            "symbol": symbol,
            "price": price,
            "truth": {
                "missing_ts_is_not_causal": True,
                "no_lookahead": True,
                "live_money": "BLOCKED",
            },
        }
    if compare_ts(quote_ts, as_of) > 0:
        raise MarketSimError(
            "LOOKAHEAD_REFUSED",
            f"Future quote {quote_ts} after as_of {as_of} for {symbol or 'symbol'}",
            http_status=409,
        )
    return {
        "status": "ALLOW",
        "allowed": True,
        "as_of": as_of,
        "quote_ts": quote_ts,
        "symbol": symbol,
        "price": price,
        "truth": {
            "no_lookahead": True,
            "live_money": "BLOCKED",
        },
    }


def filter_quotes_as_of(
    quotes: list[Mapping[str, Any]],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Drop poison/future quotes; never invent replacements."""
    visible: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for raw in quotes or []:
        q = dict(raw)
        ts = str(q.get("ts") or q.get("timestamp") or q.get("as_of") or "")
        try:
            decision = refuse_future_quote(
                quote_ts=ts or None,
                as_of=as_of,
                symbol=str(q.get("symbol") or ""),
                price=float(q["price"]) if q.get("price") is not None else None,
            )
        except MarketSimError as exc:
            dropped.append({"quote": q, "error_code": exc.code, "error": str(exc)})
            continue
        if not decision.get("allowed"):
            dropped.append({"quote": q, "decision": decision})
            continue
        visible.append(q)
    return {
        "as_of": as_of,
        "visible": visible,
        "dropped": dropped,
        "visible_count": len(visible),
        "dropped_count": len(dropped),
        "truth": {
            "poison_future_invisible": True,
            "no_lookahead": True,
            "no_invented_replacement_quotes": True,
        },
    }


def live_external_alpaca_status(*, credentials_present: bool) -> dict[str, Any]:
    """Honest LIVE_EXTERNAL_TEST marker when Alpaca paper credentials absent."""
    if credentials_present:
        return {
            "LIVE_EXTERNAL_TEST": "CONFIGURED",
            "status": "CONFIGURED",
            "measurement": "CONFIGURED",
            "truth": {
                "credentials_present_is_not_measured_pass": True,
                "live_money": "BLOCKED",
            },
        }
    return {
        "LIVE_EXTERNAL_TEST": "UNMEASURED",
        "status": "UNMEASURED",
        "measurement": "UNMEASURED",
        "reason": "alpaca_paper_credentials_unavailable",
        "truth": {
            "unmeasured_is_not_pass": True,
            "unmeasured_is_not_fail": True,
            "live_money": "BLOCKED",
        },
    }
