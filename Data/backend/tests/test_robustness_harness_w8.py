"""Wave 8 — real robustness harness executes new perturbation runs."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.agent_lab import AcceptanceCriteria
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.robustness import (
    RobustnessPerturbation,
    aggregate_robustness_verdict,
    apply_parameter_jitter,
    default_perturbation_matrix,
    run_robustness_matrix,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


def _csv(path: Path, n: int = 90) -> None:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(hours=i)).isoformat()
            px = 100.0 + i * 0.05
            fh.write(f"{ts},{px},{px + 0.4},{px - 0.2},{px + 0.1},50\n")


def _plane(tmp: str):
    root = Path(tmp)
    markets = root / "markets"
    markets.mkdir()
    _csv(markets / "RB_1h.csv")
    store = MarketSimStore(root / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    imported = data.import_and_validate(markets / "RB_1h.csv", symbol="RB", timeframe="1h", seal=True)
    return plane, imported["source"], imported["dataset"]


class RobustnessHarnessTests(unittest.TestCase):
    def test_robustness_executes_new_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane(tmp)
            strat = plane.create_strategy(
                name="rb-hold",
                entry_rules={"version": 3, "kind": "hold"},
                exit_rules={"kind": "hold"},
                parameters={"period": 10},
            )
            sid = strat["strategy"]["strategy_id"]
            run_ids: list[str] = []

            def execute(pert, seed):
                fee = 5.0 * pert.fee_bps_factor
                slip = 2.0 * pert.slippage_bps_factor + pert.spread_bps_add
                ep = plane.create_gym_episode(
                    source_id=source["source_id"],
                    strategy_id=sid,
                    strategy_version=1,
                    split_role="VAL",
                    dataset_id=dataset["dataset_id"],
                    dataset_version=dataset["version"],
                    mode="complete",
                    seed=seed,
                    fee_bps=fee,
                    slippage_bps=slip,
                    require_split_binding=True,
                    metadata={"episode_tag": f"robustness:{pert.perturbation_id}"},
                )
                result = plane.run_gym_episode_on_worker(ep["episode"]["run_id"])
                run_ids.append(ep["episode"]["run_id"])
                return {"run_id": ep["episode"]["run_id"], "metrics": result.get("metrics") or {"trade_count": 0}}

            acc = AcceptanceCriteria(min_trades=0, max_drawdown_pct=100.0)
            verdict = run_robustness_matrix(
                execute_episode=execute,
                evaluate_acceptance=lambda m: acc.evaluate(m, val_pass=True, robustness_pass=True),
                perturbations=default_perturbation_matrix(include_parameter=False, include_time=False)[:3],
                base_seed=1,
                min_pass_ratio=0.0,
            )
            self.assertGreaterEqual(len(run_ids), 3)
            self.assertEqual(len(set(run_ids)), len(run_ids))
            self.assertTrue(all(r.get("run_id") for r in verdict["results"]))
            self.assertTrue(verdict["truth"]["executed_new_runs"])

    def test_cost_shock(self) -> None:
        matrix = default_perturbation_matrix()
        cost = next(p for p in matrix if p.kind == "cost")
        self.assertGreaterEqual(cost.fee_bps_factor, 2.0)

    def test_slippage_shock(self) -> None:
        matrix = default_perturbation_matrix()
        self.assertTrue(any(p.kind == "slippage" and p.slippage_bps_factor >= 2.0 for p in matrix))

    def test_spread_shock(self) -> None:
        matrix = default_perturbation_matrix()
        self.assertTrue(any(p.kind == "spread" and p.spread_bps_add > 0 for p in matrix))

    def test_parameter_perturbation(self) -> None:
        jittered = apply_parameter_jitter({"period": 10, "threshold": 1.5}, {"_relative": 0.2}, seed=7)
        changed = jittered["period"] != 10 or abs(float(jittered["threshold"]) - 1.5) > 1e-12
        self.assertTrue(changed)
        self.assertIsInstance(jittered["period"], int)

    def test_start_date_sensitivity(self) -> None:
        matrix = default_perturbation_matrix(include_time=True)
        self.assertTrue(any(p.kind == "time" and p.start_shift_bars for p in matrix))

    def test_regime_slices(self) -> None:
        matrix = default_perturbation_matrix(include_regime=True)
        self.assertTrue(any(p.kind == "regime" for p in matrix))

    def test_robustness_missing_data_blocks(self) -> None:
        from Data.modules.market_sim.robustness import RobustnessRunResult

        results = [
            RobustnessRunResult(
                perturbation=RobustnessPerturbation("x", "cost", "x"),
                run_id="r1",
                metrics={},
                accepted=False,
                measurement="UNMEASURED",
            )
        ]
        verdict = aggregate_robustness_verdict(results)
        self.assertFalse(verdict["accepted"])
        self.assertEqual(verdict["reason"], "robustness_missing_data_blocks")

    def test_rescore_only_is_not_authority(self) -> None:
        """A verdict without executed run_ids cannot accept."""
        from Data.modules.market_sim.robustness import RobustnessRunResult

        results = [
            RobustnessRunResult(
                perturbation=RobustnessPerturbation("c", "cost", "c"),
                run_id=None,
                metrics={"trade_count": 10},
                accepted=True,
                status="completed",
                measurement="MEASURED",
            )
        ]
        verdict = aggregate_robustness_verdict(results, require_new_runs=True)
        self.assertFalse(verdict["accepted"])
        self.assertEqual(verdict["reason"], "robustness_missing_executed_runs")


if __name__ == "__main__":
    unittest.main()
