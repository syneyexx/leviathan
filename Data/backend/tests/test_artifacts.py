from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ArtifactStore(root / "db.sqlite", root / "artifacts")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_and_verify_hash(self) -> None:
        record = self.store.create_from_bytes(
            data=b"leviathan-artifact",
            artifact_type="text",
            producer="test",
            filename="note.txt",
            run_id="run-1",
        )
        self.assertTrue(Path(record.path).is_file())
        self.assertTrue(self.store.verify_hash(record.artifact_id))
        loaded = self.store.get(record.artifact_id)
        assert loaded is not None
        self.assertEqual(loaded.verification_status, "verified")

    def test_rejects_path_traversal_filename(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create_from_bytes(
                data=b"x",
                artifact_type="text",
                producer="test",
                filename="../evil.txt",
            )


if __name__ == "__main__":
    unittest.main()
