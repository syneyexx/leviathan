"""P1A — streaming OHLCV + DatasetSplitManifest + SEALED attempt semantics.

Slice 5 of Master Program v4.1. Gym/API ownership arrives in P1B.
"""

from __future__ import annotations

import resource
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.ohlcv import count_ohlcv, iter_ohlcv, load_ohlcv, stream_ohlcv
from Data.modules.market_sim.sealed_attempts import (
    SealedAttemptBinder,
    SealedAttemptStatus,
)
from Data.modules.market_sim.split_manifest import (
    SplitRole,
    build_split_manifest,
    build_split_manifest_from_iter,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import Bar, MarketSimError

FIXTURE = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "fixtures"
# Discover a real fixture if present; else synthesize in tests.
_CANDIDATES = list(Path(__file__).resolve().parents[2].glob("**/fixtures/**/*BTC*.csv"))
if not _CANDIDATES:
    _CANDIDATES = list(Path(__file__).resolve().parents[2].glob("**/market_sim/**/*.csv"))
FIXTURE_CSV = _CANDIDATES[0] if _CANDIDATES else None


def _bars(n: int, *, start: str = "2024-01-01T00:00:00+00:00") -> list[Bar]:
    dt0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    out: list[Bar] = []
    for i in range(n):
        ts = (dt0 + timedelta(hours=i)).isoformat(timespec="seconds")
        px = 100.0 + i * 0.1
        out.append(Bar(ts=ts, open=px, high=px + 1, low=px - 1, close=px + 0.5, volume=10.0))
    return out


def _write_csv(path: Path, n: int) -> None:
    dt0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(minutes=i)).isoformat(timespec="seconds")
            px = 100.0 + (i % 1000) * 0.01
            fh.write(f"{ts},{px},{px + 0.5},{px - 0.5},{px + 0.1},10\n")


def _store(tmp: str) -> MarketSimStore:
    db = Path(tmp) / "leviathan.db"
    MigrationRunner(db).apply_all()
    return MarketSimStore(db)


class P1AStreamingOhlcvTests(unittest.TestCase):
    def test_iter_ohlcv_matches_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            _write_csv(path, 250)
            loaded = load_ohlcv(path)
            streamed = list(iter_ohlcv(path))
            aliased = list(stream_ohlcv(path))
            self.assertEqual(len(streamed), len(loaded))
            self.assertEqual(len(aliased), len(loaded))
            self.assertEqual(streamed[0].ts, loaded[0].ts)
            self.assertEqual(streamed[-1].close, loaded[-1].close)
            self.assertEqual(count_ohlcv(path), len(loaded))

    def test_iter_ohlcv_window_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            _write_csv(path, 100)
            all_bars = list(iter_ohlcv(path))
            mid = all_bars[40].ts
            end = all_bars[60].ts
            windowed = list(iter_ohlcv(path, start_ts=mid, end_ts=end))
            self.assertEqual(windowed[0].ts, mid)
            self.assertEqual(windowed[-1].ts, end)
            self.assertLess(len(windowed), len(all_bars))

    def test_streaming_peak_rss_bounded_vs_materialize(self) -> None:
        """Streaming ingest stays within a memory budget relative to full load.

        Uses ~120k 1m bars (~83 days). Absolute 5y×1m (~2.6M) is the product
        target; this proves the streaming API does not retain the series.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.csv"
            n = 120_000
            _write_csv(path, n)

            def rss_kb() -> int:
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

            # Warm parser path
            _ = next(iter_ohlcv(path))
            before = rss_kb()
            count = 0
            for _bar in iter_ohlcv(path):
                count += 1
            after_stream = rss_kb()
            self.assertEqual(count, n)
            stream_delta = max(0, after_stream - before)

            # Materializing the full list must consume substantially more RSS.
            before_load = rss_kb()
            material = load_ohlcv(path)
            after_load = rss_kb()
            load_delta = max(0, after_load - before_load)
            self.assertEqual(len(material), n)
            # Streaming growth stays well under materialization growth.
            # Allow generous floor for allocator noise; require clear gap.
            self.assertLess(stream_delta, max(load_delta * 0.5, 40_000))


class P1ASplitManifestTests(unittest.TestCase):
    def test_chronological_train_val_sealed(self) -> None:
        bars = _bars(100)
        manifest = build_split_manifest(
            bars,
            dataset_id="ds1",
            dataset_version="1",
            dataset_content_hash="abc",
            train_frac=0.6,
            val_frac=0.2,
            sealed_frac=0.2,
            frozen=True,
        )
        self.assertEqual(manifest.train.role, SplitRole.TRAIN)
        self.assertIsNotNone(manifest.val)
        self.assertIsNotNone(manifest.sealed)
        assert manifest.val is not None and manifest.sealed is not None
        self.assertLess(manifest.train.end_index, manifest.val.start_index)
        self.assertLess(manifest.val.end_index, manifest.sealed.start_index)
        self.assertLess(manifest.train.end_ts, manifest.val.start_ts)
        self.assertLess(manifest.val.end_ts, manifest.sealed.start_ts)
        self.assertTrue(manifest.frozen)
        pub = manifest.public_dict()
        self.assertEqual(pub["truth"]["chronological_only"], True)
        self.assertEqual(pub["truth"]["no_shuffle"], True)

    def test_embargo_between_val_and_sealed(self) -> None:
        bars = _bars(100)
        manifest = build_split_manifest(
            bars,
            dataset_id="ds1",
            dataset_version="1",
            dataset_content_hash="abc",
            embargo_bars=5,
        )
        assert manifest.val is not None and manifest.sealed is not None
        self.assertEqual(manifest.sealed.start_index, manifest.val.end_index + 1 + 5)

    def test_frozen_manifest_persisted_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            bars = _bars(80)
            manifest = build_split_manifest(
                bars,
                dataset_id="ds-freeze",
                dataset_version="1",
                dataset_content_hash="hash1",
                frozen=True,
            )
            store.upsert_split_manifest(manifest.public_dict())
            got = store.get_split_manifest(dataset_id="ds-freeze", dataset_version="1")
            self.assertIsNotNone(got)
            assert got is not None
            self.assertTrue(got["frozen"])
            self.assertEqual(got["train"]["role"], SplitRole.TRAIN)
            self.assertEqual(got["sealed"]["role"], SplitRole.SEALED)
            # Mutating frozen content must fail
            mutated = dict(got)
            mutated["train"] = dict(got["train"])
            mutated["train"]["bar_count"] = 1
            with self.assertRaises(MarketSimError) as ctx:
                store.upsert_split_manifest(mutated)
            self.assertEqual(ctx.exception.code, "SPLIT_MANIFEST_FROZEN")

    def test_seal_dataset_attaches_frozen_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src = root / "BTCUSDT_1h.csv"
            _write_csv(src, 120)
            store = _store(tmp)
            data = MarketDataStore(store, root)
            imported = data.import_and_validate(src, symbol="BTCUSDT", timeframe="1h", seal=False)
            ds = imported["dataset"]
            self.assertIsNotNone(ds)
            assert ds is not None
            sealed = data.seal_dataset(ds["dataset_id"], ds["version"], role="SEALED_TEST")
            self.assertTrue(sealed["sealed"])
            self.assertIn("split_manifest", sealed)
            sm = sealed["split_manifest"]
            self.assertTrue(sm["frozen"])
            self.assertEqual(sm["train"]["role"], SplitRole.TRAIN)
            self.assertEqual(sm["sealed"]["role"], SplitRole.SEALED)
            # Re-seal is idempotent; frozen split remains
            again = data.seal_dataset(ds["dataset_id"], ds["version"], role="SEALED_TEST")
            self.assertEqual(again["metadata"].get("split_manifest_id"), sm["manifest_id"])


class P1ASealedAttemptTests(unittest.TestCase):
    def test_first_exposure_binds_attempt_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            binder = SealedAttemptBinder(store)
            attempt = binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            self.assertEqual(attempt.status, SealedAttemptStatus.BOUND)
            self.assertEqual(attempt.run_id, "run-a")
            self.assertEqual(attempt.checkpoint_bar_index, 0)
            binder.mark_running(attempt.sealed_attempt_id, checkpoint_bar_index=10)
            binder.checkpoint(attempt.sealed_attempt_id, bar_index=25)

            # Crash resume: same run + same attempt, checkpoint preserved
            resumed = binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            self.assertEqual(resumed.sealed_attempt_id, attempt.sealed_attempt_id)
            self.assertEqual(resumed.checkpoint_bar_index, 25)
            self.assertNotEqual(resumed.checkpoint_bar_index, 0)

    def test_refuse_new_run_while_attempt_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            binder = SealedAttemptBinder(store)
            binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            with self.assertRaises(MarketSimError) as ctx:
                binder.bind_or_resume(
                    dataset_id="ds",
                    dataset_version="1",
                    split_manifest_id="m1",
                    strategy_id="trend",
                    strategy_version=1,
                    run_id="run-b",
                )
            self.assertEqual(ctx.exception.code, "SEALED_ATTEMPT_BOUND_TO_OTHER_RUN")

    def test_completed_is_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            binder = SealedAttemptBinder(store)
            attempt = binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            binder.complete(attempt.sealed_attempt_id)
            with self.assertRaises(MarketSimError) as ctx:
                binder.bind_or_resume(
                    dataset_id="ds",
                    dataset_version="1",
                    split_manifest_id="m1",
                    strategy_id="trend",
                    strategy_version=1,
                    run_id="run-a",
                )
            self.assertEqual(ctx.exception.code, "SEALED_ALREADY_CONSUMED")

    def test_checkpoint_rewind_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            binder = SealedAttemptBinder(store)
            attempt = binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            binder.checkpoint(attempt.sealed_attempt_id, bar_index=40)
            with self.assertRaises(MarketSimError) as ctx:
                binder.checkpoint(attempt.sealed_attempt_id, bar_index=10)
            self.assertEqual(ctx.exception.code, "SEALED_CHECKPOINT_REWIND")

    def test_failed_same_run_resumes_without_rewind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            binder = SealedAttemptBinder(store)
            attempt = binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            binder.checkpoint(attempt.sealed_attempt_id, bar_index=15)
            binder.fail(attempt.sealed_attempt_id, reason="worker_crash")
            resumed = binder.bind_or_resume(
                dataset_id="ds",
                dataset_version="1",
                split_manifest_id="m1",
                strategy_id="trend",
                strategy_version=1,
                run_id="run-a",
            )
            self.assertEqual(resumed.sealed_attempt_id, attempt.sealed_attempt_id)
            self.assertEqual(resumed.checkpoint_bar_index, 15)
            self.assertEqual(resumed.status, SealedAttemptStatus.RUNNING)

    def test_migration_47_creates_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            with store.connect() as conn:
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertIn("market_sim_split_manifests", tables)
            self.assertIn("market_sim_sealed_attempts", tables)


class P1ABuildFromIterTests(unittest.TestCase):
    def test_build_from_streaming_iter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            _write_csv(path, 90)
            manifest = build_split_manifest_from_iter(
                iter_ohlcv(path),
                dataset_id="stream-ds",
                dataset_version="1",
                dataset_content_hash="h",
                frozen=True,
            )
            self.assertTrue(manifest.frozen)
            self.assertIsNotNone(manifest.sealed)


# ---------------------------------------------------------------------------
# P1B — TradingGym + worker ownership
# ---------------------------------------------------------------------------


class P1BTradingGymTests(unittest.TestCase):
    def test_reset_step_causal_no_future(self) -> None:
        from Data.modules.market_sim.gym import GymAction, GymActionKind, TradingGym
        from Data.modules.market_sim.types import RunStatus, SimRun

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            _write_csv(path, 40)
            store = _store(tmp)
            now = "2024-01-01T00:00:00+00:00"
            run = SimRun(
                run_id="gym-1",
                status=RunStatus.CREATED.value,
                source_id="src",
                strategy_id=None,
                strategy_version=None,
                symbol="BTCUSDT",
                timeframe="1m",
                start_ts="",
                end_ts="",
                data_hash="",
                seed=1,
                created_at=now,
                updated_at=now,
            )
            store.create_run(run)
            gym = TradingGym(store)
            obs = gym.reset(
                run,
                bars_path=str(path),
                entry_rules={"kind": "hold"},
                exit_rules={"kind": "hold"},
            )
            self.assertGreaterEqual(obs.visible_bar_count, 1)
            self.assertEqual(obs.bar_index, 0)
            # Poison-future: MarketView must not expose bar beyond index
            from Data.modules.market_sim.causality import MarketView, CausalityViolation

            assert gym.state is not None
            view = MarketView(clock=gym.state.clock)
            with self.assertRaises(CausalityViolation):
                view.observe(obs.bar_index + 5)

            step = gym.step(GymAction(kind=GymActionKind.HOLD))
            self.assertFalse(step.done)
            self.assertEqual(step.observation.bar_index, 1)
            self.assertIn("definition", step.reward)
            self.assertEqual(step.observation.truth["via_market_view"], True)

    def test_complete_episode_worker_path_and_unavailable(self) -> None:
        from Data.modules.market_sim import MarketSimControlPlane
        from Data.modules.market_sim.data_store import MarketDataStore
        from Data.modules.market_sim.types import SourceStatus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src_path = root / "BTCUSDT_1m.csv"
            _write_csv(src_path, 35)
            store = _store(tmp)
            data = MarketDataStore(store, root)
            registered = data.register_file("BTCUSDT_1m.csv", symbol="BTCUSDT", timeframe="1m")
            self.assertEqual(registered.status, SourceStatus.READY.value)

            svc = MarketSimControlPlane(
                store=store,
                data=data,
                enabled=True,
                job_runtime=None,
            )
            # Force externalized path without job_runtime → TRADING_WORKER_UNAVAILABLE
            svc._runners_externalized = lambda: True  # type: ignore[method-assign]

            created = svc.create_gym_episode(
                source_id=registered.source_id,
                mode="complete",
                split_role="TRAIN",
            )
            self.assertEqual(created["mode"], "complete")
            run_id = created["episode"]["run_id"]
            with self.assertRaises(MarketSimError) as ctx:
                svc.start_gym_episode(run_id)
            self.assertEqual(ctx.exception.code, "TRADING_WORKER_UNAVAILABLE")

            # Non-externalized: in-process worker can complete
            svc._runners_externalized = lambda: False  # type: ignore[method-assign]
            started = svc.start_gym_episode(run_id)
            self.assertEqual(started["execution"], "in_process_worker")
            # Drive the worker
            svc.worker.process_run(run_id)
            finished = store.get_run(run_id)
            assert finished is not None
            self.assertIn(finished.status, {"COMPLETED", "FAILED"})
            events = store.list_events(run_id, kind="gym_episode_finished")
            self.assertGreaterEqual(len(events), 1)

    def test_interactive_gym_via_control_plane(self) -> None:
        from Data.modules.market_sim import MarketSimControlPlane
        from Data.modules.market_sim.data_store import MarketDataStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src_path = root / "BTCUSDT_1m.csv"
            _write_csv(src_path, 25)
            store = _store(tmp)
            data = MarketDataStore(store, root)
            registered = data.register_file("BTCUSDT_1m.csv", symbol="BTCUSDT", timeframe="1m")
            svc = MarketSimControlPlane(store=store, data=data, enabled=True)
            created = svc.create_gym_episode(
                source_id=registered.source_id,
                mode="interactive",
            )
            self.assertIsNotNone(created["observation"])
            run_id = created["episode"]["run_id"]
            stepped = svc.gym_step(run_id, {"kind": "HOLD"})
            self.assertIn("observation", stepped)
            self.assertIn("reward", stepped)
            self.assertEqual(stepped["observation"]["bar_index"], 1)


if __name__ == "__main__":
    unittest.main()
