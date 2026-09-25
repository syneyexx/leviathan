"""T1 — Causality + Data Foundation regression tests.

Covers epistemic firewall, MarketView, sealed datasets, provenance/hashes,
timestamp policy, and causal Brain / StrategyMemory / news boundaries.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from Data.modules.common.hashing import sha256_file
from Data.modules.market_sim.brain_hooks import BrainFacade
from Data.modules.market_sim.causality import MarketView, SimulationClock, assert_no_future
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.dataset_pipeline import (
    MarketDatasetPipeline,
    assert_dataset_immutable,
    analyze_bars,
)
from Data.modules.market_sim.engine import SimulationEngine
from Data.modules.market_sim.epistemic import (
    EpistemicFirewall,
    EvaluationWindow,
    TimedWindow,
    compare_ts,
    is_available,
)
from Data.modules.market_sim.experiments import StrategyMemoryEntry, StrategyMemoryIndex
from Data.modules.market_sim.knowledge_snapshot import build_knowledge_snapshot
from Data.modules.market_sim.ohlcv import _normalize_ts, validate_ohlcv_file
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import Bar, CausalityViolation, MarketSimError, SimRun


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


def _bars(n: int = 10) -> list[Bar]:
    out: list[Bar] = []
    for i in range(n):
        ts = f"2024-01-01T{i:02d}:00:00+00:00"
        px = 100.0 + i
        out.append(Bar(ts=ts, open=px, high=px + 1, low=px - 1, close=px + 0.5, volume=1000))
    return out


def _run(**kwargs: object) -> SimRun:
    base: dict = dict(
        run_id="run-t1",
        status="QUEUED",
        source_id="src",
        strategy_id="strat",
        strategy_version=1,
        symbol="BTCUSDT",
        timeframe="1h",
        start_ts="",
        end_ts="",
        data_hash=sha256_file(FIXTURE),
        seed=42,
        initial_cash=100_000.0,
        cash=100_000.0,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    base.update(kwargs)
    return SimRun(**base)  # type: ignore[arg-type]


class EpistemicFirewallTests(unittest.TestCase):
    def test_available_at_boundary(self) -> None:
        self.assertTrue(
            is_available(
                available_at="2024-01-01T00:00:00+00:00",
                as_of="2024-01-01T00:00:00+00:00",
            )
        )
        self.assertFalse(
            is_available(
                available_at="2024-01-02T00:00:00+00:00",
                as_of="2024-01-01T00:00:00+00:00",
            )
        )

    def test_assert_available_raises_on_future(self) -> None:
        fw = EpistemicFirewall(as_of="2020-01-01T00:00:00+00:00")
        with self.assertRaises(CausalityViolation):
            fw.assert_available("2024-06-01T00:00:00+00:00", label="news")
        self.assertEqual(fw.violations, 1)

    def test_sealed_holdout_blocked_during_research(self) -> None:
        fw = EpistemicFirewall(
            as_of="2019-01-01T00:00:00+00:00",
            window=EvaluationWindow.RESEARCH,
            sealed_windows=[
                TimedWindow(
                    role=EvaluationWindow.SEALED_TEST,
                    start_ts="2020-01-01T00:00:00+00:00",
                    end_ts="2020-12-31T00:00:00+00:00",
                    sealed=True,
                )
            ],
        )
        with self.assertRaises(CausalityViolation):
            fw.assert_not_in_sealed_holdout("2020-06-01T00:00:00+00:00", purpose="strategy_design")

    def test_sealed_dataset_readable_only_in_sealed_window(self) -> None:
        fw = EpistemicFirewall(as_of="2019-01-01T00:00:00+00:00", window=EvaluationWindow.RESEARCH)
        with self.assertRaises(CausalityViolation):
            fw.assert_dataset_readable(
                dataset_sealed=True,
                dataset_role=EvaluationWindow.SEALED_TEST,
                purpose="strategy_creation",
            )
        fw2 = EpistemicFirewall(as_of="2020-06-01T00:00:00+00:00", window=EvaluationWindow.SEALED_TEST)
        fw2.assert_dataset_readable(
            dataset_sealed=True,
            dataset_role=EvaluationWindow.SEALED_TEST,
            purpose="evaluation",
        )

    def test_filter_records_by_available_at(self) -> None:
        fw = EpistemicFirewall(as_of="2024-06-01T00:00:00+00:00")
        kept = fw.filter_records(
            [
                {"id": "a", "available_at": "2024-01-01T00:00:00+00:00"},
                {"id": "b", "available_at": "2024-12-01T00:00:00+00:00"},
                {"id": "c", "published_at": "2023-01-01T00:00:00+00:00"},
            ]
        )
        ids = {r["id"] for r in kept}
        self.assertEqual(ids, {"a", "c"})

    def test_compare_ts_not_lexicographic(self) -> None:
        # Lex would claim "9" > "2024-..." ; datetime compare must refuse non-ISO.
        with self.assertRaises(MarketSimError):
            compare_ts("9", "2024-01-01T00:00:00+00:00")


class MarketViewTests(unittest.TestCase):
    def test_market_view_hides_future(self) -> None:
        clock = SimulationClock(bars=_bars(5))
        clock.advance()
        clock.advance()  # index 1
        view = MarketView(clock=clock, instrument="BTCUSDT", timeframe="1h")
        visible = view.visible_bars()
        self.assertEqual(len(visible), 2)
        self.assertEqual(visible[-1].ts, clock.current_ts)
        with self.assertRaises(CausalityViolation):
            view.observe(4)
        with self.assertRaises(CausalityViolation):
            view.bar_at_or_before("2024-01-01T04:00:00+00:00")

    def test_feature_closes_are_causal(self) -> None:
        clock = SimulationClock(bars=_bars(8))
        for _ in range(5):
            clock.advance()
        view = MarketView(clock=clock)
        closes = view.feature("closes", window=3)
        self.assertEqual(len(closes), 3)  # type: ignore[arg-type]
        self.assertEqual(closes[-1], view.current().close)  # type: ignore[index]


class AssertNoFutureTests(unittest.TestCase):
    def test_datetime_aware_comparison(self) -> None:
        assert_no_future(["2024-01-01T00:00:00+00:00"], "2024-01-01T00:00:00+00:00")
        with self.assertRaises(CausalityViolation):
            assert_no_future(["2024-01-02T00:00:00+00:00"], "2024-01-01T00:00:00+00:00")
        with self.assertRaises(MarketSimError):
            assert_no_future(["9"], "2024-01-01T00:00:00+00:00")


class DataHashPrepareTests(unittest.TestCase):
    def test_prepare_refuses_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "leviathan.db")
            store.initialize()
            engine = SimulationEngine(store)
            run = _run(data_hash="definitely-not-the-file-hash", bar_index=0)
            with self.assertRaises(MarketSimError) as ctx:
                engine.prepare(run, bars_path=str(FIXTURE))
            self.assertEqual(ctx.exception.code, "DATA_HASH_MISMATCH")

    def test_prepare_accepts_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "leviathan.db")
            store.initialize()
            engine = SimulationEngine(store)
            run = _run(bar_index=0)
            state = engine.prepare(run, bars_path=str(FIXTURE))
            self.assertGreater(len(state.clock.bars), 0)


class TimestampNormalizationTests(unittest.TestCase):
    def test_yyyymmdd_parses_as_calendar_date(self) -> None:
        ts = _normalize_ts("20240115")
        self.assertTrue(ts.startswith("2024-01-15"))

    def test_microsecond_epoch(self) -> None:
        us = "1704067200000000"  # 2024-01-01T00:00:00Z in microseconds
        ts = _normalize_ts(us)
        self.assertTrue(ts.startswith("2024-01-01"))


class OhlcvValidationTests(unittest.TestCase):
    def test_duplicate_timestamps_rejected(self) -> None:
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

    def test_unordered_timestamps_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T01:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T00:00:00+00:00,1.5,2.5,1,2,10\n",
                encoding="utf-8",
            )
            result = validate_ohlcv_file(path)
            self.assertFalse(result.ok)

    def test_path_traversal_rejected_on_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root)
            with self.assertRaises(MarketSimError) as ctx:
                data.register_file("../../etc/passwd")
            self.assertEqual(ctx.exception.code, "PATH_ESCAPE")

    def test_deterministic_hash(self) -> None:
        h1 = sha256_file(FIXTURE)
        h2 = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(h1, h2)
        validation = validate_ohlcv_file(FIXTURE)
        self.assertTrue(validation.ok)
        self.assertEqual(validation.content_hash, h1)


class SealedDatasetTests(unittest.TestCase):
    def test_import_seal_and_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src = root / "BTCUSDT_1h.csv"
            src.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root)
            result = data.import_and_validate(src, symbol="BTCUSDT", timeframe="1h", seal=True, role="SEALED_TEST")
            self.assertIsNotNone(result["dataset"])
            ds = result["dataset"]
            self.assertTrue(ds["sealed"])
            self.assertEqual(ds["quality_state"], "SEALED")
            # Same hash + sealed → immutable check
            sealed = SealedAdapter(ds)
            with self.assertRaises(CausalityViolation):
                assert_dataset_immutable(sealed, new_hash="0" * 64)
            # DB trigger refuses content mutation
            mutated = dict(ds)
            mutated["content_hash"] = "0" * 64
            with self.assertRaises(Exception):
                store.upsert_dataset_version(mutated)

    def test_correction_creates_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src = root / "BTCUSDT_1h.csv"
            src.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root)
            first = data.import_and_validate(src, symbol="BTCUSDT", timeframe="1h", seal=True)
            ds = first["dataset"]
            # Build a corrected file (extra bar → new hash)
            bars = FIXTURE.read_text(encoding="utf-8").strip().splitlines()
            bars.append("2024-12-31T23:00:00+00:00,50000,50100,49900,50050,200")
            corrected = root / "BTCUSDT_1h_corrected.csv"
            corrected.write_text("\n".join(bars) + "\n", encoding="utf-8")
            second = data.correct_sealed_dataset(
                ds["dataset_id"], ds["version"], corrected, reason="append missing bar"
            )
            self.assertIsNotNone(second["dataset"])
            self.assertNotEqual(second["dataset"]["content_hash"], ds["content_hash"])
            self.assertEqual(second["dataset"]["parent_version"], ds["version"])
            self.assertEqual(second["dataset"]["version"], "2")
            # Original sealed version still resolvable unchanged
            original = store.get_dataset_version(ds["dataset_id"], ds["version"])
            assert original is not None
            self.assertEqual(original["content_hash"], ds["content_hash"])

    def test_gap_reporting(self) -> None:
        bars = [
            Bar("2024-01-01T00:00:00+00:00", 1, 2, 0.5, 1.5, 10),
            Bar("2024-01-10T00:00:00+00:00", 1, 2, 0.5, 1.5, 10),
        ]
        report = analyze_bars(bars, timeframe="1h")
        self.assertTrue(report.ok)  # gaps are warnings, not hard errors
        self.assertGreater(len(report.gaps), 0)


class SealedAdapter:
    """Minimal adapter for assert_dataset_immutable tests."""

    def __init__(self, payload: dict) -> None:
        self.sealed = payload["sealed"]
        self.content_hash = payload["content_hash"]
        self.version_key = f"{payload['dataset_id']}@{payload['version']}"


class KnowledgeSnapshotTests(unittest.TestCase):
    def test_snapshot_hash_stable(self) -> None:
        a = build_knowledge_snapshot(
            run_id="r1",
            as_of="2024-01-01T00:00:00+00:00",
            market_dataset_id="d1",
            market_dataset_hash="abc",
            market_dataset_version="1",
            random_seed=7,
            created_at="2024-01-01T00:00:00+00:00",
        )
        b = build_knowledge_snapshot(
            run_id="r1",
            as_of="2024-01-01T00:00:00+00:00",
            market_dataset_id="d1",
            market_dataset_hash="abc",
            market_dataset_version="1",
            random_seed=7,
            created_at="2024-01-01T00:00:00+00:00",
        )
        self.assertEqual(a.snapshot_hash, b.snapshot_hash)
        self.assertTrue(a.snapshot_hash)

    def test_persisted_on_run_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            dest = root / "BTCUSDT_1h.csv"
            dest.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root)
            from Data.modules.market_sim.service import MarketSimControlPlane

            svc = MarketSimControlPlane(store, data, enabled=True)
            sources = svc.scan_market_data()
            self.assertEqual(len(sources), 1)
            run = svc.create_run(source_id=sources[0]["source_id"])
            snaps = svc.get_run_knowledge_snapshots(run["run_id"])
            self.assertEqual(len(snaps), 1)
            self.assertEqual(snaps[0]["market_dataset_hash"], sources[0]["content_hash"])
            self.assertIn("knowledge_snapshot_hash", run.get("metadata") or {})


class StrategyMemoryCausalityTests(unittest.TestCase):
    def test_future_memory_unavailable(self) -> None:
        idx = StrategyMemoryIndex()
        idx.add(
            StrategyMemoryEntry(
                memory_id="m1",
                strategy_id="s1",
                strategy_version=1,
                features={"trend": "up"},
                applicability={},
                outcome_summary="won",
                trial_id="t1",
                created_at="2024-06-01T00:00:00+00:00",
                available_at="2024-06-01T00:00:00+00:00",
            )
        )
        self.assertEqual(idx.search(as_of_ts="2024-01-01T00:00:00+00:00"), [])
        self.assertEqual(len(idx.search(as_of_ts="2024-07-01T00:00:00+00:00")), 1)


class BrainCausalBoundaryTests(unittest.TestCase):
    def test_future_brain_content_blocked(self) -> None:
        class Mem:
            def search(self, query: str, *, limit: int = 3):
                return [
                    {
                        "memory_id": "past",
                        "content": "known then",
                        "available_at": "2020-01-01T00:00:00+00:00",
                    },
                    {
                        "memory_id": "future",
                        "content": "known later",
                        "available_at": "2025-01-01T00:00:00+00:00",
                    },
                ]

        facade = BrainFacade(memory=Mem())  # type: ignore[arg-type]
        fw = EpistemicFirewall(as_of="2021-01-01T00:00:00+00:00")
        out = facade.retrieve("q", dependencies=["memory"], firewall=fw)
        ids = [h.get("memory_id") for h in out.hits]
        self.assertEqual(ids, ["past"])
        self.assertTrue(any("as_of filter dropped" in n for n in out.notes))


class HoldoutVersionMutationTests(unittest.TestCase):
    def test_completed_holdout_does_not_mutate_current_version_in_place(self) -> None:
        """Adaptation after holdout disclosure requires a NEW strategy version.

        T1 foundation: sealed dataset + knowledge snapshot bind the tested
        version; mutating sealed dataset content in place is refused.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = MarketDatasetPipeline(Path(tmp) / "markets")
            src = Path(tmp) / "in.csv"
            src.write_bytes(FIXTURE.read_bytes())
            result = pipeline.ingest_file(
                src, symbol="BTCUSDT", timeframe="1h", seal=True, role="SEALED_TEST"
            )
            assert result.dataset is not None
            with self.assertRaises(CausalityViolation):
                assert_dataset_immutable(result.dataset, new_hash="deadbeef")


if __name__ == "__main__":
    unittest.main()
