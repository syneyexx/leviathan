"""TradingGym — deterministic causal reset/step environment (T8 / G26).

Uses the same SimulationClock + MarketView causality kernel as backtests.
SEALED dataset windows are unreachable by construction. Rewards are computed
by the gym kernel from equity deltas — never caller-supplied.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from .causality import MarketView, SimulationClock
from .metrics import _safe_sharpe, max_drawdown, periods_per_year_for_timeframe
from .ohlcv import load_ohlcv
from .portfolio import Portfolio, RiskEngine, RiskLimits
from .types import Bar, CausalityViolation, MarketSimError


CURRICULUM_STAGES: tuple[str, ...] = (
    "trend",
    "mean_reversion",
    "mixed",
    "stress",
    "randomized_costs",
    "multi_asset",
    "adversarial",
)

# Actions: discrete macro-actions validated by the kernel.
ACTIONS = ("HOLD", "BUY", "SELL", "FLAT")


@dataclass
class DomainRandomization:
    """Cost / latency / spread randomization applied at reset (T8B)."""

    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    latency_bars: int = 1
    spread_bps: float = 1.0
    seed: int = 0

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def sample(cls, seed: int, *, stage: str = "randomized_costs") -> "DomainRandomization":
        rng = random.Random(int(seed))
        if stage in {"trend", "mean_reversion", "mixed"}:
            return cls(fee_bps=5.0, slippage_bps=2.0, latency_bars=1, spread_bps=1.0, seed=seed)
        if stage == "stress":
            return cls(
                fee_bps=rng.uniform(10.0, 40.0),
                slippage_bps=rng.uniform(5.0, 25.0),
                latency_bars=rng.randint(1, 3),
                spread_bps=rng.uniform(5.0, 20.0),
                seed=seed,
            )
        if stage == "adversarial":
            return cls(
                fee_bps=rng.uniform(20.0, 80.0),
                slippage_bps=rng.uniform(15.0, 50.0),
                latency_bars=rng.randint(2, 5),
                spread_bps=rng.uniform(10.0, 40.0),
                seed=seed,
            )
        # randomized_costs / multi_asset defaults
        return cls(
            fee_bps=rng.uniform(2.0, 20.0),
            slippage_bps=rng.uniform(1.0, 15.0),
            latency_bars=rng.randint(1, 3),
            spread_bps=rng.uniform(0.5, 10.0),
            seed=seed,
        )


@dataclass
class GymEpisodeSpec:
    episode_spec_id: str
    source_id: str | None
    bars_path: str
    data_hash: str
    curriculum_stage: str
    seed: int
    start_index: int = 0
    end_index: int | None = None
    initial_cash: float = 100_000.0
    timeframe: str = "1h"
    symbol: str = ""
    randomization: DomainRandomization = field(default_factory=DomainRandomization)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "episode_spec_id": self.episode_spec_id,
            "source_id": self.source_id,
            "bars_path": self.bars_path,
            "data_hash": self.data_hash,
            "curriculum_stage": self.curriculum_stage,
            "seed": self.seed,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "initial_cash": self.initial_cash,
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "randomization": self.randomization.public_dict(),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "truth": {
                "sealed_unreachable": True,
                "reward_from_kernel": True,
                "deterministic_given_seed": True,
            },
        }


@dataclass
class GymObservation:
    """Causal observation — only bars visible at the current clock."""

    as_of: str | None
    bar_index: int
    close: float | None
    window_closes: list[float]
    position_qty: float
    cash: float
    equity: float
    stage: str
    cost_model: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GymStepResult:
    observation: GymObservation
    reward: float
    done: bool
    info: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.public_dict(),
            "reward": self.reward,
            "done": self.done,
            "info": dict(self.info),
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_not_sealed_dataset(dataset: dict[str, Any] | None) -> None:
    """Gym must never observe SEALED holdout windows (G26)."""
    if dataset is None:
        return
    role = str(dataset.get("role") or "").upper()
    sealed = bool(dataset.get("sealed"))
    if sealed or role.startswith("SEALED"):
        raise MarketSimError(
            "SEALED_WINDOW_UNREACHABLE",
            f"TradingGym cannot read sealed dataset role={role!r}",
            http_status=403,
        )


class TradingGym:
    """Causal gym: reset → observation; step(action) → (obs, reward, done, info)."""

    def __init__(
        self,
        bars: Sequence[Bar],
        *,
        spec: GymEpisodeSpec,
        store: Any | None = None,
    ) -> None:
        if not bars:
            raise MarketSimError("GYM_EMPTY_BARS", "TradingGym requires at least one bar")
        self.spec = spec
        self.store = store
        start = max(0, int(spec.start_index))
        end = int(spec.end_index) if spec.end_index is not None else len(bars) - 1
        end = min(end, len(bars) - 1)
        if end < start:
            raise MarketSimError("GYM_BAD_WINDOW", f"end_index {end} < start_index {start}")
        self._bars = list(bars[start : end + 1])
        self.clock = SimulationClock(bars=self._bars, index=-1)
        self.view = MarketView(
            clock=self.clock,
            instrument=spec.symbol,
            timeframe=spec.timeframe,
        )
        self.portfolio = Portfolio(cash=float(spec.initial_cash))
        self.risk = RiskEngine(
            RiskLimits(max_position_pct=25.0, max_drawdown_pct=35.0, per_trade_risk_pct=5.0)
        )
        self.rng = random.Random(int(spec.seed))
        self.episode_id: str | None = None
        self.steps: int = 0
        self.rewards: list[float] = []
        self.trajectory: list[dict[str, Any]] = []
        self.violations = {
            "causality": 0,
            "risk_rejections": 0,
            "invalid_actions": 0,
            "override_attempts": 0,
        }
        self._pending_side: str | None = None
        self._pending_eligible: int = -1
        self._last_equity = float(spec.initial_cash)
        self._done = False
        self._started = False

    def reset(self, *, episode_id: str | None = None) -> GymObservation:
        self.clock.set_index(-1)
        self.portfolio = Portfolio(cash=float(self.spec.initial_cash))
        self.rng = random.Random(int(self.spec.seed))
        self.episode_id = episode_id or str(uuid.uuid4())
        self.steps = 0
        self.rewards = []
        self.trajectory = []
        self.violations = {
            "causality": 0,
            "risk_rejections": 0,
            "invalid_actions": 0,
            "override_attempts": 0,
        }
        self._pending_side = None
        self._pending_eligible = -1
        self._last_equity = float(self.spec.initial_cash)
        self._done = False
        self._started = True
        # Advance to first bar so observation is non-empty.
        bar = self.clock.advance()
        assert bar is not None
        equity = self.portfolio.mark_to_market(bar.close)
        self._last_equity = equity
        obs = self._observation()
        self._persist_episode(status="running", observation=obs)
        return obs

    def step(self, action: str) -> GymStepResult:
        if not self._started:
            raise MarketSimError("GYM_NOT_RESET", "Call reset() before step()", http_status=409)
        if self._done:
            raise MarketSimError("GYM_EPISODE_DONE", "Episode finished — reset to continue", http_status=409)

        action_u = str(action or "").strip().upper()
        if action_u not in ACTIONS:
            self.violations["invalid_actions"] += 1
            action_u = "HOLD"

        # Fill pending order from prior decision (latency_bars delay).
        reward_fill = 0.0
        if self._pending_side and self.clock.index >= self._pending_eligible:
            reward_fill = self._execute_pending()
            self._pending_side = None

        # Queue new action with latency.
        if action_u in {"BUY", "SELL", "FLAT"}:
            latency = max(1, int(self.spec.randomization.latency_bars))
            self._pending_side = action_u
            self._pending_eligible = self.clock.index + latency

        # Advance clock (causal).
        bar = self.clock.advance()
        if bar is None:
            self._done = True
            obs = self._observation()
            info = self._info(action_u, filled=False)
            result = GymStepResult(observation=obs, reward=0.0, done=True, info=info)
            self._record_step(action_u, result)
            self._persist_episode(status="completed", observation=obs)
            return result

        equity = self.portfolio.mark_to_market(bar.close)
        # Kernel reward = equity delta (never caller-supplied).
        reward = float(equity - self._last_equity) + reward_fill
        self._last_equity = equity
        self.steps += 1
        self.rewards.append(reward)

        done = self.clock.done
        self._done = done
        obs = self._observation()
        info = self._info(action_u, filled=reward_fill != 0.0)
        result = GymStepResult(observation=obs, reward=reward, done=done, info=info)
        self._record_step(action_u, result)
        self._persist_episode(
            status="completed" if done else "running",
            observation=obs,
        )
        return result

    def _execute_pending(self) -> float:
        bar = self.clock.current_bar
        if bar is None or not self._pending_side:
            return 0.0
        rnd = self.spec.randomization
        mid = float(bar.open)
        half_spread = mid * (float(rnd.spread_bps) / 10_000.0) / 2.0
        slip = mid * (float(rnd.slippage_bps) / 10_000.0)
        before = float(self.portfolio.cash + self.portfolio.position_qty * mid)

        side = self._pending_side
        if side == "FLAT":
            if self.portfolio.position_qty > 0:
                side = "SELL"
            elif self.portfolio.position_qty < 0:
                side = "BUY"
            else:
                return 0.0

        qty_target = (self.portfolio.cash * 0.1) / max(mid, 1e-12)
        if side == "BUY":
            price = mid + half_spread + slip
            fee = price * qty_target * (float(rnd.fee_bps) / 10_000.0)
            cost = price * qty_target + fee
            if cost > self.portfolio.cash or qty_target <= 0:
                self.violations["risk_rejections"] += 1
                return 0.0
            # Simple long-only portfolio update
            new_qty = self.portfolio.position_qty + qty_target
            if new_qty > 0:
                self.portfolio.avg_entry = (
                    (self.portfolio.avg_entry * self.portfolio.position_qty + price * qty_target)
                    / new_qty
                    if self.portfolio.position_qty > 0
                    else price
                )
            self.portfolio.position_qty = new_qty
            self.portfolio.cash -= cost
        elif side == "SELL":
            if self.portfolio.position_qty <= 0:
                self.violations["risk_rejections"] += 1
                return 0.0
            qty = self.portfolio.position_qty
            price = mid - half_spread - slip
            fee = price * qty * (float(rnd.fee_bps) / 10_000.0)
            proceeds = price * qty - fee
            realized = (price - self.portfolio.avg_entry) * qty - fee
            self.portfolio.realized_pnl += realized
            self.portfolio.cash += proceeds
            self.portfolio.position_qty = 0.0
            self.portfolio.avg_entry = 0.0
        after = float(self.portfolio.cash + self.portfolio.position_qty * mid)
        return after - before

    def _observation(self) -> GymObservation:
        bar = self.clock.current_bar
        closes: list[float] = []
        try:
            closes = self.view.closes(min(20, max(1, self.clock.index + 1)))
        except CausalityViolation:
            self.violations["causality"] += 1
        equity = float(
            self.portfolio.cash
            + self.portfolio.position_qty * (bar.close if bar else 0.0)
        )
        return GymObservation(
            as_of=self.clock.current_ts,
            bar_index=self.clock.index,
            close=float(bar.close) if bar else None,
            window_closes=closes,
            position_qty=float(self.portfolio.position_qty),
            cash=float(self.portfolio.cash),
            equity=equity,
            stage=self.spec.curriculum_stage,
            cost_model=self.spec.randomization.public_dict(),
        )

    def _info(self, action: str, *, filled: bool) -> dict[str, Any]:
        return {
            "action": action,
            "filled": filled,
            "steps": self.steps,
            "episode_id": self.episode_id,
            "violations": dict(self.violations),
            "curriculum_stage": self.spec.curriculum_stage,
            "truth": {
                "reward_from_kernel": True,
                "sealed_unreachable": True,
                "caller_reward_rejected": True,
            },
        }

    def _record_step(self, action: str, result: GymStepResult) -> None:
        self.trajectory.append(
            {
                "step": self.steps,
                "action": action,
                "reward": result.reward,
                "as_of": result.observation.as_of,
                "bar_index": result.observation.bar_index,
                "equity": result.observation.equity,
                "done": result.done,
            }
        )

    def episode_public_dict(self) -> dict[str, Any]:
        equity = list(self.portfolio.equity_curve) or [float(self.spec.initial_cash)]
        returns = []
        for i in range(1, len(equity)):
            if equity[i - 1] > 0:
                returns.append((equity[i] - equity[i - 1]) / equity[i - 1])
        ppy = periods_per_year_for_timeframe(self.spec.timeframe)
        return {
            "episode_id": self.episode_id,
            "episode_spec_id": self.spec.episode_spec_id,
            "status": "completed" if self._done else ("running" if self._started else "proposed"),
            "curriculum_stage": self.spec.curriculum_stage,
            "seed": self.spec.seed,
            "steps": self.steps,
            "total_reward": float(sum(self.rewards)),
            "equity_curve": equity,
            "sharpe": _safe_sharpe(returns, periods_per_year=ppy),
            "max_drawdown": max_drawdown(equity),
            "violations": dict(self.violations),
            "randomization": self.spec.randomization.public_dict(),
            "trajectory": list(self.trajectory),
            "trajectory_len": len(self.trajectory),
            "data_hash": self.spec.data_hash,
            "truth": {
                "deterministic_given_seed": True,
                "reward_from_kernel": True,
                "sealed_unreachable": True,
            },
        }

    def _persist_episode(self, *, status: str, observation: GymObservation) -> None:
        if self.store is None or not self.episode_id:
            return
        payload = self.episode_public_dict()
        payload["status"] = status
        payload["last_observation"] = observation.public_dict()
        payload["trajectory"] = list(self.trajectory)
        payload["updated_at"] = payload.get("updated_at") or ""
        try:
            self.store.save_gym_episode(payload)
        except Exception:  # noqa: BLE001 — gym must not crash on optional persist
            pass


def new_episode_spec(
    *,
    bars_path: str,
    data_hash: str = "",
    source_id: str | None = None,
    curriculum_stage: str = "trend",
    seed: int = 42,
    start_index: int = 0,
    end_index: int | None = None,
    initial_cash: float = 100_000.0,
    timeframe: str = "1h",
    symbol: str = "",
    created_at: str,
    dataset: dict[str, Any] | None = None,
) -> GymEpisodeSpec:
    assert_not_sealed_dataset(dataset)
    stage = curriculum_stage if curriculum_stage in CURRICULUM_STAGES else "trend"
    rnd = DomainRandomization.sample(seed, stage=stage)
    path_hash = data_hash or _sha256_text(bars_path)
    return GymEpisodeSpec(
        episode_spec_id=str(uuid.uuid4()),
        source_id=source_id,
        bars_path=bars_path,
        data_hash=path_hash,
        curriculum_stage=stage,
        seed=seed,
        start_index=start_index,
        end_index=end_index,
        initial_cash=initial_cash,
        timeframe=timeframe,
        symbol=symbol,
        randomization=rnd,
        created_at=created_at,
    )


def load_gym_from_path(spec: GymEpisodeSpec, *, store: Any | None = None) -> TradingGym:
    bars = load_ohlcv(spec.bars_path)
    return TradingGym(bars, spec=spec, store=store)


def curriculum_catalog() -> list[dict[str, Any]]:
    descriptions = {
        "trend": "Trend-following friendly regimes",
        "mean_reversion": "Mean-reversion friendly regimes",
        "mixed": "Alternating trend / mean-reversion",
        "stress": "High-cost stress regime",
        "randomized_costs": "Domain-randomized fees/slippage/latency/spread",
        "multi_asset": "Multi-asset curriculum placeholder (single-asset kernel)",
        "adversarial": "Adversarial cost/latency perturbation",
    }
    return [
        {
            "stage": s,
            "index": i,
            "description": descriptions[s],
            "requires_prior": CURRICULUM_STAGES[i - 1] if i > 0 else None,
        }
        for i, s in enumerate(CURRICULUM_STAGES)
    ]


def can_enter_curriculum_stage(current: str | None, target: str) -> bool:
    """Curriculum gating — may only advance one stage at a time from catalog order."""
    if target not in CURRICULUM_STAGES:
        return False
    if current is None or current == "":
        return target == CURRICULUM_STAGES[0]
    if current not in CURRICULUM_STAGES:
        return False
    if current == target:
        return True
    return CURRICULUM_STAGES.index(target) <= CURRICULUM_STAGES.index(current) + 1
