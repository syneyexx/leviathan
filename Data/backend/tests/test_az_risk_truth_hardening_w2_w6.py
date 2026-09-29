"""A–Z Waves 2–6: RiskGuard fail-closed health, SHORT path, durable receipts, evidence honesty."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.autonomous_paper_loop import (
    autonomous_paper_evidence_receipt,
    build_a3_promotion_evidence,
    build_a4_promotion_evidence,
    shadow_evidence_receipt,
)
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.execution import OrderIntent
from Data.modules.market_sim.portefeuille.ledger import PortfolioBook
from Data.modules.market_sim.portefeuille.risk import evaluate_portfolio_order
from Data.modules.market_sim.risk_guard import HealthState, RiskGuard, RiskLimits
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.short_margin import ShortMarginPolicy
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


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


def _healthy(guard: RiskGuard) -> RiskGuard:
    guard.bind_measured_runtime_health(
        provider_ok=True,
        broker_ok=True,
        data_age_seconds=0.0,
    )
    return guard


class FailClosedHealthTests(unittest.TestCase):
    def test_unknown_defaults_are_not_healthy(self) -> None:
        guard = RiskGuard(RiskLimits())
        snap = guard.health_snapshot()
        self.assertEqual(snap["provider_health"], HealthState.UNKNOWN.value)
        self.assertEqual(snap["broker_recon_health"], HealthState.UNKNOWN.value)
        self.assertEqual(snap["data_freshness_health"], HealthState.UNKNOWN.value)
        self.assertFalse(guard.provider_healthy)

    def test_unknown_provider_blocks_new_risk(self) -> None:
        guard = RiskGuard(RiskLimits(require_provider_healthy=True))
        # freshness still unknown — bind only broker so provider stays UNKNOWN
        guard.update_health(broker_reconciled=True, data_age_seconds=0.0)
        d = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(d.allowed)
        self.assertEqual(d.rejection_code, "PROVIDER_HEALTH_UNKNOWN")

    def test_unknown_freshness_blocks_new_risk(self) -> None:
        guard = RiskGuard(RiskLimits(require_provider_healthy=True, stale_data_max_age_seconds=30.0))
        guard.update_health(provider_healthy=True, broker_reconciled=True)
        # data_age unset → freshness UNKNOWN
        d = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(d.allowed)
        self.assertEqual(d.rejection_code, "DATA_FRESHNESS_UNKNOWN")

    def test_stale_feed_blocks_new_risk(self) -> None:
        guard = _healthy(RiskGuard(RiskLimits(stale_data_max_age_seconds=30.0)))
        guard.update_health(data_age_seconds=90.0)
        d = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(d.allowed)
        self.assertEqual(d.rejection_code, "STALE_DATA_STOP")

    def test_provider_outage_blocks_new_risk(self) -> None:
        guard = _healthy(RiskGuard(RiskLimits(require_provider_healthy=True)))
        guard.update_health(provider_healthy=False)
        d = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(d.allowed)
        self.assertEqual(d.rejection_code, "PROVIDER_HEALTH_STOP")

    def test_reconciliation_failure_blocks_new_risk(self) -> None:
        guard = _healthy(RiskGuard(RiskLimits(require_broker_reconciled=True)))
        guard.update_health(broker_reconciled=False)
        d = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(d.allowed)
        self.assertEqual(d.rejection_code, "BROKER_RECONCILIATION_STOP")

    def test_kill_switch_blocks_new_risk_allows_reduction(self) -> None:
        guard = _healthy(RiskGuard(RiskLimits()))
        guard.arm_kill_switch("ops")
        denied = guard.evaluate_intent(_intent(), wallet=_wallet(), price=100.0)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.rejection_code, "KILL_SWITCH")
        sell = guard.evaluate_intent(
            _intent(side="SELL", qty=1.0),
            wallet=_wallet(qty=2.0),
            price=100.0,
        )
        self.assertTrue(sell.allowed)

    def test_unknown_never_silently_becomes_healthy_boolean(self) -> None:
        guard = RiskGuard(RiskLimits())
        self.assertIs(guard.provider_health, HealthState.UNKNOWN)
        self.assertFalse(bool(guard.provider_healthy))


class ShortThroughRiskGuardTests(unittest.TestCase):
    def test_portfolio_short_goes_through_riskguard(self) -> None:
        book = PortfolioBook(
            portfolio_id="pf1",
            cash=money(50_000),
            shorting_enabled=True,
        )
        marks = {"XYZ": 100.0}
        # Kill switch must block SHORT (previously bypassed RiskGuard)
        gate = evaluate_portfolio_order(
            book=book,
            symbol="XYZ",
            side="SHORT",
            qty=10.0,
            price=100.0,
            marks=marks,
            settings={},
            kill_switch=True,
            shorting_enabled=True,
        )
        self.assertFalse(gate.get("allowed"))
        self.assertEqual(gate.get("code"), "KILL_SWITCH")

    def test_portfolio_short_riskguard_sizes_and_margins(self) -> None:
        book = PortfolioBook(
            portfolio_id="pf1",
            cash=money(1_000),  # insufficient for large short margin
            shorting_enabled=True,
            initial_margin_pct=money(50),
            maintenance_margin_pct=money(30),
        )
        gate = evaluate_portfolio_order(
            book=book,
            symbol="XYZ",
            side="SHORT",
            qty=100.0,
            price=100.0,
            marks={"XYZ": 100.0},
            settings={"initial_margin_pct": 50.0, "maintenance_margin_pct": 30.0},
            shorting_enabled=True,
        )
        # Must not return short_via_portfolio_gate bypass
        risk = gate.get("risk") or {}
        self.assertNotEqual(risk.get("reason"), "short_via_portfolio_gate")
        if gate.get("allowed"):
            self.assertLessEqual(float(gate["sized_qty"]) * 100.0 * 0.5, 1_000.0 + 1.0)
        else:
            self.assertIn(
                gate.get("code"),
                {
                    "RISK_VETO",
                    "INSUFFICIENT_MARGIN",
                    "MARGIN_BLOCK",
                    "INSUFFICIENT_SIZE",
                    "MAX_LEVERAGE",
                    "MAX_GROSS_EXPOSURE",
                    "ALLOCATION_BLOCK",
                },
            )


class DurableRiskReceiptTests(unittest.TestCase):
    def test_rejection_survives_store_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "market.db")
            store.initialize()
            sink_ids: list[str] = []

            def sink(entry: dict) -> None:
                saved = store.save_risk_receipt(entry)
                sink_ids.append(saved["receipt_id"])

            guard = _healthy(
                RiskGuard(
                    RiskLimits(require_provider_healthy=True),
                    receipt_sink=sink,
                )
            )
            guard.update_health(provider_healthy=False)
            d = guard.evaluate_intent(
                _intent(strategy_id="s1", symbol="BTC", decision_id="d1"),
                wallet=_wallet(),
                price=100.0,
            )
            self.assertFalse(d.allowed)
            self.assertTrue(d.durable_persisted)
            self.assertTrue(sink_ids)
            loaded = store.get_risk_receipt(sink_ids[0])
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["rejection_code"], "PROVIDER_HEALTH_STOP")
            self.assertEqual(loaded["persistence_status"], "DURABLE")
            self.assertEqual(loaded["health"]["provider_health"], HealthState.UNHEALTHY.value)


class EvidenceHonestyTests(unittest.TestCase):
    def test_shadow_measured_is_not_automatic_pass(self) -> None:
        obs = [
            {"observation_id": f"o{i}", "signal_side": "BUY", "feed_status": "unknown"}
            for i in range(5)
        ]
        receipt = shadow_evidence_receipt(shadow_run_id="s1", observations=obs)
        self.assertEqual(receipt["status"], "MEASURED")
        self.assertFalse(receipt["paper_shadow_pass"])
        self.assertEqual(receipt["result"], "FAIL")
        self.assertFalse(receipt["feed_reliable"])

    def test_shadow_pass_requires_feed_reliability(self) -> None:
        obs = [
            {"observation_id": f"o{i}", "signal_side": "BUY", "feed_status": "live"}
            for i in range(5)
        ]
        receipt = shadow_evidence_receipt(shadow_run_id="s1", observations=obs)
        self.assertTrue(receipt["paper_shadow_pass"])

    def test_autonomous_paper_count_alone_not_pass_with_errors(self) -> None:
        steps = [
            {"step_id": f"s{i}", "allowed": True, "error": "boom"} for i in range(5)
        ]
        receipt = autonomous_paper_evidence_receipt(
            paper_deployment_id="dep",
            paper_session_id="sess",
            step_receipts=steps,
        )
        self.assertEqual(receipt["status"], "MEASURED")
        self.assertFalse(receipt["autonomous_paper_pass"])

    def test_a3_does_not_invent_acceptance_without_evidence(self) -> None:
        obs = [
            {"observation_id": f"o{i}", "signal_side": "BUY", "feed_status": "live"}
            for i in range(5)
        ]
        shadow = shadow_evidence_receipt(shadow_run_id="s1", observations=obs)
        ev = build_a3_promotion_evidence(shadow_receipt=shadow)
        self.assertFalse(ev["sealed_pass"])
        self.assertEqual(ev["acceptance"]["measurement"], "UNMEASURED")
        self.assertFalse(ev["acceptance"]["passed"])

    def test_a4_does_not_hardcode_sealed_pass(self) -> None:
        steps = [{"step_id": f"s{i}", "allowed": True} for i in range(5)]
        paper = autonomous_paper_evidence_receipt(
            paper_deployment_id="dep",
            paper_session_id="sess",
            step_receipts=steps,
        )
        self.assertTrue(paper["autonomous_paper_pass"])
        ev = build_a4_promotion_evidence(paper_receipt=paper)
        self.assertFalse(ev["sealed_pass"])
        self.assertEqual(ev["acceptance"]["measurement"], "UNMEASURED")

    def test_a4_with_sealed_attempt_resolves_lineage(self) -> None:
        steps = [{"step_id": f"s{i}", "allowed": True} for i in range(5)]
        paper = autonomous_paper_evidence_receipt(
            paper_deployment_id="dep",
            paper_session_id="sess",
            step_receipts=steps,
        )
        ev = build_a4_promotion_evidence(
            paper_receipt=paper,
            sealed_attempt_id="sealed-1",
        )
        self.assertTrue(ev["sealed_pass"])
        self.assertEqual(ev["acceptance"]["criteria_id"], "sealed_attempt_lineage")

    def test_failed_shadow_blocks_a3_builder(self) -> None:
        obs = [
            {"observation_id": f"o{i}", "signal_side": "BUY", "feed_status": "unknown"}
            for i in range(5)
        ]
        shadow = shadow_evidence_receipt(shadow_run_id="s1", observations=obs)
        with self.assertRaises(MarketSimError) as ctx:
            build_a3_promotion_evidence(shadow_receipt=shadow)
        self.assertEqual(ctx.exception.code, "SHADOW_EVIDENCE_FAILED")


class OperatingProfileStubTests(unittest.TestCase):
    """Wave 12 precursor — profile constant must exist once profile module lands."""

    def test_profile_module_exports_autonomous_paper_real_data(self) -> None:
        from Data.modules.market_sim.operating_profiles import (
            AUTONOMOUS_PAPER_REAL_DATA,
            OperatingProfile,
            resolve_operating_profile,
        )

        self.assertEqual(AUTONOMOUS_PAPER_REAL_DATA, "AUTONOMOUS_PAPER_REAL_DATA")
        profile = resolve_operating_profile(AUTONOMOUS_PAPER_REAL_DATA)
        self.assertIsInstance(profile, OperatingProfile)
        self.assertTrue(profile.real_market_data)
        self.assertTrue(profile.paper_only)
        self.assertFalse(profile.live_money_allowed)
        self.assertTrue(profile.deterministic_risk_guard)


if __name__ == "__main__":
    unittest.main()
