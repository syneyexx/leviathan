"""Simulation engine.

One event loop drives everything: the clock, the point-in-time gateway, the exchange
simulator, the ledger, the risk engine and the strategy runtime. Backtest and paper mode run
the *same* loop; the only difference is where events come from and how fast they arrive.

Order of operations inside one market event, which is where most backtest bugs live:

1. advance the clock to the event's availability time;
2. mark open positions and accrue funding, borrow and financing since the previous event;
3. apply corporate actions that became public at or before this instant;
4. match resting orders against this event — this is where fills happen;
5. run instrument lifecycle (expiry, delisting, maturity, liquidation);
6. ask the strategy for a decision using data up to and including this event;
7. pass every intent through the risk engine, then submit survivors with an eligibility time
   strictly after this event.

Step 4 before step 6 is deliberate: an order placed on this event cannot fill on this event.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, Sequence

from trading_lab.accounting import LedgerEntry, Portfolio, ledger_rows
from trading_lab.adapters import InstrumentAdapter, adapter_for
from trading_lab.calendars import timeframe_seconds
from trading_lab.clock import (
    DataAccessPolicy,
    DatasetBinding,
    PointInTimeGateway,
    SimulationClock,
    SimulationControl,
    earliest_order_time,
)
from trading_lab.contracts import (
    CostModel,
    DecisionRecord,
    FillEvent,
    InstrumentSpec,
    MarketEvent,
    OrderEvent,
    PortfolioSnapshot,
    RiskLimits,
    SplitName,
    StrategySpec,
    stable_hash,
    to_decimal,
    utc_iso,
)
from trading_lab.execution import ExchangeSimulator, deterministic_event_id
from trading_lab.risk import RiskContext, RiskEngine, correlation_groups_from_specs
from trading_lab.strategies import StrategyContext, StrategyRuntime

ZERO = Decimal("0")


class RunSink(Protocol):
    """Persistence hooks. The engine works without one; the service supplies a store-backed sink."""

    def on_order(self, record: dict[str, Any]) -> None: ...
    def on_order_event(self, event: OrderEvent) -> None: ...
    def on_fill(self, fill: FillEvent) -> None: ...
    def on_ledger(self, rows: Sequence[dict[str, Any]]) -> None: ...
    def on_snapshot(self, snapshot: PortfolioSnapshot) -> None: ...
    def on_checkpoint(self, event_time: str, checkpoint: dict[str, Any]) -> None: ...
    def on_decision(self, record: DecisionRecord) -> None: ...
    def on_progress(self, progress: dict[str, Any]) -> None: ...


class NullSink:
    def on_order(self, record: dict[str, Any]) -> None: ...
    def on_order_event(self, event: OrderEvent) -> None: ...
    def on_fill(self, fill: FillEvent) -> None: ...
    def on_ledger(self, rows: Sequence[dict[str, Any]]) -> None: ...
    def on_snapshot(self, snapshot: PortfolioSnapshot) -> None: ...
    def on_checkpoint(self, event_time: str, checkpoint: dict[str, Any]) -> None: ...
    def on_decision(self, record: DecisionRecord) -> None: ...
    def on_progress(self, progress: dict[str, Any]) -> None: ...


@dataclass
class EngineConfig:
    run_id: str
    strategy: StrategySpec
    bindings: dict[str, DatasetBinding]
    start: str
    end: str | None = None
    mode: str = "backtest"
    split: SplitName = "development"
    base_currency: str = "USD"
    starting_cash: Decimal = Decimal("100000")
    cost_model: CostModel = field(default_factory=CostModel)
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    seed: int = 7
    lookback: int = 300
    snapshot_every: int = 500
    decision_every: int = 1
    max_events: int = 500_000
    fx_rates: dict[str, Decimal] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)
    deferred_evaluation_events: int = 10
    engine_version: str = "trading-lab-engine-1"
    base_commit: str = ""
    parent_run_id: str | None = None
    branch_point: str | None = None

    def fingerprint(self) -> str:
        """Everything that changes results. Two runs with the same fingerprint must agree."""
        return stable_hash(
            {
                "engine": self.engine_version,
                "strategy": self.strategy.content_hash(),
                "bindings": sorted(
                    f"{binding.instrument_id}:{binding.dataset_id}:{binding.checksum}:{binding.split}"
                    for binding in self.bindings.values()
                ),
                "start": self.start,
                "end": self.end,
                "cash": str(self.starting_cash),
                "currency": self.base_currency,
                "costs": self.cost_model.as_json(),
                "risk": self.risk_limits.as_json(),
                "seed": self.seed,
                "lookback": self.lookback,
                "mode": self.mode,
            }
        )


@dataclass
class RunResult:
    run_id: str
    status: str = "completed"
    events_processed: int = 0
    decisions: int = 0
    orders_submitted: int = 0
    orders_blocked: int = 0
    fills: int = 0
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    benchmark_curve: list[tuple[str, float]] = field(default_factory=list)
    final_snapshot: PortfolioSnapshot | None = None
    reconciliation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    lookahead_violations: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    fingerprint: str = ""
    intrabar_ambiguous_fills: int = 0
    partial_fills: int = 0
    rejected_orders: int = 0
    forced_events: list[dict[str, Any]] = field(default_factory=list)
    costs: dict[str, str] = field(default_factory=dict)
    last_event_time: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "events_processed": self.events_processed,
            "decisions": self.decisions,
            "orders_submitted": self.orders_submitted,
            "orders_blocked": self.orders_blocked,
            "fills": self.fills,
            "equity_curve": [[stamp, value] for stamp, value in self.equity_curve],
            "benchmark_curve": [[stamp, value] for stamp, value in self.benchmark_curve],
            "final_snapshot": self.final_snapshot.as_json() if self.final_snapshot else None,
            "reconciliation": self.reconciliation,
            "warnings": self.warnings,
            "lookahead_violations": self.lookahead_violations,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "fingerprint": self.fingerprint,
            "intrabar_ambiguous_fills": self.intrabar_ambiguous_fills,
            "partial_fills": self.partial_fills,
            "rejected_orders": self.rejected_orders,
            "forced_events": self.forced_events,
            "costs": self.costs,
            "last_event_time": self.last_event_time,
        }


class SimulationEngine:
    def __init__(
        self,
        config: EngineConfig,
        *,
        bar_store: Any,
        registry: Any,
        event_store: Any | None = None,
        sink: RunSink | None = None,
        control: SimulationControl | None = None,
        policy: DataAccessPolicy | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.sink = sink or NullSink()
        self.control = control or SimulationControl()
        self.clock = SimulationClock(config.start, end=config.end)
        self.policy = policy or DataAccessPolicy.for_agent(config.run_id, splits=(config.split,))
        self.gateway = PointInTimeGateway(
            bar_store=bar_store,
            clock=self.clock,
            policy=self.policy,
            bindings=config.bindings,
            event_store=event_store,
        )
        self.specs: dict[str, InstrumentSpec] = {
            instrument_id: registry.get(instrument_id) for instrument_id in config.bindings
        }
        self.adapters: dict[str, InstrumentAdapter] = {
            instrument_id: adapter_for(spec) for instrument_id, spec in self.specs.items()
        }
        self.portfolio = Portfolio(
            base_currency=config.base_currency,
            starting_cash={config.base_currency: to_decimal(config.starting_cash)},
        )
        for currency, rate in (config.fx_rates or {}).items():
            self.portfolio.set_fx_rate(currency, to_decimal(rate))
        data_levels = {binding.data_level for binding in config.bindings.values()} or {"ohlcv"}
        self.exchange = ExchangeSimulator(cost_model=config.cost_model, available_data_levels=tuple(data_levels))
        self.risk = RiskEngine(config.risk_limits)
        self.runtime = StrategyRuntime(config.strategy)
        self.correlation_groups = correlation_groups_from_specs(self.specs.values())
        self.result = RunResult(run_id=config.run_id, fingerprint=config.fingerprint())
        self.primary = config.strategy.instruments[0]
        self._previous_event_time: dict[str, str] = {}
        self._applied_actions: set[str] = set()
        self._peak_equity = to_decimal(config.starting_cash)
        self._day_realized: Decimal = ZERO
        self._current_day: str = ""
        self._benchmark_base: float | None = None
        self._pending_outcomes: list[tuple[str, str, str, float]] = []
        self._decision_index = 0
        self._event_index = 0
        self._last_snapshot_at = ""
        self._last_processed: tuple[str, str] | None = None
        self._resume_after: tuple[str, str] | None = None

    # --- main loop ---------------------------------------------------------------

    def run(self, *, max_events: int | None = None) -> RunResult:
        self.result.started_at = utc_iso(datetime.now(tz=UTC))
        limit = max_events if max_events is not None else self.config.max_events
        try:
            paused_checkpoint_saved = False
            for event in self.gateway.iter_timeline(start=self.config.start, end=self.config.end):
                while not self.control.cancelled:
                    if self.control.may_process_event():
                        self.control._pace()
                        break
                    if not paused_checkpoint_saved and self.result.last_event_time:
                        self.sink.on_checkpoint(self.result.last_event_time, self.checkpoint())
                        self.sink.on_progress(self.progress())
                        paused_checkpoint_saved = True
                    time.sleep(0.05)
                else:
                    self.result.status = "cancelled"
                    break
                paused_checkpoint_saved = False
                if self._event_index >= limit:
                    self.result.status = "truncated"
                    self.result.warnings.append(f"event_limit_reached:{limit}")
                    break
                if self._already_processed(event):
                    continue
                self.process_event(event)
                self._event_index += 1
                if self.control.should_emit_frame() or self.control.paused:
                    self.sink.on_progress(self.progress())
                    if self.control.paused:
                        self.sink.on_checkpoint(event.event_time, self.checkpoint())
                        paused_checkpoint_saved = True
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a failed run
            self.result.status = "failed"
            self.result.warnings.append(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self._finalise()
        return self.result

    def _already_processed(self, event: MarketEvent) -> bool:
        """After restoring a checkpoint, skip the event that produced it and everything before."""
        if self._resume_after is None:
            return False
        key = (event.available_at, event.instrument_id)
        if key <= self._resume_after:
            return True
        self._resume_after = None
        return False

    def process_event(self, event: MarketEvent) -> None:
        config = self.config
        spec = self.specs.get(event.instrument_id)
        if spec is None:
            return
        adapter = self.adapters[event.instrument_id]
        self.clock.advance_to(event.available_at)
        self.result.events_processed += 1
        self.result.last_event_time = event.event_time
        self._last_processed = (event.available_at, event.instrument_id)
        self._roll_day(event.event_time)

        self._mark(event, spec)
        self._accrue(event, spec, adapter)
        self._corporate_actions(event, spec, adapter)
        self._execute(event, spec, adapter)
        self._lifecycle(event, spec, adapter)
        self._update_margin(event, spec, adapter)
        self._resolve_pending_outcomes(event)

        if event.instrument_id == self.primary:
            self._decide(event)
            self._sample_curves(event)
        if config.snapshot_every and self.result.events_processed % max(1, config.snapshot_every) == 0:
            self._snapshot(event.event_time)

    # --- steps -------------------------------------------------------------------

    def _mark(self, event: MarketEvent, spec: InstrumentSpec) -> None:
        try:
            price = to_decimal(event.mark_price if event.mark_price is not None else event.reference_price)
        except ValueError:
            self.result.warnings.append(f"event_without_price:{event.instrument_id}@{event.event_time}")
            return
        self.portfolio.mark(event.instrument_id, price, event.event_time)

    def _accrue(self, event: MarketEvent, spec: InstrumentSpec, adapter: InstrumentAdapter) -> None:
        position = self.portfolio.position(event.instrument_id)
        if position is None or position.is_flat:
            self._previous_event_time[event.instrument_id] = event.event_time
            return
        previous = self._previous_event_time.get(event.instrument_id)
        flows = adapter.periodic_accruals(spec, position, event, previous_event_time=previous)
        multiplier = self.config.cost_model.funding_multiplier
        for flow in flows:
            amount = flow.amount * multiplier if flow.kind == "funding" else flow.amount
            entries = self.portfolio.apply_cash_flow(
                source_event_id=deterministic_event_id(
                    self.config.run_id, event.instrument_id, event.event_time, flow.kind, flow.suffix
                ),
                event_time=event.event_time,
                currency=flow.currency,
                amount=amount,
                kind=flow.kind,
                instrument_id=event.instrument_id,
                memo=flow.memo,
            )
            self._emit_ledger(entries)
        self._previous_event_time[event.instrument_id] = event.event_time

    def _corporate_actions(self, event: MarketEvent, spec: InstrumentSpec, adapter: InstrumentAdapter) -> None:
        if spec.family not in {"equity", "etf"}:
            return
        try:
            actions = self.gateway.auxiliary_events(event.instrument_id, kind="corporate_action")
        except Exception:  # noqa: BLE001 - a missing auxiliary series is not fatal
            return
        for action in actions:
            key = f"{event.instrument_id}:{action.get('event_time')}:{action.get('kind')}"
            if key in self._applied_actions:
                continue
            available_at = str(action.get("available_at") or action.get("event_time") or "")
            if available_at > self.clock.now:
                continue
            self._applied_actions.add(key)
            payload = dict(action.get("payload") or {})
            payload.setdefault("kind", action.get("kind", "corporate_action"))
            flows = adapter.apply_corporate_action(
                spec,
                self.portfolio,
                payload,
                str(action.get("event_time") or event.event_time),
                event_id=deterministic_event_id(self.config.run_id, key),
            )
            for flow in flows:
                entries = self.portfolio.apply_cash_flow(
                    source_event_id=deterministic_event_id(self.config.run_id, key, flow.kind),
                    event_time=str(action.get("event_time") or event.event_time),
                    currency=flow.currency,
                    amount=flow.amount,
                    kind=flow.kind,
                    instrument_id=event.instrument_id,
                    memo=flow.memo,
                )
                self._emit_ledger(entries)

    def _execute(self, event: MarketEvent, spec: InstrumentSpec, adapter: InstrumentAdapter) -> None:
        positions = {
            instrument_id: position.signed_quantity
            for instrument_id, position in self.portfolio.positions.items()
        }
        outcome = self.exchange.process_event(event, position_quantities=positions)
        for order_event in outcome.order_events:
            self.sink.on_order_event(order_event)
            if order_event.kind == "rejected":
                self.result.rejected_orders += 1
        for fill in outcome.fills:
            self._book_fill(fill, spec, adapter)
        for order in outcome.touched_orders:
            self.sink.on_order(order.as_record(self.config.run_id))

    def _book_fill(self, fill: FillEvent, spec: InstrumentSpec, adapter: InstrumentAdapter) -> None:
        entries = self.portfolio.apply_fill(
            fill,
            spec,
            settlement_style=adapter.settlement_style,
            cash_notional=adapter.cash_notional(spec, fill),
            accrued_interest=adapter.accrued_interest(spec, fill),
        )
        if not entries:
            return  # already applied: replay-safe
        self.result.fills += 1
        if fill.intrabar_ambiguous:
            self.result.intrabar_ambiguous_fills += 1
        self.sink.on_fill(fill)
        self._emit_ledger(entries)

    def _lifecycle(self, event: MarketEvent, spec: InstrumentSpec, adapter: InstrumentAdapter) -> None:
        position = self.portfolio.position(event.instrument_id)
        if position is None or position.is_flat:
            return
        for action in adapter.lifecycle(spec, position, event):
            if action.kind in {"settle_expiry", "force_close_delisted", "redeem_maturity", "liquidate"}:
                quantity = action.quantity if action.quantity is not None else abs(position.signed_quantity)
                if quantity <= 0:
                    continue
                price = action.price if action.price is not None else to_decimal(event.reference_price)
                side = "sell" if position.signed_quantity > 0 else "buy"
                order, order_event, fill = self.exchange.forced_fill(
                    spec,
                    side=side,  # type: ignore[arg-type]
                    quantity=quantity,
                    price=price,
                    event_time=event.event_time,
                    reason=action.reason,
                    liquidity="liquidation" if action.kind == "liquidate" else "settlement",
                    strategy_id=self.config.strategy.strategy_id or None,
                )
                self.sink.on_order(order.as_record(self.config.run_id))
                self.sink.on_order_event(order_event)
                self._book_fill(fill, spec, adapter)
                self.result.forced_events.append(
                    {"kind": action.kind, "instrument_id": spec.instrument_id, "event_time": event.event_time, "reason": action.reason}
                )
            for flow in action.cash_flows:
                entries = self.portfolio.apply_cash_flow(
                    source_event_id=deterministic_event_id(
                        self.config.run_id, spec.instrument_id, event.event_time, action.kind, flow.kind, flow.suffix
                    ),
                    event_time=event.event_time,
                    currency=flow.currency,
                    amount=flow.amount,
                    kind=flow.kind,
                    instrument_id=spec.instrument_id,
                    memo=flow.memo or action.reason,
                )
                self._emit_ledger(entries)
            if action.kind == "liquidate":
                cancelled = self.exchange.cancel_all(
                    event.event_time, reason="liquidation", instrument_id=spec.instrument_id
                )
                for order_event in cancelled.order_events:
                    self.sink.on_order_event(order_event)

    def _update_margin(self, event: MarketEvent, spec: InstrumentSpec, adapter: InstrumentAdapter) -> None:
        position = self.portfolio.position(event.instrument_id)
        if position is None or position.is_flat:
            return
        mark = position.mark_price
        if mark is None:
            return
        self.portfolio.set_margin(event.instrument_id, adapter.margin_requirement(spec, position, mark))

    def _decide(self, event: MarketEvent) -> None:
        if self.config.decision_every > 1 and self.result.events_processed % self.config.decision_every:
            return
        observations = {}
        for instrument_id in self.config.strategy.instruments:
            if instrument_id not in self.config.bindings:
                continue
            observations[instrument_id] = self.gateway.observe(instrument_id, lookback=self.config.lookback)
        primary_observation = observations.get(self.primary)
        if primary_observation is None or not primary_observation.bars:
            return
        equity, unconverted = self.portfolio.equity()
        context = StrategyContext(
            as_of=self.clock.now,
            observations=observations,
            positions={
                instrument_id: position.signed_quantity
                for instrument_id, position in self.portfolio.positions.items()
            },
            equity=equity,
            specs=self.specs,
            auxiliary=lambda instrument_id, kind: self._auxiliary(instrument_id, kind),
            models=self.config.models,
            event_count=self.result.events_processed,
        )
        decision = self.runtime.decide(context)
        self._decision_index += 1
        self.result.decisions += 1
        eligible_from = earliest_order_time(primary_observation)
        latency = self.config.cost_model.latency_events
        if latency:
            step = timeframe_seconds(primary_observation.timeframe)
            eligible_from = utc_iso(
                datetime.fromisoformat(eligible_from) + timedelta(seconds=step * int(latency))
            )

        intents, notes = self.runtime.intents(
            decision,
            context,
            intent_prefix=f"{self.config.run_id}:{self._decision_index}",
        )
        data_status = self._data_status(primary_observation)
        record_ids: list[str] = []
        risk_decision = None
        action = "wait"
        action_reason = decision.no_trade_reason or ("blocked: " + decision.block_reason if decision.blocked else "no order needed")

        for intent in intents:
            spec = self.specs[intent.instrument_id]
            adapter = self.adapters[intent.instrument_id]
            observation = observations.get(intent.instrument_id) or primary_observation
            risk_decision = self.risk.evaluate(
                intent,
                spec=spec,
                adapter=adapter,
                portfolio=self.portfolio,
                context=RiskContext(
                    event=observation.last,
                    equity=equity,
                    peak_equity=self._peak_equity,
                    day_realized_pnl=self._day_realized,
                    open_order_count=len(self.exchange.open_orders()),
                    stale_seconds=observation.stale_seconds,
                    data_complete=not unconverted,
                    correlation_groups=self.correlation_groups,
                ),
            )
            if risk_decision.decision == "block":
                self.result.orders_blocked += 1
                action = "reject"
                action_reason = "; ".join(risk_decision.reasons)[:480]
                continue
            approved = intent.model_copy(update={"quantity": risk_decision.approved_quantity})
            outcome = self.exchange.submit(
                approved,
                spec,
                eligible_from=eligible_from,
                now=self.clock.now,
                position_quantity=self.portfolio.position(intent.instrument_id).signed_quantity
                if self.portfolio.position(intent.instrument_id)
                else ZERO,
            )
            for order_event in outcome.order_events:
                self.sink.on_order_event(order_event)
            for order in outcome.touched_orders:
                self.sink.on_order(order.as_record(self.config.run_id))
                record_ids.append(order.order_id)
            accepted = [order for order in outcome.touched_orders if order.status != "rejected"]
            if accepted:
                self.result.orders_submitted += len(accepted)
                action = "reduce" if approved.reduce_only else "execute"
                action_reason = (
                    f"submitted {len(accepted)} order(s) eligible from {eligible_from}"
                    + ("; quantity reduced by the risk engine" if risk_decision.decision == "allow_reduced" else "")
                )
            else:
                self.result.orders_blocked += 1
                action = "reject"
                action_reason = "; ".join(
                    order_event.reason for order_event in outcome.order_events if order_event.kind == "rejected"
                )[:480]

        if notes and action == "wait" and not action_reason:
            action_reason = "; ".join(notes)[:480]

        deferred_at = self._deferred_evaluation_time(primary_observation)
        record = DecisionRecord(
            decision_id=deterministic_event_id(self.config.run_id, "decision", self._decision_index),
            run_id=self.config.run_id,
            event_time=event.event_time,
            instrument_id=self.primary,
            strategy_id=self.config.strategy.strategy_id or None,
            strategy_version=self.config.strategy.version,
            model_version=str(self.config.strategy.params.get("model", "")) or None,
            data_status=data_status,
            observed={
                "as_of": self.clock.now,
                "observations": {
                    instrument_id: {
                        "bars": len(observation.bars),
                        "last_event_time": observation.bars[-1].event_time if observation.bars else None,
                        "stale_seconds": observation.stale_seconds,
                        "dataset_id": observation.dataset_id,
                        "split": observation.split,
                    }
                    for instrument_id, observation in observations.items()
                },
                "equity": str(equity),
                "notes": notes,
                "signal_notes": decision.notes,
            },
            in_scope=decision.in_scope,
            signal=decision.signal,
            signal_uncertainty=decision.uncertainty,
            cost_assessment=self._cost_assessment(primary_observation),
            action=action,  # type: ignore[arg-type]
            action_reason=action_reason[:2000],
            risk_decision=risk_decision,
            order_ids=record_ids,
            deferred_evaluation_at=deferred_at,
        )
        self.sink.on_decision(record)
        if deferred_at:
            self._pending_outcomes.append(
                (record.decision_id, deferred_at, self.primary, float(primary_observation.bars[-1].reference_price))
            )

    def _resolve_pending_outcomes(self, event: MarketEvent) -> None:
        """Attach what actually happened after a decision, once the future has arrived."""
        if not self._pending_outcomes:
            return
        remaining: list[tuple[str, str, str, float]] = []
        for decision_id, due_at, instrument_id, reference in self._pending_outcomes:
            if instrument_id != event.instrument_id or event.event_time < due_at:
                remaining.append((decision_id, due_at, instrument_id, reference))
                continue
            try:
                later = float(event.reference_price)
            except ValueError:
                continue
            change = 0.0 if reference == 0 else (later / reference) - 1.0
            outcome = {
                "resolved_at": event.event_time,
                "reference_price": reference,
                "later_price": later,
                "price_change": change,
                "note": "outcome of one decision; a single realisation is evidence about luck, not about skill",
            }
            handler = getattr(self.sink, "on_decision_outcome", None)
            if callable(handler):
                handler(decision_id, outcome)
        self._pending_outcomes = remaining

    # --- helpers -----------------------------------------------------------------

    def _auxiliary(self, instrument_id: str, kind: str) -> list[dict[str, Any]]:
        try:
            return self.gateway.auxiliary_events(instrument_id, kind=kind)
        except Exception:  # noqa: BLE001
            return []

    def _data_status(self, observation: Any) -> str:
        if not observation.bars:
            return "no_data"
        if observation.stale_seconds and observation.stale_seconds > 0:
            return f"stale:{observation.stale_seconds:.0f}s"
        if observation.truncated:
            return "complete_truncated_to_lookback"
        return "complete"

    def _cost_assessment(self, observation: Any) -> str:
        model = self.config.cost_model
        return (
            f"modelled round trip: fees {model.taker_fee_bps}bps taker / {model.maker_fee_bps}bps maker, "
            f"half spread {model.half_spread_bps}bps, slippage {model.slippage_bps}bps, "
            f"participation cap {model.max_volume_participation}. All modelled, none observed."
        )

    def _deferred_evaluation_time(self, observation: Any) -> str | None:
        if not observation.bars or self.config.deferred_evaluation_events <= 0:
            return None
        step = timeframe_seconds(observation.timeframe)
        return utc_iso(
            datetime.fromisoformat(observation.bars[-1].event_time)
            + timedelta(seconds=step * self.config.deferred_evaluation_events)
        )

    def _roll_day(self, event_time: str) -> None:
        day = event_time[:10]
        if day != self._current_day:
            self._current_day = day
            self._day_realized = ZERO

    def _emit_ledger(self, entries: Sequence[LedgerEntry]) -> None:
        if not entries:
            return
        rows = ledger_rows(entries)
        self.sink.on_ledger(rows)
        for entry in entries:
            if entry.account == "realized_pnl":
                self._day_realized += entry.amount

    def _sample_curves(self, event: MarketEvent) -> None:
        equity, unconverted = self.portfolio.equity()
        if unconverted:
            warning = f"unconverted_balances:{','.join(unconverted)}"
            if warning not in self.result.warnings:
                self.result.warnings.append(warning)
        value = float(equity)
        if equity > self._peak_equity:
            self._peak_equity = equity
        self.result.equity_curve.append((event.event_time, value))
        try:
            price = float(event.reference_price)
        except ValueError:
            return
        if self._benchmark_base is None and price > 0:
            self._benchmark_base = price
        if self._benchmark_base:
            self.result.benchmark_curve.append(
                (event.event_time, float(self.config.starting_cash) * (price / self._benchmark_base))
            )

    def _snapshot(self, as_of: str) -> None:
        snapshot = self.portfolio.snapshot(as_of)
        self._last_snapshot_at = as_of
        self.sink.on_snapshot(snapshot)
        self.sink.on_checkpoint(as_of, self.checkpoint())

    def _finalise(self) -> None:
        as_of = self.result.last_event_time or self.clock.now
        snapshot = self.portfolio.snapshot(as_of)
        self.result.final_snapshot = snapshot
        if self._last_snapshot_at != as_of:
            self.sink.on_snapshot(snapshot)
        self.sink.on_checkpoint(as_of, self.checkpoint())
        self.result.reconciliation = self.portfolio.reconcile()
        self.result.lookahead_violations = self.gateway.violations
        self.result.finished_at = utc_iso(datetime.now(tz=UTC))
        self.result.partial_fills = sum(1 for order in self.exchange.orders.values() if order.status == "partially_filled")
        self.result.costs = {
            "fees_paid": str(self.portfolio.fees_paid),
            "funding_paid": str(self.portfolio.funding_paid),
            "borrow_paid": str(self.portfolio.borrow_paid),
        }
        if self.result.status == "completed" and self.clock.is_finished():
            self.result.status = "completed"
        if not self.result.equity_curve:
            self.result.warnings.append("no_equity_samples: the primary instrument produced no events in this window")

    # --- control and checkpoints -------------------------------------------------

    def progress(self) -> dict[str, Any]:
        return {
            "run_id": self.config.run_id,
            "simulation_time": self.clock.now,
            "events_processed": self.result.events_processed,
            "decisions": self.result.decisions,
            "orders_submitted": self.result.orders_submitted,
            "orders_blocked": self.result.orders_blocked,
            "fills": self.result.fills,
            "equity": self.result.equity_curve[-1][1] if self.result.equity_curve else float(self.config.starting_cash),
            "state": "cancelled" if self.control.cancelled else ("paused" if self.control.paused else "running"),
            "mode": self.config.mode,
        }

    def checkpoint(self) -> dict[str, Any]:
        return {
            "version": 1,
            "run_id": self.config.run_id,
            "fingerprint": self.result.fingerprint,
            "clock": self.clock.snapshot(),
            "portfolio": self.portfolio.state(),
            "exchange": self.exchange.state(),
            "counters": {
                "events_processed": self.result.events_processed,
                "decisions": self.result.decisions,
                "orders_submitted": self.result.orders_submitted,
                "orders_blocked": self.result.orders_blocked,
                "fills": self.result.fills,
                "decision_index": self._decision_index,
                "event_index": self._event_index,
            },
            "peak_equity": str(self._peak_equity),
            "day_realized": str(self._day_realized),
            "current_day": self._current_day,
            "benchmark_base": self._benchmark_base,
            "previous_event_time": dict(self._previous_event_time),
            "applied_actions": sorted(self._applied_actions),
            "pending_outcomes": [list(item) for item in self._pending_outcomes],
            "equity_curve": [[stamp, value] for stamp, value in self.result.equity_curve[-5000:]],
            "benchmark_curve": [[stamp, value] for stamp, value in self.result.benchmark_curve[-5000:]],
            "last_event_time": self.result.last_event_time,
            "last_available_at": self._last_processed[0] if self._last_processed else self.result.last_event_time,
            "last_instrument_id": self._last_processed[1] if self._last_processed else "",
        }

    def restore(self, checkpoint: dict[str, Any]) -> None:
        if checkpoint.get("fingerprint") and checkpoint["fingerprint"] != self.result.fingerprint:
            raise ValueError(
                "checkpoint_fingerprint_mismatch: this checkpoint belongs to a different configuration; "
                "resuming it would silently change the run"
            )
        self.clock = SimulationClock.restore(checkpoint["clock"])
        self.gateway.clock = self.clock
        self.gateway.clear_cache()
        self.portfolio = Portfolio.restore(checkpoint["portfolio"])
        self.exchange.restore(checkpoint["exchange"], self.specs)
        counters = checkpoint.get("counters") or {}
        self.result.events_processed = int(counters.get("events_processed", 0))
        self.result.decisions = int(counters.get("decisions", 0))
        self.result.orders_submitted = int(counters.get("orders_submitted", 0))
        self.result.orders_blocked = int(counters.get("orders_blocked", 0))
        self.result.fills = int(counters.get("fills", 0))
        self._decision_index = int(counters.get("decision_index", 0))
        self._event_index = int(counters.get("event_index", 0))
        self._peak_equity = to_decimal(checkpoint.get("peak_equity", "0"))
        self._day_realized = to_decimal(checkpoint.get("day_realized", "0"))
        self._current_day = str(checkpoint.get("current_day", ""))
        self._benchmark_base = checkpoint.get("benchmark_base")
        self._previous_event_time = dict(checkpoint.get("previous_event_time") or {})
        self._applied_actions = set(checkpoint.get("applied_actions") or [])
        self._pending_outcomes = [tuple(item) for item in (checkpoint.get("pending_outcomes") or [])]  # type: ignore[misc]
        self.result.equity_curve = [(item[0], float(item[1])) for item in (checkpoint.get("equity_curve") or [])]
        self.result.benchmark_curve = [(item[0], float(item[1])) for item in (checkpoint.get("benchmark_curve") or [])]
        self.result.last_event_time = str(checkpoint.get("last_event_time", ""))
        last_available = str(checkpoint.get("last_available_at") or checkpoint.get("last_event_time") or "")
        last_instrument = str(checkpoint.get("last_instrument_id") or "")
        if last_available:
            self._last_processed = (last_available, last_instrument)
            self._resume_after = (last_available, last_instrument)

    def resume_from(self, checkpoint: dict[str, Any], *, max_events: int | None = None) -> RunResult:
        """Continue a paused, interrupted or branched run from its last processed event."""
        self.restore(checkpoint)
        resume_at = self.result.last_event_time or self.clock.now
        self.config = replace(self.config, start=resume_at)
        return self.run(max_events=max_events)


def select_checkpoint_for_rewind(
    event_time: str,
    timed_checkpoints: Sequence[tuple[str, dict[str, Any]]],
    latest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Nearest engine checkpoint at or before ``event_time``. Never mutates the parent run."""
    eligible = [
        (stamp, payload)
        for stamp, payload in timed_checkpoints
        if stamp <= event_time and payload
    ]
    if eligible:
        return max(eligible, key=lambda item: item[0])[1]
    if latest and str(latest.get("last_event_time") or "") <= event_time:
        return latest
    return None


def thin_curve(curve: Sequence[tuple[str, float]], *, max_points: int = 2000) -> list[list[Any]]:
    """Even downsample for the UI. Keeps the first and last point exactly."""
    if len(curve) <= max_points:
        return [[stamp, value] for stamp, value in curve]
    stride = max(1, len(curve) // max_points)
    thinned = [[curve[index][0], curve[index][1]] for index in range(0, len(curve), stride)]
    if thinned[-1][0] != curve[-1][0]:
        thinned.append([curve[-1][0], curve[-1][1]])
    return thinned


__all__ = [
    "EngineConfig",
    "NullSink",
    "RunResult",
    "RunSink",
    "SimulationEngine",
    "select_checkpoint_for_rewind",
    "thin_curve",
]
