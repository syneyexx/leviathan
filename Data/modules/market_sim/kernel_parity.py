"""G14 — Kernel v2 vs legacy fill-model parity report.

Canonical kernel: NextBarFillModel + WalletLedger (SimulationEngine.step_once).
Legacy: fill_model.FillModel shim over NextBarFillModel (must not diverge on
basic market-order fills).
"""

from __future__ import annotations

from typing import Any

from .accounting import WalletLedger, money
from .execution import NextBarFillModel, make_intent
from .fill_model import FillModel
from .portfolio import Portfolio
from .types import OrderSide


def kernel_legacy_parity_report(
    *,
    open_px: float = 100.0,
    qty: float = 1.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Compare a MARKET BUY fill between canonical and legacy paths."""
    # Canonical
    w_canon = WalletLedger(
        wallet_id="canon",
        owner_id="t",
        owner_kind="agent",
        cash=money(100_000),
    )
    intent = make_intent(
        run_id="parity",
        agent_id="a",
        wallet_id="canon",
        side=OrderSide.BUY.value,
        qty=money(qty),
        decision_bar_index=0,
        decision_ts="2024-01-01T00:00:00Z",
        info_version="parity",
    )
    intent.eligible_bar_index = 1
    canon = NextBarFillModel(fee_bps=fee_bps, slippage_bps=slippage_bps, max_participation=1.0)
    c_fill = canon.execute_intent(
        wallet=w_canon,
        intent=intent,
        fill_open=open_px,
        bar_volume=1_000_000,
        fill_bar_index=1,
        fill_high=open_px,
        fill_low=open_px,
        fill_close=open_px,
    )

    # Legacy Portfolio shim
    port = Portfolio(cash=100_000.0)
    legacy = FillModel(fee_bps=fee_bps, slippage_bps=slippage_bps, max_participation=1.0)
    l_fill = legacy.execute(
        portfolio=port,
        side="BUY",
        qty=qty,
        bar_close=open_px,
        bar_volume=1_000_000,
    )

    price_match = abs(float(c_fill.price) - float(l_fill.price)) < 1e-9
    filled_match = bool(c_fill.filled) == bool(l_fill.filled)
    qty_match = abs(float(c_fill.qty) - float(l_fill.qty)) < 1e-9
    ok = bool(c_fill.filled and l_fill.filled and price_match and qty_match and filled_match)

    return {
        "ok": ok,
        "canonical": {
            "model": "NextBarFillModel",
            "wallet": "WalletLedger",
            "filled": c_fill.filled,
            "qty": str(c_fill.qty),
            "price": str(c_fill.price),
            "fee": str(c_fill.fee),
        },
        "legacy": {
            "model": "FillModel(shim)",
            "portfolio": "Portfolio",
            "filled": l_fill.filled,
            "qty": l_fill.qty,
            "price": l_fill.price,
            "fee": l_fill.fee,
        },
        "checks": {
            "filled_match": filled_match,
            "price_match": price_match,
            "qty_match": qty_match,
        },
        "truth": {
            "canonical_is_next_bar_fill_model": True,
            "legacy_is_shim_only": True,
            "engine_step_once_must_not_use_legacy": True,
            "parity_is_not_microstructure_claim": True,
        },
    }
