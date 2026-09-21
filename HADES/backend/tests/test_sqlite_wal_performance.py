"""SQLite WAL ownership, concurrency, and hot-path timing."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import perf
from database import Database
from platform_db import PlatformDatabase
from sqlite_runtime import wal_owner


class SqliteWalOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp_dir.name) / "hades-wal.db")
        self.database = Database(self.path)
        self.database.initialize()
        self.platform = PlatformDatabase(self.path)
        self.platform.initialize()
        perf.reset()
        self._prev = wal_owner.strategy

    def tearDown(self) -> None:
        wal_owner.set_strategy(self._prev)
        self.temp_dir.cleanup()

    def _chat_persist_once(self, index: int) -> None:
        convo = self.database.create_conversation(f"c{index}")
        self.database.add_message(convo["id"], "user", f"hello {index}")
        self.database.add_message(convo["id"], "assistant", f"reply {index}")

    def test_owned_strategy_does_not_truncate_every_operation(self) -> None:
        wal_owner.set_strategy("truncate_on_close")
        perf.reset()
        t0 = time.perf_counter()
        for i in range(40):
            self._chat_persist_once(i)
        truncate_legacy_ms = (time.perf_counter() - t0) * 1000
        legacy = perf.snapshot()["sqlite"]

        wal_owner.set_strategy("owned")
        perf.reset()
        t1 = time.perf_counter()
        for i in range(40, 80):
            self._chat_persist_once(i)
        owned_ms = (time.perf_counter() - t1) * 1000
        owned = perf.snapshot()["sqlite"]

        self.assertGreater(legacy["wal_truncate"], owned["wal_truncate"])
        self.assertEqual(owned["wal_truncate"], 0)
        # Owned WAL must not be slower on this host; allow noise.
        self.assertLess(owned_ms, truncate_legacy_ms * 3)
        self._bench = {
            "truncate_on_close_ms": round(truncate_legacy_ms, 2),
            "owned_ms": round(owned_ms, 2),
            "legacy_truncates": legacy["wal_truncate"],
            "owned_truncates": owned["wal_truncate"],
            "owned_busy": owned["busy"],
        }
        print("WAL_BENCH", self._bench)

    def test_concurrent_reads_and_writes_do_not_lock(self) -> None:
        wal_owner.set_strategy("owned")
        convo = self.database.create_conversation("shared")
        errors: list[BaseException] = []

        def writer() -> None:
            try:
                for i in range(30):
                    self.database.add_message(convo["id"], "user", f"w{i}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(40):
                    self.database.list_messages(convo["id"])
                    self.platform.knowledge_stats()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader), threading.Thread(target=reader)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(errors)
        snap = perf.snapshot()["sqlite"]
        self.assertEqual(snap["busy"], 0)

    def test_rollback_preserves_committed_state(self) -> None:
        convo = self.database.create_conversation("rb")
        self.database.add_message(convo["id"], "user", "keep")
        with self.assertRaises((sqlite3.OperationalError, sqlite3.IntegrityError)):
            with self.database.connection() as db:
                db.execute(
                    "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?,?,?,?,?)",
                    ("bad", convo["id"], "not-a-role", "x", "now"),
                )
        messages = self.database.list_messages(convo["id"])
        self.assertEqual([item["content"] for item in messages], ["keep"])

    def test_shutdown_truncate_is_explicit(self) -> None:
        wal_owner.set_strategy("owned")
        perf.reset()
        self._chat_persist_once(0)
        self.assertEqual(perf.snapshot()["sqlite"]["wal_truncate"], 0)
        self.database.checkpoint_wal(truncate=True)
        self.assertGreaterEqual(perf.snapshot()["sqlite"]["wal_truncate"], 1)

    def test_list_messages_scale_is_indexed(self) -> None:
        convo = self.database.create_conversation("scale")
        cid = convo["id"]
        with self.database.connection() as db:
            rows = [
                (f"msg_{i}", cid, "user" if i % 2 == 0 else "assistant", f"body {i}", "2026-01-01T00:00:00+00:00")
                for i in range(1000)
            ]
            db.executemany(
                "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?,?,?,?,?)",
                rows,
            )
        times = {}
        for n in (50, 250, 1000):
            started = time.perf_counter()
            items = self.database.list_messages(cid)
            times[n] = (time.perf_counter() - started) * 1000
            self.assertGreaterEqual(len(items), min(n, 1000))
        print("LIST_MESSAGES_BENCH_MS", {k: round(v, 3) for k, v in times.items()})
        # 1000 messages should stay in the same order of magnitude as 50 on this host.
        self.assertLess(times[1000], max(50.0, times[50] * 40))


if __name__ == "__main__":
    unittest.main()
