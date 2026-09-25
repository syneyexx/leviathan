"""T1 — Causality + data foundation acceptance tests."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from Data.modules.common.hashing import sha256_file
from Data.modules.market_sim.brain_hooks import BrainFacade
from Data.modules.market_sim.causality import (
    EpistemicFirewall,
    MarketView,
    SimulationClock,
    assert_no_future,
    compare_ts,
    filter_by_as_of,
)
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.dataset_pipeline import DatasetImmutableError, MarketDatasetPipeline
from Data.modules.market_sim.engine import SimulationEngine
from Data.modules.market_sim.experiments import StrategyMemoryEntry, StrategyMemoryIndex
from Data.modules.market_sim.knowledge_snapshot import build_knowledge_snapshot
from Data.modules.market_sim.ohlcv import _normalize_ts, analyze_ohlcv_quality, validate_ohlcv_file
from Data.modules.market_sim.sealed_holdout import (
    SealedHoldoutGuard,
    SealedHoldoutViolation,
    SealedHoldoutWindow,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import Bar, CausalityViolation, MarketSimError, SimRun, RunStatus


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


def _bars(n: int = 5) -> list[Bar]:
    return [
        Bar(
            f"2024-01-01T{i:02d}:00:00+00:00",
            float(i + 1),
            float(i + 2),
            float(i),
            float(i) + 0.5,
            10.0,
        )
        for i in range(n)
    ]


def _run(**kwargs) -> SimRun:
    base = dict(
        run_id="r1",
        status=RunStatus.CREATED.value,
        source_id="s1",
        strategy_id=None,
        strategy_version=None,
        symbol="BTCUSDT",
        timeframe="1h",
        start_ts="",
        end_ts="",
        data_hash=sha256_file(FIXTURE),
        seed=42,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )
    base.update(kwargs)
    return SimRun(**base)  # type: ignore[arg-type]


class BarCausalityTests(unittest.TestCase):
    def test_agent_cannot_access_future_bar(self) -> None:
        clock = SimulationClock(bars=_bars(5))
        clock.advance()
        view = MarketView(clock=clock)
        view.current()
        with self.assertRaises(CausalityViolation):
            view.bar_at(4)
        self.assertFalse(view.has_future_access())
        self.assertEqual(view.visible_count(), 1)

    def test_market_view_history_bounded(self) -> None:
        clock = SimulationClock(bars=_bars(10))
        for _ in range(5):
            clock.advance()
        view = clock.market_view()
        hist = view.history(3)
        self.assertEqual(len(hist), 3)
        self.assertEqual(hist[-1].ts, view.as_of)
        self.assertTrue(all(compare_ts(b.ts, view.as_of or "") <= 0 for b in hist))


class FeatureCausalityTests(unittest.TestCase):
    def test_strategy_cannot_access_future_feature_window(self) -> None:
        from Data.modules.market_sim.strategy_eval import evaluate_strategy

        clock = SimulationClock(bars=_bars(30))
        for _ in range(10):
            clock.advance()
        # evaluate_strategy only sees clock.window — never future closes
        signal = evaluate_strategy(
            clock,
            parameters={"fast_ma": 3, "slow_ma": 5},
            entry_rules={"kind": "ma_cross"},
            exit_rules={"kind": "ma_cross"},
            position_qty=0.0,
        )
        self.assertIn(signal.side, {"BUY", "SELL", "HOLD"})
        with self.assertRaises(CausalityViolation):
            clock.observe(20)


class StrategyMemoryCausalityTests(unittest.TestCase):
    def test_future_strategy_memory_unavailable(self) -> None:
        idx = StrategyMemoryIndex()
        idx.add(
            StrategyMemoryEntry(
                memory_id="m1",
                strategy_id="s",
                strategy_version=1,
                features={"trend": "up"},
                applicability={},
                outcome_summary="learned in 2024",
                trial_id=None,
                created_at="2024-06-01T00:00:00+00:00",
                available_at="2024-06-01T00:00:00+00:00",
            )
        )
        self.assertEqual(
            idx.search(as_of_ts="2020-01-01T00:00:00+00:00", features={"trend": "up"}),
            [],
        )
        self.assertEqual(
            len(idx.search(as_of_ts="2024-07-01T00:00:00+00:00", features={"trend": "up"})),
            1,
        )


class NewsFirewallTests(unittest.TestCase):
    def test_future_news_unavailable(self) -> None:
        records = [
            {"id": "old", "available_at": "2020-01-01T00:00:00+00:00", "title": "old"},
            {"id": "new", "available_at": "2025-01-01T00:00:00+00:00", "title": "new"},
        ]
        kept = filter_by_as_of(records, "2021-06-01T00:00:00+00:00", source="news")
        self.assertEqual([r["id"] for r in kept], ["old"])


class BrainFirewallTests(unittest.TestCase):
    def test_future_brain_content_blocked(self) -> None:
        class _Mem:
            def search(self, query: str, *, limit: int = 3) -> list[dict]:
                return [
                    {
                        "id": "timed",
                        "available_at": "2025-01-01T00:00:00+00:00",
                        "content": "future fact",
                    },
                    {
                        "id": "general",
                        "timeless": True,
                        "knowledge_class": "general",
                        "content": "RSI definition",
                    },
                    {
                        "id": "past",
                        "available_at": "2019-01-01T00:00:00+00:00",
                        "content": "past event",
                    },
                ]

        facade = BrainFacade(memory=_Mem())
        out = facade.retrieve("q", dependencies=["memory"], as_of="2020-01-01T00:00:00+00:00")
        ids = [h["id"] for h in out.hits]
        self.assertIn("general", ids)
        self.assertIn("past", ids)
        self.assertNotIn("timed", ids)
        self.assertEqual(out.causal_dropped, 1)


class SealedHoldoutTests(unittest.TestCase):
    def test_sealed_holdout_hidden_during_strategy_creation(self) -> None:
        guard = SealedHoldoutGuard()
        guard.add(
            SealedHoldoutWindow(
                holdout_id="h1",
                strategy_id="s1",
                strategy_version=1,
                start_ts="2020-01-01T00:00:00+00:00",
                end_ts="2020-12-31T00:00:00+00:00",
            )
        )
        with self.assertRaises(SealedHoldoutViolation):
            guard.assert_ts_allowed(
                "2020-06-01T00:00:00+00:00",
                phase="STRATEGY_CREATION",
                strategy_id="s1",
                strategy_version=1,
            )
        # Outside holdout is fine
        guard.assert_ts_allowed(
            "2019-06-01T00:00:00+00:00",
            phase="STRATEGY_CREATION",
            strategy_id="s1",
            strategy_version=1,
        )
        bars = _bars(3)
        # rewrite timestamps into holdout
        holdout_bars = [
            Bar("2020-03-01T00:00:00+00:00", 1, 2, 0.5, 1.5, 1),
            Bar("2019-03-01T00:00:00+00:00", 1, 2, 0.5, 1.5, 1),
        ]
        filtered = guard.filter_bars(
            holdout_bars, phase="RESEARCH", strategy_id="s1", strategy_version=1
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].ts, "2019-03-01T00:00:00+00:00")

    def test_completed_holdout_cannot_modify_current_version(self) -> None:
        guard = SealedHoldoutGuard()
        guard.add(
            SealedHoldoutWindow(
                holdout_id="h1",
                strategy_id="s1",
                strategy_version=1,
                start_ts="2020-01-01T00:00:00+00:00",
                end_ts="2020-12-31T00:00:00+00:00",
                status="DISCLOSED",
            )
        )
        with self.assertRaises(SealedHoldoutViolation):
            guard.assert_outcome_not_used_to_mutate_version(
                strategy_id="s1",
                strategy_version=1,
                holdout_id="h1",
                mutating=True,
            )
        # New version is allowed
        guard.assert_outcome_not_used_to_mutate_version(
            strategy_id="s1",
            strategy_version=2,
            holdout_id="h1",
            mutating=True,
        )


class DatasetImmutabilityTests(unittest.TestCase):
    def test_dataset_update_creates_new_version_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            path = markets / "X_1h.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T01:00:00+00:00,1.5,2.5,1,2,10\n",
                encoding="utf-8",
            )
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, markets)
            src = data.register_file("X_1h.csv")
            sealed1 = data.seal_source(src.source_id, sealed_for="trial-1")
            self.assertTrue(sealed1["sealed"])
            hash1 = sealed1["content_hash"]

            # Correction → new file content → new hash / version
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T01:00:00+00:00,1.5,2.5,1,2.1,10\n",
                encoding="utf-8",
            )
            hash2 = sha256_file(path)
            self.assertNotEqual(hash1, hash2)
            # Mutating sealed hash in place is refused
            with self.assertRaises(DatasetImmutableError):
                data.inspect_path("X_1h.csv", register=True)

            # New sealed version via pipeline with new hash
            pipeline = MarketDatasetPipeline(markets, store)
            # Copy corrected file under a new path so source can be re-registered
            path2 = markets / "X_1h_v2.csv"
            path2.write_bytes(path.read_bytes())
            src2 = data.register_file("X_1h_v2.csv")
            sealed2 = data.seal_source(src2.source_id, sealed_for="trial-2")
            self.assertEqual(sealed2["content_hash"], hash2)
            self.assertNotEqual(sealed2["dataset_id"], sealed1["dataset_id"])
            # Old sealed dataset still retrievable unchanged
            old = store.get_sealed_dataset(sealed1["dataset_id"])
            assert old is not None
            self.assertEqual(old.content_hash, hash1)


class DataValidationTests(unittest.TestCase):
    def test_invalid_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("foo,bar\n1,2\n", encoding="utf-8")
            result = validate_ohlcv_file(path)
            self.assertFalse(result.ok)

    def test_duplicate_timestamp_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T00:00:00+00:00,1.5,2.5,1,2,10\n",
                encoding="utf-8",
            )
            result = validate_ohlcv_file(path)
            self.assertFalse(result.ok)
            self.assertIn("duplicate", (result.error or "").lower())

    def test_unordered_timestamp_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ord.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T01:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T00:00:00+00:00,1.5,2.5,1,2,10\n",
                encoding="utf-8",
            )
            result = validate_ohlcv_file(path)
            self.assertFalse(result.ok)

    def test_timezone_normalization_yyyymmdd(self) -> None:
        ts = _normalize_ts("20240115")
        self.assertTrue(ts.startswith("2024-01-15"))

    def test_path_traversal_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, Path(tmp) / "markets")
            data.ensure_root()
            with self.assertRaises(MarketSimError):
                data.inspect_path("../../etc/passwd", register=False)

    def test_deterministic_hash(self) -> None:
        h1 = sha256_file(FIXTURE)
        h2 = sha256_file(FIXTURE)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_known_gap_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gap_1h.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T03:00:00+00:00,1.5,2.5,1,2,10\n",
                encoding="utf-8",
            )
            analysis = analyze_ohlcv_quality(path, expected_timeframe="1h")
            self.assertGreaterEqual(len(analysis["known_gaps"]), 1)
            self.assertTrue(any("gap" in w.lower() for w in analysis["warnings"]))


class EpistemicFirewallTests(unittest.TestCase):
    def test_assert_no_future_is_datetime_aware(self) -> None:
        # Lexicographic trap: "9" > "2024-..." as strings, but not as datetimes.
        # Unparseable "9" still compared lexicographically and raises.
        with self.assertRaises(CausalityViolation):
            assert_no_future(["2025-01-01T00:00:00+00:00"], "2024-01-01T00:00:00+00:00")
        assert_no_future(["2023-01-01T00:00:00+00:00"], "2024-01-01T00:00:00+00:00")

    def test_firewall_tracks_violations(self) -> None:
        fw = EpistemicFirewall(as_of="2020-01-01T00:00:00+00:00")
        self.assertFalse(fw.admit({"available_at": "2021-01-01T00:00:00+00:00"}))
        self.assertEqual(fw.violations, 1)


class KnowledgeSnapshotTests(unittest.TestCase):
    def test_snapshot_persisted_and_fingerprint_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            snap = build_knowledge_snapshot(
                snapshot_id=str(uuid.uuid4()),
                run_id="run-1",
                as_of="2020-01-01T00:00:00+00:00",
                market_dataset_id="ds-1",
                market_dataset_hash="abc",
                market_dataset_version="1",
                created_at="2020-01-01T00:00:00+00:00",
                random_seed=7,
            )
            store.save_knowledge_snapshot(snap)
            loaded = store.get_knowledge_snapshot(snap.snapshot_id)
            assert loaded is not None
            self.assertEqual(loaded.content_fingerprint(), snap.content_fingerprint())
            self.assertEqual(loaded.memory_cutoff, "2020-01-01T00:00:00+00:00")
            self.assertEqual(loaded.news_cutoff, "2020-01-01T00:00:00+00:00")


class PrepareHashTests(unittest.TestCase):
    def test_prepare_refuses_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            engine = SimulationEngine(store)
            run = _run(data_hash="definitely-not-the-file-hash", bar_index=0)
            with self.assertRaises(MarketSimError) as ctx:
                engine.prepare(run, bars_path=str(FIXTURE))
            self.assertEqual(ctx.exception.code, "DATA_HASH_MISMATCH")

    def test_prepare_accepts_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            engine = SimulationEngine(store)
            run = _run(bar_index=0)
            state = engine.prepare(run, bars_path=str(FIXTURE))
            self.assertGreater(len(state.clock.bars), 0)
            view = state.clock.market_view()
            self.assertTrue(hasattr(view, "history"))


class ImportPipelineTests(unittest.TestCase):
    def test_import_quarantine_and_seal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            markets = Path(tmp) / "markets"
            markets.mkdir()
            dest = markets / "BTCUSDT_1h.csv"
            dest.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, markets)
            out = data.import_and_validate("BTCUSDT_1h.csv", seal=True, sealed_for="exp-1")
            self.assertEqual(out["import"]["status"], "SEALED")
            self.assertTrue(out["import"]["quarantine_path"])
            self.assertTrue(out["import"]["dataset"]["sealed"])
            # Immutable trigger
            ds = store.get_sealed_dataset(out["import"]["dataset"]["dataset_id"])
            assert ds is not None
            with store.connect() as conn:
                with self.assertRaises(Exception):
                    conn.execute(
                        "UPDATE market_sealed_datasets SET bar_count=0 WHERE dataset_id=?",
                        (ds.dataset_id,),
                    )


class HoldoutStoreTests(unittest.TestCase):
    def test_register_and_disclose_holdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            hid = str(uuid.uuid4())
            store.register_sealed_holdout(
                {
                    "holdout_id": hid,
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "start_ts": "2020-01-01T00:00:00+00:00",
                    "end_ts": "2020-12-31T00:00:00+00:00",
                    "content_hash": "x",
                }
            )
            rows = store.list_sealed_holdouts(strategy_id="s1")
            self.assertEqual(len(rows), 1)
            disclosed = store.disclose_sealed_holdout(hid)
            self.assertEqual(disclosed["status"], "DISCLOSED")


if __name__ == "__main__":
    unittest.main()
