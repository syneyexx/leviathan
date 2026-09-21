from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from build_agent import BuildAgentService


class BuildAgentRunIdBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows path semantics are required for this regression")
    def test_restore_rejects_backslash_run_id_that_escapes_runs_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = base / "workspace"
            service = BuildAgentService(workspace)

            outside_run = base / "outside-run"
            work = outside_run / "work"
            backup = outside_run / "pre_apply_backup"
            work.mkdir(parents=True)
            backup.mkdir(parents=True)

            source = base / "source"
            source.mkdir()
            source_file = source / "owned.txt"
            source_file.write_text("applied\n", encoding="utf-8")
            (work / "owned.txt").write_text("applied\n", encoding="utf-8")
            (backup / "owned.txt").write_text("before\n", encoding="utf-8")
            (outside_run / "meta.json").write_text(
                json.dumps(
                    {
                        "run_id": "foreign",
                        "source": str(source),
                        "work_root": str(work),
                        "baseline_hashes": {},
                    }
                ),
                encoding="utf-8",
            )

            malicious_run_id = r"..\..\outside-run"
            with self.assertRaises(ValueError):
                service.restore_backup(malicious_run_id)

            self.assertEqual(source_file.read_text(encoding="utf-8"), "applied\n")



    def test_restore_rejects_parent_run_id_that_escapes_runs_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            service = BuildAgentService(base / "workspace")
            with self.assertRaises(ValueError):
                service.restore_backup("../outside-run")


if __name__ == "__main__":
    unittest.main()
