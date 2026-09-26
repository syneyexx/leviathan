"""W13 — Trading Lab I: PIT universe, multi-symbol WalletBook, costs, inferential stats."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.accounting import WalletBook, WalletLedger, money
from Data.modules.market_sim.costs import CostModelPack
from Data.modules.market_sim.instruments import InstrumentFamily, InstrumentSpec
from Data.modules.market_sim.stats_inferential import (
    benjamini_hochberg,
    block_bootstrap_mean,
    combinatorial_purged_cv_paths,
    deflated_sharpe_ratio,
    minimum_useful_sample,
    monte_carlo_mean_resample,
    probability_of_backtest_overfitting,
    purge_embargo_indices,
    sharpe_ratio,
)
from Data.modules.market_sim.types import MetricStatus
from Data.modules.market_sim.universe import (
    CorporateAction,
    DatasetRevisionIdentity,
    MembershipEvent,
    MembershipEventKind,
    PointInTimeUniverse,
    SessionCalendarDay,
)

class PointInTimeUniverseTests(unittest.TestCase):
    def _universe(self) -> PointInTimeUniverse:
        return PointInTimeUniverse(
            events=[
                MembershipEvent("AAA", MembershipEventKind.LISTED, "2020-01-01T00:00:00Z"),
                MembershipEvent("BBB", MembershipEventKind.LISTED, "2020-01-01T00:00:00Z"),
                MembershipEvent("CCC", MembershipEventKind.LISTED, "2021-06-01T00:00:00Z"),
                MembershipEvent("BBB", MembershipEventKind.DELISTED, "2022-01-01T00:00:00Z"),
                MembershipEvent(
                    "AAA",
                    MembershipEventKind.RENAMED,
                    "2023-01-01T00:00:00Z",
                    new_symbol="AAA_NEW",
                ),
            ],
            corporate_actions=[
                CorporateAction("AAA", "split", "2021-03-01T00:00:00Z", factor=2.0),
                CorporateAction("AAA", "dividend", "2021-06-15T00:00:00Z", cash_amount=0.5),
            ],
            calendar=[
                SessionCalendarDay("2021-12-25", "holiday", exchange="NASDAQ", timezone="America/New_York"),
                SessionCalendarDay(
                    "2021-12-27",
                    "open",
                    open_ts="2021-12-27T14:30:00Z",
                    close_ts="2021-12-27T21:00:00Z",
                    exchange="NASDAQ",
                    timezone="America/New_York",
                ),
            ],
        )

    def test_as_of_membership_excludes_future_listings_and_delistings(self) -> None:
        u = self._universe()
        self.assertEqual(u.as_of_membership("2020-06-01T00:00:00Z"), {"AAA", "BBB"})
        self.assertEqual(u.as_of_membership("2021-07-01T00:00:00Z"), {"AAA", "BBB", "CCC"})
        self.assertEqual(u.as_of_membership("2022-06-01T00:00:00Z"), {"AAA", "CCC"})
        self.assertEqual(u.as_of_membership("2023-06-01T00:00:00Z"), {"AAA_NEW", "CCC"})

    def test_delisted_do_not_silently_vanish_from_event_history(self) -> None:
        u = self._universe()
        kinds = {(e.symbol, e.kind) for e in u.events}
        self.assertIn(("BBB", MembershipEventKind.DELISTED), kinds)
        self.assertIn(("BBB", MembershipEventKind.LISTED), kinds)

    def test_today_universe_must_be_labelled(self) -> None:
        labelled = PointInTimeUniverse(
            events=[MembershipEvent("X", MembershipEventKind.LISTED, "2020-01-01T00:00:00Z")],
            survivorship_mode="labelled_today_universe",
        )
        payload = labelled.public_dict()
        self.assertEqual(payload["survivorship_mode"], "labelled_today_universe")
        self.assertFalse(payload["truth"]["point_in_time_default"])
        rev = DatasetRevisionIdentity(
            revision_id="r1",
            published_at="2024-01-01T00:00:00Z",
            available_at="2024-01-02T00:00:00Z",
            observed_at="2024-01-03T00:00:00Z",
            content_hash="abc",
            survivorship_mode="labelled_today_universe",
        )
        self.assertFalse(rev.public_dict()["truth"]["today_universe_is_not_historical_by_default"])

    def test_corporate_actions_and_calendar_are_causal(self) -> None:
        u = self._universe()
        self.assertEqual(len(u.corporate_actions_as_of("AAA", "2021-02-01T00:00:00Z")), 0)
        self.assertEqual(len(u.corporate_actions_as_of("AAA", "2021-07-01T00:00:00Z")), 2)
        self.assertFalse(u.is_trading_day("2021-12-25", exchange="NASDAQ"))
        self.assertTrue(u.is_trading_day("2021-12-27", exchange="NASDAQ"))

    def test_instrument_settlement_currency(self) -> None:
        spec = InstrumentSpec(
            instrument_id="eq:ZZZ",
            symbol="ZZZ",
            family=InstrumentFamily.EQUITY,
            venue="NASDAQ",
            quote_currency="USD",
        )
        self.assertEqual(spec.resolved_settlement_currency(), "USD")
        self.assertEqual(spec.public_dict()["settlement_currency"], "USD")


class MultiSymbolWalletTests(unittest.TestCase):
    def test_multi_symbol_positions_equity_and_exposure(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="agent-a",
            owner_kind="agent",
            cash=money(100_000),
            currency="USD",
            currency_mode="single",
        )
        w.apply_buy(qty=10, price=100, fee=1, tx_id="b1", symbol="AAA")
        w.apply_buy(qty=5, price=200, fee=1, tx_id="b2", symbol="BBB")
        self.assertIn("AAA", w.positions)
        self.assertIn("BBB", w.positions)
        marks = {"AAA": 110, "BBB": 180}
        eq = w.equity_at_marks(marks)
        # cash 100000 - 1001 - 1001 = 97998; MV = 10*110 + 5*180 = 2000
        self.assertEqual(eq, money(97998 + 2000))
        self.assertEqual(w.gross_exposure(marks), money(2000))
        self.assertEqual(w.net_exposure(marks), money(2000))
        w.apply_sell(qty=10, price=110, fee=1, tx_id="s1", symbol="AAA")
        self.assertNotIn("AAA", w.positions)
        self.assertIn("BBB", w.positions)

    def test_currency_mismatch_refused(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="a",
            owner_kind="agent",
            cash=money(10_000),
            currency="USD",
        )
        with self.assertRaises(ValueError) as ctx:
            w.apply_buy(qty=1, price=10, fee=0, tx_id="x", symbol="EURUSD", quote_currency="EUR")
        self.assertIn("currency_mismatch", str(ctx.exception))

    def test_multi_currency_mode_not_silent(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="a",
            owner_kind="agent",
            cash=money(10_000),
            currency_mode="multi",
        )
        with self.assertRaises(ValueError) as ctx:
            w.apply_buy(qty=1, price=10, fee=0, tx_id="x", symbol="AAA")
        self.assertIn("FX", str(ctx.exception))

    def test_legacy_scalar_path_still_works(self) -> None:
        book = WalletBook()
        w = book.ensure_agent("solo", initial_cash=10_000)
        w.apply_buy(qty=2, price=50, fee=0, tx_id="b")
        self.assertEqual(w.position_qty, money(2))
        w.apply_sell(qty=2, price=55, fee=0, tx_id="s")
        self.assertEqual(w.position_qty, money(0))
        payload = w.public_dict(55)
        self.assertTrue(payload["truth"]["no_silent_currency_mix"])


class CostModelPackTests(unittest.TestCase):
    def test_unmeasured_is_not_zero_and_assumed_is_visible(self) -> None:
        pack = CostModelPack.from_fee_slippage_bps(fee_bps=5.0, slippage_bps=2.0, seed=7)
        self.assertEqual(pack.fee.status, MetricStatus.ASSUMED)
        self.assertEqual(pack.spread.status, MetricStatus.ASSUMED)
        self.assertEqual(pack.impact.status, MetricStatus.UNMEASURED)
        self.assertEqual(pack.latency.status, MetricStatus.UNMEASURED)
        self.assertIsNone(pack.impact.value)
        payload = pack.public_dict()
        self.assertTrue(payload["truth"]["no_fake_microstructure_without_data"])
        self.assertTrue(payload["impact"]["truth"]["unmeasured_is_not_zero_cost"])
        self.assertEqual(pack.total_assumed_friction_bps(), 7.0)

    def test_zero_config_stays_unmeasured(self) -> None:
        pack = CostModelPack.from_fee_slippage_bps()
        self.assertEqual(pack.fee.status, MetricStatus.UNMEASURED)
        self.assertEqual(pack.effective_fee_bps(), 0.0)


class InferentialStatsTests(unittest.TestCase):
    def test_bootstrap_and_monte_carlo_cis(self) -> None:
        rets = [0.01, -0.005, 0.002, 0.003, -0.001, 0.004] * 10
        boot = block_bootstrap_mean(rets, block_size=3, samples=200, seed=1)
        mc = monte_carlo_mean_resample(rets, samples=200, seed=1)
        self.assertEqual(boot.n, len(rets))
        self.assertLessEqual(boot.ci_low, boot.mean)
        self.assertGreaterEqual(boot.ci_high, boot.mean)
        self.assertEqual(mc.method, "monte_carlo_iid")

    def test_deflated_sharpe_uses_trial_count(self) -> None:
        rets = [0.01] * 50 + [-0.005] * 20
        sr = sharpe_ratio(rets)
        self.assertIsNotNone(sr)
        one = deflated_sharpe_ratio(float(sr), n_trials=1, n_observations=len(rets))
        many = deflated_sharpe_ratio(float(sr), n_trials=100, n_observations=len(rets))
        self.assertEqual(one["measurement"], "MEASURED")
        self.assertTrue(one["truth"]["trial_ledger_count_used"])
        self.assertLess(many["dsr"], one["dsr"])

    def test_pbo_and_fdr_and_cpcv_geometry(self) -> None:
        sharpes = [0.5, 0.1, -0.2, 0.8, 0.05, 0.3, -0.1, 0.4]
        pbo = probability_of_backtest_overfitting(sharpes, samples=100, seed=3)
        self.assertEqual(pbo["measurement"], "MEASURED")
        self.assertTrue(pbo["truth"]["losing_trials_must_remain_in_ledger"])
        fdr = benjamini_hochberg([0.001, 0.02, 0.04, 0.2], q=0.05)
        self.assertEqual(fdr["measurement"], "MEASURED")
        gap = purge_embargo_indices(100, train_end=60, test_start=60, purge_bars=5, embargo_bars=2)
        self.assertTrue(gap["causal_gap_ok"])
        cpcv = combinatorial_purged_cv_paths(100, n_groups=5, n_test_groups=2, purge_bars=2, embargo_bars=1)
        self.assertEqual(cpcv["measurement"], "MEASURED")
        self.assertGreater(cpcv["n_paths"], 0)
        self.assertTrue(cpcv["truth"]["no_time_shuffle"])
        power = minimum_useful_sample(effect_size=0.2)
        self.assertEqual(power["measurement"], "ASSUMED")
        self.assertIsInstance(power["n"], int)


if __name__ == "__main__":
    unittest.main()
