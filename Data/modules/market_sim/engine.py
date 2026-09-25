"""Bar-by-bar simulation engine with strict causality and next-bar fills.

Canonical path: WalletLedger + RiskGuard + NextBarFillModel.
Legacy Portfolio / FillModel are not used in step_once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .accounting import WalletLedger, money
from .causality import CausalityViolation, SimulationClock
from .deliberation import DeliberationRuntime
from .execution import NextBarFillModel, OrderIntent, make_intent
from .instruments import infer_family, spec_for_symbol
from .metrics import compute_metrics, resolve_periods_per_year
from .ohlcv import load_ohlcv
from .portfolio import Portfolio
from .position_episodes import PositionEpisodeTracker
from .risk_guard import RiskGuard, RiskLimits
from .store import MarketSimStore, utc_now
from .strategy_eval import evaluate_strategy
from .types import (
    FillStatus,
    IntrabarPathPolicy,
    MarketSimError,
    OrderSide,
    OrderType,
    RunStatus,
    SimFill,
    SimRun,
    TimeInForce,
)

from Data.modules.common.hashing import sha256_file
from pathlib import Path


CancelCheck = Callable[[], bool]


@dataclass
class EngineState:
    run: SimRun
    clock: SimulationClock
    wallet: WalletLedger
    risk: RiskGuard
    fills: list[SimFill] = field(default_factory=list)
    pending_intents: list[OrderIntent] = field(default_factory=list)
    agreement_samples: list[float] = field(default_factory=list)
    veto_count: int = 0
    deliberation_rounds: int = 0
    benchmark_equity: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    episodes: PositionEpisodeTracker | None = None
    fill_model: NextBarFillModel | None = None
    intrabar_path_policy: str = IntrabarPathPolicy.CONSERVATIVE.value

    @property
    def portfolio(self) -> Portfolio:
        """Compatibility shim — mirrors wallet floats; mutations are not written back."""
        p = Portfolio(
            cash=float(self.wallet.cash),
            position_qty=float(self.wallet.position_qty),
            avg_entry=float(self.wallet.avg_entry),
            realized_pnl=float(self.wallet.realized_pnl),
            peak_equity=float(self.wallet.peak_equity),
        )
        p.equity_curve = list(self.equity_curve)
        return p


class SimulationEngine:
    """Discrete bar engine.

    Decision on bar T close → order eligible on bar T+1 open (no same-close fill).
    EXTERNAL-FIRST: heavy stepping runs in MarketSimWorker.
    """

    FILL_ASSUMPTIONS = NextBarFillModel.ASSUMPTIONS

    def __init__(
        self,
        store: MarketSimStore,
        *,
        deliberation: DeliberationRuntime | None = None,
    ) -> None:
        self.store = store
        self.deliberation = deliberation or DeliberationRuntime()

    def prepare(
        self,
        run: SimRun,
        *,
        bars_path: str,
        strategy_params: dict[str, Any] | None = None,
        entry_rules: dict[str, Any] | None = None,
        exit_rules: dict[str, Any] | None = None,
        brain_dependencies: list[str] | None = None,
        verify_data_hash: bool = True,
    ) -> EngineState:
        path = Path(bars_path)
        if verify_data_hash and run.data_hash:
            if not path.is_file():
                raise MarketSimError(
                    "DATA_NOT_FOUND",
                    f"Market file not found for hash verify: {bars_path}",
                    http_status=404,
                )
            file_hash = sha256_file(path)
            if file_hash != run.data_hash:
                raise MarketSimError(
                    "DATA_HASH_MISMATCH",
                    f"Run data_hash {run.data_hash[:16]}… does not match file "
                    f"{file_hash[:16]}… — refusing prepare (reproducibility)",
                    http_status=409,
                )
        bars = load_ohlcv(bars_path, start_ts=run.start_ts or None, end_ts=run.end_ts or None)
        clock = SimulationClock(bars=bars, index=run.bar_index - 1 if run.bar_index > 0 else -1)
        if run.bar_index > 0:
            clock.index = min(run.bar_index, len(bars) - 1)

        meta = dict(run.metadata or {})
        cash0 = run.cash if run.bar_index > 0 else run.initial_cash
        wallet = WalletLedger(
            wallet_id="shared",
            owner_id="shared",
            owner_kind="shared",
            cash=money(cash0),
            position_qty=money(run.position_qty if run.bar_index > 0 else 0.0),
            avg_entry=money(0),
            realized_pnl=money(run.realized_pnl if run.bar_index > 0 else 0.0),
            peak_equity=money(max(cash0, run.equity or cash0)),
        )
        risk = RiskGuard(
            RiskLimits(
                max_position_pct=run.max_position_pct,
                max_drawdown_pct=run.max_drawdown_pct,
                per_trade_risk_pct=run.per_trade_risk_pct,
            )
        )
        policy = str(
            meta.get("intrabar_path_policy")
            or meta.get("intrabarPathPolicy")
            or IntrabarPathPolicy.CONSERVATIVE.value
        )
        fill_model = NextBarFillModel(
            fee_bps=run.fee_bps,
            slippage_bps=run.slippage_bps,
            intrabar_path_policy=policy,
        )
        run.bar_count = len(bars)
        first_price = bars[0].close
        bh_shares = run.initial_cash / first_price if first_price > 0 else 0.0
        state = EngineState(
            run=run,
            clock=clock,
            wallet=wallet,
            risk=risk,
            benchmark_equity=[],
            equity_curve=[],
            episodes=PositionEpisodeTracker(
                run_id=run.run_id,
                instrument=run.symbol,
                strategy_id=run.strategy_id,
                strategy_version=run.strategy_version,
            ),
            fill_model=fill_model,
            intrabar_path_policy=policy,
        )
        state._bh_shares = bh_shares  # type: ignore[attr-defined]
        state._strategy_params = dict(strategy_params or {"fast_ma": 10, "slow_ma": 30})  # type: ignore[attr-defined]
        state._entry_rules = dict(entry_rules or {"kind": "ma_cross"})  # type: ignore[attr-defined]
        state._exit_rules = dict(exit_rules or {"kind": "ma_cross"})  # type: ignore[attr-defined]
        state._brain_deps = list(brain_dependencies or ["knowledge", "memory", "neuro"])  # type: ignore[attr-defined]
        return state

    def step_once(self, state: EngineState) -> bool:
        run = state.run
        bar = state.clock.advance()
        if bar is None:
            return False

        run.bar_index = state.clock.index
        run.clock_ts = bar.ts

        bh_shares = getattr(state, "_bh_shares", 0.0)
        state.benchmark_equity.append(bh_shares * bar.close)

        fill_model = state.fill_model or NextBarFillModel(
            fee_bps=run.fee_bps,
            slippage_bps=run.slippage_bps,
            intrabar_path_policy=state.intrabar_path_policy,
        )

        # --- Fill intents decided on prior bars (eligible at this open) ---
        still: list[OrderIntent] = []
        for intent in state.pending_intents:
            if state.clock.index < intent.eligible_bar_index:
                still.append(intent)
                continue

            decision = state.risk.evaluate_intent(
                intent, wallet=state.wallet, price=bar.open
            )
            if not decision.allowed or decision.sized_qty <= 0:
                intent.status = "rejected"
                self.store.add_event(
                    run.run_id,
                    kind="risk_reject",
                    payload={"intent": intent.public_dict(), "reason": decision.reason},
                    bar_index=state.clock.index,
                )
                continue
            if decision.sized_qty > 0:
                intent.qty = money(decision.sized_qty)

            before_realized = float(state.wallet.realized_pnl)
            fill = fill_model.execute_intent(
                wallet=state.wallet,
                intent=intent,
                fill_open=bar.open,
                bar_volume=bar.volume,
                fill_bar_index=state.clock.index,
                fill_high=bar.high,
                fill_low=bar.low,
                fill_close=bar.close,
                intrabar_path_policy=state.intrabar_path_policy,
            )
            if fill.filled:
                realized_delta = float(state.wallet.realized_pnl) - before_realized
                remaining = float(fill.remaining_qty) if fill.remaining_qty is not None else None
                trade_id = None
                if state.episodes is not None:
                    trade_id = state.episodes.current_trade_id()
                    closed = state.episodes.on_fill(
                        side=intent.side,
                        qty=float(fill.qty),
                        price=float(fill.price),
                        fee=float(fill.fee),
                        slippage=float(fill.slippage),
                        ts=bar.ts,
                        bar_index=state.clock.index,
                        status=fill.status,
                        agent_id=intent.agent_id,
                        close_reason=intent.rationale or "signal",
                        trade_id=trade_id,
                    )
                    trade_id = (
                        closed.trade_id
                        if closed is not None
                        else state.episodes.current_trade_id()
                    )
                    if closed is not None:
                        self.store.add_closed_trade(closed)
                record = SimFill(
                    fill_id=str(uuid.uuid4()),
                    run_id=run.run_id,
                    bar_index=state.clock.index,
                    ts=bar.ts,
                    side=intent.side,
                    qty=float(fill.qty),
                    price=float(fill.price),
                    fee=float(fill.fee),
                    slippage=float(fill.slippage),
                    agent_id=intent.agent_id,
                    rationale=intent.rationale,
                    status=fill.status,
                    created_at=utc_now(),
                    realized_delta=float(realized_delta),
                    remaining_qty=remaining,
                    order_type=fill.order_type or intent.order_type,
                    fill_price_source=fill.fill_price_source,
                    observed_execution=False,
                    decision_bar_index=intent.decision_bar_index,
                    intent_id=intent.intent_id,
                    trade_id=trade_id,
                )
                self.store.add_fill(record)
                state.fills.append(record)
                self.store.add_event(
                    run.run_id,
                    kind="fill",
                    payload=record.public_dict(),
                    bar_index=state.clock.index,
                )
                state.risk.orders_today += 1

            if intent.status == "working":
                still.append(intent)
            # filled / rejected / cancelled → drop from pending
        state.pending_intents = still

        should_deliberate = (
            bool(run.agents)
            and (state.clock.index % max(1, run.deliberation_every_n) == 0)
        )

        side = OrderSide.HOLD.value
        qty: float | None = None
        rationale = "hold"
        agent_id = None
        order_type = OrderType.MARKET.value
        limit_price: float | None = None
        stop_price: float | None = None
        time_in_force = TimeInForce.BAR.value

        pos_qty = float(state.wallet.position_qty)
        try:
            if should_deliberate:
                result = self.deliberation.run_round(
                    run_id=run.run_id,
                    clock=state.clock,
                    agents=list(run.agents),
                    strategy_params=getattr(state, "_strategy_params"),
                    entry_rules=getattr(state, "_entry_rules"),
                    exit_rules=getattr(state, "_exit_rules"),
                    position_qty=pos_qty,
                    brain_dependencies=getattr(state, "_brain_deps"),
                )
                for msg in result.messages:
                    self.store.add_message(msg)
                run.brain_hits += result.brain_hits
                run.brain_misses += result.brain_misses
                state.agreement_samples.append(result.agreement_rate)
                state.deliberation_rounds += 1
                if result.veto_applied:
                    state.veto_count += 1
                side = result.final_side
                qty = result.final_qty
                rationale = result.rationale
                agent_id = "allocator"
            else:
                signal = evaluate_strategy(
                    state.clock,
                    parameters=getattr(state, "_strategy_params"),
                    entry_rules=getattr(state, "_entry_rules"),
                    exit_rules=getattr(state, "_exit_rules"),
                    position_qty=pos_qty,
                )
                side = signal.side
                qty = signal.qty
                rationale = signal.rationale
                agent_id = "strategy"
        except CausalityViolation as exc:
            run.causality_violations += 1
            self.store.add_event(
                run.run_id,
                kind="causality_violation",
                payload={"error": str(exc), "bar_index": state.clock.index},
                bar_index=state.clock.index,
            )
            side = OrderSide.HOLD.value

        equity = float(state.wallet.mark(bar.close))
        if state.equity_curve and len(state.equity_curve) == state.clock.index + 1:
            state.equity_curve[-1] = equity
        else:
            state.equity_curve.append(equity)
        if not state.risk.check_drawdown(state.wallet, bar.close):
            if state.wallet.position_qty > 0:
                side = OrderSide.SELL.value
                qty = float(state.wallet.position_qty)
                rationale = state.risk.kill_reason or "drawdown kill-switch"
            else:
                side = OrderSide.HOLD.value

        # Queue intent for NEXT bar — do not fill on this bar's close
        if side in {OrderSide.BUY.value, OrderSide.SELL.value}:
            intent = make_intent(
                run_id=run.run_id,
                agent_id=agent_id or "strategy",
                wallet_id=state.wallet.wallet_id,
                side=side,
                qty=qty,
                decision_bar_index=state.clock.index,
                decision_ts=bar.ts,
                info_version=f"wallet-{state.clock.index}-{bar.ts}",
                strategy_id=run.strategy_id,
                strategy_version=run.strategy_version,
                rationale=rationale,
                decision_scope="shared",
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force,
            )
            state.pending_intents.append(intent)
            self.store.add_event(
                run.run_id,
                kind="order_intent",
                payload=intent.public_dict(),
                bar_index=state.clock.index,
            )

        equity = float(state.wallet.mark(bar.close))
        if state.equity_curve:
            state.equity_curve[-1] = equity
        else:
            state.equity_curve.append(equity)
        run.cash = float(state.wallet.cash)
        run.equity = equity
        run.position_qty = float(state.wallet.position_qty)
        run.realized_pnl = float(state.wallet.realized_pnl)
        run.unrealized_pnl = float(state.wallet.unrealized_pnl(bar.close))
        run.metadata = dict(run.metadata or {})
        run.metadata["fill_assumptions"] = list(self.FILL_ASSUMPTIONS)
        run.metadata["intrabar_path_policy"] = state.intrabar_path_policy
        run.metadata["pending_intents"] = [i.public_dict() for i in state.pending_intents]
        run.metadata["execution"] = {
            "model": "NextBarFillModel",
            "wallet": "WalletLedger",
            "risk": "RiskGuard",
            "legacy_fill_model": False,
        }
        self.store.add_equity_point(
            run.run_id,
            state.clock.index,
            bar.ts,
            equity,
            float(state.wallet.cash),
            float(state.wallet.position_qty),
        )
        return True

    def run_bars(
        self,
        state: EngineState,
        *,
        max_bars: int | None = None,
        cancel_check: CancelCheck | None = None,
        persist_every: int = 25,
    ) -> EngineState:
        processed = 0
        while True:
            if cancel_check and cancel_check():
                state.run.status = RunStatus.CANCELLED.value
                state.run.error = "cancelled"
                break
            if state.run.status == RunStatus.PAUSED.value:
                break
            if max_bars is not None and processed >= max_bars:
                break
            advanced = self.step_once(state)
            if not advanced:
                state.run.status = RunStatus.COMPLETED.value
                break
            processed += 1
            if state.run.status == RunStatus.STEPPING.value and processed >= 1:
                state.run.status = RunStatus.PAUSED.value
                break
            if processed % persist_every == 0:
                self.store.update_run(state.run)

        self._finalize_metrics(state)
        self.store.update_run(state.run)
        return state

    def _finalize_metrics(self, state: EngineState) -> None:
        run = state.run
        equity = list(state.equity_curve) or [run.initial_cash]
        fill_payloads = [f.public_dict() for f in state.fills]
        agreement = (
            sum(state.agreement_samples) / len(state.agreement_samples)
            if state.agreement_samples
            else None
        )
        veto_rate = (
            state.veto_count / state.deliberation_rounds
            if state.deliberation_rounds
            else None
        )
        family = infer_family(run.symbol, metadata=dict(run.metadata or {}))
        spec = spec_for_symbol(
            run.symbol,
            timeframe=run.timeframe,
            metadata=dict(run.metadata or {}),
        )
        bar_timestamps = [b.ts for b in state.clock.bars] if state.clock.bars else None
        annualization = resolve_periods_per_year(
            timeframe=run.timeframe,
            instrument_family=family,
            instrument_spec=spec,
            bar_timestamps=bar_timestamps,
        )
        closed_payloads = (
            [t.public_dict() for t in state.episodes.closed]
            if state.episodes is not None
            else []
        )
        run.metrics = compute_metrics(
            equity=equity,
            fills=fill_payloads,
            initial_cash=run.initial_cash,
            benchmark_equity=state.benchmark_equity or None,
            causality_violations=run.causality_violations,
            brain_hits=run.brain_hits,
            brain_misses=run.brain_misses,
            agreement_rate=agreement,
            veto_rate=veto_rate,
            periods_per_year=None,
            annualization=annualization,
            closed_trades=closed_payloads,
            timeframe=run.timeframe,
            instrument_family=family.value,
            instrument_spec=spec,
            bar_timestamps=bar_timestamps,
        )
        run.metrics["fill_assumptions"] = list(self.FILL_ASSUMPTIONS)
        run.metrics["intrabar_path_policy"] = state.intrabar_path_policy
        if state.run.status == RunStatus.COMPLETED.value:
            state.run.finished_at = utc_now()
