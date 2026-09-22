"""Sandboxed strategy DSL — structured rules only, no arbitrary code exec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from Data.modules.common.hashing import sha256_text

from .causality import SimulationClock
from .types import OrderSide


@dataclass(frozen=True)
class StrategySignal:
    side: str  # BUY | SELL | HOLD
    qty: float | None
    confidence: float
    rationale: str
    parameters_used: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "qty": self.qty,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "parameters_used": self.parameters_used,
        }


def strategy_content_hash(
    *,
    parameters: dict[str, Any],
    entry_rules: dict[str, Any],
    exit_rules: dict[str, Any],
    risk_rules: dict[str, Any],
    required_timeframes: list[str],
    brain_dependencies: list[str],
) -> str:
    payload = {
        "parameters": parameters,
        "entry_rules": entry_rules,
        "exit_rules": exit_rules,
        "risk_rules": risk_rules,
        "required_timeframes": required_timeframes,
        "brain_dependencies": brain_dependencies,
    }
    import json

    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _sma(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_strategy(
    clock: SimulationClock,
    *,
    parameters: dict[str, Any],
    entry_rules: dict[str, Any],
    exit_rules: dict[str, Any],
    position_qty: float,
    role_bias: str | None = None,
) -> StrategySignal:
    """Evaluate safe structured rules against a causal window only."""
    fast = int(parameters.get("fast_ma", entry_rules.get("fast_ma", 10)))
    slow = int(parameters.get("slow_ma", entry_rules.get("slow_ma", 30)))
    lookback = max(fast, slow, int(parameters.get("lookback", 20)))
    lookback = max(2, min(lookback, 500))

    closes = clock.closes(lookback)
    if len(closes) < lookback:
        return StrategySignal(
            side=OrderSide.HOLD.value,
            qty=None,
            confidence=0.1,
            rationale=f"warming up ({len(closes)}/{lookback} bars)",
            parameters_used={"fast_ma": fast, "slow_ma": slow, "lookback": lookback},
        )

    fast_ma = _sma(closes[-fast:])
    slow_ma = _sma(closes[-slow:])
    last = closes[-1]
    prev_fast = _sma(closes[-fast - 1 : -1]) if len(closes) > fast else fast_ma
    prev_slow = _sma(closes[-slow - 1 : -1]) if len(closes) > slow else slow_ma

    kind = (entry_rules.get("kind") or "ma_cross").lower()
    exit_kind = (exit_rules.get("kind") or "ma_cross").lower()

    # Role bias adjusts interpretation slightly without breaking causality.
    if role_bias == "mean_reversion":
        kind = "mean_reversion"
    elif role_bias == "trend":
        kind = "ma_cross"

    signal_side = OrderSide.HOLD.value
    rationale = "no setup"
    confidence = 0.4

    if kind == "ma_cross":
        bullish_cross = prev_fast <= prev_slow and fast_ma > slow_ma
        bearish_cross = prev_fast >= prev_slow and fast_ma < slow_ma
        if position_qty <= 0 and bullish_cross:
            signal_side = OrderSide.BUY.value
            rationale = f"bullish MA cross fast={fast_ma:.4f} slow={slow_ma:.4f}"
            confidence = 0.65
        elif position_qty > 0 and (bearish_cross or (exit_kind == "ma_cross" and fast_ma < slow_ma)):
            signal_side = OrderSide.SELL.value
            rationale = f"bearish MA / exit fast={fast_ma:.4f} slow={slow_ma:.4f}"
            confidence = 0.6
        elif position_qty <= 0 and fast_ma > slow_ma:
            signal_side = OrderSide.HOLD.value
            rationale = "trend up but no fresh cross"
            confidence = 0.45
    elif kind == "mean_reversion":
        window = closes[-lookback:]
        mean = _sma(window)
        std = (sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5
        z = (last - mean) / std if std > 1e-12 else 0.0
        entry_z = float(entry_rules.get("entry_z", parameters.get("entry_z", -1.5)))
        exit_z = float(exit_rules.get("exit_z", parameters.get("exit_z", 0.0)))
        if position_qty <= 0 and z <= entry_z:
            signal_side = OrderSide.BUY.value
            rationale = f"mean-reversion entry z={z:.2f}"
            confidence = min(0.85, 0.5 + abs(z) * 0.1)
        elif position_qty > 0 and z >= exit_z:
            signal_side = OrderSide.SELL.value
            rationale = f"mean-reversion exit z={z:.2f}"
            confidence = 0.55
        else:
            rationale = f"z={z:.2f} within band"
    else:
        rationale = f"unknown rule kind {kind}; holding"

    return StrategySignal(
        side=signal_side,
        qty=None,
        confidence=confidence,
        rationale=rationale,
        parameters_used={
            "fast_ma": fast,
            "slow_ma": slow,
            "lookback": lookback,
            "kind": kind,
            "last": last,
            "fast_value": fast_ma,
            "slow_value": slow_ma,
        },
    )
