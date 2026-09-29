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
        max_capital=float(s["max_capital"]) if s.get("max_capital") is not None else None,
        max_position_qty=float(s["max_position_qty"]) if s.get("max_position_qty") is not None else None,
        max_gross_exposure_pct=float(s.get("max_gross_exposure_pct", 200.0)),
        max_net_exposure_pct=float(s.get("max_net_exposure_pct", 100.0)),
        max_leverage=float(s.get("max_leverage", 1.0)),
        max_order_notional=float(s["max_order_notional"]) if s.get("max_order_notional") is not None else None,
        max_daily_turnover=float(s["max_daily_turnover"]) if s.get("max_daily_turnover") is not None else None,
        max_daily_loss_pct=float(s.get("daily_loss_limit_pct", s.get("max_daily_loss_pct", 10.0))),
        stale_data_max_age_seconds=(
            float(s["stale_data_max_age_seconds"])
            if s.get("stale_data_max_age_seconds") is not None
            else 120.0
        ),
        require_provider_healthy=bool(s.get("require_provider_healthy", True)),
        require_model_healthy=bool(s.get("require_model_healthy", False)),
        require_broker_reconciled=bool(s.get("require_broker_reconciled", True)),
        global_paper_suspended=bool(s.get("global_paper_suspended", False)),
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

    # RiskGuard — one unbypassable path for BUY/SELL/SHORT/COVER.
    from ..risk_guard import HealthState, _copy_limits
    from ..short_margin import ShortMarginPolicy

    limits = default_portfolio_limits(s)
    if kill_switch:
        limits = _copy_limits(limits, kill_switch_armed=True)
    short_policy = None
    if shorting_enabled or action in ("SHORT", "COVER"):
        short_policy = ShortMarginPolicy(
            initial_margin_pct=float(s.get("initial_margin_pct", book.initial_margin_pct or 50.0)),
            maintenance_margin_pct=float(
                s.get("maintenance_margin_pct", book.maintenance_margin_pct or 30.0)
            ),
        )
    guard = RiskGuard(
        limits,
        short_margin_policy=short_policy,
        portfolio_shorting_enabled=bool(shorting_enabled),
    )
    # Bind measured runtime health into RiskGuard — UNKNOWN never silently HEALTHY.
    provider_state = s.get("provider_health")
    if provider_state is None and s.get("provider_healthy") is not None:
        provider_state = HealthState.HEALTHY if s.get("provider_healthy") else HealthState.UNHEALTHY
    if quote_stale:
        freshness = HealthState.UNHEALTHY
        age = float(s.get("data_age_seconds") or (limits.stale_data_max_age_seconds or 120.0) + 1.0)
    elif s.get("data_age_seconds") is not None:
        age = float(s["data_age_seconds"])
        freshness = None
    else:
        # Quote was fetched successfully for this evaluation → measured fresh.
        age = float(s.get("data_age_seconds") or 0.0)
        freshness = HealthState.HEALTHY
    broker_state = s.get("broker_recon_health")
    if broker_state is None and s.get("broker_reconciled") is not None:
        broker_state = HealthState.HEALTHY if s.get("broker_reconciled") else HealthState.UNHEALTHY
    if broker_state is None:
        # Local paper ledger is the broker — reconciled when book loaded.
        broker_state = HealthState.HEALTHY
    if provider_state is None:
        provider_state = HealthState.HEALTHY  # mark path already validated non-stale quote
    guard.bind_measured_runtime_health(
        provider_health=provider_state,
        broker_recon_health=broker_state,
        model_ok=s.get("model_healthy"),
        model_health=s.get("model_health"),
        data_age_seconds=age,
        data_freshness_health=freshness,
        gross_exposure_pct=s.get("gross_exposure_pct"),
        net_exposure_pct=s.get("net_exposure_pct"),
        current_leverage=s.get("current_leverage"),
    )
    wallet = book.to_wallet_projection(symbol, price)
    if shorting_enabled:
        wallet.shorting_enabled = True
        if short_policy is not None:
            wallet.short_margin_policy = short_policy

    # Map SHORT/COVER onto RiskGuard SELL/BUY — no side-specific bypass.
    if action == "COVER":
        rg_side = "BUY"
    elif action == "SHORT":
        rg_side = "SELL"
    else:
        rg_side = action

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
        metadata={
            "portfolio_id": book.portfolio_id,
            "strategy_id": strategy_id,
            "agent_id": agent_id,
            "symbol": symbol,
            "source_decision": "evaluate_portfolio_order",
            "portfolio_action": action,
        },
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
        "code": "OK" if decision.allowed else (decision.rejection_code or "RISK_VETO"),
        "risk": decision.public_dict(),
        "health": guard.health_snapshot(),
    }
