"""Capability matrix, strategy lifecycle and holdout single-use enforcement.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from trading_lab.capabilities import (
    capability_matrix,
    instrument_capability,
    validate_order_capability,
    validate_strategy_capability,
)
from trading_lab.contracts import InstrumentSpec, OrderIntent, StrategyHypothesis, StrategySpec
from trading_lab.registry import (
    HoldoutExhausted,
    PromotionRefused,
    PromotionRequest,
    StrategyRegistry,
)
from trading_lab.store import TradingLabStore

SPOT = InstrumentSpec(
    instrument_id="crypto_spot:test:BTCUSDT",
    family="crypto_spot",
    venue="test",
    symbol="BTCUSDT",
    base_currency="BTC",
    quote_currency="USDT",
    shorting_allowed=False,
)


def intent(**overrides) -> OrderIntent:
    payload = {
        "intent_id": "i1",
        "instrument_id": SPOT.instrument_id,
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


class CapabilityMatrixTest(unittest.TestCase):
    def test_matrix_declares_every_family_strategy_and_order_type(self) -> None:
        matrix = capability_matrix()
        self.assertTrue(matrix["instruments"])
        self.assertTrue(matrix["strategies"])
        self.assertTrue(matrix["order_types"])
        self.assertIn("SIMULATION/PAPER", matrix["execution_mode"])
        allowed = {"implemented", "implemented_needs_data", "blocked_missing_data"}
        for group in ("instruments", "strategies", "order_types"):
            for entry in matrix[group]:
                self.assertIn(
                    entry["implementation"],
                    allowed,
                    f"{group} entry must state an honest implementation status: {entry}",
                )
                if entry["implementation"] != "implemented":
                    self.assertTrue(
                        entry["missing_external_data"],
                        f"{entry['implementation']} must name the data it is waiting for: {entry}",
                    )

    def test_spot_cannot_be_shorted_but_may_be_sold_down(self) -> None:
        ok, reason = validate_order_capability(SPOT, intent(side="sell"))
        self.assertFalse(ok)
        self.assertIn("short_not_allowed_for_instrument", reason)

        ok, reason = validate_order_capability(SPOT, intent(side="sell", reduce_only=True))
        self.assertTrue(ok, reason)

    def test_unsupported_time_in_force_is_refused(self) -> None:
        capability = instrument_capability("crypto_spot")
        self.assertNotIn("GTD", capability.time_in_force)

    def test_a_strategy_family_refuses_an_instrument_family_it_cannot_model(self) -> None:
        ok, reason = validate_strategy_capability("option_volatility", [SPOT])
        self.assertFalse(ok)
        self.assertIn("instrument_family_not_supported_by_strategy", reason)

    def test_pairs_trading_requires_more_than_one_instrument(self) -> None:
        ok, reason = validate_strategy_capability("pairs_trading", [SPOT])
        self.assertFalse(ok)
        self.assertIn("at_least_2_instruments", reason)

    def test_a_short_strategy_is_refused_on_an_instrument_that_cannot_short(self) -> None:
        ok, reason = validate_strategy_capability("trend_following", [SPOT], direction="long_short")
        self.assertFalse(ok)
        self.assertIn("forbids_it", reason)

    def test_an_unknown_strategy_family_is_refused_instead_of_defaulted(self) -> None:
        ok, reason = validate_strategy_capability("magic", [SPOT])
        self.assertFalse(ok)
        self.assertIn("unknown_strategy_family", reason)


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.database = PlatformDatabase(str(Path(self._tmp.name) / "hades.db"))
        self.store = TradingLabStore(self.database)
        self.store.initialize()
        self.registry = StrategyRegistry(self.store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def spec(self) -> StrategySpec:
        return StrategySpec(
            name="Donchian breakout",
            family="breakout",
            instruments=[SPOT.instrument_id],
            hypothesis=StrategyHypothesis(
                economic_rationale="Breakouts follow through while slower trend followers add to the position.",
                plausible_regimes="trending, expanding volatility",
                implausible_regimes="mean-reverting chop",
                falsification_criteria=["No edge after costs over three chronological folds"],
                benchmarks=["buy_and_hold"],
            ),
        )

    def test_a_strategy_without_a_hypothesis_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.create(self.spec().model_copy(update={"hypothesis": None}))

    def test_promotion_to_validated_requires_an_evaluation_report(self) -> None:
        strategy = self.registry.create(self.spec(), created_by="researcher")
        with self.assertRaises(PromotionRefused):
            self.registry.transition(
                PromotionRequest(
                    strategy_id=strategy["strategy_id"],
                    version=1,
                    target_state="validated",
                    requested_by="researcher",
                )
            )

    def test_lifecycle_skipping_is_refused(self) -> None:
        strategy = self.registry.create(self.spec(), created_by="researcher")
        with self.assertRaises(PromotionRefused):
            self.registry.transition(
                PromotionRequest(
                    strategy_id=strategy["strategy_id"],
                    version=1,
                    target_state="paper",
                    requested_by="researcher",
                )
            )

    def test_the_sealed_test_split_can_only_be_consumed_once_per_version(self) -> None:
        strategy = self.registry.create(self.spec(), created_by="researcher")
        strategy_id = strategy["strategy_id"]
        available, _ = self.registry.holdout_available(strategy_id, 1)
        self.assertTrue(available)
        self.registry.consume_holdout(
            strategy_id=strategy_id, version=1, used_by="independent_validator", report_id="rep_1"
        )
        with self.assertRaises(HoldoutExhausted):
            self.registry.consume_holdout(
                strategy_id=strategy_id, version=1, used_by="independent_validator", report_id="rep_2"
            )

    def test_a_new_version_gets_its_own_sealed_test_allowance(self) -> None:
        strategy = self.registry.create(self.spec(), created_by="researcher")
        strategy_id = strategy["strategy_id"]
        self.registry.consume_holdout(
            strategy_id=strategy_id, version=1, used_by="independent_validator", report_id="rep_1"
        )
        version = self.registry.add_version(strategy_id, self.spec(), created_by="researcher")
        self.assertEqual(version, 2)
        available, _ = self.registry.holdout_available(strategy_id, version)
        self.assertTrue(available)

    def test_evidence_dossier_reports_what_is_still_missing(self) -> None:
        strategy = self.registry.create(self.spec(), created_by="researcher")
        evidence = self.registry.evidence(strategy["strategy_id"])
        self.assertIn("next_step", evidence)
        self.assertEqual(evidence.get("evaluations"), [])

    def test_tables_are_created_idempotently(self) -> None:
        self.store.initialize()
        self.assertIsInstance(self.store.list_instruments(), list)
        self.assertIsInstance(self.store.list_strategies(), list)


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
