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
            family=InstrumentFamily.OPTIONS.value,
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading="BLOCKED",
            data_providers=[],
            paper_brokers=[],
            notes="Options require contract rules, greeks, and E2E proof before claiming support.",
            verified_by="explicitly not implemented",
        ),
        MarketModeStatus(
            family=InstrumentFamily.FUTURES.value,
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading="BLOCKED",
            data_providers=[],
            paper_brokers=[],
            notes="Futures not implemented — no contract/margin accounting yet.",
            verified_by="explicitly not implemented",
        ),
        MarketModeStatus(
            family=InstrumentFamily.FOREX.value,
            historical_sim="NOT_IMPLEMENTED",
            live_paper="NOT_IMPLEMENTED",
            live_trading="BLOCKED",
            data_providers=[],
            paper_brokers=[],
            notes="Forex not implemented.",
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
        "truth": {
            "capability_from_adapters": True,
            "not_from_ui_presence": True,
            "profitable_backtest_is_not_proof": True,
            "ohlcv_is_not_orderbook": True,
        },
    }


def register_market_sim_module_capabilities(catalog: Any) -> None:
    """Register paper/sim mutation capabilities (MODULE provider → control plane).

    These are operator-surface mutations for research/paper only. Gateway policy
    treats ``approval_mode=receipt_only`` as auto-allowed (receipt still recorded).
    """
    from Data.modules.function_runtime.types import SideEffect
    from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind

    def _mod(
        *,
        cap_id: str,
        name: str,
        description: str,
        provider_ref: str,
        required: list[str] | None = None,
        properties: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> None:
        props = dict(properties or {})
        catalog.register(
            CapabilityDefinition(
                id=cap_id,
                name=name,
                description=description,
                side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
                provider_kind=CapabilityProviderKind.MODULE,
                provider_ref=provider_ref,
                input_schema={
                    "type": "object",
                    "required": list(required or []),
                    "properties": props,
                },
                output_schema={"type": "object"},
                required_permissions=("process.execute",),
                metadata={
                    "tags": ["market_sim", "trading", "paper"],
                    "domains": ["market_sim", "trading"],
                    "approval_mode": "receipt_only",
                    "paper_sim_only": True,
                    "idempotent": idempotent,
                },
            )
        )

    _mod(
        cap_id="market_sim.run.start",
        name="Start Market Sim Run",
        description="Start or resume a paper/historical simulation run.",
        provider_ref="run.start",
        required=["run_id"],
        properties={"run_id": {"type": "string"}},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.run.pause",
        name="Pause Market Sim Run",
        description="Pause an active simulation run.",
        provider_ref="run.pause",
        required=["run_id"],
        properties={"run_id": {"type": "string"}},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.run.step",
        name="Step Market Sim Run",
        description="Advance one bar on a simulation run.",
        provider_ref="run.step",
        required=["run_id"],
        properties={"run_id": {"type": "string"}},
    )
    _mod(
        cap_id="market_sim.run.stop",
        name="Stop Market Sim Run",
        description="Stop a simulation run.",
        provider_ref="run.stop",
        required=["run_id"],
        properties={"run_id": {"type": "string"}},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.run.create",
        name="Create Market Sim Run",
        description="Create a queued simulation run.",
        provider_ref="run.create",
        required=["source_id"],
        properties={
            "source_id": {"type": "string"},
            "strategy_id": {"type": "string"},
            "strategy_version": {"type": "integer"},
            "seed": {"type": "integer"},
            "initial_cash": {"type": "number"},
            "agents": {"type": "array"},
            "game_mode": {"type": "string"},
            "metadata": {"type": "object"},
        },
    )
    _mod(
        cap_id="market_sim.strategy.create",
        name="Create Strategy",
        description="Create a versioned strategy (legacy or DSL v2).",
        provider_ref="strategy.create",
        required=["name"],
        properties={
            "name": {"type": "string"},
            "description": {"type": "string"},
            "parameters": {"type": "object"},
            "entry_rules": {"type": "object"},
            "dsl_spec": {"type": "object"},
            "family": {"type": "string"},
            "tags": {"type": "array"},
        },
    )
    _mod(
        cap_id="market_sim.strategy.version",
        name="Version Strategy",
        description="Append an immutable strategy version.",
        provider_ref="strategy.version",
        required=["strategy_id"],
        properties={
            "strategy_id": {"type": "string"},
            "parameters": {"type": "object"},
            "dsl_spec": {"type": "object"},
            "changelog": {"type": "string"},
        },
    )
    _mod(
        cap_id="market_sim.strategy.fork",
        name="Fork Strategy",
        description="Fork a strategy into a new lineage.",
        provider_ref="strategy.fork",
        required=["strategy_id"],
        properties={"strategy_id": {"type": "string"}, "name": {"type": "string"}},
    )
    _mod(
        cap_id="market_sim.strategy.archive",
        name="Archive Strategy",
        description="Archive a strategy record.",
        provider_ref="strategy.archive",
        required=["strategy_id"],
        properties={"strategy_id": {"type": "string"}},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.strategy.validate",
        name="Validate Strategy DSL",
        description="Validate a Strategy Spec DSL v2 document.",
        provider_ref="strategy.validate",
        required=["dsl_spec"],
        properties={"dsl_spec": {"type": "object"}},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.data.scan",
        name="Scan Market Data",
        description="Scan markets_root and register sources.",
        provider_ref="data.scan",
        properties={},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.data.register",
        name="Register Market Data",
        description="Register a market data file under markets_root.",
        provider_ref="data.register",
        required=["path"],
        properties={
            "path": {"type": "string"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
        },
    )
    _mod(
        cap_id="market_sim.data.import",
        name="Import Market Dataset",
        description="Import and optionally seal a market dataset version.",
        provider_ref="data.import",
        required=["path"],
        properties={
            "path": {"type": "string"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "seal": {"type": "boolean"},
            "role": {"type": "string"},
            "provider": {"type": "string"},
        },
    )
    _mod(
        cap_id="market_sim.dataset.seal",
        name="Seal Market Dataset",
        description="Seal an immutable market dataset version.",
        provider_ref="dataset.seal",
        required=["dataset_id", "version"],
        properties={
            "dataset_id": {"type": "string"},
            "version": {"type": "string"},
            "role": {"type": "string"},
        },
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.paper.session.start",
        name="Start Paper Session",
        description="Start a live-paper trading session (no real money).",
        provider_ref="paper.session.start",
        required=["symbol"],
        properties={
            "symbol": {"type": "string"},
            "strategy_id": {"type": "string"},
            "strategy_version": {"type": "integer"},
            "broker_id": {"type": "string"},
            "provider_id": {"type": "string"},
            "initial_cash": {"type": "number"},
        },
    )
    _mod(
        cap_id="market_sim.paper.order.place",
        name="Place Paper Order",
        description="Place a paper order on an active session.",
        provider_ref="paper.order.place",
        required=["session_id", "side", "qty"],
        properties={
            "session_id": {"type": "string"},
            "side": {"type": "string"},
            "qty": {"type": "number"},
            "client_order_id": {"type": "string"},
        },
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.paper.kill_switch",
        name="Paper Kill Switch",
        description="Arm or disarm the paper session kill switch.",
        provider_ref="paper.kill_switch",
        required=["session_id"],
        properties={"session_id": {"type": "string"}, "armed": {"type": "boolean"}},
        idempotent=True,
    )
    _mod(
        cap_id="market_sim.experiment.propose",
        name="Propose Experiment",
        description="Propose a strategy research trial.",
        provider_ref="experiment.propose",
        required=["strategy_id", "hypothesis", "proposer_agent_id", "source_id"],
        properties={
            "strategy_id": {"type": "string"},
            "hypothesis": {"type": "string"},
            "proposer_agent_id": {"type": "string"},
            "source_id": {"type": "string"},
            "seed": {"type": "integer"},
            "acceptance_criteria": {"type": "object"},
            "config": {"type": "object"},
        },
    )
    _mod(
        cap_id="market_sim.experiment.complete",
        name="Complete Experiment",
        description="Complete a research trial with metrics.",
        provider_ref="experiment.complete",
        required=["trial_id", "metrics"],
        properties={
            "trial_id": {"type": "string"},
            "metrics": {"type": "object"},
            "strategy_version": {"type": "integer"},
        },
    )
    _mod(
        cap_id="market_sim.demo.run",
        name="Run Market Demo",
        description="Run a short seeded market simulation demo.",
        provider_ref="demo.run",
        properties={"family": {"type": "string"}, "bars_limit": {"type": "integer"}},
    )
