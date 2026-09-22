from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.datasets.offline import (
    discover_under_roots,
    offline_index_preflight,
)


class OfflineDiscoveryTests(unittest.TestCase):
    def test_discovers_allowed_extensions_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.jsonl").write_text('{"id":"1","text":"a"}\n', encoding="utf-8")
            (root / "skip.bin").write_bytes(b"\x00\x01")
            (root / ".hidden.jsonl").write_text("{}\n", encoding="utf-8")
            sources = discover_under_roots([("t", root)], max_files=50)
            paths = {s.relative_path for s in sources}
            self.assertIn("keep.jsonl", paths)
            self.assertNotIn("skip.bin", paths)
            self.assertTrue(all(not p.startswith(".") for p in paths))

    def test_rejects_parent_escape_via_symlink_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            target = outside / "secret.jsonl"
            target.write_text('{"id":"x","text":"y"}\n', encoding="utf-8")
            link = root / "linked.jsonl"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks not supported")
            sources = discover_under_roots([("t", root)], follow_symlinks=False)
            self.assertEqual(sources, [])

    def test_offline_preflight_blocks_remote_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = offline_index_preflight(
                target_dir=Path(tmp),
                source_size_bytes=100,
                embedding_status={"provider_id": "openai", "available": True, "local": False},
                offline_only=True,
            )
            self.assertFalse(pf.ok)
            self.assertTrue(any("REMOTE" in b for b in pf.blockers))

    def test_offline_preflight_allows_local_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = offline_index_preflight(
                target_dir=Path(tmp),
                source_size_bytes=10,
                embedding_status={"provider_id": "local_hash", "available": True},
                offline_only=True,
            )
            self.assertTrue(pf.ok)


if __name__ == "__main__":
    unittest.main()
