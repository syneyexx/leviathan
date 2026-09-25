"""T6 — Strategy Library, causal memory, promotion state machine, provenance fingerprint."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.brain_hooks import BrainFacade
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.deliberation import DeliberationRuntime
from Data.modules.market_sim.knowledge_snapshot import build_knowledge_snapshot
from Data.modules.market_sim.multi_engine import MultiAgentEngine
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.strategy_library import (
    PROMOTION_TRANSITIONS,
    StrategyLibrary,
    can_promote,
    compute_provenance_fingerprint,
    lesson_from_memory,
)
from Data.modules.market_sim.types import MarketSimError, StrategyStatus


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


class StrategyLibraryTests(unittest.TestCase):
    def test_persist_recall_lessons_causal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            lib = StrategyLibrary(store)
            lib.persist_memory(
                {
                    "memory_id": "m-old",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "features": {"trend": "up"},
                    "applicability": {"trends": ["up"]},
                    "outcome_summary": "worked in uptrend",
                    "trial_id": "t1",
                    "available_at": "2024-01-01T00:00:00+00:00",
                    "created_at": utc_now(),
                    "rejected": False,
                }
            )
            lib.persist_memory(
                {
                    "memory_id": "m-future",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "features": {"trend": "down"},
                    "applicability": {"trends": ["down"]},
                    "outcome_summary": "future leak",
                    "trial_id": "t2",
                    "available_at": "2025-06-01T00:00:00+00:00",
                    "created_at": utc_now(),
                    "rejected": True,
                }
            )
            recalled = lib.recall(
                strategy_id="s1",
                as_of_ts="2024-06-01T00:00:00+00:00",
                features={"trend": "up"},
            )
            self.assertEqual(len(recalled), 1)
            self.assertEqual(recalled[0]["memory_id"], "m-old")
            lessons = lib.lessons(strategy_id="s1", as_of_ts="2024-06-01T00:00:00+00:00")
            self.assertEqual(len(lessons), 1)
            self.assertIn("worked", lessons[0]["claim"])
            with self.assertRaises(MarketSimError):
                lib.recall(strategy_id="s1", as_of_ts="")

    def test_multi_prepare_hydrates_memories(self) -> None:
        src = inspect.getsource(MultiAgentEngine.prepare)
        self.assertIn("hydrate_for_run", src)
        from Data.modules.market_sim.strategy_library import StrategyLibrary

        self.assertIn("list_strategy_memories", inspect.getsource(StrategyLibrary.hydrate_for_run))

        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            store.save_strategy_memory(
                {
                    "memory_id": "m1",
                    "strategy_id": "strat",
                    "strategy_version": 1,
                    "features": {"trend": "up"},
                    "applicability": {},
                    "outcome_summary": "ok",
                    "trial_id": None,
                    "available_at": "2020-01-01T00:00:00+00:00",
                    "created_at": utc_now(),
                    "rejected": False,
                    "metadata": {},
                }
            )
            from Data.modules.market_sim.types import SimRun
            import hashlib

            run = SimRun(
                run_id="r1",
                status="QUEUED",
                source_id="src",
                strategy_id="strat",
                strategy_version=1,
                symbol="BTCUSDT",
                timeframe="1h",
                start_ts="",
                end_ts="",
                data_hash=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                seed=1,
                agents=[{"agent_id": "a1", "role": "trend", "authority": {"may_order": True}}],
            )
            state = MultiAgentEngine(store).prepare(run, bars_path=str(FIXTURE))
            self.assertGreaterEqual(len(state.memory._entries), 1)


class BrainAsOfTests(unittest.TestCase):
    def test_excluded_without_as_of(self) -> None:
        class _Mem:
            def search(self, query: str, *, limit: int = 3) -> list[dict]:
                return [{"id": "x", "created_at": "2024-01-01T00:00:00+00:00"}]

        facade = BrainFacade(memory=_Mem())
        out = facade.retrieve("q", dependencies=["memory"])
        self.assertEqual(out.hits, [])
        self.assertTrue(any("as_of required" in n for n in out.notes))

    def test_deliberation_passes_as_of(self) -> None:
        src = inspect.getsource(DeliberationRuntime.run_round)
        self.assertIn("as_of=bar.ts", src)


class PromotionStateMachineTests(unittest.TestCase):
    def test_allowed_and_forbidden_edges(self) -> None:
        self.assertTrue(can_promote("RESEARCH", "CANDIDATE"))
        self.assertTrue(can_promote("CANDIDATE", "PAPER_READY"))
        self.assertTrue(can_promote("PAPER_READY", "ACTIVE"))
        self.assertFalse(can_promote("DRAFT", "ACTIVE"))
        self.assertFalse(can_promote("ARCHIVED", "ACTIVE"))
        self.assertIn(StrategyStatus.ARCHIVED.value, PROMOTION_TRANSITIONS["ACTIVE"])

    def test_service_promote_and_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            svc = MarketSimControlPlane(store, MarketDataStore(store, markets), enabled=True)
            created = svc.create_strategy(name="promo-test")
            sid = created["strategy"]["strategy_id"]
            # New strategies start ACTIVE; move into research then candidate.
            research = svc.promote_strategy(sid, to_status="RESEARCH", reason="start research")
            self.assertEqual(research["status"], "RESEARCH")
            candidate = svc.promote_strategy(sid, to_status="CANDIDATE", reason="passed holdout")
            self.assertEqual(candidate["status"], "CANDIDATE")
            events = store.list_promotion_events(strategy_id=sid)
            self.assertGreaterEqual(len(events), 2)
            with self.assertRaises(MarketSimError) as ctx:
                svc.promote_strategy(sid, to_status="ACTIVE")  # skip PAPER_READY
            self.assertEqual(ctx.exception.code, "INVALID_PROMOTION")


class ProvenanceFingerprintTests(unittest.TestCase):
    def test_fingerprint_stable_and_sensitive(self) -> None:
        a = compute_provenance_fingerprint(
            market_dataset_hash="h1",
            strategy_content_hash="s1",
            random_seed=1,
        )
        b = compute_provenance_fingerprint(
            market_dataset_hash="h1",
            strategy_content_hash="s1",
            random_seed=1,
        )
        c = compute_provenance_fingerprint(
            market_dataset_hash="h1",
            strategy_content_hash="s1",
            random_seed=2,
        )
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)

    def test_knowledge_snapshot_includes_fingerprint(self) -> None:
        snap = build_knowledge_snapshot(
            run_id="r",
            as_of="2024-01-01T00:00:00+00:00",
            market_dataset_id="d",
            market_dataset_hash="abc123",
            strategy_id="s",
            strategy_version=1,
            random_seed=7,
            strategy_content_hash="content-xyz",
        )
        self.assertTrue(snap.provenance_fingerprint)
        self.assertTrue(snap.snapshot_hash)
        pub = snap.public_dict()
        self.assertTrue(pub["truth"]["full_provenance_fingerprint"])


class LessonHelperTests(unittest.TestCase):
    def test_lesson_from_memory(self) -> None:
        lesson = lesson_from_memory(
            {
                "memory_id": "m",
                "strategy_id": "s",
                "strategy_version": 2,
                "outcome_summary": "avoid chop",
                "applicability": {"regime": "range"},
                "rejected": True,
                "trial_id": "t",
                "available_at": "2024-01-01T00:00:00+00:00",
                "created_at": "2024-01-01T00:00:00+00:00",
            }
        )
        self.assertEqual(lesson.claim, "avoid chop")
        self.assertTrue(lesson.rejected)
        self.assertTrue(lesson.public_dict()["truth"]["lesson_is_not_a_trade_signal"])


if __name__ == "__main__":
    unittest.main()
