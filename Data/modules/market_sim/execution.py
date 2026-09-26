"""Order intents + next-bar fill schedule (no same-close fill after deciding on that close).

Canonical historical executor: NextBarFillModel.
Legacy float Portfolio FillModel lives in fill_model.py as a compatibility shim only.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from .accounting import D, WalletLedger, money
from .types import (
    FillStatus,
    IntrabarPathPolicy,
    OrderSide,
    OrderType,
    TimeInForce,
)


def deterministic_id(*parts: Any) -> str:
    blob = "|".join(str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def default_tif_for_order_type(order_type: str) -> str:
    ot = (order_type or OrderType.MARKET.value).upper()
    if ot == OrderType.MARKET.value:
        return TimeInForce.BAR.value
    if ot in {OrderType.LIMIT.value, OrderType.STOP.value, OrderType.STOP_LIMIT.value}:
        return TimeInForce.GTC.value
    return TimeInForce.BAR.value


@dataclass
class OrderIntent:
    """Decision at bar T becomes eligible for fill at bar T+1 open (default)."""

    intent_id: str
    run_id: str
    agent_id: str
    wallet_id: str
    side: str  # BUY | SELL | HOLD
    qty: Decimal | None
    decision_bar_index: int
    decision_ts: str
    eligible_bar_index: int
    strategy_id: str | None = None
    strategy_version: int | None = None
    rationale: str = ""
    confidence: float = 0.0
    decision_scope: str = "individual"  # individual | shared
    status: str = "pending_eligibility"  # pending_eligibility | working | filled | rejected | cancelled
    metadata: dict[str, Any] = field(default_factory=dict)
    info_version: str = ""  # hash of frozen market snapshot at decision time
    order_type: str = OrderType.MARKET.value
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: str = TimeInForce.BAR.value
    stop_triggered: bool = False  # STOP_LIMIT: stop armed → active limit
    original_qty: Decimal | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "wallet_id": self.wallet_id,
            "side": self.side,
            "qty": None if self.qty is None else str(self.qty),
            "original_qty": None if self.original_qty is None else str(self.original_qty),
            "decision_bar_index": self.decision_bar_index,
            "decision_ts": self.decision_ts,
            "eligible_bar_index": self.eligible_bar_index,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "decision_scope": self.decision_scope,
            "status": self.status,
            "info_version": self.info_version,
            "order_type": self.order_type,
            "limit_price": None if self.limit_price is None else str(self.limit_price),
            "stop_price": None if self.stop_price is None else str(self.stop_price),
            "time_in_force": self.time_in_force,
            "stop_triggered": self.stop_triggered,
            "metadata": self.metadata,
            "truth": {
                "fill_schedule": "next_bar_open",
                "same_bar_close_fill_forbidden": True,
            },
        }


@dataclass
class FillResult:
    filled: bool
    qty: Decimal
    price: Decimal
    fee: Decimal
    slippage: Decimal
    detail: str
    status: str = FillStatus.FILLED.value
    observed_execution: bool = False  # always False for sim fills
    remaining_qty: Decimal | None = None
    fill_price_source: str = "next_bar_open"
    order_type: str = OrderType.MARKET.value
    intent_id: str | None = None
    triggered: bool = True
    unresolved_intrabar: bool = False

    def public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "filled": self.filled,
            "qty": str(self.qty),
            "price": str(self.price),
            "fee": str(self.fee),
            "slippage": str(self.slippage),
            "detail": self.detail,
            "status": self.status,
            "observed_execution": self.observed_execution,
            "fill_price_source": self.fill_price_source,
            "order_type": self.order_type,
            "triggered": self.triggered,
        }
        if self.remaining_qty is not None:
            out["remaining_qty"] = str(self.remaining_qty)
        if self.intent_id is not None:
            out["intent_id"] = self.intent_id
        if self.unresolved_intrabar:
            out["unresolved_intrabar"] = True
        return out


def resolve_intrabar_path(
    *,
    side: str,
    stop_price: float | None,
    target_price: float | None,
    open_px: float,
    high: float,
    low: float,
    policy: str = IntrabarPathPolicy.CONSERVATIVE.value,
) -> dict[str, Any]:
    """Resolve OHLCV ambiguity when stop and target both lie inside the bar.

    Never silently chooses the favorable path for the position.
    """
    pol = (policy or IntrabarPathPolicy.CONSERVATIVE.value).upper()
    if pol == IntrabarPathPolicy.PESSIMISTIC.value:
        pol = IntrabarPathPolicy.CONSERVATIVE.value

    stop_hit = stop_price is not None and low <= float(stop_price) <= high
    target_hit = target_price is not None and low <= float(target_price) <= high

    if not (stop_hit and target_hit):
        if stop_hit:
            return {"outcome": "stop", "policy": pol, "ambiguous": False}
        if target_hit:
            return {"outcome": "target", "policy": pol, "ambiguous": False}
        return {"outcome": "none", "policy": pol, "ambiguous": False}

    if pol == IntrabarPathPolicy.UNRESOLVED.value:
        return {"outcome": "unresolved", "policy": pol, "ambiguous": True}

    # Path policies for sequence assumptions
    if pol == IntrabarPathPolicy.OPEN_HIGH_LOW_CLOSE.value:
        # high before low
        if side.upper() == "LONG" or side.upper() == "BUY":
            # long: target (high) then stop (low) → target first
            return {"outcome": "target", "policy": pol, "ambiguous": True}
        return {"outcome": "stop", "policy": pol, "ambiguous": True}
    if pol == IntrabarPathPolicy.OPEN_LOW_HIGH_CLOSE.value:
        if side.upper() == "LONG" or side.upper() == "BUY":
            return {"outcome": "stop", "policy": pol, "ambiguous": True}
        return {"outcome": "target", "policy": pol, "ambiguous": True}

    # CONSERVATIVE / PESSIMISTIC: adverse to the position
    if side.upper() in {"LONG", "BUY"}:
        return {"outcome": "stop", "policy": IntrabarPathPolicy.CONSERVATIVE.value, "ambiguous": True}
    return {"outcome": "stop", "policy": IntrabarPathPolicy.CONSERVATIVE.value, "ambiguous": True}


class NextBarFillModel:
    """Canonical historical executor: next eligible bar ± modelled assumptions."""

    ASSUMPTIONS = (
        "OHLCV only — not order-book realism",
        "Market orders fill at next bar open ± modelled slippage",
        "Limit/Stop use next-bar OHLC trigger rules; no guaranteed fills",
        "Partial fills when qty exceeds participation * bar volume or cash",
        "MARKET default TimeInForce=BAR — no implicit eternal market orders",
        "Intrabar stop+target ambiguity uses explicit IntrabarPathPolicy (default CONSERVATIVE)",
        "observed_execution=False — costs are modelled, not measured",
    )

    def __init__(
        self,
        *,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        max_participation: float = 0.1,
        intrabar_path_policy: str = IntrabarPathPolicy.CONSERVATIVE.value,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.max_participation = max_participation
        self.intrabar_path_policy = intrabar_path_policy

    def execute_intent(
        self,
        *,
        wallet: WalletLedger,
        intent: OrderIntent,
        fill_open: float,
        bar_volume: float,
        fill_bar_index: int,
        fill_high: float | None = None,
        fill_low: float | None = None,
        fill_close: float | None = None,
        intrabar_path_policy: str | None = None,
    ) -> FillResult:
        high = float(fill_high if fill_high is not None else fill_open)
        low = float(fill_low if fill_low is not None else fill_open)
        # Ensure OHLC consistency for degenerate inputs
        high = max(high, float(fill_open), low)
        low = min(low, float(fill_open), high)
        policy = intrabar_path_policy or self.intrabar_path_policy

        if fill_bar_index < intent.eligible_bar_index:
            return FillResult(
                False,
                money(0),
                money(fill_open),
                money(0),
                money(0),
                "not yet eligible — causality guard",
                status=FillStatus.REJECTED.value,
                intent_id=intent.intent_id,
                order_type=intent.order_type,
                triggered=False,
            )
        if intent.side == OrderSide.HOLD.value or intent.qty is None or D(intent.qty) <= 0:
            intent.status = "cancelled"
            return FillResult(
                False,
                money(0),
                money(fill_open),
                money(0),
                money(0),
                "hold/no qty",
                intent_id=intent.intent_id,
                order_type=intent.order_type,
                triggered=False,
            )

        order_type = (intent.order_type or OrderType.MARKET.value).upper()
        tif = (intent.time_in_force or default_tif_for_order_type(order_type)).upper()
        intent.time_in_force = tif
        if intent.original_qty is None and intent.qty is not None:
            intent.original_qty = money(intent.qty)

        trigger = self._resolve_trigger(
            intent=intent,
            order_type=order_type,
            open_px=float(fill_open),
            high=high,
            low=low,
            policy=policy,
        )
        if not trigger["triggered"]:
            return self._handle_no_trigger(intent, tif, fill_open, trigger.get("detail", "not triggered"))

        reference = money(trigger["reference"])
        price_source = str(trigger.get("fill_price_source") or "next_bar_open")
        unresolved = bool(trigger.get("unresolved_intrabar"))

        qty_requested = money(intent.qty)
        qty = qty_requested

        # Participation cap → partial fills
        if bar_volume > 0 and self.max_participation > 0:
            max_qty = money(D(bar_volume) * D(self.max_participation))
            if qty > max_qty and max_qty > 0:
                qty = max_qty

        slip_frac = D(self.slippage_bps) / D(10_000)
        if intent.side == OrderSide.BUY.value:
            fill_price = money(reference * (D(1) + slip_frac))
        else:
            fill_price = money(reference * (D(1) - slip_frac))

        # FOK: must be able to fill full requested qty
        if tif == TimeInForce.FOK.value and qty < qty_requested:
            intent.status = "rejected"
            return FillResult(
                False,
                money(0),
                fill_price,
                money(0),
                money(0),
                "FOK — full quantity unavailable",
                status=FillStatus.REJECTED.value,
                remaining_qty=qty_requested,
                fill_price_source=price_source,
                order_type=order_type,
                intent_id=intent.intent_id,
            )

        tx_id = deterministic_id(intent.intent_id, fill_bar_index, intent.status, str(qty))

        try:
            if intent.side == OrderSide.BUY.value:
                notional = money(qty * fill_price)
                fee = money(notional * D(self.fee_bps) / D(10_000))
                total = money(notional + fee)
                if total > wallet.cash + money("0.00000001"):
                    affordable = money(
                        wallet.available_cash
                        / (fill_price * (D(1) + D(self.fee_bps) / D(10_000)))
                    )
                    if affordable <= 0:
                        return self._reject(intent, fill_price, "insufficient cash", order_type, price_source)
                    if tif == TimeInForce.FOK.value:
                        return self._reject(
                            intent, fill_price, "FOK — insufficient cash for full qty", order_type, price_source
                        )
                    qty = affordable
                    notional = money(qty * fill_price)
                    fee = money(notional * D(self.fee_bps) / D(10_000))
                slip_cost = money(abs(fill_price - reference) * qty)
                wallet.apply_buy(qty=qty, price=fill_price, fee=fee, tx_id=tx_id)
            else:
                if wallet.position_qty <= 0:
                    return self._reject(intent, fill_price, "no position", order_type, price_source)
                sell_qty = money(min(qty, wallet.position_qty))
                if tif == TimeInForce.FOK.value and sell_qty < qty_requested:
                    return self._reject(
                        intent, fill_price, "FOK — full sell quantity unavailable", order_type, price_source
                    )
                fee = money(sell_qty * fill_price * D(self.fee_bps) / D(10_000))
                slip_cost = money(abs(fill_price - reference) * sell_qty)
                wallet.apply_sell(qty=sell_qty, price=fill_price, fee=fee, tx_id=tx_id)
                qty = sell_qty

            remaining = money(qty_requested - qty)
            if remaining < 0:
                remaining = money(0)
            return self._finalize_partial_or_full(
                intent=intent,
                qty=qty,
                qty_requested=qty_requested,
                remaining=remaining,
                fill_price=fill_price,
                fee=fee if intent.side == OrderSide.BUY.value else fee,
                slip_cost=slip_cost,
                tif=tif,
                order_type=order_type,
                price_source=price_source,
                unresolved=unresolved,
            )
        except ValueError as exc:
            return self._reject(intent, fill_price, str(exc), order_type, price_source)

    def _resolve_trigger(
        self,
        *,
        intent: OrderIntent,
        order_type: str,
        open_px: float,
        high: float,
        low: float,
        policy: str,
    ) -> dict[str, Any]:
        if order_type == OrderType.MARKET.value:
            return {
                "triggered": True,
                "reference": open_px,
                "fill_price_source": "next_bar_open",
            }

        if order_type == OrderType.LIMIT.value:
            if intent.limit_price is None:
                return {"triggered": False, "detail": "LIMIT requires limit_price"}
            limit = float(intent.limit_price)
            if intent.side == OrderSide.BUY.value:
                if low > limit:
                    return {"triggered": False, "detail": "LIMIT BUY not triggered"}
                reference = open_px if open_px <= limit else limit
                source = "next_bar_open" if open_px <= limit else "limit_price"
            else:
                if high < limit:
                    return {"triggered": False, "detail": "LIMIT SELL not triggered"}
                reference = open_px if open_px >= limit else limit
                source = "next_bar_open" if open_px >= limit else "limit_price"
            return {
                "triggered": True,
                "reference": reference,
                "fill_price_source": source,
            }

        if order_type == OrderType.STOP.value:
            if intent.stop_price is None:
                return {"triggered": False, "detail": "STOP requires stop_price"}
            stop = float(intent.stop_price)
            if intent.side == OrderSide.BUY.value:
                # STOP BUY gap handling
                if open_px >= stop:
                    return {
                        "triggered": True,
                        "reference": open_px,
                        "fill_price_source": "next_bar_open_gap",
                    }
                if high >= stop:
                    return {
                        "triggered": True,
                        "reference": stop,
                        "fill_price_source": "stop_price",
                    }
                return {"triggered": False, "detail": "STOP BUY not triggered"}
            # STOP SELL
            if open_px <= stop:
                return {
                    "triggered": True,
                    "reference": open_px,
                    "fill_price_source": "next_bar_open_gap",
                }
            if low <= stop:
                return {
                    "triggered": True,
                    "reference": stop,
                    "fill_price_source": "stop_price",
                }
            return {"triggered": False, "detail": "STOP SELL not triggered"}

        if order_type == OrderType.STOP_LIMIT.value:
            if intent.stop_price is None or intent.limit_price is None:
                return {"triggered": False, "detail": "STOP_LIMIT requires stop_price and limit_price"}
            stop = float(intent.stop_price)
            limit = float(intent.limit_price)
            # Arm stop if not yet triggered
            if not intent.stop_triggered:
                if intent.side == OrderSide.BUY.value:
                    armed = open_px >= stop or high >= stop
                else:
                    armed = open_px <= stop or low <= stop
                if not armed:
                    return {"triggered": False, "detail": "STOP_LIMIT stop not armed"}
                intent.stop_triggered = True
            # After arming: behave as LIMIT — no magical guaranteed fill
            if intent.side == OrderSide.BUY.value:
                if low > limit:
                    return {
                        "triggered": False,
                        "detail": "STOP_LIMIT armed but LIMIT BUY not filled",
                    }
                reference = open_px if open_px <= limit else limit
                source = "next_bar_open" if open_px <= limit else "limit_price"
            else:
                if high < limit:
                    return {
                        "triggered": False,
                        "detail": "STOP_LIMIT armed but LIMIT SELL not filled",
                    }
                reference = open_px if open_px >= limit else limit
                source = "next_bar_open" if open_px >= limit else "limit_price"
            # Optional: if both stop and a protective target live in metadata, resolve path
            target = intent.metadata.get("take_profit_price")
            path = resolve_intrabar_path(
                side="LONG" if intent.side == OrderSide.BUY.value else "SHORT",
                stop_price=stop,
                target_price=float(target) if target is not None else None,
                open_px=open_px,
                high=high,
                low=low,
                policy=policy,
            )
            unresolved = bool(path.get("ambiguous") and path.get("outcome") == "unresolved")
            if path.get("outcome") == "unresolved":
                return {
                    "triggered": False,
                    "detail": "intrabar path UNRESOLVED",
                    "unresolved_intrabar": True,
                }
            return {
                "triggered": True,
                "reference": reference,
                "fill_price_source": source,
                "unresolved_intrabar": unresolved,
            }

        return {"triggered": False, "detail": f"ORDER_TYPE_INVALID:{order_type}"}

    def _handle_no_trigger(
        self,
        intent: OrderIntent,
        tif: str,
        fill_open: float,
        detail: str,
    ) -> FillResult:
        if tif in {TimeInForce.GTC.value, TimeInForce.DAY.value}:
            intent.status = "working"
            return FillResult(
                False,
                money(0),
                money(fill_open),
                money(0),
                money(0),
                detail,
                status=FillStatus.WORKING.value,
                remaining_qty=money(intent.qty) if intent.qty is not None else money(0),
                order_type=intent.order_type,
                intent_id=intent.intent_id,
                triggered=False,
            )
        # BAR / IOC / FOK — expire without fill
        intent.status = "cancelled"
        return FillResult(
            False,
            money(0),
            money(fill_open),
            money(0),
            money(0),
            detail + f" — {tif} expired",
            status=FillStatus.CANCELLED.value,
            remaining_qty=money(intent.qty) if intent.qty is not None else money(0),
            order_type=intent.order_type,
            intent_id=intent.intent_id,
            triggered=False,
        )

    def _reject(
        self,
        intent: OrderIntent,
        fill_price: Decimal,
        detail: str,
        order_type: str,
        price_source: str,
    ) -> FillResult:
        intent.status = "rejected"
        return FillResult(
            False,
            money(0),
            fill_price,
            money(0),
            money(0),
            detail,
            status=FillStatus.REJECTED.value,
            remaining_qty=money(intent.qty) if intent.qty is not None else money(0),
            fill_price_source=price_source,
            order_type=order_type,
            intent_id=intent.intent_id,
        )

    def _finalize_partial_or_full(
        self,
        *,
        intent: OrderIntent,
        qty: Decimal,
        qty_requested: Decimal,
        remaining: Decimal,
        fill_price: Decimal,
        fee: Decimal,
        slip_cost: Decimal,
        tif: str,
        order_type: str,
        price_source: str,
        unresolved: bool,
    ) -> FillResult:
        is_partial = remaining > money("0.00000001")
        if is_partial and tif in {TimeInForce.GTC.value, TimeInForce.DAY.value}:
            intent.qty = remaining
            intent.status = "working"
            status = FillStatus.PARTIAL.value
            detail = f"partial {intent.side.lower()} — remainder WORKING ({tif})"
        elif is_partial:
            # BAR / IOC — remainder cancelled (no eternal MARKET)
            intent.qty = money(0)
            intent.status = "filled"
            status = FillStatus.PARTIAL.value
            detail = f"partial {intent.side.lower()} — remainder cancelled ({tif})"
            remaining = money(0)
        else:
            intent.qty = money(0)
            intent.status = "filled"
            status = FillStatus.FILLED.value
            detail = f"filled {intent.side.lower()}"
            remaining = money(0)

        return FillResult(
            True,
            qty,
            fill_price,
            fee,
            slip_cost,
            detail,
            status=status,
            remaining_qty=remaining,
            fill_price_source=price_source,
            order_type=order_type,
            intent_id=intent.intent_id,
            unresolved_intrabar=unresolved,
        )


def make_intent(
    *,
    run_id: str,
    agent_id: str,
    wallet_id: str,
    side: str,
    qty: Any,
    decision_bar_index: int,
    decision_ts: str,
    info_version: str,
    strategy_id: str | None = None,
    strategy_version: int | None = None,
    rationale: str = "",
    confidence: float = 0.0,
    decision_scope: str = "individual",
    metadata: dict[str, Any] | None = None,
    order_type: str = OrderType.MARKET.value,
    limit_price: Any = None,
    stop_price: Any = None,
    time_in_force: str | None = None,
) -> OrderIntent:
    ot = (order_type or OrderType.MARKET.value).upper()
    tif = (time_in_force or default_tif_for_order_type(ot)).upper()
    qty_m = None if qty is None else money(qty)
    intent_id = deterministic_id(
        run_id, agent_id, decision_bar_index, side, qty, info_version, ot, tif,
        limit_price, stop_price,
    )
    return OrderIntent(
        intent_id=intent_id or str(uuid.uuid4()),
        run_id=run_id,
        agent_id=agent_id,
        wallet_id=wallet_id,
        side=side,
        qty=qty_m,
        original_qty=qty_m,
        decision_bar_index=decision_bar_index,
        decision_ts=decision_ts,
        eligible_bar_index=decision_bar_index + 1,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        rationale=rationale,
        confidence=confidence,
        decision_scope=decision_scope,
        info_version=info_version,
        metadata=dict(metadata or {}),
        order_type=ot,
        limit_price=None if limit_price is None else money(limit_price),
        stop_price=None if stop_price is None else money(stop_price),
        time_in_force=tif,
    )


# ---------------------------------------------------------------------------
# W13 — execution laboratory (TWAP/VWAP-style parent→child slices; ASSUMED impact)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporaryImpactAssumption:
    """ASSUMED temporary impact — never MEASURED from OHLCV alone."""

    bps_per_participation_pct: float = 0.5
    status: str = "ASSUMED"
    provenance: str = "linear_participation_impact_v1"

    def impact_bps(self, participation_pct: float) -> float:
        return float(self.bps_per_participation_pct) * max(0.0, float(participation_pct))

    def public_dict(self) -> dict[str, Any]:
        return {
            "bpsPerParticipationPct": self.bps_per_participation_pct,
            "status": self.status,
            "provenance": self.provenance,
            "truth": {
                "impact_from_ohlcv_is_ASSUMED_not_MEASURED": True,
                "observed_execution": False,
            },
        }


@dataclass
class ChildOrderSlice:
    parent_intent_id: str
    slice_index: int
    qty: Decimal
    target_bar_offset: int
    participation_pct: float
    assumed_impact_bps: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "parentIntentId": self.parent_intent_id,
            "sliceIndex": self.slice_index,
            "qty": str(self.qty),
            "targetBarOffset": self.target_bar_offset,
            "participationPct": self.participation_pct,
            "assumedImpactBps": self.assumed_impact_bps,
            "truth": {"observed_execution": False, "child_is_schedule_not_fill": True},
        }


def schedule_twap_slices(
    parent: OrderIntent,
    *,
    n_slices: int,
    bar_volume: float | None = None,
    impact: TemporaryImpactAssumption | None = None,
) -> list[ChildOrderSlice]:
    """Deterministic TWAP-style child schedule from a parent intent.

    Does not fabricate fills or L2 depth. Impact is ASSUMED when configured.
    """
    if n_slices < 1:
        raise ValueError("n_slices must be >= 1")
    if parent.qty is None or parent.qty <= 0:
        return []
    model = impact or TemporaryImpactAssumption()
    slice_qty = (parent.qty / Decimal(n_slices)).quantize(Decimal("0.00000001"))
    # Fix residual on last slice
    allocated = slice_qty * (n_slices - 1)
    last_qty = parent.qty - allocated
    out: list[ChildOrderSlice] = []
    for i in range(n_slices):
        q = last_qty if i == n_slices - 1 else slice_qty
        part = 0.0
        if bar_volume and bar_volume > 0:
            part = float(q) / float(bar_volume) * 100.0
        out.append(
            ChildOrderSlice(
                parent_intent_id=parent.intent_id,
                slice_index=i,
                qty=q,
                target_bar_offset=i,
                participation_pct=part,
                assumed_impact_bps=model.impact_bps(part),
            )
        )
    return out


def schedule_vwap_weights(
    parent: OrderIntent,
    *,
    volume_weights: Sequence[float],
    impact: TemporaryImpactAssumption | None = None,
) -> list[ChildOrderSlice]:
    """Slice parent qty by relative volume weights (ASSUMED schedule, not measured VWAP fill)."""
    weights = [max(0.0, float(w)) for w in volume_weights]
    total = sum(weights)
    if total <= 0 or parent.qty is None or parent.qty <= 0:
        return []
    model = impact or TemporaryImpactAssumption()
    out: list[ChildOrderSlice] = []
    remaining = parent.qty
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            q = remaining
        else:
            q = money(float(parent.qty) * (w / total))
            remaining = remaining - q
        part = (w / total) * 100.0
        out.append(
            ChildOrderSlice(
                parent_intent_id=parent.intent_id,
                slice_index=i,
                qty=q,
                target_bar_offset=i,
                participation_pct=part,
                assumed_impact_bps=model.impact_bps(part),
            )
        )
    return out
