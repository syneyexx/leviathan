"""End-to-end research integrity path: split → TRAIN → VAL → robustness → SEALED."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.epistemic import EvidenceClass, is_adaptive_evidence
from Data.modules.market_sim.learning import create_learning_run
from Data.modules.market_sim.learning_runtime import run_learning_on_worker, persist_learning_run
from Data.modules.market_sim.learning_types import LearningObjectiveSpec
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.trading_brain import TradingBrainAdapter, TradingRetrievalRequest
from Data.modules.market_sim.types import MarketSimError


def _bars_csv(path: Path, n: int = 120) -> None:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(hours=i)).isoformat()
            px = 100.0 + i * 0.15
            fh.write(f"{ts},{px},{px + 0.5},{px - 0.2},{px + 0.1},80\n")


class E2EResearchIntegrityTests(unittest.TestCase):
    def test_e2e_train_val_robustness_sealed_firewall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            _bars_csv(markets / "E2E_1h.csv", 120)
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            imported = data.import_and_validate(
                markets / "E2E_1h.csv", symbol="E2E", timeframe="1h", seal=True
            )
            source = imported["source"]
            dataset = imported["dataset"]
            self.assertTrue(dataset.get("sealed") or dataset.get("split_manifest"))

            strat = plane.create_strategy(
                name="e2e-hold",
                entry_rules={"version": 3, "kind": "hold"},
                exit_rules={"kind": "hold"},
                parameters={"period": 5},
            )
            sid = strat["strategy"]["strategy_id"]

            # Explicit SEALED bind via gym proves binder path.
            ep = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=sid,
                strategy_version=1,
                split_role="SEALED",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
            )
            self.assertIsNotNone(ep.get("sealed_attempt"))
            plane.run_gym_episode_on_worker(ep["episode"]["run_id"])

            # Second SEALED attempt rejected.
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_gym_episode(
                    source_id=source["source_id"],
                    strategy_id=sid,
                    strategy_version=1,
                    split_role="SEALED",
                    dataset_id=dataset["dataset_id"],
                    dataset_version=dataset["version"],
                    mode="complete",
                )
            self.assertEqual(ctx.exception.code, "SEALED_ALREADY_CONSUMED")

            # Adapted version cannot reuse disclosed holdout.
            plane.version_strategy(
                sid,
                parameters={"period": 7},
                entry_rules={"version": 3, "kind": "hold"},
                exit_rules={"kind": "hold"},
                changelog="post sealed",
            )
            with self.assertRaises(MarketSimError) as ctx2:
                plane.create_gym_episode(
                    source_id=source["source_id"],
                    strategy_id=sid,
                    strategy_version=2,
                    split_role="SEALED",
                    dataset_id=dataset["dataset_id"],
                    dataset_version=dataset["version"],
                    mode="complete",
                )
            self.assertEqual(ctx2.exception.code, "HOLDOUT_LINEAGE_CONTAMINATED")

            # Brain cannot retrieve sealed adaptive memory.
            from Data.modules.market_sim.experiments import build_strategy_memory_record
            from Data.modules.market_sim.store import utc_now

            now = utc_now()
            plane.store.save_strategy_memory(
                build_strategy_memory_record(
                    strategy_id=sid,
                    strategy_version=1,
                    outcome_summary="train adaptive edge momentum",
                    rejected=False,
                    available_at=now,
                    origin="learning_trial",
                    validation_stage="train",
                    extra_metadata={
                        "evidence_class": EvidenceClass.TRAIN_ADAPTIVE.value,
                        "adaptive": True,
                    },
                )
            )
            plane.store.save_strategy_memory(
                build_strategy_memory_record(
                    strategy_id=sid,
                    strategy_version=1,
                    outcome_summary="sealed qualification poison momentum",
                    rejected=False,
                    available_at=now,
                    origin="learning_trial",
                    validation_stage="sealed",
                    extra_metadata={
                        "evidence_class": EvidenceClass.SEALED_QUALIFICATION_EVIDENCE.value,
                        "adaptive": False,
                    },
                )
            )
            brain = TradingBrainAdapter(
                strategy_memory_lister=lambda **kw: plane.store.list_strategy_memories(**kw)
            )
            hits = brain.retrieve(
                TradingRetrievalRequest(query="momentum edge", decision_as_of=now, max_hits=10)
            )
            text = " ".join(h.content_excerpt or "" for h in hits.hits)
            self.assertIn("train adaptive", text)
            self.assertNotIn("sealed qualification poison", text)
            self.assertFalse(
                is_adaptive_evidence(
                    evidence_class=EvidenceClass.SEALED_QUALIFICATION_EVIDENCE.value
                )
            )


if __name__ == "__main__":
    unittest.main()
