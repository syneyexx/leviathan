from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from build_agent import BuildAgentService


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BuildAgentRestoreAddedFileHonestyTests(unittest.TestCase):
    def test_restore_removes_file_that_apply_added_to_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source"
            source.mkdir()
            existing = source / "existing.txt"
            existing.write_text("before\n", encoding="utf-8")
            baseline_hash = _sha256(existing)

            service = BuildAgentService(base / "hades-workspace")
            run_id = "restore-added-file"
            run_root = service.runs_root / run_id
            work = run_root / "work"
            work.mkdir(parents=True)
            (work / "existing.txt").write_text("after\n", encoding="utf-8")
            (work / "added.txt").write_text("new file\n", encoding="utf-8")
            (run_root / "meta.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "source": str(source),
                        "work_root": str(work),
                        "baseline_commit": None,
                        "baseline_hashes": {"existing.txt": baseline_hash},
                    }
                ),
                encoding="utf-8",
            )

            applied = service.apply_to_source(run_id, approved=True)
            self.assertTrue(applied["applied"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "after\n")
            self.assertTrue((source / "added.txt").exists())

            restored = service.restore_backup(run_id)

            self.assertTrue(restored["restored"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "before\n")
            self.assertFalse((source / "added.txt").exists())


if __name__ == "__main__":
    unittest.main()
