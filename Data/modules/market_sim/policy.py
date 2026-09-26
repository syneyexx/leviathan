"""Canonical TradingGym policy contract — Strategy DSL → GymAction (no fills/risk ownership).

Complete gym episodes with a bound strategy MUST execute that strategy via a
``TradingPolicy``. Silent ``policy=None`` HOLD while a strategy is bound is
fail-closed (``POLICY_REQUIRED`` / ``POLICY_LOAD_FAILED``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .features import FeatureEngine
from .gym import GymAction, GymActionKind, GymObservation
from .strategy_dsl import (
    apply_risk_exits,
    evaluate_dsl_v2,
    parse_strategy_spec,
    validate_strategy_spec,
)
from .strategy_eval import evaluate_strategy
from .types import MarketSimError, OrderSide


OBSERVATION_SPEC_VERSION = 1
ACTION_SPEC_VERSION = 1
POLICY_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class ObservationSpec:
    """Versioned gym observation schema ownership (v1)."""

    version: int = OBSERVATION_SPEC_VERSION
    required_fields: tuple[str, ...] = (
        "timestamp",
        "bar_index",
        "symbol",
        "timeframe",
        "causal_as_of",
        "current_ohlcv",
        "feature_snapshot",
        "position",
        "cash",
        "equity",
        "realized_pnl",
        "unrealized_pnl",
        "drawdown_context",
        "position_avg_entry",
        "bars_held",
        "regime_state",
        "transaction_cost_state",
        "feature_statuses",
        "split_role",
        "dataset_fingerprint",
        "strategy_identity",
        "environment_version",
    )

    def public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "required_fields": list(self.required_fields),
            "truth": {
                "causal_features_only": True,
                "no_future_bars": True,
                "no_hidden_next_bar": True,
            },
        }


@dataclass(frozen=True)
class ActionSpec:
    """Versioned gym action schema ownership (v1)."""

    version: int = ACTION_SPEC_VERSION
    kinds: tuple[str, ...] = (
        GymActionKind.HOLD,
        GymActionKind.BUY,
        GymActionKind.SELL,
        GymActionKind.CLOSE,
    )

    def public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "kinds": list(self.kinds),
            "truth": {
                "policy_proposes_intent_only": True,
                "no_fill_authority": True,
                "no_wallet_mutation": True,
                "risk_guard_authoritative": True,
            },
        }


@dataclass
class PolicyContext:
    """Runtime context for a policy act() call — causal engine state refs only."""

    symbol: str = ""
    timeframe: str = ""
    split_role: str = "TRAIN"
    dataset_fingerprint: str = ""
    strategy_id: str | None = None
    strategy_version: int | None = None
    environment_version: str = "market_sim.gym.v1"
    feature_engine: FeatureEngine | None = None
    engine_state: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "split_role": self.split_role,
            "dataset_fingerprint": self.dataset_fingerprint,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "environment_version": self.environment_version,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class TradingPolicy(Protocol):
    """Canonical strategy policy contract for TradingGym."""

    @property
    def policy_id(self) -> str: ...

    @property
    def policy_version(self) -> str: ...

    def act(self, observation: GymObservation, context: PolicyContext) -> GymAction: ...


def _side_to_gym_action(
    side: str,
    *,
    qty: float | None,
    rationale: str,
    position_qty: float,
) -> GymAction:
    s = str(side or OrderSide.HOLD.value).upper()
    if s == OrderSide.HOLD.value or s == GymActionKind.HOLD:
        return GymAction(kind=GymActionKind.HOLD, rationale=rationale)
    if s in {OrderSide.BUY.value, GymActionKind.BUY}:
        if position_qty < 0:
            # Flatten short then optionally reverse — CLOSE first is safer.
            return GymAction(kind=GymActionKind.CLOSE, rationale=f"close_short_before_buy:{rationale}")
        return GymAction(kind=GymActionKind.BUY, qty=qty, rationale=rationale)
    if s in {OrderSide.SELL.value, GymActionKind.SELL}:
        if position_qty > 0:
            return GymAction(kind=GymActionKind.CLOSE, rationale=f"close_long:{rationale}")
        if position_qty == 0:
            # Short entry when flat
            return GymAction(kind=GymActionKind.SELL, qty=qty, rationale=rationale)
        return GymAction(kind=GymActionKind.SELL, qty=qty, rationale=rationale)
    if s in {GymActionKind.CLOSE, "FLAT", "EXIT"}:
        return GymAction(kind=GymActionKind.CLOSE, rationale=rationale)
    raise MarketSimError("POLICY_ACTION_INVALID", f"unsupported side={side}", http_status=400)


@dataclass
class DslStrategyPolicy:
    """Production TradingPolicy over Strategy DSL v2/v3 + FeatureEngine.

    Does not fill, mutate wallets, or bypass RiskGuard — only emits GymAction intents.
    """

    entry_rules: dict[str, Any]
    exit_rules: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_rules: dict[str, Any] = field(default_factory=dict)
    policy_id: str = "dsl_strategy"
    policy_version: str = "1"
    strategy_id: str | None = None
    strategy_version: int | None = None
    content_hash: str = ""
    feature_engine: FeatureEngine | None = None
    _bars_held: int = 0
    _avg_entry: float | None = None
    _prev_qty: float = 0.0
    _load_error: str | None = None

    def __post_init__(self) -> None:
        try:
            spec = parse_strategy_spec(
                self.entry_rules,
                exit_rules=self.exit_rules,
                parameters=self.parameters,
            )
            ok, reason = validate_strategy_spec(spec)
            if not ok:
                self._load_error = reason
        except Exception as exc:  # noqa: BLE001 — capture load failure for fail-closed act()
            self._load_error = str(exc)

    @classmethod
    def from_strategy_payload(
        cls,
        payload: dict[str, Any],
        *,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        content_hash: str = "",
        feature_engine: FeatureEngine | None = None,
    ) -> "DslStrategyPolicy":
        return cls(
            entry_rules=dict(payload.get("entry_rules") or {"kind": "hold"}),
            exit_rules=dict(payload.get("exit_rules") or {}),
            parameters=dict(payload.get("parameters") or {}),
            risk_rules=dict(payload.get("risk_rules") or {}),
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            content_hash=content_hash,
            feature_engine=feature_engine or FeatureEngine(),
            policy_id=f"dsl:{strategy_id or 'anon'}:{strategy_version or 0}",
        )

    def ensure_loaded(self) -> None:
        if self._load_error:
            raise MarketSimError(
                "POLICY_LOAD_FAILED",
                f"strategy policy cannot execute: {self._load_error}",
                http_status=400,
            )

    def act(self, observation: GymObservation, context: PolicyContext) -> GymAction:
        self.ensure_loaded()
        state = context.engine_state
        if state is None:
            raise MarketSimError(
                "POLICY_CONTEXT_MISSING",
                "engine_state required for DslStrategyPolicy.act",
                http_status=409,
            )
        clock = state.clock
        position_qty = float(getattr(observation, "position_qty", 0.0) or 0.0)

        # Track bars held / avg entry from engine wallet when available
        wallet = getattr(state, "wallet", None)
        if wallet is not None:
            position_qty = float(wallet.position_qty)
            avg = getattr(wallet, "avg_entry", None)
            if avg is None:
                avg = getattr(wallet, "average_entry", None)
            if position_qty != 0 and self._prev_qty == 0:
                self._bars_held = 0
                self._avg_entry = float(avg) if avg is not None else (
                    float(observation.last_bar["close"]) if observation.last_bar else None
                )
            elif abs(position_qty) < 1e-12:
                self._bars_held = 0
                self._avg_entry = None
            else:
                self._bars_held += 1
                if avg is not None:
                    self._avg_entry = float(avg)
            self._prev_qty = position_qty

        # Risk exits first when in a position
        spec = parse_strategy_spec(
            self.entry_rules,
            exit_rules=self.exit_rules,
            parameters=self.parameters,
        )
        last_price = float(observation.last_bar["close"]) if observation.last_bar else 0.0
        if position_qty > 0 and self._avg_entry is not None and last_price > 0:
            risk = apply_risk_exits(
                position_qty=position_qty,
                entry_price=self._avg_entry,
                last_price=last_price,
                bars_held=self._bars_held,
                spec=spec,
            )
            if risk.get("triggered"):
                return GymAction(
                    kind=GymActionKind.CLOSE,
                    rationale=str(risk.get("reason") or "risk_exit"),
                )

        engine = context.feature_engine or self.feature_engine or FeatureEngine()
        signal = evaluate_strategy(
            clock,
            parameters=self.parameters,
            entry_rules=self.entry_rules,
            exit_rules=self.exit_rules,
            position_qty=position_qty,
        )
        # Prefer DSL path explicitly for v2/v3 documents (evaluate_strategy already dispatches)
        _ = evaluate_dsl_v2  # retained for contract clarity / import side-effects free
        return _side_to_gym_action(
            signal.side,
            qty=signal.qty,
            rationale=signal.rationale or "dsl_strategy",
            position_qty=position_qty,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "content_hash": self.content_hash,
            "kind": (self.entry_rules or {}).get("kind"),
            "load_error": self._load_error,
            "truth": {
                "contract_version": POLICY_CONTRACT_VERSION,
                "no_fill_authority": True,
                "risk_guard_not_bypassed": True,
            },
        }


@dataclass
class HoldPolicy:
    """Explicit HOLD policy — valid when intentionally configured."""

    policy_id: str = "hold"
    policy_version: str = "1"
    rationale: str = "explicit_hold"

    def act(self, observation: GymObservation, context: PolicyContext) -> GymAction:
        return GymAction(kind=GymActionKind.HOLD, rationale=self.rationale)


def strategy_is_explicit_hold(payload: dict[str, Any] | None) -> bool:
    payload = dict(payload or {})
    entry = dict(payload.get("entry_rules") or {})
    kind = str(entry.get("kind") or "").lower()
    return kind == "hold"


def strategy_requires_policy(payload: dict[str, Any] | None, *, strategy_id: str | None) -> bool:
    """True when a real strategy is bound and must not silently HOLD."""
    if strategy_id:
        return not strategy_is_explicit_hold(payload)
    payload = dict(payload or {})
    entry = dict(payload.get("entry_rules") or {})
    kind = str(entry.get("kind") or "").lower()
    if not kind or kind == "hold":
        return False
    return True


def resolve_gym_policy(
    payload: dict[str, Any] | None,
    *,
    strategy_id: str | None = None,
    strategy_version: int | None = None,
    content_hash: str = "",
    allow_missing_as_hold: bool = False,
) -> TradingPolicy:
    """Resolve a TradingPolicy for a complete gym episode.

    Fail-closed when a strategy is bound but cannot be loaded, unless the
    strategy is an explicit HOLD.
    """
    payload = dict(payload or {})
    if not strategy_requires_policy(payload, strategy_id=strategy_id):
        if allow_missing_as_hold or strategy_is_explicit_hold(payload) or not strategy_id:
            return HoldPolicy(rationale="explicit_or_unbound_hold")
        raise MarketSimError(
            "POLICY_REQUIRED",
            "complete gym episode requires a strategy policy",
            http_status=400,
        )
    policy = DslStrategyPolicy.from_strategy_payload(
        payload,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        content_hash=content_hash,
    )
    policy.ensure_loaded()
    return policy


def policy_callable(policy: TradingPolicy, context: PolicyContext):
    """Adapt TradingPolicy to ``callable(obs) -> GymAction`` for ``run_episode``."""

    def _fn(obs: GymObservation) -> GymAction:
        # Refresh engine_state from context each step (same object mutated by gym)
        return policy.act(obs, context)

    return _fn
