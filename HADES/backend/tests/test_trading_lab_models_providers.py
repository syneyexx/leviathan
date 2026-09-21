"""Model training honesty and provider status honesty.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import math
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.models import TrainedModel, train_model
from trading_lab.providers import KNOWN_DATA_GAPS, provider_statuses


def series(count: int) -> tuple[list[float], list[str]]:
    closes: list[float] = []
    timestamps: list[str] = []
    first = datetime(2020, 1, 1, tzinfo=UTC)
    price = 100.0
    for index in range(count):
        price *= 1.0 + 0.004 * math.sin(index / 7.0) + 0.0002
        closes.append(price)
        timestamps.append((first + timedelta(hours=index)).isoformat())
    return closes, timestamps


class ModelTrainingTest(unittest.TestCase):
    def test_too_little_history_refuses_instead_of_fitting_noise(self) -> None:
        closes, timestamps = series(40)
        model, report = train_model(
            model_id="m1",
            name="m1",
            kind="ridge",
            closes=closes,
            timestamps=timestamps,
            instrument_id="crypto_spot:test:BTCUSDT",
            timeframe="1h",
            dataset_ids=["ds_1"],
        )
        self.assertIsNone(model)
        self.assertIn("insufficient_rows", report.get("error", ""))

    def test_an_unknown_kind_is_refused(self) -> None:
        closes, timestamps = series(400)
        model, report = train_model(
            model_id="m2",
            name="m2",
            kind="deep_magic",
            closes=closes,
            timestamps=timestamps,
            instrument_id="crypto_spot:test:BTCUSDT",
            timeframe="1h",
            dataset_ids=["ds_1"],
        )
        self.assertIsNone(model)
        self.assertIn("unknown_model_kind", report.get("error", ""))

    def test_training_reports_a_cutoff_window_and_a_baseline_comparison(self) -> None:
        closes, timestamps = series(400)
        model, report = train_model(
            model_id="m3",
            name="m3",
            kind="ridge",
            closes=closes,
            timestamps=timestamps,
            instrument_id="crypto_spot:test:BTCUSDT",
            timeframe="1h",
            dataset_ids=["ds_1"],
            created_at="2020-02-01T00:00:00+00:00",
        )
        self.assertIsNotNone(model)
        self.assertTrue(report["trained"])
        window = report["training_window"]
        self.assertLessEqual(window["start"], window["end"])
        self.assertLessEqual(window["end"], window["cutoff"])
        self.assertGreater(window["validation_rows"], 0)
        baseline = report["baseline_comparison"]
        self.assertTrue(baseline["available"])
        self.assertIn("beats_baseline", baseline)
        self.assertIsInstance(baseline["beats_baseline"], bool)

    def test_training_is_deterministic_for_a_seed(self) -> None:
        closes, timestamps = series(400)
        first, _ = train_model(
            model_id="m4", name="m4", kind="ridge", closes=closes, timestamps=timestamps,
            instrument_id="crypto_spot:test:BTCUSDT", timeframe="1h", dataset_ids=["ds_1"], seed=11,
        )
        second, _ = train_model(
            model_id="m4", name="m4", kind="ridge", closes=closes, timestamps=timestamps,
            instrument_id="crypto_spot:test:BTCUSDT", timeframe="1h", dataset_ids=["ds_1"], seed=11,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first.artefact_hash, second.artefact_hash)

    def test_artefact_round_trip_preserves_predictions(self) -> None:
        closes, timestamps = series(400)
        model, _ = train_model(
            model_id="m5", name="m5", kind="ridge", closes=closes, timestamps=timestamps,
            instrument_id="crypto_spot:test:BTCUSDT", timeframe="1h", dataset_ids=["ds_1"],
        )
        self.assertIsNotNone(model)
        restored = TrainedModel.from_json(model.as_json())
        self.assertEqual(restored.artefact_hash, model.artefact_hash)
        self.assertEqual(restored.training_cutoff, model.training_cutoff)


class ProviderStatusTest(unittest.TestCase):
    def test_offline_by_default_and_the_reason_names_the_requirement(self) -> None:
        statuses = {item["provider_id"]: item for item in provider_statuses({"allow_network": False})}
        self.assertTrue(statuses["csv_import"]["usable"], "importing a file never needs the network")
        network_providers = [item for item in statuses.values() if item["requires_network"]]
        self.assertTrue(network_providers, "there is at least one optional online provider")
        for item in network_providers:
            self.assertFalse(item["usable"])
            self.assertIn("allow_network", item["reason"])

    def test_enabling_the_network_makes_online_providers_usable(self) -> None:
        statuses = provider_statuses({"allow_network": True})
        online = [item for item in statuses if item["requires_network"]]
        for item in online:
            self.assertTrue(item["usable"], item["reason"])

    def test_every_provider_declares_a_licence(self) -> None:
        for item in provider_statuses({}):
            self.assertTrue(item["licence"])
            self.assertTrue(item["reason"])

    def test_known_gaps_state_the_consequence_not_just_the_absence(self) -> None:
        self.assertTrue(KNOWN_DATA_GAPS)
        for gap in KNOWN_DATA_GAPS:
            self.assertTrue(gap["area"])
            self.assertTrue(gap["missing"])
            self.assertTrue(gap["consequence"])


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
