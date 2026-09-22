from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.memory import MemoryKind, MemoryStatus, MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "mem.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_and_search(self) -> None:
        record = self.store.create(
            content="User prefers concise Leviathan answers",
            kind=MemoryKind.PREFERENCE,
            tags=["style"],
        )
        self.assertEqual(record.status, MemoryStatus.ACTIVE)
        self.assertTrue(record.public_dict()["truth"]["model_output_is_not_automatic_memory"])
        hits = self.store.search("concise Leviathan")
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0].memory_id, record.memory_id)

    def test_rejects_model_output_trust(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create(content="assistant said X", trust="model_output")

    def test_archive(self) -> None:
        record = self.store.create(content="temporary note")
        archived = self.store.set_status(record.memory_id, MemoryStatus.ARCHIVED)
        assert archived is not None
        self.assertEqual(archived.status, MemoryStatus.ARCHIVED)
        self.assertEqual(self.store.list(status=MemoryStatus.ACTIVE), [])

    def test_new_kinds_and_budgeted_retrieve(self) -> None:
        self.store.create(content="Decision to keep SQLite central", kind=MemoryKind.DECISION)
        self.store.create(content="Relation atom: A like B", kind=MemoryKind.RELATION)
        self.store.create(content="Summary of last research lane", kind=MemoryKind.SUMMARY)
        self.store.create(content="Residue leftover taxonomy", kind=MemoryKind.RESIDUE)
        hits = self.store.budgeted_retrieve("SQLite central", token_budget=50, limit=10)
        self.assertTrue(hits)
        self.assertTrue(any(h.kind == MemoryKind.DECISION for h in hits))

    def test_snapshot_restore_lock_safe(self) -> None:
        created = self.store.create(content="Snapshot me", kind=MemoryKind.EPISODIC, tags=["t"])
        snap = self.store.snapshot(label="test")
        self.assertTrue(snap["snapshot_id"])
        self.store.set_status(created.memory_id, MemoryStatus.ARCHIVED)
        restored = self.store.restore_snapshot(snap["snapshot_id"], replace_active=False)
        self.assertGreaterEqual(restored, 1)
        active = self.store.list(status=MemoryStatus.ACTIVE)
        self.assertTrue(any(item.content == "Snapshot me" for item in active))


if __name__ == "__main__":
    unittest.main()
