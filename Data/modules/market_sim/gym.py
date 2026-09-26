"""TradingGym — causal reset/step environment over SimulationEngine (P1B).

Observations are always via ``MarketView`` (no future bars). Complete episodes
are EXTERNAL_REQUIRED and must execute on the market_sim worker; FastAPI may
only create/queue/step interactively (STEPPING) or report
``TRADING_WORKER_UNAVAILABLE``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .causality import MarketView
from .engine import EngineState, SimulationEngine
from .execution import OrderIntent, make_intent
from .ohlcv import iter_ohlcv, load_ohlcv
from .reward import RewardDefinition, RewardSpec, compute_step_reward
from .split_manifest import SplitRole
from .store import MarketSimStore, utc_now
from .trajectory import TrajectoryBuilder
from .types import (
    MarketSimError,
    OrderSide,
    OrderType,
    RunStatus,
    SimRun,
    TimeInForce,
)


class GymActionKind:
    HOLD = "HOLD"
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"


@dataclass
class GymAction:
    kind: str = GymActionKind.HOLD
    qty: float | None = None  # None → RiskGuard sizing
    order_type: str = OrderType.MARKET.value
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = TimeInForce.BAR.value
    rationale: str = "gym_action"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "GymAction":
        raw = dict(raw or {})
        kind = str(raw.get("kind") or raw.get("action") or GymActionKind.HOLD).upper()
        if kind in {"FLAT", "EXIT"}:
            kind = GymActionKind.CLOSE
        return cls(
            kind=kind,
            qty=float(raw["qty"]) if raw.get("qty") is not None else None,
            order_type=str(raw.get("order_type") or raw.get("orderType") or OrderType.MARKET.value),
            limit_price=float(raw["limit_price"]) if raw.get("limit_price") is not None else (
                float(raw["limitPrice"]) if raw.get("limitPrice") is not None else None
            ),
            stop_price=float(raw["stop_price"]) if raw.get("stop_price") is not None else (
                float(raw["stopPrice"]) if raw.get("stopPrice") is not None else None
            ),
            time_in_force=str(
                raw.get("time_in_force") or raw.get("timeInForce") or TimeInForce.BAR.value
            ),
            rationale=str(raw.get("rationale") or "gym_action"),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "qty": self.qty,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "rationale": self.rationale,
        }


OBSERVATION_SPEC_V1 = 1
ACTION_SPEC_V1 = 1


@dataclass
class GymObservation:
    bar_index: int
    ts: str | None
    visible_bar_count: int
    last_bar: dict[str, Any] | None
    cash: float
    equity: float
    position_qty: float
    realized_pnl: float
    split_role: str
    done: bool
    truth: dict[str, Any] = field(default_factory=dict)
    # ObservationSpec v1 extensions (causal only)
    symbol: str = ""
    timeframe: str = ""
    causal_as_of: str | None = None
    unrealized_pnl: float | None = None
    drawdown_context: dict[str, Any] = field(default_factory=dict)
    position_avg_entry: float | None = None
    bars_held: int = 0
    regime_state: dict[str, Any] = field(default_factory=dict)
    transaction_cost_state: dict[str, Any] = field(default_factory=dict)
    feature_snapshot: dict[str, Any] = field(default_factory=dict)
    feature_statuses: dict[str, str] = field(default_factory=dict)
    dataset_fingerprint: str = ""
    strategy_identity: dict[str, Any] = field(default_factory=dict)
    environment_version: str = "market_sim.gym.v1"
    observation_spec_version: int = OBSERVATION_SPEC_V1

    def public_dict(self) -> dict[str, Any]:
        return {
            "observation_spec_version": self.observation_spec_version,
            "bar_index": self.bar_index,
            "timestamp": self.ts,
            "ts": self.ts,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "causal_as_of": self.causal_as_of or self.ts,
            "visible_bar_count": self.visible_bar_count,
            "current_ohlcv": self.last_bar,
            "last_bar": self.last_bar,
            "feature_snapshot": dict(self.feature_snapshot),
            "feature_statuses": dict(self.feature_statuses),
            "position": self.position_qty,
            "position_qty": self.position_qty,
            "cash": self.cash,
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "drawdown_context": dict(self.drawdown_context),
            "position_avg_entry": self.position_avg_entry,
            "bars_held": self.bars_held,
            "regime_state": dict(self.regime_state),
            "transaction_cost_state": dict(self.transaction_cost_state),
            "split_role": self.split_role,
            "dataset_fingerprint": self.dataset_fingerprint,
            "strategy_identity": dict(self.strategy_identity),
            "environment_version": self.environment_version,
            "done": self.done,
            "truth": {
                "via_market_view": True,
                "no_future_bars": True,
                "observation_spec_version": self.observation_spec_version,
                **dict(self.truth or {}),
            },
        }


@dataclass
class GymStepResult:
    observation: GymObservation
    reward: dict[str, Any]
    done: bool
    info: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.public_dict(),
            "reward": self.reward,
            "done": self.done,
            "info": self.info,
        }


def _bar_public(bar: Any) -> dict[str, Any]:
    return {
        "ts": bar.ts,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


class TradingGym:
    """Causal single-agent gym over the canonical SimulationEngine."""

    def __init__(
        self,
        store: MarketSimStore,
        engine: SimulationEngine | None = None,
    ) -> None:
        self.store = store
        self.engine = engine or SimulationEngine(store)
        self._state: EngineState | None = None
        self._split_role: str = SplitRole.TRAIN
        self._prev_equity: float | None = None
        self._prev_realized: float | None = None
        self._reward_spec: RewardSpec = RewardSpec()
        self._trajectory: TrajectoryBuilder | None = None
        self._policy_context: dict[str, Any] = {}
        self._bars_held: int = 0
        self._peak_equity: float | None = None

    @property
    def state(self) -> EngineState | None:
        return self._state

    def bind_policy_context(self, **kwargs: Any) -> None:
        """Attach ObservationSpec identity fields for subsequent observations."""
        self._policy_context.update(kwargs)

    def reset(
        self,
        run: SimRun,
        *,
        bars_path: str,
        split_role: str = SplitRole.TRAIN,
        start_ts: str | None = None,
        end_ts: str | None = None,
        strategy_params: dict[str, Any] | None = None,
        entry_rules: dict[str, Any] | None = None,
        exit_rules: dict[str, Any] | None = None,
        reward_spec: RewardSpec | dict[str, Any] | None = None,
    ) -> GymObservation:
        """Reset environment. Window may come from DatasetSplitManifest bounds."""
        self._split_role = str(split_role or SplitRole.TRAIN).upper()
        self._reward_spec = (
            reward_spec
            if isinstance(reward_spec, RewardSpec)
            else RewardSpec.from_dict(reward_spec)
        )
        # Apply window onto run for prepare/load
        if start_ts:
            run.start_ts = start_ts
        if end_ts:
            run.end_ts = end_ts
        meta = dict(run.metadata or {})
        meta["gym"] = True
        meta["split_role"] = self._split_role
        meta["gym_reset_at"] = utc_now()
        meta["reward_spec"] = self._reward_spec.public_dict()
        run.metadata = meta
        run.bar_index = 0
        run.status = RunStatus.RUNNING.value
        self._state = self.engine.prepare(
            run,
            bars_path=bars_path,
            strategy_params=strategy_params,
            entry_rules=entry_rules or {"kind": "hold"},
            exit_rules=exit_rules or {"kind": "hold"},
        )
        self._trajectory = TrajectoryBuilder(
            run_id=run.run_id,
            split_role=self._split_role,
            reward_spec=self._reward_spec.public_dict(),
            input_fingerprint=str((run.metadata or {}).get("input_fingerprint") or ""),
            metadata={"symbol": run.symbol, "timeframe": run.timeframe},
        )
        # Advance to first bar so observation is non-empty
        if self._state.clock.index < 0 and self._state.clock.bar_count > 0:
            first = self._state.clock.advance()
            if first is not None:
                run.bar_index = self._state.clock.index
                run.clock_ts = first.ts
                eq = float(self._state.wallet.equity(first.close))
                self._state.equity_curve.append(eq)
                run.equity = eq
                run.cash = float(self._state.wallet.cash)
                self._prev_equity = eq
                self._prev_realized = float(self._state.wallet.realized_pnl)
                self._peak_equity = eq
        self._bars_held = 0
        self.store.update_run(run)
        return self._observe()

    def step(self, action: GymAction | dict[str, Any] | None = None) -> GymStepResult:
        if self._state is None:
            raise MarketSimError("GYM_NOT_RESET", "call reset() before step()", http_status=409)
        action = action if isinstance(action, GymAction) else GymAction.from_dict(action)
        state = self._state
        run = state.run

        if state.clock.done or state.clock.index >= state.clock.bar_count - 1:
            obs = self._observe()
            return GymStepResult(
                observation=obs,
                reward=compute_step_reward(
                    self._reward_spec,
                    prev_equity=self._prev_equity,
                    equity=float(run.equity),
                    prev_realized_pnl=self._prev_realized,
                    realized_pnl=float(state.wallet.realized_pnl),
                    done=True,
                    initial_cash=float(run.initial_cash),
                ),
                done=True,
                info={"reason": "episode_complete"},
            )

        intent = self._action_to_intent(action, state)
        if intent is not None:
            # Clear auto-strategy for this bar; gym action is authoritative
            state.pending_intents.append(intent)

        # Force hold strategy so evaluate_strategy doesn't fight the gym action
        prev_entry = getattr(state, "_entry_rules", {"kind": "hold"})
        prev_exit = getattr(state, "_exit_rules", {"kind": "hold"})
        state._entry_rules = {"kind": "hold"}  # type: ignore[attr-defined]
        state._exit_rules = {"kind": "hold"}  # type: ignore[attr-defined]

        advanced = self.engine.step_once(state)
        state._entry_rules = prev_entry  # type: ignore[attr-defined]
        state._exit_rules = prev_exit  # type: ignore[attr-defined]

        done = (not advanced) or state.clock.done or run.status in {
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }
        if done and run.status == RunStatus.RUNNING.value:
            if state.clock.done or not advanced:
                run.status = RunStatus.COMPLETED.value
                run.finished_at = utc_now()
                self.engine._finalize_metrics(state)  # noqa: SLF001

        equity_now = float(run.equity)
        realized_now = float(state.wallet.realized_pnl)
        reward = compute_step_reward(
            self._reward_spec,
            prev_equity=self._prev_equity,
            equity=equity_now,
            prev_realized_pnl=self._prev_realized,
            realized_pnl=realized_now,
            done=done,
            initial_cash=float(run.initial_cash),
        )
        self._prev_equity = equity_now
        self._prev_realized = realized_now
        self.store.update_run(run)
        obs = self._observe()
        if self._trajectory is not None:
            self._trajectory.add_step(
                observation=obs.public_dict(),
                action=action.public_dict(),
                reward=reward,
                done=done,
                info={
                    "bar_index": run.bar_index,
                    "run_status": run.status,
                },
            )
            self.store.add_event(
                run.run_id,
                kind="gym_step",
                payload={
                    "observation": obs.public_dict(),
                    "action": action.public_dict(),
                    "reward": reward,
                    "done": done,
                },
                bar_index=run.bar_index,
            )
        return GymStepResult(
            observation=obs,
            reward=reward,
            done=done,
            info={
                "action": action.public_dict(),
                "bar_index": run.bar_index,
                "run_status": run.status,
            },
        )

    def run_episode(
        self,
        run: SimRun,
        *,
        bars_path: str,
        policy: Any = None,
        split_role: str = SplitRole.TRAIN,
        start_ts: str | None = None,
        end_ts: str | None = None,
        max_steps: int | None = None,
        strategy_params: dict[str, Any] | None = None,
        entry_rules: dict[str, Any] | None = None,
        exit_rules: dict[str, Any] | None = None,
        reward_spec: RewardSpec | dict[str, Any] | None = None,
        require_policy: bool = False,
        policy_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a complete episode (worker path).

        ``policy`` is callable(obs)->action, a TradingPolicy-like object with ``act``,
        or None. When ``require_policy`` is True (strategy-bound episode), ``policy``
        must be provided — silent HOLD is refused.
        """
        if require_policy and policy is None:
            raise MarketSimError(
                "POLICY_REQUIRED",
                "complete gym episode with bound strategy cannot use policy=None HOLD",
                http_status=400,
            )
        # Normalize TradingPolicy → callable
        act_fn = policy
        policy_meta: dict[str, Any] = {"policy_id": policy_id}
        if policy is not None and not callable(policy) and hasattr(policy, "act"):
            from .policy import PolicyContext, policy_callable

            ctx = PolicyContext(
                symbol=str(run.symbol or ""),
                timeframe=str(run.timeframe or ""),
                split_role=str(split_role or SplitRole.TRAIN),
                dataset_fingerprint=str((run.metadata or {}).get("input_fingerprint") or ""),
                strategy_id=run.strategy_id,
                strategy_version=run.strategy_version,
            )
            # engine_state bound after reset
            def _bound(obs: GymObservation) -> GymAction:
                ctx.engine_state = self._state
                return policy.act(obs, ctx)  # type: ignore[union-attr]

            act_fn = _bound
            policy_meta = {
                "policy_id": getattr(policy, "policy_id", policy_id),
                "policy_version": getattr(policy, "policy_version", None),
            }
        elif callable(policy):
            act_fn = policy

        self.bind_policy_context(
            symbol=str(run.symbol or ""),
            timeframe=str(run.timeframe or ""),
            dataset_fingerprint=str((run.metadata or {}).get("input_fingerprint") or ""),
            strategy_id=run.strategy_id,
            strategy_version=run.strategy_version,
            **policy_meta,
        )
        obs = self.reset(
            run,
            bars_path=bars_path,
            split_role=split_role,
            start_ts=start_ts,
            end_ts=end_ts,
            strategy_params=strategy_params,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            reward_spec=reward_spec,
        )
        steps = 0
        last: GymStepResult | None = None
        non_hold_actions = 0
        limit = max_steps if max_steps is not None else max(1, run.bar_count or 10_000_000)
        while steps < limit:
            if act_fn is None:
                action: GymAction | dict[str, Any] = GymAction(kind=GymActionKind.HOLD)
            else:
                action = act_fn(obs)
            if isinstance(action, GymAction):
                if action.kind != GymActionKind.HOLD:
                    non_hold_actions += 1
            elif isinstance(action, dict) and str(action.get("kind") or "").upper() != GymActionKind.HOLD:
                non_hold_actions += 1
            last = self.step(action)
            steps += 1
            obs = last.observation
            if last.done:
                break
        artifact = None
        if self._trajectory is not None:
            sealed = self._trajectory.seal()
            artifact = sealed.public_dict()
            meta = dict(run.metadata or {})
            meta["trajectory_id"] = sealed.trajectory_id
            meta["trajectory_hash"] = sealed.trajectory_hash
            meta["policy"] = policy_meta
            meta["non_hold_actions"] = non_hold_actions
            run.metadata = meta
            self.store.update_run(run)
        return {
            "run_id": run.run_id,
            "steps": steps,
            "done": bool(last.done if last else True),
            "observation": obs.public_dict(),
            "reward": last.reward if last else compute_step_reward(
                self._reward_spec,
                prev_equity=None,
                equity=None,
            ),
            "metrics": dict(run.metrics or {}),
            "status": run.status,
            "split_role": self._split_role,
            "trajectory": artifact,
            "non_hold_actions": non_hold_actions,
            "policy": policy_meta,
            "action_spec_version": ACTION_SPEC_V1,
            "observation_spec_version": OBSERVATION_SPEC_V1,
            "truth": {
                "worker_owned_complete_episode": True,
                "via_trading_gym": True,
                "policy_driven": act_fn is not None,
                "silent_hold_forbidden_when_strategy_bound": True,
            },
        }

    def _observe(self) -> GymObservation:
        assert self._state is not None
        state = self._state
        view = MarketView(clock=state.clock)
        visible = view.visible_bars()
        last = visible[-1] if visible else None
        qty = float(state.wallet.position_qty)
        if abs(qty) > 1e-12:
            self._bars_held += 1
        else:
            self._bars_held = 0
        equity = float(state.run.equity)
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity
        peak = float(self._peak_equity or equity or 1.0)
        dd = (peak - equity) / peak if peak else 0.0
        avg_entry = getattr(state.wallet, "avg_entry", None)
        if avg_entry is None:
            avg_entry = getattr(state.wallet, "average_entry", None)
        unrealized = None
        if last is not None and avg_entry is not None and abs(qty) > 1e-12:
            try:
                unrealized = (float(last.close) - float(avg_entry)) * float(qty)
            except (TypeError, ValueError):
                unrealized = None
        ctx = dict(self._policy_context or {})
        # Causal feature snapshot (best-effort; statuses labeled)
        feature_snapshot: dict[str, Any] = {}
        feature_statuses: dict[str, str] = {}
        try:
            from .features import FeatureEngine

            engine = FeatureEngine()
            as_of = view.as_of or state.clock.current_ts
            if as_of and visible:
                for name, period in (("sma", 10), ("sma", 30), ("rsi", 14), ("adx", 14)):
                    key = f"{name}_{period}"
                    res = engine.compute(visible, name, as_of=as_of, period=period)
                    feature_statuses[key] = str(getattr(res, "status", None) or "UNMEASURED")
                    feature_snapshot[key] = res.value if feature_statuses[key] == "MEASURED" else None
        except Exception:  # noqa: BLE001 — observation enrichment must not break episode
            feature_statuses["feature_engine"] = "UNMEASURED"

        return GymObservation(
            bar_index=state.clock.index,
            ts=state.clock.current_ts,
            visible_bar_count=len(visible),
            last_bar=_bar_public(last) if last else None,
            cash=float(state.wallet.cash),
            equity=equity,
            position_qty=qty,
            realized_pnl=float(state.wallet.realized_pnl),
            split_role=self._split_role,
            done=state.clock.done or state.run.status in {
                RunStatus.COMPLETED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
            },
            truth={"via_market_view": True, "no_future_bars": True},
            symbol=str(ctx.get("symbol") or state.run.symbol or ""),
            timeframe=str(ctx.get("timeframe") or state.run.timeframe or ""),
            causal_as_of=view.as_of or state.clock.current_ts,
            unrealized_pnl=unrealized,
            drawdown_context={"peak_equity": peak, "drawdown_pct": dd * 100.0},
            position_avg_entry=float(avg_entry) if avg_entry is not None else None,
            bars_held=int(self._bars_held),
            regime_state={},
            transaction_cost_state={
                "fee_bps": getattr(state.run, "fee_bps", None),
                "slippage_bps": getattr(state.run, "slippage_bps", None),
            },
            feature_snapshot=feature_snapshot,
            feature_statuses=feature_statuses,
            dataset_fingerprint=str(ctx.get("dataset_fingerprint") or ""),
            strategy_identity={
                "strategy_id": ctx.get("strategy_id") or state.run.strategy_id,
                "strategy_version": ctx.get("strategy_version") or state.run.strategy_version,
                "policy_id": ctx.get("policy_id"),
            },
            environment_version=str(ctx.get("environment_version") or "market_sim.gym.v1"),
        )

    def seal_trajectory(self) -> Any:
        if self._trajectory is None:
            raise MarketSimError("GYM_NO_TRAJECTORY", "no trajectory builder", http_status=409)
        return self._trajectory.seal()

    def _action_to_intent(self, action: GymAction, state: EngineState) -> OrderIntent | None:
        kind = action.kind.upper()
        if kind == GymActionKind.HOLD:
            return None
        qty_pos = float(state.wallet.position_qty)
        ts = state.clock.current_ts or utc_now()
        run = state.run
        if kind == GymActionKind.CLOSE:
            if abs(qty_pos) < 1e-12:
                return None
            side = OrderSide.SELL if qty_pos > 0 else OrderSide.BUY
            qty = abs(qty_pos)
            return make_intent(
                run_id=run.run_id,
                agent_id="gym",
                wallet_id=state.wallet.wallet_id,
                side=side.value if hasattr(side, "value") else str(side),
                qty=qty,
                decision_bar_index=state.clock.index,
                decision_ts=ts,
                info_version=f"gym:{state.clock.index}",
                order_type=OrderType.MARKET.value,
                time_in_force=TimeInForce.BAR.value,
                rationale=action.rationale or "gym_close",
            )
        if kind == GymActionKind.BUY:
            side = OrderSide.BUY
        elif kind == GymActionKind.SELL:
            side = OrderSide.SELL
        else:
            raise MarketSimError("GYM_ACTION_INVALID", f"unknown action kind={kind}", http_status=400)
        qty = action.qty
        if qty is None:
            eq = float(state.run.equity or state.run.initial_cash)
            price = float(state.clock.current_bar.close) if state.clock.current_bar else 1.0
            qty = max(eq * 0.01 / max(price, 1e-9), 0.0)
        if qty <= 0:
            return None
        return make_intent(
            run_id=run.run_id,
            agent_id="gym",
            wallet_id=state.wallet.wallet_id,
            side=side.value if hasattr(side, "value") else str(side),
            qty=float(qty),
            decision_bar_index=state.clock.index,
            decision_ts=ts,
            info_version=f"gym:{state.clock.index}",
            order_type=action.order_type,
            limit_price=action.limit_price,
            stop_price=action.stop_price,
            time_in_force=action.time_in_force,
            rationale=action.rationale,
        )


def resolve_split_window(
    manifest: dict[str, Any] | None,
    split_role: str,
) -> tuple[str | None, str | None]:
    """Return (start_ts, end_ts) for a split role from a DatasetSplitManifest dict."""
    role = str(split_role or SplitRole.TRAIN).upper()
    if not manifest:
        return None, None
    key = {"TRAIN": "train", "VAL": "val", "VALIDATION": "val", "SEALED": "sealed"}.get(role, "train")
    window = manifest.get(key)
    if not window:
        return None, None
    return window.get("start_ts"), window.get("end_ts")
