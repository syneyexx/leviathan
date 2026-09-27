"""W17/W18/W9 — behavior fingerprint, covariance, risk-budgeted construction, regime matrix."""

from __future__ import annotations

import hashlib
import json
import unittest

from Data.modules.market_sim.behavior_fingerprint import (
    compute_behavior_fingerprint,
    similarity,
)
from Data.modules.market_sim.institutional_core.construction import (
    ConstructionConstraints,
    estimate_covariance,
    optimize_risk_budgeted,
)
from Data.modules.market_sim.institutional_core.status import MeasurementState
from Data.modules.market_sim.regimes import evaluate_regime_matrix


def _sha_canon(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BehaviorFingerprintTests(unittest.TestCase):
    def test_fingerprint_hashes_are_canonical_sha256(self) -> None:
        signals = [{"side": "buy", "qty": 1}, {"side": "sell", "qty": 1}]
        positions = [{"symbol": "AAPL", "qty": 10}]
        trades = ["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"]
        returns = [0.01, -0.02, 0.005]
        features = ["mom", "vol"]
        regime = {"vol": "low", "trend": "up"}

        fp = compute_behavior_fingerprint(
            strategy_id="s1",
            strategy_version=3,
            dataset_version_id="dv1",
            signals=signals,
            positions=positions,
            trade_timestamps=trades,
            returns=returns,
            feature_set=features,
            regime_response=regime,
            summary={"label": "unit"},
        )

        self.assertEqual(fp["signal_hash"], _sha_canon(signals))
        self.assertEqual(fp["position_hash"], _sha_canon(positions))
        self.assertEqual(fp["trade_timing_hash"], _sha_canon(trades))
        self.assertEqual(fp["return_series_hash"], _sha_canon(returns))
        self.assertEqual(fp["feature_set_hash"], _sha_canon(features))
        self.assertEqual(fp["regime_response_hash"], _sha_canon(regime))
        self.assertEqual(
            fp["fingerprint_id"],
            _sha_canon(
                {
                    "strategy_id": "s1",
                    "strategy_version": 3,
                    "dataset_version_id": "dv1",
                    "signal_hash": fp["signal_hash"],
                    "position_hash": fp["position_hash"],
                    "trade_timing_hash": fp["trade_timing_hash"],
                    "return_series_hash": fp["return_series_hash"],
                    "feature_set_hash": fp["feature_set_hash"],
                    "regime_response_hash": fp["regime_response_hash"],
                }
            ),
        )
        self.assertIn("summary_json", fp)
        self.assertIn("created_at", fp)

        # Deterministic identity for same inputs (ignore created_at).
        fp2 = compute_behavior_fingerprint(
            strategy_id="s1",
            strategy_version=3,
            dataset_version_id="dv1",
            signals=signals,
            positions=positions,
            trade_timestamps=trades,
            returns=returns,
            feature_set=features,
            regime_response=regime,
            summary={"label": "unit"},
        )
        self.assertEqual(fp["fingerprint_id"], fp2["fingerprint_id"])
        self.assertEqual(fp["signal_hash"], fp2["signal_hash"])

    def test_similarity_signal_hash_agreement(self) -> None:
        a = compute_behavior_fingerprint(
            strategy_id="a",
            strategy_version=1,
            dataset_version_id="d",
            signals=[1, 0, 1],
            returns=[0.01, 0.02, -0.01],
        )
        b = compute_behavior_fingerprint(
            strategy_id="b",
            strategy_version=1,
            dataset_version_id="d",
            signals=[1, 0, 1],
            returns=[0.01, 0.02, -0.01],
        )
        c = compute_behavior_fingerprint(
            strategy_id="c",
            strategy_version=1,
            dataset_version_id="d",
            signals=[0, 1, 0],
        )

        agree = similarity(a, b)
        self.assertEqual(agree["signal_agreement"]["value"], 1.0)
        self.assertEqual(agree["signal_agreement"]["state"], MeasurementState.MEASURED.value)
        self.assertEqual(agree["return_correlation"]["state"], MeasurementState.MEASURED.value)

        disagree = similarity(a, c)
        self.assertEqual(disagree["signal_agreement"]["value"], 0.0)
        self.assertEqual(
            disagree["return_correlation"]["state"],
            MeasurementState.UNMEASURED.value,
        )


class CovarianceConstructionTests(unittest.TestCase):
    def test_covariance_insufficient_history(self) -> None:
        cov = estimate_covariance(
            {"A": [0.01, 0.02], "B": [0.0, -0.01]},
            min_samples=20,
        )
        self.assertEqual(cov.state, MeasurementState.INSUFFICIENT_HISTORY.value)
        self.assertEqual(cov.covariance, [])
        self.assertEqual(cov.correlation, [])
        self.assertLess(cov.sample_count, 20)

    def test_optimize_risk_budgeted_correlation_limit_infeasible(self) -> None:
        # Highly correlated strategies with a tight correlation cap.
        n = 40
        base = [0.01 * ((-1) ** i) for i in range(n)]
        returns = {
            "A": list(base),
            "B": [x + 1e-6 for x in base],  # nearly identical → corr ~ 1
        }
        cov = estimate_covariance(returns, min_samples=20)
        self.assertNotEqual(cov.state, MeasurementState.INSUFFICIENT_HISTORY.value)

        result = optimize_risk_budgeted(
            {"A": 1.0, "B": 1.0},
            cov,
            ConstructionConstraints(max_pairwise_correlation=0.5),
        )
        self.assertEqual(result.status, MeasurementState.INFEASIBLE.value)
        self.assertTrue(
            any(
                v == "CORRELATION_LIMIT" or v.startswith("CORRELATION_LIMIT:")
                for v in result.violations
            ),
            msg=result.violations,
        )
        self.assertEqual(result.weights, {})


class RegimeMatrixTests(unittest.TestCase):
    def test_evaluate_regime_matrix_returns_results(self) -> None:
        # Trending then volatile series long enough for detectors.
        closes: list[float] = []
        price = 100.0
        for i in range(80):
            if i < 40:
                price *= 1.002
            else:
                price *= 1.0 + (0.02 if i % 2 == 0 else -0.018)
            closes.append(price)

        results = evaluate_regime_matrix(
            closes,
            timestamps=[f"t{i}" for i in range(len(closes))],
            min_bars_per_regime=5,
            policy={"vol_window": 10, "trend_fast": 5, "trend_slow": 15},
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertTrue(hasattr(row, "regime_id"))
            self.assertTrue(hasattr(row, "state"))
            self.assertTrue(hasattr(row, "passed"))
            self.assertIn(row.state, {m.value for m in MeasurementState})

        gated = evaluate_regime_matrix(
            closes,
            min_bars_per_regime=5,
            policy={"include_hmm": True, "vol_window": 10, "trend_fast": 5, "trend_slow": 15},
        )
        hmm_rows = [r for r in gated if r.regime_id == "hmm"]
        self.assertEqual(len(hmm_rows), 1)
        self.assertEqual(hmm_rows[0].state, MeasurementState.FEATURE_GATED.value)
        self.assertFalse(hmm_rows[0].passed)


if __name__ == "__main__":
    unittest.main()
