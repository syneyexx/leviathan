"""Wave 1 — research integrity: split binding, SEALED gateway, epistemic sink.

Poison-future leakage tests prove TRAIN cannot observe VAL/SEALED bars and
VAL cannot observe SEALED bars — not merely metadata assertions.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.epistemic import (
    EvidenceClass,
    evidence_class_for_split_role,
    is_adaptive_evidence,
)
from Data.modules.market_sim.learning import create_learning_run
from Data.modules.market_sim.learning_runtime import (
    _append_trial,
    _run_candidate_episode,
    persist_learning_run,
)
from Data.modules.market_sim.learning_types import CandidateProposal, LearningObjectiveSpec
from Data.modules.market_sim.ohlcv import load_ohlcv
from Data.modules.market_sim.sealed_attempts import SealedAttemptBinder, SealedAttemptStatus
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.split_manifest import (
    SplitRole,
    build_split_manifest,
    resolve_research_episode_binding,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.trading_brain import TradingBrainAdapter, TradingRetrievalRequest
from Data.modules.market_sim.types import MarketSimError


def _write_poison_csv(path: Path, *, n: int = 90) -> None:
    """TRAIN neutral / VAL extreme / SEALED unique poison markers by price level."""
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(hours=i)).isoformat()
            # Approximate thirds: TRAIN ~0-53, VAL ~54-71, SEALED ~72-89 with default fracs.
            if i < 54:
                px = 100.0 + (i % 5) * 0.01  # neutral
            elif i < 72:
                px = 5000.0 + i  # extreme VAL marker
            else:
                px = 99999.0 + i  # unique SEALED poison
            fh.write(f"{ts},{px},{px + 0.5},{px - 0.5},{px},10\n")


def _plane_with_poison(tmp: str, *, n: int = 90) -> tuple[MarketSimControlPlane, dict, dict]:
    root = Path(tmp)
    markets = root / "markets"
    markets.mkdir()
    csv_path = markets / "POISON_1h.csv"
    _write_poison_csv(csv_path, n=n)
    store = MarketSimStore(root / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    imported = data.import_and_validate(csv_path, symbol="POISON", timeframe="1h", seal=True)
    source = imported["source"]
    dataset = imported["dataset"]
    return plane, source, dataset


def _strategy(plane: MarketSimControlPlane, name: str = "ri-strat"):
    return plane.create_strategy(
        name=name,
        entry_rules={"version": 3, "kind": "hold"},
        exit_rules={"kind": "hold"},
        parameters={},
    )


class SplitBindingContractTests(unittest.TestCase):
    def test_binding_derives_manifest_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            manifest = plane.store.get_split_manifest(
                dataset_id=dataset["dataset_id"], dataset_version=dataset["version"]
            )
            self.assertTrue(manifest["frozen"])
            binding = resolve_research_episode_binding(manifest, split_role="TRAIN")
            self.assertEqual(binding.start_ts, manifest["train"]["start_ts"])
            self.assertEqual(binding.end_ts, manifest["train"]["end_ts"])
            self.assertTrue(binding.split_manifest_hash)

    def test_caller_cannot_expand_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            manifest = plane.store.get_split_manifest(
                dataset_id=dataset["dataset_id"], dataset_version=dataset["version"]
            )
            with self.assertRaises(MarketSimError) as ctx:
                resolve_research_episode_binding(
                    manifest,
                    split_role="TRAIN",
                    caller_start_ts="2020-01-01T00:00:00+00:00",
                )
            self.assertEqual(ctx.exception.code, "SPLIT_WINDOW_EXPANSION_FORBIDDEN")

    def test_split_window_runtime_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane)
            ep = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="TRAIN",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
                require_split_binding=True,
            )
            run = plane._get_run(ep["episode"]["run_id"])
            binding = ep["split_binding"]
            self.assertEqual(run.start_ts, binding["start_ts"])
            self.assertEqual(run.end_ts, binding["end_ts"])
            result = plane.run_gym_episode_on_worker(run.run_id)
            self.assertIsNotNone(result)
            # Loaded bars must stay within TRAIN window.
            bars = load_ohlcv(
                plane._resolve_bars_path(run),
                start_ts=run.start_ts,
                end_ts=run.end_ts,
            )
            self.assertTrue(all(b.ts <= run.end_ts for b in bars))
            self.assertTrue(all(b.close < 1000 for b in bars))  # no VAL/SEALED poison


class LeakageFirewallTests(unittest.TestCase):
    def test_train_cannot_read_val(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "train-val")
            ep = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="TRAIN",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
                require_split_binding=True,
            )
            run = plane._get_run(ep["episode"]["run_id"])
            bars = load_ohlcv(
                plane._resolve_bars_path(run),
                start_ts=run.start_ts,
                end_ts=run.end_ts,
            )
            self.assertTrue(bars)
            self.assertTrue(all(b.close < 200 for b in bars))

    def test_train_cannot_read_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            # Mutate only SEALED region on a copy — TRAIN output must be unchanged.
            strat = _strategy(plane, "train-sealed")
            ep1 = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="TRAIN",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
                require_split_binding=True,
            )
            r1 = plane.run_gym_episode_on_worker(ep1["episode"]["run_id"])
            train_metrics = dict(r1.get("metrics") or {})

            # Poison SEALED further by rewriting file after seal — corrections need new version.
            # Instead verify TRAIN window bars never include sealed poison prices.
            run = plane._get_run(ep1["episode"]["run_id"])
            bars = load_ohlcv(
                plane._resolve_bars_path(run),
                start_ts=run.start_ts,
                end_ts=run.end_ts,
            )
            self.assertTrue(all(b.close < 1000 for b in bars))
            self.assertNotIn("99999", str(train_metrics))

    def test_val_cannot_read_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "val-sealed")
            ep = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="VAL",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
                require_split_binding=True,
            )
            run = plane._get_run(ep["episode"]["run_id"])
            bars = load_ohlcv(
                plane._resolve_bars_path(run),
                start_ts=run.start_ts,
                end_ts=run.end_ts,
            )
            self.assertTrue(bars)
            self.assertTrue(all(4000 < b.close < 20000 for b in bars))
            self.assertTrue(all(b.close < 90000 for b in bars))

    def test_poison_future_train_invariant_to_val_sealed_mutation(self) -> None:
        """TRAIN episode metrics unchanged when only VAL/SEALED prices change (new version)."""
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "poison-inv")
            ep = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="TRAIN",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
                require_split_binding=True,
                seed=11,
            )
            before = plane.run_gym_episode_on_worker(ep["episode"]["run_id"])
            train_eq = (before.get("metrics") or {}).get("equity") or (before.get("metrics") or {}).get(
                "final_equity"
            )

            # Build a second dataset with VAL/SEALED mutated but TRAIN identical.
            root = Path(tmp)
            mutated = root / "markets" / "POISON2_1h.csv"
            dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
            with mutated.open("w", encoding="utf-8") as fh:
                fh.write("timestamp,open,high,low,close,volume\n")
                for i in range(90):
                    ts = (dt0 + timedelta(hours=i)).isoformat()
                    if i < 54:
                        px = 100.0 + (i % 5) * 0.01
                    elif i < 72:
                        px = 7777.0 + i  # different VAL
                    else:
                        px = 88888.0 + i  # different SEALED
                    fh.write(f"{ts},{px},{px + 0.5},{px - 0.5},{px},10\n")
            imported2 = plane.data.import_and_validate(
                mutated, symbol="POISON2", timeframe="1h", seal=True
            )
            ep2 = plane.create_gym_episode(
                source_id=imported2["source"]["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="TRAIN",
                dataset_id=imported2["dataset"]["dataset_id"],
                dataset_version=imported2["dataset"]["version"],
                mode="complete",
                require_split_binding=True,
                seed=11,
            )
            after = plane.run_gym_episode_on_worker(ep2["episode"]["run_id"])
            # Hold policy: equity path determined by TRAIN prices only → identical closes.
            run_a = plane._get_run(ep["episode"]["run_id"])
            run_b = plane._get_run(ep2["episode"]["run_id"])
            bars_a = load_ohlcv(
                plane._resolve_bars_path(run_a), start_ts=run_a.start_ts, end_ts=run_a.end_ts
            )
            bars_b = load_ohlcv(
                plane._resolve_bars_path(run_b), start_ts=run_b.start_ts, end_ts=run_b.end_ts
            )
            self.assertEqual([b.close for b in bars_a], [b.close for b in bars_b])
            if train_eq is not None:
                train_eq2 = (after.get("metrics") or {}).get("equity") or (after.get("metrics") or {}).get(
                    "final_equity"
                )
                self.assertEqual(train_eq, train_eq2)


class SealedGatewayTests(unittest.TestCase):
    def test_sealed_requires_canonical_binder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            # SEALED without strategy_id cannot bind.
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_gym_episode(
                    source_id=source["source_id"],
                    split_role="SEALED",
                    dataset_id=dataset["dataset_id"],
                    dataset_version=dataset["version"],
                    mode="complete",
                )
            self.assertEqual(ctx.exception.code, "SEALED_STRATEGY_REQUIRED")
            # SEALED with strategy always returns sealed_attempt from binder.
            strat = _strategy(plane, "sealed-bind")
            ep = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                split_role="SEALED",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
            )
            self.assertIsNotNone(ep.get("sealed_attempt"))
            self.assertTrue(ep["truth"]["sealed_binder_enforced"])
            plane.run_gym_episode_on_worker(ep["episode"]["run_id"])

    def test_sealed_single_use_gym_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "sealed-once")
            sid = strat["strategy"]["strategy_id"]
            ep1 = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=sid,
                strategy_version=1,
                split_role="SEALED",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
            )
            self.assertIsNotNone(ep1.get("sealed_attempt"))
            plane.run_gym_episode_on_worker(ep1["episode"]["run_id"])
            attempt = plane.store.get_sealed_attempt(ep1["sealed_attempt"]["sealed_attempt_id"])
            self.assertEqual(attempt["status"], SealedAttemptStatus.COMPLETED)
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

    def test_sealed_retry_resumes_same_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "sealed-resume")
            sid = strat["strategy"]["strategy_id"]
            ep1 = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=sid,
                strategy_version=1,
                split_role="SEALED",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
            )
            attempt_id = ep1["sealed_attempt"]["sealed_attempt_id"]
            run_id = ep1["episode"]["run_id"]
            # Mid-flight: still BOUND/RUNNING — second create must refuse new run.
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
            self.assertEqual(ctx.exception.code, "SEALED_ATTEMPT_BOUND_TO_OTHER_RUN")
            self.assertIn(run_id, ctx.exception.message)
            # Resume original.
            plane.run_gym_episode_on_worker(run_id)
            again = plane.store.get_sealed_attempt(attempt_id)
            self.assertEqual(again["status"], SealedAttemptStatus.COMPLETED)

    def test_sealed_restart_resumes_same_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "sealed-restart")
            sid = strat["strategy"]["strategy_id"]
            ep1 = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=sid,
                strategy_version=1,
                split_role="SEALED",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
            )
            attempt_id = ep1["sealed_attempt"]["sealed_attempt_id"]
            binder = SealedAttemptBinder(plane.store)
            binder.fail(attempt_id, reason="crash")
            # Resume same run after FAILED.
            resumed = binder.bind_or_resume(
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                split_manifest_id=ep1["sealed_attempt"]["split_manifest_id"],
                strategy_id=sid,
                strategy_version=1,
                run_id=ep1["episode"]["run_id"],
                sealed_attempt_id=attempt_id,
            )
            self.assertEqual(resumed.sealed_attempt_id, attempt_id)
            plane.run_gym_episode_on_worker(ep1["episode"]["run_id"])
            self.assertEqual(
                plane.store.get_sealed_attempt(attempt_id)["status"],
                SealedAttemptStatus.COMPLETED,
            )

    def test_adapted_strategy_requires_new_holdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "sealed-adapt")
            sid = strat["strategy"]["strategy_id"]
            ep1 = plane.create_gym_episode(
                source_id=source["source_id"],
                strategy_id=sid,
                strategy_version=1,
                split_role="SEALED",
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["version"],
                mode="complete",
            )
            plane.run_gym_episode_on_worker(ep1["episode"]["run_id"])
            # Adapt → new strategy version.
            plane.version_strategy(
                sid,
                parameters={"period": 9},
                entry_rules={"version": 3, "kind": "hold"},
                exit_rules={"kind": "hold"},
                changelog="post-sealed adaptation",
            )
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_gym_episode(
                    source_id=source["source_id"],
                    strategy_id=sid,
                    strategy_version=2,
                    split_role="SEALED",
                    dataset_id=dataset["dataset_id"],
                    dataset_version=dataset["version"],
                    mode="complete",
                )
            self.assertEqual(ctx.exception.code, "HOLDOUT_LINEAGE_CONTAMINATED")


class SealedEpistemicSinkTests(unittest.TestCase):
    def test_evidence_class_mapping(self) -> None:
        self.assertEqual(evidence_class_for_split_role("TRAIN"), EvidenceClass.TRAIN_ADAPTIVE)
        self.assertEqual(
            evidence_class_for_split_role("SEALED"),
            EvidenceClass.SEALED_QUALIFICATION_EVIDENCE,
        )
        self.assertFalse(is_adaptive_evidence(split_role="SEALED"))
        self.assertTrue(is_adaptive_evidence(split_role="TRAIN"))

    def test_sealed_does_not_write_adaptive_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "mem-sealed")
            sid = strat["strategy"]["strategy_id"]
            obj = LearningObjectiveSpec.from_dict(
                {
                    "min_trades": 0,
                    "max_drawdown_pct": 100.0,
                    "require_val_pass": False,
                    "require_robustness_pass": False,
                    "require_sealed_pass": False,
                    "generation_budget": 1,
                    "trial_budget": 5,
                    "population_size": 2,
                    "seed": 1,
                }
            )
            run = create_learning_run(
                lab_id=None,
                campaign_id=None,
                strategy_id=sid,
                parent_strategy_version=1,
                source_id=source["source_id"],
                objective=obj,
                seed=1,
            )
            persist_learning_run(plane.store, run)
            cand = CandidateProposal(
                candidate_id="c-sealed",
                generation=1,
                strategy_id=sid,
                strategy_version=1,
                content_hash="h",
                hypothesis="hold",
                family="hold",
                parameters={},
                entry_rules={"kind": "hold"},
                exit_rules={"kind": "hold"},
                risk_rules={},
                proposal_method="test",
                parent_refs=[],
                learner_state_hash=run.learner_state.state_hash(),
            )
            episode = _run_candidate_episode(
                plane, run=run, candidate=cand, split_role="SEALED", seed=1
            )
            _append_trial(
                plane,
                run=run,
                candidate=cand,
                split_role="SEALED",
                seed=1,
                episode=episode,
                fitness_payload={"fitness_score": 0.1},
                status="completed",
            )
            rows = plane.store.list_strategy_memories(strategy_id=sid, limit=50)
            sealed_rows = [
                r
                for r in rows
                if str((r.get("metadata") or {}).get("validation_stage") or "").lower() == "sealed"
            ]
            self.assertTrue(sealed_rows)
            for r in sealed_rows:
                meta = r.get("metadata") or {}
                self.assertEqual(
                    meta.get("evidence_class"),
                    EvidenceClass.SEALED_QUALIFICATION_EVIDENCE.value,
                )
                self.assertFalse(meta.get("adaptive", True) and is_adaptive_evidence(
                    evidence_class=meta.get("evidence_class"),
                    validation_stage=meta.get("validation_stage"),
                ))

    def test_brain_excludes_sealed_adaptive_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            from Data.modules.market_sim.experiments import build_strategy_memory_record
            from Data.modules.market_sim.store import utc_now

            now = utc_now()
            plane.store.save_strategy_memory(
                build_strategy_memory_record(
                    strategy_id="s1",
                    strategy_version=1,
                    outcome_summary="train win breakout momentum",
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
                    strategy_id="s1",
                    strategy_version=1,
                    outcome_summary="sealed poison should never retrieve momentum",
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
            result = brain.retrieve(
                TradingRetrievalRequest(
                    query="momentum breakout",
                    decision_as_of=now,
                    max_hits=10,
                )
            )
            texts = " ".join(h.content_excerpt or "" for h in result.hits)
            self.assertIn("train win", texts)
            self.assertNotIn("sealed poison", texts)

    def test_split_manifest_hash_bound_to_trial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, source, dataset = _plane_with_poison(tmp)
            strat = _strategy(plane, "hash-trial")
            sid = strat["strategy"]["strategy_id"]
            obj = LearningObjectiveSpec.from_dict(
                {
                    "min_trades": 0,
                    "max_drawdown_pct": 100.0,
                    "require_val_pass": False,
                    "require_robustness_pass": False,
                    "require_sealed_pass": False,
                    "generation_budget": 1,
                    "trial_budget": 3,
                    "population_size": 2,
                    "seed": 3,
                }
            )
            run = create_learning_run(
                lab_id=None,
                campaign_id=None,
                strategy_id=sid,
                parent_strategy_version=1,
                source_id=source["source_id"],
                objective=obj,
                seed=3,
            )
            persist_learning_run(plane.store, run)
            cand = CandidateProposal(
                candidate_id="c-hash",
                generation=1,
                strategy_id=sid,
                strategy_version=1,
                content_hash="h",
                hypothesis="hold",
                family="hold",
                parameters={},
                entry_rules={"kind": "hold"},
                exit_rules={"kind": "hold"},
                risk_rules={},
                proposal_method="test",
                parent_refs=[],
                learner_state_hash=run.learner_state.state_hash(),
            )
            episode = _run_candidate_episode(
                plane, run=run, candidate=cand, split_role="TRAIN", seed=3
            )
            self.assertIn("split_binding", episode)
            self.assertTrue(episode["split_binding"]["split_manifest_hash"])
            _append_trial(
                plane,
                run=run,
                candidate=cand,
                split_role="TRAIN",
                seed=3,
                episode=episode,
                fitness_payload={"fitness_score": 0.0},
                status="completed",
            )
            mems = plane.store.list_strategy_memories(strategy_id=sid, limit=10)
            self.assertTrue(mems)
            binding = (mems[0].get("metadata") or {}).get("split_binding") or {}
            self.assertEqual(
                binding.get("split_manifest_hash"),
                episode["split_binding"]["split_manifest_hash"],
            )


class CalendarFailClosedTests(unittest.TestCase):
    def test_unknown_calendar_fails_closed(self) -> None:
        from Data.modules.market_sim.instruments import InstrumentFamily, InstrumentSpec, equity_session_is_open
        from Data.modules.market_sim.universe import PointInTimeUniverse

        spec = InstrumentSpec(
            instrument_id="eq1",
            symbol="AAPL",
            family=InstrumentFamily.EQUITY,
            venue="XNAS",
            quote_currency="USD",
        )
        missing = equity_session_is_open(spec, "2024-06-03", universe=None)
        self.assertFalse(missing["isOpen"])
        self.assertEqual(missing["status"], "UNKNOWN")

        uni = PointInTimeUniverse()
        uni.calendar = []  # configured-empty still UNKNOWN
        state = uni.trading_day_state("2024-06-03", exchange="XNAS")
        self.assertEqual(state, "UNKNOWN")
        self.assertFalse(uni.is_trading_day("2024-06-03", exchange="XNAS"))


class AccountingInvariantTests(unittest.TestCase):
    def test_reserved_cash_invariant(self) -> None:
        from Data.modules.market_sim.accounting import WalletLedger
        from decimal import Decimal

        wallet = WalletLedger(wallet_id="w1", owner_id="t", owner_kind="agent", cash=Decimal("100"))
        wallet.reserved_cash = Decimal("150")
        with self.assertRaises(ValueError):
            wallet.assert_invariants(Decimal("10"))


if __name__ == "__main__":
    unittest.main()
