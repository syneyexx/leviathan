"""Bar-by-bar simulation engine with strict causality."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .causality import CausalityViolation, SimulationClock
from .deliberation import DeliberationRuntime
from .fill_model import FillModel
from .metrics import compute_metrics
from .ohlcv import load_ohlcv
from .portfolio import Portfolio, RiskEngine, RiskLimits
from .store import MarketSimStore, utc_now
from .strategy_eval import evaluate_strategy
from .types import FillStatus, OrderSide, RunStatus, SimFill, SimRun


CancelCheck = Callable[[], bool]


@dataclass
class EngineState:
    run: SimRun
    clock: SimulationClock
    portfolio: Portfolio
    risk: RiskEngine
    fills: list[SimFill] = field(default_factory=list)
    agreement_samples: list[float] = field(default_factory=list)
    veto_count: int = 0
    deliberation_rounds: int = 0
    benchmark_equity: list[float] = field(default_factory=list)


class SimulationEngine:
    """Discrete event / bar-by-bar engine.

    EXTERNAL-FIRST: heavy stepping is intended to run in MarketSimWorker,
    not inline on HTTP request threads.
    """

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
    ) -> EngineState:
        bars = load_ohlcv(bars_path, start_ts=run.start_ts or None, end_ts=run.end_ts or None)
        clock = SimulationClock(bars=bars, index=run.bar_index - 1 if run.bar_index > 0 else -1)
        if run.bar_index > 0:
            clock.index = min(run.bar_index, len(bars) - 1)
        portfolio = Portfolio(cash=run.cash if run.bar_index > 0 else run.initial_cash)
        if run.bar_index > 0:
            portfolio.position_qty = run.position_qty
            portfolio.realized_pnl = run.realized_pnl
        risk = RiskEngine(
            RiskLimits(
                max_position_pct=run.max_position_pct,
                max_drawdown_pct=run.max_drawdown_pct,
                per_trade_risk_pct=run.per_trade_risk_pct,
            )
        )
        run.bar_count = len(bars)
        # Buy-and-hold benchmark shares
        first_price = bars[0].close
        bh_shares = run.initial_cash / first_price if first_price > 0 else 0.0
        state = EngineState(
            run=run,
            clock=clock,
            portfolio=portfolio,
            risk=risk,
            benchmark_equity=[],
        )
        state._bh_shares = bh_shares  # type: ignore[attr-defined]
        state._strategy_params = dict(strategy_params or {"fast_ma": 10, "slow_ma": 30})  # type: ignore[attr-defined]
        state._entry_rules = dict(entry_rules or {"kind": "ma_cross"})  # type: ignore[attr-defined]
        state._exit_rules = dict(exit_rules or {"kind": "ma_cross"})  # type: ignore[attr-defined]
        state._brain_deps = list(brain_dependencies or ["knowledge", "memory", "neuro"])  # type: ignore[attr-defined]
        return state

    def step_once(self, state: EngineState) -> bool:
        """Advance one bar. Returns False when finished."""
        run = state.run
        bar = state.clock.advance()
        if bar is None:
            return False

        run.bar_index = state.clock.index
        run.clock_ts = bar.ts

        # Benchmark mark
        bh_shares = getattr(state, "_bh_shares", 0.0)
        state.benchmark_equity.append(bh_shares * bar.close)

        fill_model = FillModel(
            fee_bps=run.fee_bps,
            slippage_bps=run.slippage_bps,
            seed=run.seed + state.clock.index,
            stochastic=bool((run.metadata or {}).get("stochastic_slippage")),
        )

        should_deliberate = (
            bool(run.agents)
            and (state.clock.index % max(1, run.deliberation_every_n) == 0)
        )

        side = OrderSide.HOLD.value
        qty: float | None = None
        rationale = "hold"
        agent_id = None

        try:
            if should_deliberate:
                result = self.deliberation.run_round(
                    run_id=run.run_id,
                    clock=state.clock,
                    agents=list(run.agents),
                    strategy_params=getattr(state, "_strategy_params"),
                    entry_rules=getattr(state, "_entry_rules"),
                    exit_rules=getattr(state, "_exit_rules"),
                    position_qty=state.portfolio.position_qty,
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
                    position_qty=state.portfolio.position_qty,
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

        equity = state.portfolio.mark_to_market(bar.close)
        if not state.risk.check_drawdown(state.portfolio, equity):
            # Flatten on kill-switch
            if state.portfolio.position_qty > 0:
                side = OrderSide.SELL.value
                qty = state.portfolio.position_qty
                rationale = state.risk.kill_reason or "drawdown kill-switch"
            else:
                side = OrderSide.HOLD.value

        decision = state.risk.size_order(
            portfolio=state.portfolio,
            price=bar.close,
            side=side,
            requested_qty=qty,
            equity=equity,
        )
        if decision.allowed and decision.sized_qty > 0 and side in {OrderSide.BUY.value, OrderSide.SELL.value}:
            before_realized = state.portfolio.realized_pnl
            fill = fill_model.execute(
                portfolio=state.portfolio,
                side=side,
                qty=decision.sized_qty,
                bar_close=bar.close,
                bar_volume=bar.volume,
            )
            if fill.filled:
                realized_delta = state.portfolio.realized_pnl - before_realized
                record = SimFill(
                    fill_id=str(uuid.uuid4()),
                    run_id=run.run_id,
                    bar_index=state.clock.index,
                    ts=bar.ts,
                    side=side,
                    qty=fill.qty,
                    price=fill.price,
                    fee=fill.fee,
                    slippage=fill.slippage,
                    agent_id=agent_id,
                    rationale=rationale,
                    status=FillStatus.FILLED.value,
                    created_at=utc_now(),
                )
                self.store.add_fill(record)
                state.fills.append(record)
                # Persist realized delta in event for metrics
                self.store.add_event(
                    run.run_id,
                    kind="fill",
                    payload={
                        **record.public_dict(),
                        "realized_delta": realized_delta,
                    },
                    bar_index=state.clock.index,
                )

        equity = state.portfolio.mark_to_market(bar.close)
        run.cash = state.portfolio.cash
        run.equity = equity
        run.position_qty = state.portfolio.position_qty
        run.realized_pnl = state.portfolio.realized_pnl
        run.unrealized_pnl = (
            state.portfolio.position_qty * (bar.close - state.portfolio.avg_entry)
            if state.portfolio.position_qty
            else 0.0
        )
        self.store.add_equity_point(
            run.run_id,
            state.clock.index,
            bar.ts,
            equity,
            state.portfolio.cash,
            state.portfolio.position_qty,
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
        equity = list(state.portfolio.equity_curve) or [run.initial_cash]
        fill_payloads = []
        for f in state.fills:
            payload = f.public_dict()
            fill_payloads.append(payload)
        # Attach realized deltas from events when available
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
        )
        if state.run.status == RunStatus.COMPLETED.value:
            state.run.finished_at = utc_now()
