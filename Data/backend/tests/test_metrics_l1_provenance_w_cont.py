"""Wave continuation — bootstrap CIs, CPCV scoring, L1 fills, provenance, futures VM."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.capabilities import execution_granularity_matrix
from Data.modules.market_sim.execution import QuoteL1FillModel, make_intent
from Data.modules.market_sim.futures_contracts import ES_CME
from Data.modules.market_sim.hashes import full_provenance_fingerprint, run_input_fingerprint
from Data.modules.market_sim.metrics import compute_metrics
from Data.modules.market_sim.stats_inferential import score_cpcv_paths
from Data.modules.market_sim.types import OrderSide, OrderType


class MetricsBootstrapCITests(unittest.TestCase):
    def test_compute_metrics_includes_bootstrap_ci(self) -> None:
        equity = [100.0]
        for r in [0.01, -0.005, 0.002, 0.003, -0.001, 0.004]:
            equity.append(equity[-1] * (1 + r))
        m = compute_metrics(equity=equity, fills=[], initial_cash=100.0)
        ci = m["mean_return_bootstrap_ci"]
        self.assertIn(ci["status"], {"MEASURED", "UNMEASURED"})
        self.assertIsNotNone(ci["value"])
        self.assertLessEqual(ci["ci_low"], ci["value"])
        self.assertGreaterEqual(ci["ci_high"], ci["value"])
        self.assertIn("APPROXIMATE", ci["method"])
        self.assertFalse(ci["truth"]["qualification_authority"])

    def test_empty_equity_bootstrap_unmeasured(self) -> None:
        m = compute_metrics(equity=[], fills=[], initial_cash=100.0)
        ci = m["mean_return_bootstrap_ci"]
        self.assertEqual(ci["status"], "UNMEASURED")
        self.assertIsNone(ci["value"])


class CpcvScoringTests(unittest.TestCase):
    def test_cpcv_scores_oos_without_overlap(self) -> None:
        rets = [0.01 * ((-1) ** i) for i in range(60)]
        out = score_cpcv_paths(rets, n_groups=6, n_test_groups=2, purge_bars=1, embargo_bars=1)
        self.assertEqual(out["measurement"], "MEASURED")
        self.assertFalse(out["truth"]["cpcv_geometry_only"])
        self.assertTrue(out["truth"]["cpcv_scored"])
        self.assertTrue(out["truth"]["train_test_overlap_forbidden"])
        self.assertGreater(out["n_paths"], 0)
        for path in out["paths"]:
            self.assertEqual(path["train_test_overlap"], [])


class QuoteL1FillTests(unittest.TestCase):
    def test_buy_fills_at_ask(self) -> None:
        w = WalletLedger(wallet_id="w", owner_id="t", owner_kind="agent", cash=money(10000))
        intent = make_intent(
            run_id="r1",
            agent_id="a1",
            wallet_id="w",
            side=OrderSide.BUY.value,
            qty=money(1),
            decision_bar_index=0,
            decision_ts="2024-01-01T00:00:00Z",
            info_version="iv1",
        )
        # Force eligible now for unit test
        intent.eligible_bar_index = 0
        model = QuoteL1FillModel(fee_bps=0)
        fill = model.execute_intent(wallet=w, intent=intent, bid=99.0, ask=101.0, fill_bar_index=0)
        self.assertTrue(fill.filled)
        self.assertEqual(float(fill.price), 101.0)
        self.assertEqual(fill.fill_price_source, "ask")

    def test_missing_quotes_fail_closed(self) -> None:
        w = WalletLedger(wallet_id="w", owner_id="t", owner_kind="agent", cash=money(10000))
        intent = make_intent(
            run_id="r1",
            agent_id="a1",
            wallet_id="w",
            side=OrderSide.BUY.value,
            qty=money(1),
            decision_bar_index=0,
            decision_ts="2024-01-01T00:00:00Z",
            info_version="iv1",
        )
        intent.eligible_bar_index = 0
        fill = QuoteL1FillModel().execute_intent(
            wallet=w, intent=intent, bid=None, ask=None, fill_bar_index=0
        )
        self.assertFalse(fill.filled)
        self.assertIn("L1_QUOTES_REQUIRED", fill.detail)

    def test_l1_capability_supported(self) -> None:
        rows = {r["granularity"]: r for r in execution_granularity_matrix()}
        self.assertEqual(rows["QUOTE_L1"]["status"], "SUPPORTED")
        self.assertEqual(rows["QUOTE_L1"]["fill_model"], "QuoteL1FillModel")
        self.assertEqual(rows["BOOK_L2"]["status"], "UNSUPPORTED")
        self.assertTrue(rows["BOOK_L2"]["truth"]["synthetic_l2_forbidden"])


class ProvenanceFingerprintTests(unittest.TestCase):
    def test_full_provenance_stable(self) -> None:
        rip = run_input_fingerprint(
            dataset_content_hash="abc",
            strategy_content_hash="s1",
            seed=1,
            fee_bps=5,
            slippage_bps=2,
        )
        a = full_provenance_fingerprint(
            run_input_fp=rip,
            dataset_content_hash="abc",
            dataset_version="v1",
            split_manifest_hash="sm1",
            objective_hash="obj1",
            strategy_version="1",
            trial_ledger_refs=["t1", "t2"],
        )
        b = full_provenance_fingerprint(
            run_input_fp=rip,
            dataset_content_hash="abc",
            dataset_version="v1",
            split_manifest_hash="sm1",
            objective_hash="obj1",
            strategy_version="1",
            trial_ledger_refs=["t1", "t2"],
        )
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        self.assertTrue(a["truth"]["reconstructable_qualification_evidence"])
        # Mutation of lineage changes fingerprint
        c = full_provenance_fingerprint(
            run_input_fp=rip,
            dataset_content_hash="abc",
            dataset_version="v2",
            split_manifest_hash="sm1",
            objective_hash="obj1",
            strategy_version="1",
        )
        self.assertNotEqual(a["fingerprint"], c["fingerprint"])


class FuturesVariationMarginTests(unittest.TestCase):
    def test_futures_multiplier(self) -> None:
        # ES multiplier 50: 1 pt move on 2 contracts = $100
        vm = ES_CME.variation_margin(2, 5000, 5001)
        self.assertEqual(float(vm), 100.0)
        self.assertEqual(float(ES_CME.notional(2, 5000)), 500_000.0)

    def test_wallet_futures_vm_path(self) -> None:
        w = WalletLedger(
            wallet_id="w",
            owner_id="t",
            owner_kind="agent",
            cash=money(50_000),
            primary_symbol="ES",
            valuation_mode="futures_vm",
            contract_multiplier=money(50),
        )
        w.apply_buy(qty=2, price=5000, fee=0, tx_id="open", symbol="ES")
        # Open must NOT debit full notional
        self.assertEqual(float(w.cash), 50_000.0)
        out = w.apply_variation_margin(
            qty=2,
            price_from=5000,
            price_to=5001,
            multiplier=50,
            tx_id="vm1",
            symbol="ES",
        )
        self.assertTrue(out["applied"])
        self.assertEqual(float(w.cash), 50_100.0)
        w.assert_invariants(5001)

    def test_futures_hist_capability_available(self) -> None:
        from Data.modules.market_sim.capabilities import build_market_capabilities

        caps = build_market_capabilities(feature_enabled=True, binance_reachable=False, alpaca_paper=False)
        by_fam = {m["family"]: m for m in caps["markets"]}
        self.assertEqual(by_fam["futures"]["HISTORICAL_SIM_AVAILABLE"], "AVAILABLE")
        self.assertEqual(by_fam["forex"]["HISTORICAL_SIM_AVAILABLE"], "AVAILABLE")
        self.assertEqual(by_fam["options"]["HISTORICAL_SIM_AVAILABLE"], "NOT_IMPLEMENTED")
        self.assertEqual(by_fam["futures"]["LIVE_TRADING_AVAILABLE"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
