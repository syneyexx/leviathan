"""Wave 18 — paper trading safety kill controls on RiskGuard."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.execution import OrderIntent
from Data.modules.market_sim.risk_guard import RiskGuard, RiskLimits


def _wallet(cash: float = 10_000.0, qty: float = 0.0) -> WalletLedger:
    return WalletLedger(
        wallet_id="w1",
        owner_id="paper",
        owner_kind="paper_session",
        cash=money(cash),
        position_qty=money(qty),
        avg_entry=money(100 if qty else 0),
        peak_equity=money(cash),
    )


def _intent(side: str = "BUY", qty: float | None = 1.0, **meta: object) -> OrderIntent:
    return OrderIntent(
        intent_id="i1",
        run_id="r1",
        agent_id="a1",
        wallet_id="w1",
        side=side,
        qty=None if qty is None else money(qty),
        decision_bar_index=0,
        decision_ts="2026-01-01T00:00:00+00:00",
        eligible_bar_index=1,
        metadata=dict(meta),
    )


def _guard(limits: RiskLimits | None = None) -> RiskGuard:
    """RiskGuard with measured healthy runtime — required after fail-closed defaults."""
    guard = RiskGuard(limits or RiskLimits())
    guard.bind_measured_runtime_health(
        provider_ok=True,
        broker_ok=True,
        data_age_seconds=0.0,
    )
    return guard


class PaperSafetyKillControlTests(unittest.TestCase):
    def test_llm_cannot_bypass(self) -> None:
        guard = _guard()
        decision = guard.evaluate_intent(
            _intent(bypass_risk=True, approved_by_model=True),
            wallet=_wallet(),
            price=100.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rejection_code, "LLM_OVERRIDE_REJECTED")
        self.assertTrue(decision.persisted)
        self.assertTrue(guard.rejection_log)

    def test_kill_switch_and_global_paper_suspension(self) -> None:
        guard = _guard()
        guard.suspend_global_paper("ops halt")
        decision = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(decision.allowed)
        self.assertIn(decision.rejection_code, {"GLOBAL_PAPER_SUSPENDED", "KILL_SWITCH"})
        # Risk reduction still allowed when configured.
        wal = _wallet(qty=2.0)
        sell = guard.evaluate_intent(_intent(side="SELL", qty=1.0), wallet=wal, price=100.0)
        self.assertTrue(sell.allowed)

    def test_per_strategy_suspension(self) -> None:
        guard = _guard()
        guard.suspend_strategy("strat-x")
        denied = guard.evaluate_intent(
            _intent(strategy_id="strat-x"),
            wallet=_wallet(),
            price=100.0,
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.rejection_code, "STRATEGY_SUSPENDED")
        allowed = guard.evaluate_intent(
            _intent(strategy_id="strat-y"),
            wallet=_wallet(),
            price=100.0,
        )
        self.assertTrue(allowed.allowed)

    def test_stale_provider_model_broker_stops(self) -> None:
        guard = _guard(
            RiskLimits(
                stale_data_max_age_seconds=30.0,
                require_provider_healthy=True,
                require_model_healthy=True,
                require_broker_reconciled=True,
            )
        )
        guard.update_health(data_age_seconds=90.0, model_healthy=True)
        self.assertEqual(
            guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0).rejection_code,
            "STALE_DATA_STOP",
        )
        guard.update_health(data_age_seconds=1.0, provider_healthy=False)
        self.assertEqual(
            guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0).rejection_code,
            "PROVIDER_HEALTH_STOP",
        )
        guard.update_health(provider_healthy=True, model_degraded=True)
        self.assertEqual(
            guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0).rejection_code,
            "MODEL_HEALTH_STOP",
        )
        guard.update_health(model_degraded=False, model_healthy=True, broker_reconciled=False)
        self.assertEqual(
            guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0).rejection_code,
            "BROKER_RECONCILIATION_STOP",
        )

    def test_exposure_leverage_notional_turnover_caps(self) -> None:
        guard = _guard(
            RiskLimits(
                max_order_notional=50.0,
                max_gross_exposure_pct=50.0,
                max_leverage=1.0,
                leverage_allowed=False,
                max_daily_turnover=200.0,
                max_position_qty=5.0,
                max_capital=50_000.0,
            )
        )
        # Order notional cap
        d = guard.evaluate_intent(_intent(qty=10.0), wallet=_wallet(), price=100.0)
        self.assertTrue(d.allowed)
        self.assertLessEqual(d.sized_qty * 100.0, 50.0 + 1e-6)

        # Gross exposure stop
        guard.update_health(gross_exposure_pct=80.0)
        denied = guard.evaluate_intent(_intent(qty=0.1), wallet=_wallet(), price=100.0)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.rejection_code, "MAX_GROSS_EXPOSURE")
        guard.update_health(gross_exposure_pct=10.0)

        # Daily turnover stop
        guard.record_fill_turnover(200.0)
        denied_t = guard.evaluate_intent(_intent(qty=0.1), wallet=_wallet(), price=100.0)
        self.assertFalse(denied_t.allowed)
        self.assertEqual(denied_t.rejection_code, "MAX_DAILY_TURNOVER")

    def test_drawdown_and_daily_loss_arm_kill(self) -> None:
        guard = _guard(RiskLimits(max_drawdown_pct=10.0, max_daily_loss_pct=5.0))
        wal = _wallet(cash=8_000.0)
        wal.peak_equity = money(10_000.0)
        self.assertFalse(guard.check_drawdown(wal, 100.0))
        self.assertTrue(guard.kill_switch_state()["armed"])

        guard2 = _guard(RiskLimits(max_daily_loss_pct=5.0))
        wal2 = _wallet(cash=10_000.0)
        guard2.day_start_equity = 10_000.0
        wal2.cash = money(9_000.0)  # -10% mark
        denied = guard2.evaluate_intent(_intent(), wallet=wal2, price=100.0)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.rejection_code, "DAILY_LOSS_STOP")

    def test_rejection_reasons_persisted(self) -> None:
        guard = _guard(RiskLimits(require_provider_healthy=True))
        guard.update_health(provider_healthy=False)
        d = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertTrue(d.persisted)
        self.assertEqual(guard.rejection_log[-1]["rejection_code"], "PROVIDER_HEALTH_STOP")
        pub = d.public_dict()
        self.assertTrue(pub["truth"]["llm_cannot_bypass"])


if __name__ == "__main__":
    unittest.main()
