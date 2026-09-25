"""Portfolio-level allocation gate + RiskGuard integration.

AI Risk Officer may recommend; RiskGuard remains final authority.
"""

from __future__ import annotations

from typing import Any

from ..accounting import D, ZERO, money
from ..execution import OrderIntent
from ..risk_guard import RiskDecision, RiskGuard, RiskLimits
from .ledger import PortfolioBook


def default_portfolio_limits(settings: dict[str, Any] | None = None) -> RiskLimits:
    s = settings or {}
    return RiskLimits(
        max_position_pct=float(s.get("max_position_pct", 25.0)),
        max_drawdown_pct=float(s.get("max_drawdown_pct", 20.0)),
        per_trade_risk_pct=float(s.get("per_trade_risk_pct", 1.0)),
        max_orders_per_day=int(s.get("max_orders_per_day", 50)),
        max_symbol_exposure_pct=float(s.get("max_symbol_exposure_pct", s.get("asset_concentration_pct", 40.0))),
        leverage_allowed=bool(s.get("leverage_allowed", float(s.get("max_leverage", 1.0)) > 1.0)),
        kill_switch_armed=bool(s.get("kill_switch_armed", False)),
    )


def check_allocation_gate(
    *,
    book: PortfolioBook,
    marks: dict[str, Any],
    side: str,
    symbol: str,
    qty: float,
    price: float,
    agent_id: str | None,
    strategy_id: str | None,
    allocations: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Ceiling/budget check for agent and strategy allocations."""
    s = settings or {}
    eq = float(book.equity(marks))
    if eq <= 0:
        return False, "portfolio equity is zero"
    notional = abs(qty * price)
    action = side.upper()

    # Cash reserve for new risk-increasing buys/shorts
    cash_reserve_pct = float(s.get("cash_reserve_pct", 10.0))
    if action in ("BUY", "SHORT"):
        min_cash = eq * cash_reserve_pct / 100.0
        cash_after = float(book.available_cash) - (notional if action == "BUY" else notional * float(s.get("initial_margin_pct", 50)) / 100.0)
        if cash_after < min_cash - 1e-6:
            return False, f"cash reserve below configured threshold ({cash_reserve_pct}%)"

    agent_ceiling = float(s.get("agent_allocation_ceiling_pct", 100.0))
    strategy_ceiling = float(s.get("strategy_allocation_ceiling_pct", 100.0))

    def _budget(kind: str, target_id: str | None) -> float | None:
        if not target_id:
            return None
        for a in allocations:
            if a.get("kind") == kind and str(a.get("target_id")) == str(target_id) and a.get("active", True):
                return float(a.get("target_allocation_pct") or 0) / 100.0 * eq
        return None

    if agent_id and action in ("BUY", "SHORT"):
        used = 0.0
        for pos in book.open_positions_public(marks):
            if pos.get("agent_id") == agent_id:
                used += abs(float(pos["market_value"]))
        budget = _budget("agent", agent_id)
        if budget is not None and used + notional > budget + 1e-6:
            return False, f"agent allocation exceeded for {agent_id}"
        ceiling_budget = eq * agent_ceiling / 100.0
        if used + notional > ceiling_budget + 1e-6:
            return False, f"agent allocation ceiling ({agent_ceiling}%) exceeded"

    if strategy_id and action in ("BUY", "SHORT"):
        used = 0.0
        for pos in book.open_positions_public(marks):
            if pos.get("strategy_id") == strategy_id:
                used += abs(float(pos["market_value"]))
        budget = _budget("strategy", strategy_id)
        if budget is not None and used + notional > budget + 1e-6:
            return False, f"strategy allocation exceeded for {strategy_id}"
        ceiling_budget = eq * strategy_ceiling / 100.0
        if used + notional > ceiling_budget + 1e-6:
            return False, f"strategy allocation ceiling ({strategy_ceiling}%) exceeded"

    # Gross / net exposure
    max_gross = float(s.get("max_gross_exposure_pct", 200.0))
    max_net = float(s.get("max_net_exposure_pct", 150.0))
    max_lev = float(s.get("max_leverage", 1.0))
    signed = notional if action in ("BUY",) else (-notional if action in ("SELL", "SHORT") else 0)
    new_gross = float(book.gross_exposure(marks)) + (notional if action in ("BUY", "SHORT") else 0)
    new_net = float(book.net_exposure(marks)) + signed
    if eq > 0:
        if new_gross / eq * 100 > max_gross + 1e-6 and action in ("BUY", "SHORT"):
            return False, f"max gross exposure ({max_gross}%) exceeded"
        if abs(new_net) / eq * 100 > max_net + 1e-6 and action in ("BUY", "SHORT"):
            return False, f"max net exposure ({max_net}%) exceeded"
        if new_gross / eq > max_lev + 1e-6 and action in ("BUY", "SHORT"):
            return False, f"max leverage ({max_lev}x) exceeded"

    return True, "allocation_ok"


def evaluate_portfolio_order(
    *,
    book: PortfolioBook,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    marks: dict[str, Any],
    settings: dict[str, Any] | None = None,
    allocations: list[dict[str, Any]] | None = None,
    agent_id: str | None = None,
    strategy_id: str | None = None,
    kill_switch: bool = False,
    quote_stale: bool = False,
    shorting_enabled: bool = False,
) -> dict[str, Any]:
    """Full gate: stale quote → kill switch → allocation → RiskGuard → short policy."""
    s = dict(settings or {})
    action = side.upper()

    if quote_stale and action in ("BUY", "SELL", "SHORT", "COVER"):
        # Allow risk-reducing closes even when stale if configured
        reducing = action in ("SELL", "COVER") or (
            action == "SELL" and book.positions.get(symbol.upper()) and book.positions[symbol.upper()].side == "LONG"
        )
        if not reducing:
            return {
                "allowed": False,
                "reason": "market quote stale — new risk blocked",
                "sized_qty": 0.0,
                "code": "STALE_QUOTE",
            }

    if kill_switch:
        reducing = False
        pos = book.positions.get(symbol.upper())
        if pos and pos.qty > ZERO:
            if action == "SELL" and pos.side == "LONG":
                reducing = True
            if action == "COVER" and pos.side == "SHORT":
                reducing = True
        if not reducing:
            return {
                "allowed": False,
                "reason": "kill switch armed",
                "sized_qty": 0.0,
                "code": "KILL_SWITCH",
            }

    if action == "SHORT" and not shorting_enabled:
        return {
            "allowed": False,
            "reason": "shorting disabled",
            "sized_qty": 0.0,
            "code": "SHORTING_DISABLED",
        }

    if action == "SELL" and not shorting_enabled:
        pos = book.positions.get(symbol.upper())
        long_qty = float(pos.qty) if pos and pos.side == "LONG" else 0.0
        if qty > long_qty + 1e-12 and long_qty <= 0:
            return {
                "allowed": False,
                "reason": "no long position to sell; shorting disabled",
                "sized_qty": 0.0,
                "code": "SHORTING_DISABLED",
            }

    ok, reason = check_allocation_gate(
        book=book,
        marks=marks,
        side=action,
        symbol=symbol,
        qty=qty,
        price=price,
        agent_id=agent_id,
        strategy_id=strategy_id,
        allocations=allocations or [],
        settings=s,
    )
    if not ok:
        return {
            "allowed": False,
            "reason": reason,
            "sized_qty": 0.0,
            "code": "ALLOCATION_BLOCK",
        }

    # Daily loss
    daily_loss_limit = float(s.get("daily_loss_limit_pct", 10.0))
    sod = float(s.get("sod_equity") or float(book.equity(marks)))
    if sod > 0:
        daily_pnl_pct = (float(book.equity(marks)) - sod) / sod * 100.0
        if daily_pnl_pct <= -daily_loss_limit and action in ("BUY", "SHORT"):
            return {
                "allowed": False,
                "reason": f"daily loss limit ({daily_loss_limit}%) exceeded",
                "sized_qty": 0.0,
                "code": "DAILY_LOSS",
            }

    # RiskGuard on projected wallet (long path)
    limits = default_portfolio_limits(s)
    if kill_switch:
        limits = RiskLimits(
            max_position_pct=limits.max_position_pct,
            max_drawdown_pct=limits.max_drawdown_pct,
            per_trade_risk_pct=limits.per_trade_risk_pct,
            max_orders_per_day=limits.max_orders_per_day,
            max_symbol_exposure_pct=limits.max_symbol_exposure_pct,
            leverage_allowed=limits.leverage_allowed,
            kill_switch_armed=True,
        )
    guard = RiskGuard(limits)
    wallet = book.to_wallet_projection(symbol, price)
    # Map SHORT/COVER to SELL/BUY for RiskGuard long-oriented evaluate when needed
    rg_side = action
    if action == "COVER":
        rg_side = "BUY"
    elif action == "SHORT":
        # Skip RiskGuard long sizing; portfolio gate already checked margin
        return {
            "allowed": True,
            "reason": "short_sized",
            "sized_qty": float(qty),
            "code": "OK",
            "risk": {"allowed": True, "reason": "short_via_portfolio_gate", "sized_qty": float(qty)},
        }

    from ..accounting import D as _D
    from ..paper_broker import utc_now

    intent = OrderIntent(
        intent_id="pf-intent",
        run_id=book.portfolio_id,
        agent_id=agent_id or "manual",
        wallet_id=wallet.wallet_id,
        side=rg_side if rg_side in ("BUY", "SELL", "HOLD") else "HOLD",
        qty=_D(qty),
        decision_bar_index=0,
        decision_ts=utc_now(),
        eligible_bar_index=0,
        strategy_id=strategy_id,
    )
    dd = book.drawdown_pct(marks)
    if dd >= limits.max_drawdown_pct and action in ("BUY", "SHORT"):
        return {
            "allowed": False,
            "reason": f"max drawdown ({limits.max_drawdown_pct}%) exceeded",
            "sized_qty": 0.0,
            "code": "MAX_DRAWDOWN",
            "risk": {"allowed": False, "reason": "max drawdown", "sized_qty": 0.0},
        }

    decision: RiskDecision = guard.evaluate_intent(intent, wallet=wallet, price=price)
    return {
        "allowed": bool(decision.allowed),
        "reason": decision.reason,
        "sized_qty": float(decision.sized_qty) if decision.allowed else 0.0,
        "code": "OK" if decision.allowed else "RISK_VETO",
        "risk": decision.public_dict(),
    }
