"""Market capability matrix — derived from adapters + config, not page presence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from .instruments import InstrumentFamily


@dataclass(frozen=True)
class MarketModeStatus:
    family: str
    historical_sim: str
    live_paper: str
    live_trading: str
    data_providers: list[str]
    paper_brokers: list[str]
    notes: str
    verified_by: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "HISTORICAL_SIM_AVAILABLE": self.historical_sim,
            "LIVE_PAPER_AVAILABLE": self.live_paper,
            "LIVE_TRADING_AVAILABLE": self.live_trading,
            "data_providers": self.data_providers,
            "paper_brokers": self.paper_brokers,
            "notes": self.notes,
            "verified_by": self.verified_by,
        }


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _alpaca_paper_configured() -> bool:
    """Secrets present does not mean live money — paper endpoint only."""
    key = os.environ.get("LEVIATHAN_ALPACA_PAPER_KEY_ID", "").strip()
    secret = os.environ.get("LEVIATHAN_ALPACA_PAPER_SECRET", "").strip()
    return bool(key and secret)


def _binance_reachable(probe: Callable[[], bool] | None = None) -> bool:
    if probe is not None:
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001
            return False
    # Lazy import to avoid circular deps at module load
    try:
        from .providers.binance import BinancePublicProvider

        return BinancePublicProvider().ping()
    except Exception:  # noqa: BLE001
        return False


def build_market_capabilities(
    *,
    feature_enabled: bool,
    binance_reachable: bool | None = None,
    alpaca_paper: bool | None = None,
    local_paper: bool = True,
) -> dict[str, Any]:
    """Compute per-family mode availability from real adapter readiness."""
    if binance_reachable is None:
        binance_reachable = _binance_reachable() if feature_enabled else False
    if alpaca_paper is None:
        alpaca_paper = _alpaca_paper_configured()

    live_trading = "BLOCKED"  # Always — TradingStub / live guard
    crypto_hist = "AVAILABLE" if feature_enabled else "UNAVAILABLE"
    equity_hist = "AVAILABLE" if feature_enabled else "UNAVAILABLE"

    # Live paper: local paper ledger against public quotes OR Alpaca paper
    crypto_paper = "UNAVAILABLE"
    equity_paper = "UNAVAILABLE"
    paper_brokers: list[str] = []
    if feature_enabled and local_paper:
        # Local paper ledger is always available when the feature is on.
        # Binance reachability only affects live quote freshness, not paper mode.
        crypto_paper = "AVAILABLE"
        equity_paper = "AVAILABLE"
        paper_brokers.append("local_paper")
        _ = binance_reachable  # retained for callers / future quote gating
    if feature_enabled and alpaca_paper:
        equity_paper = "AVAILABLE"
        paper_brokers.append("alpaca_paper")

    families = [
        MarketModeStatus(
            family=InstrumentFamily.EQUITY.value,
            historical_sim=equity_hist,
            live_paper=equity_paper if feature_enabled else "UNAVAILABLE",
            live_trading=live_trading,
            data_providers=["csv_local", "stooq_public"],
            paper_brokers=paper_brokers,
            notes=(
                "Historical OHLCV via CSV/Stooq. Live paper uses local ledger "
                "(optional Alpaca paper when secrets present). Live money blocked."
            ),
            verified_by="market_sim.capabilities + e2e equity demos",
        ),
        MarketModeStatus(
            family=InstrumentFamily.CRYPTO_SPOT.value,
            historical_sim=crypto_hist,
            live_paper=crypto_paper if feature_enabled else "UNAVAILABLE",
            live_trading=live_trading,
            data_providers=["csv_local", "binance_public"],
            paper_brokers=["local_paper"] if feature_enabled else [],
            notes=(
                "Historical via CSV or Binance public klines (data-api.binance.vision). "
                "Paper fills are local; not exchange-matched. Live money blocked."
            ),
            verified_by="market_sim.capabilities + e2e crypto demos",
        ),
        MarketModeStatus(
            family=InstrumentFamily.FUTURES.value,
            # Contract identity/multiplier exist (W10); full historical sim path is not
            # proven end-to-end — do not claim AVAILABLE from enum/model presence alone.
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading=live_trading,
            data_providers=[],
            paper_brokers=[],
            notes=(
                "Futures/perps contract multiplier identity exists; funding UNMEASURED. "
                "Historical/paper sim NOT_IMPLEMENTED until E2E path is proven. "
                "Live money blocked."
            ),
            verified_by="market_sim.futures_contracts + instruments W10 (identity only)",
        ),
        MarketModeStatus(
            family=InstrumentFamily.FOREX.value,
            # FX pip/tick model exists (W09); full historical sim path is not proven
            # end-to-end — do not claim AVAILABLE from instrument-model presence alone.
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading=live_trading,
            data_providers=[],
            paper_brokers=[],
            notes=(
                "FX spot pip/tick identity exists. "
                "Historical/paper sim NOT_IMPLEMENTED until E2E path is proven. "
                "Live money blocked."
            ),
            verified_by="market_sim.fx + instruments W09 (identity only)",
        ),
        MarketModeStatus(
            family=InstrumentFamily.OPTIONS.value,
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading="BLOCKED",
            data_providers=[],
            paper_brokers=[],
            notes="Options contract identity exists; greeks/vol UNMEASURED; trading NOT_IMPLEMENTED.",
            verified_by="market_sim.options_contracts W11",
        ),
        MarketModeStatus(
            family=InstrumentFamily.FIXED_INCOME.value,
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading="BLOCKED",
            data_providers=[],
            paper_brokers=[],
            notes="Fixed income identity/yield stubs; accrual UNMEASURED; trading NOT_IMPLEMENTED.",
            verified_by="market_sim.fixed_income W12",
        ),
        MarketModeStatus(
            family=InstrumentFamily.OTHER.value,
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading="BLOCKED",
            data_providers=[],
            paper_brokers=[],
            notes="Catch-all family — never silently treated as equity.",
            verified_by="explicitly not implemented",
        ),
    ]

    return {
        "feature_enabled": feature_enabled,
        "live_trading_default": "BLOCKED",
        "live_credentials_separated": True,
        "alpaca_paper_secrets_present": bool(alpaca_paper),
        "binance_public_reachable": bool(binance_reachable),
        "force_live_blocked": not _env_truthy("LEVIATHAN_LIVE_TRADING_UNLOCK"),
        "markets": [m.public_dict() for m in families],
        "execution_granularity": execution_granularity_matrix(),
        "truth": {
            "capability_from_adapters": True,
            "not_from_ui_presence": True,
            "profitable_backtest_is_not_proof": True,
            "ohlcv_is_not_orderbook": True,
            "granularity_honesty_required": True,
        },
    }


def execution_granularity_matrix() -> list[dict[str, Any]]:
    """Honest execution capability by market-data granularity.

    OHLCV must never be presented as order-book (L2/L3) data.
    """
    return [
        {
            "granularity": "BAR_OHLCV",
            "status": "SUPPORTED",
            "execution_semantics": "next_bar_fill",
            "supported_order_types": ["market", "limit", "stop"],
            "known_limitations": [
                "intrabar path often AMBIGUOUS",
                "no queue position",
                "volume participation is model-based",
            ],
            "latency_model": "ASSUMED_CONFIGURABLE",
            "fill_model": "NextBarFillModel",
            "cost_model": "CostModelPack",
            "capacity_assumptions": "UNMEASURED_BY_DEFAULT",
            "measurement_status": "MEASURED",
            "truth": {"ohlcv_is_not_orderbook": True},
        },
        {
            "granularity": "QUOTE_L1",
            "status": "FEATURE_GATED",
            "execution_semantics": "trade_against_bid_ask_when_quotes_present",
            "supported_order_types": ["market", "limit"],
            "known_limitations": ["requires real L1 quotes; not synthesized from OHLCV"],
            "latency_model": "CONFIGURABLE",
            "fill_model": "NOT_IMPLEMENTED",
            "cost_model": "spread_when_measured",
            "capacity_assumptions": "UNMEASURED",
            "measurement_status": "UNMEASURED",
            "truth": {"never_synthesize_from_ohlcv": True},
        },
        {
            "granularity": "BOOK_L2",
            "status": "UNSUPPORTED",
            "execution_semantics": "depth_consumption",
            "supported_order_types": [],
            "known_limitations": ["requires real depth feed; never fabricate from OHLCV"],
            "latency_model": "UNMEASURED",
            "fill_model": "NOT_IMPLEMENTED",
            "cost_model": "UNMEASURED",
            "capacity_assumptions": "UNMEASURED",
            "measurement_status": "NOT_IMPLEMENTED",
            "truth": {"ohlcv_is_not_orderbook": True, "synthetic_l2_forbidden": True},
        },
        {
            "granularity": "ORDER_EVENT_L3",
            "status": "UNSUPPORTED",
            "execution_semantics": "queue_position_order_events",
            "supported_order_types": [],
            "known_limitations": ["requires L3 order-event input"],
            "latency_model": "UNMEASURED",
            "fill_model": "NOT_IMPLEMENTED",
            "cost_model": "UNMEASURED",
            "capacity_assumptions": "UNMEASURED",
            "measurement_status": "NOT_IMPLEMENTED",
            "truth": {"unsupported_without_l3_input": True},
        },
    ]
