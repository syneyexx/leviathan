"""Multi-agent causal engine: per-agent wallets + commit-then-reveal + next-bar fills."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.hashing import sha256_file

from .accounting import WalletBook, money
from .causality import CausalityViolation, MarketView, SimulationClock
from .commit_reveal import CommitRevealProtocol
from .execution import NextBarFillModel, OrderIntent
from .experiments import StrategyMemoryIndex, market_features_from_closes
from .instruments import infer_family, spec_for_symbol
from .market_state import build_market_state
from .metrics import compute_metrics, resolve_periods_per_year
from .ohlcv import load_ohlcv
from .position_episodes import PositionEpisodeTracker
from .risk_guard import RiskGuard, RiskLimits
from .store import MarketSimStore, utc_now
from .strategy_eval import evaluate_strategy
from .types import FillStatus, MarketSimError, OrderSide, OrderType, RunStatus, SimFill


CancelCheck = Callable[[], bool]

# Game modes — same engine, different book ownership
GAME_INDIVIDUAL = "individual_competition"
GAME_SHARED = "shared_portfolio"
GAME_TOURNAMENT = "research_tournament"


@dataclass
class MultiEngineState:
    run: Any
    clock: SimulationClock
    book: WalletBook
    risk: RiskGuard
    protocol: CommitRevealProtocol
    pending_intents: list[OrderIntent] = field(default_factory=list)
    fills: list[SimFill] = field(default_factory=list)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    agreement_samples: list[float] = field(default_factory=list)
    veto_count: int = 0
    deliberation_rounds: int = 0
    benchmark_equity: list[float] = field(default_factory=list)
    memory: StrategyMemoryIndex = field(default_factory=StrategyMemoryIndex)
    game_mode: str = GAME_INDIVIDUAL
    episodes_by_wallet: dict[str, PositionEpisodeTracker] = field(default_factory=dict)


class MultiAgentEngine:
    """Agents trade on one causal clock with isolated wallets (or shared book)."""

    FILL_ASSUMPTIONS = NextBarFillModel.ASSUMPTIONS

    def __init__(self, store: MarketSimStore) -> None:
        self.store = store

    def prepare(
        self,
        run: Any,
        *,
        bars_path: str,
        strategy_params: dict[str, Any] | None = None,
        entry_rules: dict[str, Any] | None = None,
        exit_rules: dict[str, Any] | None = None,
        brain_dependencies: list[str] | None = None,
        verify_data_hash: bool = True,
    ) -> MultiEngineState:
        path = Path(bars_path)
        if verify_data_hash and getattr(run, "data_hash", None):
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
        clock = SimulationClock(bars=bars, index=-1)
        if run.bar_index > 0:
            clock.index = min(run.bar_index - 1, len(bars) - 1)

        meta = dict(run.metadata or {})
        game_mode = str(meta.get("game_mode") or GAME_INDIVIDUAL)
        currency = str(meta.get("quote_currency") or "USD")
        agent_cash = float(meta.get("agent_initial_cash") or run.initial_cash)

        book = WalletBook()
        agents = list(run.agents or [])
        trading_agents = [
            a for a in agents
            if (a.get("authority") or {}).get("may_order", True)
            and str(a.get("role")) not in {"trading_orchestrator", "evaluator", "risk_agent", "risk_officer", "critic"}
        ]
        # If roles not annotated, treat non-orch non-risk as traders
        if not trading_agents:
            trading_agents = [
                a for a in agents
                if str(a.get("role")) not in {
                    "trading_orchestrator", "evaluator", "risk_agent", "risk_officer", "critic", "orchestrator"
                }
            ]

        if game_mode == GAME_SHARED:
            book.ensure_shared(initial_cash=run.initial_cash, currency=currency)
        else:
            for a in trading_agents:
                aid = str(a.get("agent_id") or a.get("role"))
                cash = float(a.get("initial_cash") if a.get("initial_cash") is not None else agent_cash)
                book.ensure_agent(aid, initial_cash=cash, currency=currency)
            # Shared book optional for tournament leaderboard baseline
            if game_mode == GAME_TOURNAMENT:
                book.ensure_shared(initial_cash=run.initial_cash, currency=currency)

        risk = RiskGuard(
            RiskLimits(
                max_position_pct=run.max_position_pct,
                max_drawdown_pct=run.max_drawdown_pct,
                per_trade_risk_pct=run.per_trade_risk_pct,
                max_orders_per_day=int(meta.get("max_orders_per_day") or 50),
                leverage_allowed=False,
            )
        )
        run.bar_count = len(bars)
        first_price = bars[0].close if bars else 1.0
        bh_shares = run.initial_cash / first_price if first_price > 0 else 0.0

        state = MultiEngineState(
            run=run,
            clock=clock,
            book=book,
            risk=risk,
            protocol=CommitRevealProtocol(
                allow_pre_commit_discussion=bool(meta.get("allow_pre_commit_discussion", True))
            ),
            game_mode=game_mode,
        )
        state._bh_shares = bh_shares  # type: ignore[attr-defined]
        state._strategy_params = dict(strategy_params or {"fast_ma": 10, "slow_ma": 30})  # type: ignore[attr-defined]
        state._entry_rules = dict(entry_rules or {"kind": "ma_cross"})  # type: ignore[attr-defined]
        state._exit_rules = dict(exit_rules or {"kind": "ma_cross"})  # type: ignore[attr-defined]
        state._brain_deps = list(brain_dependencies or [])  # type: ignore[attr-defined]
        state._trading_agents = trading_agents  # type: ignore[attr-defined]
        state._all_agents = agents  # type: ignore[attr-defined]
        return state

    def step_once(self, state: MultiEngineState) -> bool:
        run = state.run
        # 1) Reveal + fill intents that became eligible (previous decisions → this bar open)
        bar = state.clock.advance()
        if bar is None:
            return False

        run.bar_index = state.clock.index
        run.clock_ts = bar.ts
        bh = getattr(state, "_bh_shares", 0.0)
        state.benchmark_equity.append(bh * bar.close)

        fill_model = NextBarFillModel(fee_bps=run.fee_bps, slippage_bps=run.slippage_bps)
        still_pending: list[OrderIntent] = []
        for intent in state.pending_intents:
            if state.clock.index < intent.eligible_bar_index:
                still_pending.append(intent)
                continue
            wallet = state.book.get(intent.wallet_id)
            # Risk re-check at fill time
            decision = state.risk.evaluate_intent(intent, wallet=wallet, price=bar.open)
            if not decision.allowed:
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
            before_realized = float(wallet.realized_pnl)
            fill = fill_model.execute_intent(
                wallet=wallet,
                intent=intent,
                fill_open=bar.open,
                bar_volume=bar.volume,
                fill_bar_index=state.clock.index,
            )
            if fill.filled:
                realized_delta = float(wallet.realized_pnl) - before_realized
                remaining = None
                if intent.qty is not None:
                    try:
                        rem = float(intent.qty) - float(fill.qty)
                        remaining = rem if rem > 1e-12 else 0.0
                    except (TypeError, ValueError):
                        remaining = None
                tracker = state.episodes_by_wallet.get(intent.wallet_id)
                if tracker is None:
                    tracker = PositionEpisodeTracker(
                        run_id=run.run_id,
                        instrument=run.symbol,
                        strategy_id=getattr(run, "strategy_id", None),
                        strategy_version=getattr(run, "strategy_version", None),
                    )
                    state.episodes_by_wallet[intent.wallet_id] = tracker
                trade_id = tracker.current_trade_id()
                closed = tracker.on_fill(
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
                trade_id = closed.trade_id if closed is not None else tracker.current_trade_id()
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
                    order_type=OrderType.MARKET.value,
                    fill_price_source="next_bar_open",
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
                    payload={
                        **record.public_dict(),
                        "wallet_id": intent.wallet_id,
                        "eligible_bar_index": intent.eligible_bar_index,
                        "info_version": intent.info_version,
                    },
                    bar_index=state.clock.index,
                )
                state.risk.orders_today += 1
        state.pending_intents = still_pending

        # 2) Kill-switch / drawdown on each trading wallet
        for wallet in list(state.book.wallets.values()):
            if wallet.owner_kind not in {"agent", "shared"}:
                continue
            if not state.risk.check_drawdown(wallet, bar.close):
                if wallet.position_qty > 0:
                    flatten = OrderIntent(
                        intent_id=str(uuid.uuid4()),
                        run_id=run.run_id,
                        agent_id=wallet.owner_id,
                        wallet_id=wallet.wallet_id,
                        side=OrderSide.SELL.value,
                        qty=wallet.position_qty,
                        decision_bar_index=state.clock.index,
                        decision_ts=bar.ts,
                        eligible_bar_index=state.clock.index + 1,
                        rationale=state.risk.kill_reason or "drawdown kill-switch",
                        decision_scope="individual" if wallet.owner_kind == "agent" else "shared",
                        info_version="kill-switch",
                    )
                    state.pending_intents.append(flatten)

        # 3) Commit-reveal decision round (every N bars)
        should_decide = (
            bool(getattr(state, "_trading_agents", None))
            and (state.clock.index % max(1, run.deliberation_every_n) == 0)
        )
        if should_decide:
            try:
                self._commit_round(state)
            except CausalityViolation as exc:
                run.causality_violations += 1
                self.store.add_event(
                    run.run_id,
                    kind="causality_violation",
                    payload={"error": str(exc), "bar_index": state.clock.index},
                    bar_index=state.clock.index,
                )

        # 4) Aggregate run-level portfolio view (shared or sum of agents — labeled)
        self._sync_run_portfolio(state, price=bar.close)
        self.store.add_equity_point(
            run.run_id,
            state.clock.index,
            bar.ts,
            run.equity,
            run.cash,
            run.position_qty,
        )
        # Persist wallet snapshot periodically via event
        if state.clock.index % 10 == 0:
            self.store.add_event(
                run.run_id,
                kind="wallet_snapshot",
                payload=state.book.public_dict(bar.close),
                bar_index=state.clock.index,
            )
        return True

    def _commit_round(self, state: MultiEngineState) -> None:
        run = state.run
        bar = state.clock.current_bar
        assert bar is not None
        now = utc_now()
        trading_agents = list(getattr(state, "_trading_agents"))
        # Annotate run_id for protocol
        agents_payload = []
        for a in trading_agents:
            row = dict(a)
            row["run_id"] = run.run_id
            # Per-agent entry rules if provided
            agents_payload.append(row)

        wallets_map = {}
        positions = {}
        for a in trading_agents:
            aid = str(a.get("agent_id") or a.get("role"))
            if state.game_mode == GAME_SHARED:
                w = state.book.wallets[state.book.shared_wallet_id]  # type: ignore[index]
                wallets_map[aid] = w.wallet_id
                positions[aid] = float(w.position_qty)
            else:
                w = state.book.for_owner(aid)
                if w is None:
                    continue
                wallets_map[aid] = w.wallet_id
                positions[aid] = float(w.position_qty)

        features = market_features_from_closes(state.clock.closes(min(64, state.clock.index + 1)))
        market_view = MarketView(
            clock=state.clock,
            instrument=str(run.symbol or ""),
            timeframe=str(run.timeframe or ""),
        )
        market_state = None
        try:
            market_state = build_market_state(
                market_view,
                venue=str((run.metadata or {}).get("venue") or ""),
                asset_class=str((run.metadata or {}).get("instrument_family") or ""),
                portfolio={
                    "cash": float(run.cash),
                    "equity": float(run.equity),
                    "positions": positions,
                },
                lookback=min(120, state.clock.index + 1),
            )
            # Prefer deterministic MarketState summary for memory / regime matching.
            features = {**features, **market_state.summary_features()}
        except Exception:  # noqa: BLE001 — never break the bar loop on feature warm-up
            market_state = None

        def memory_lookup(agent_id: str, role: str, ts: str) -> list[dict[str, Any]]:
            hits = state.memory.search(as_of_ts=ts, features=features, limit=3)
            return [h.public_dict() for h in hits]

        # Optional pre-commit discussion message from orchestrator
        orch = next(
            (a for a in getattr(state, "_all_agents", []) if str(a.get("role")) == "trading_orchestrator"),
            None,
        )
        if orch and state.protocol.allow_pre_commit_discussion:
            state.protocol.begin_round(
                run_id=run.run_id,
                bar_index=state.clock.index,
                clock_ts=bar.ts,
                closes=state.clock.closes(min(64, state.clock.index + 1)),
                now=now,
            )
            state.protocol.add_discussion(
                {
                    "agent_id": orch.get("agent_id"),
                    "kind": "hypothesis",
                    "content": f"Round at {bar.ts}; features={features}",
                    "ts": now,
                    "phase": "before_deadline",
                },
                before_deadline=True,
            )
            # Reset so collect can begin properly — begin_round already called
            # Actually collect_agent_commits also begin_round; close orphan
            state.protocol._open = None  # noqa: SLF001

        entry = getattr(state, "_entry_rules")
        exit_ = getattr(state, "_exit_rules")
        params = getattr(state, "_strategy_params")

        # Agents may have personal entry/exit overrides
        messages = []
        rnd = None
        # Manual per-agent commit to allow different entry rules
        closes = state.clock.closes(min(500, state.clock.index + 1))
        rnd = state.protocol.begin_round(
            run_id=run.run_id,
            bar_index=state.clock.index,
            clock_ts=bar.ts,
            closes=closes,
            now=now,
        )
        for agent in agents_payload:
            aid = str(agent.get("agent_id") or agent.get("role"))
            if aid not in wallets_map:
                continue
            role = str(agent.get("role") or "trend")
            a_params = dict(params)
            a_params.update(dict(agent.get("parameters") or {}))
            a_entry = dict(agent.get("entry_rules") or entry)
            a_exit = dict(agent.get("exit_rules") or exit_)
            role_bias = "mean_reversion" if "mean" in role or a_entry.get("kind") == "mean_reversion" else "trend"
            if a_entry.get("kind") == "mean_reversion":
                role_bias = "mean_reversion"
            memories = memory_lookup(aid, role, bar.ts)
            signal = evaluate_strategy(
                state.clock,
                parameters=a_params,
                entry_rules=a_entry,
                exit_rules=a_exit,
                position_qty=positions.get(aid, 0.0),
                role_bias=role_bias,
            )
            decision = state.protocol.commit_decision(
                agent_id=aid,
                role=role,
                side=signal.side,
                qty=signal.qty,
                wallet_id=wallets_map[aid],
                sealed_at=now,
                rationale=signal.rationale,
                confidence=signal.confidence,
                strategy_id=run.strategy_id,
                strategy_version=run.strategy_version,
                decision_scope="shared" if state.game_mode == GAME_SHARED else "individual",
                retrieved_memories=memories,
                metadata={
                    "features": features,
                    "parameters_used": signal.parameters_used,
                    "market_state_as_of": market_state.as_of if market_state else None,
                    "regime": (market_state.regime if market_state else None),
                },
            )
            decision.intent.run_id = run.run_id
            from .types import DeliberationMessage

            msg = DeliberationMessage(
                message_id=str(uuid.uuid4()),
                run_id=run.run_id,
                bar_index=state.clock.index,
                ts=bar.ts,
                agent_id=aid,
                role=role,
                kind="commit",
                content=signal.rationale,
                proposal=decision.intent.public_dict(),
                confidence=signal.confidence,
                brain_refs=memories,
                created_at=now,
            )
            messages.append(msg)
            self.store.add_message(msg)

        # Risk agent soft-veto: convert BUY commits to HOLD if flagged (binding on shared; advisory label on individual)
        risk_agents = [
            a for a in getattr(state, "_all_agents", [])
            if str(a.get("role")) in {"risk_agent", "risk_officer", "critic"}
        ]
        veto_applied = False
        for ra in risk_agents:
            for d in list(state.protocol.open_round.decisions.values()):  # type: ignore[union-attr]
                if d.intent.side == OrderSide.BUY.value and d.intent.confidence < 0.55:
                    d.intent.side = OrderSide.HOLD.value
                    d.rationale = f"risk veto by {ra.get('agent_id')}: {d.rationale}"
                    veto_applied = True
                    from .types import DeliberationMessage as _DM

                    self.store.add_message(
                        _DM(
                            message_id=str(uuid.uuid4()),
                            run_id=run.run_id,
                            bar_index=state.clock.index,
                            ts=bar.ts,
                            agent_id=str(ra.get("agent_id")),
                            role=str(ra.get("role")),
                            kind="veto",
                            content=d.rationale,
                            proposal=d.intent.public_dict(),
                            confidence=1.0,
                            created_at=now,
                        )
                    )
        if veto_applied:
            state.veto_count += 1

        state.protocol.seal(sealed_at=now)
        # Decisions stay sealed until next bar; queue intents now (eligible = bar+1)
        revealed = state.protocol.reveal(revealed_at=now)
        for d in revealed:
            if d.intent.side in {OrderSide.BUY.value, OrderSide.SELL.value}:
                # Risk size at decision time (final size at fill)
                wallet = state.book.get(d.intent.wallet_id)
                rd = state.risk.evaluate_intent(d.intent, wallet=wallet, price=bar.close)
                if not rd.allowed:
                    d.intent.status = "rejected"
                    self.store.add_event(
                        run.run_id,
                        kind="risk_reject",
                        payload={"intent": d.intent.public_dict(), "reason": rd.reason},
                        bar_index=state.clock.index,
                    )
                    continue
                if rd.sized_qty > 0:
                    d.intent.qty = money(rd.sized_qty)
                state.pending_intents.append(d.intent)
                self.store.add_event(
                    run.run_id,
                    kind="order_intent",
                    payload=d.intent.public_dict(),
                    bar_index=state.clock.index,
                )

        state.rounds.append(state.protocol.open_round.public_dict() if state.protocol.open_round else {})
        state.protocol.close()
        state.deliberation_rounds += 1
        # Agreement: fraction of non-HOLD agreeing on side
        sides = [d.intent.side for d in revealed if d.intent.side != OrderSide.HOLD.value]
        if sides:
            majority = max(sides, key=sides.count)
            state.agreement_samples.append(sides.count(majority) / len(sides))

        self.store.add_event(
            run.run_id,
            kind="commit_reveal_round",
            payload={
                "bar_index": state.clock.index,
                "features": features,
                "market_state": market_state.public_dict() if market_state else None,
                "decision_count": len(revealed),
                "pending_intents": len(state.pending_intents),
            },
            bar_index=state.clock.index,
        )

    def _sync_run_portfolio(self, state: MultiEngineState, *, price: float) -> None:
        run = state.run
        if state.game_mode == GAME_SHARED and state.book.shared_wallet_id:
            w = state.book.get(state.book.shared_wallet_id)
            run.cash = float(w.cash)
            run.equity = float(w.equity(price))
            run.position_qty = float(w.position_qty)
            run.realized_pnl = float(w.realized_pnl)
            run.unrealized_pnl = float(w.unrealized_pnl(price))
        else:
            # Aggregate labeled sum for UI — not a merged wallet
            cash = money(0)
            equity = money(0)
            pos = money(0)
            realized = money(0)
            for w in state.book.wallets.values():
                if w.owner_kind != "agent":
                    continue
                cash += w.cash
                equity += w.equity(price)
                pos += w.position_qty
                realized += w.realized_pnl
            run.cash = float(cash)
            run.equity = float(equity)
            run.position_qty = float(pos)
            run.realized_pnl = float(realized)
            run.unrealized_pnl = float(equity - cash - realized) if False else float(
                sum(float(w.unrealized_pnl(price)) for w in state.book.wallets.values() if w.owner_kind == "agent")
            )
        run.metadata = dict(run.metadata or {})
        run.metadata["wallets"] = state.book.public_dict(price)
        run.metadata["game_mode"] = state.game_mode
        run.metadata["fill_assumptions"] = list(self.FILL_ASSUMPTIONS)
        run.metadata["pending_intents"] = [i.public_dict() for i in state.pending_intents]

    def run_bars(
        self,
        state: MultiEngineState,
        *,
        max_bars: int | None = None,
        cancel_check: CancelCheck | None = None,
        persist_every: int = 25,
    ) -> MultiEngineState:
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
            if not self.step_once(state):
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

    def _finalize_metrics(self, state: MultiEngineState) -> None:
        run = state.run
        equity_curve = []
        # Rebuild from store equity points if needed
        points = self.store.list_equity(run.run_id, limit=100_000)
        if points:
            equity_curve = [float(p["equity"]) for p in points]
        else:
            equity_curve = [run.initial_cash, run.equity]
        agreement = (
            sum(state.agreement_samples) / len(state.agreement_samples)
            if state.agreement_samples
            else None
        )
        veto_rate = (
            state.veto_count / state.deliberation_rounds if state.deliberation_rounds else None
        )
        # Baseline capital must match the equity curve denomination.
        # Individual competition: sum of agent starting cash (not run.initial_cash * N).
        if state.game_mode == GAME_SHARED:
            initial_for_metrics = float(run.initial_cash)
        else:
            configured = 0.0
            non_traders = {
                "trading_orchestrator",
                "evaluator",
                "risk_agent",
                "risk_officer",
                "critic",
                "orchestrator",
            }
            for a in run.agents or []:
                if str(a.get("role") or "") in non_traders:
                    continue
                if (a.get("authority") or {}).get("may_order", True) is False:
                    continue
                if a.get("initial_cash") is not None:
                    configured += float(a["initial_cash"])
            if configured > 0:
                initial_for_metrics = configured
            elif equity_curve:
                initial_for_metrics = float(equity_curve[0])
            else:
                initial_for_metrics = float(run.initial_cash)
        family = infer_family(
            getattr(run, "symbol", ""),
            metadata=dict(getattr(run, "metadata", None) or {}),
        )
        spec = spec_for_symbol(
            getattr(run, "symbol", "UNKNOWN"),
            timeframe=getattr(run, "timeframe", "1D") or "1D",
            metadata=dict(getattr(run, "metadata", None) or {}),
        )
        bar_timestamps = [b.ts for b in state.clock.bars] if state.clock.bars else None
        annualization = resolve_periods_per_year(
            timeframe=getattr(run, "timeframe", None),
            instrument_family=family,
            instrument_spec=spec,
            bar_timestamps=bar_timestamps,
        )
        closed_payloads: list[dict[str, Any]] = []
        for tracker in state.episodes_by_wallet.values():
            closed_payloads.extend(t.public_dict() for t in tracker.closed)
        run.metrics = compute_metrics(
            equity=equity_curve,
            fills=[f.public_dict() for f in state.fills],
            initial_cash=initial_for_metrics,
            benchmark_equity=state.benchmark_equity or None,
            causality_violations=run.causality_violations,
            brain_hits=run.brain_hits,
            brain_misses=run.brain_misses,
            agreement_rate=agreement,
            veto_rate=veto_rate,
            periods_per_year=None,
            annualization=annualization,
            closed_trades=closed_payloads,
            timeframe=getattr(run, "timeframe", None),
            instrument_family=family.value,
            instrument_spec=spec,
            bar_timestamps=bar_timestamps,
        )
        run.metrics["game_mode"] = state.game_mode
        run.metrics["wallets"] = state.book.public_dict(
            state.clock.current_bar.close if state.clock.current_bar else run.equity
        )
        run.metrics["fill_assumptions"] = list(self.FILL_ASSUMPTIONS)
        run.metrics["leaderboard"] = self._leaderboard(state)
        if state.run.status == RunStatus.COMPLETED.value:
            state.run.finished_at = utc_now()

    def _leaderboard(self, state: MultiEngineState) -> list[dict[str, Any]]:
        price = state.clock.current_bar.close if state.clock.current_bar else 0.0
        rows = []
        for w in state.book.wallets.values():
            if w.owner_kind != "agent":
                continue
            rows.append(
                {
                    "agent_id": w.owner_id,
                    "equity": float(w.equity(price)),
                    "realized_pnl": float(w.realized_pnl),
                    "fees_paid": float(w.fees_paid),
                    "trades": len(w.transactions),
                    "initial_comparable": True,
                }
            )
        rows.sort(key=lambda r: -r["equity"])
        return rows
