from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_agent import BuildAgentService


class BuildAgentCopySymlinkBoundaryTests(unittest.TestCase):
    def test_detect_baseline_does_not_hash_outside_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source"
            source.mkdir()
            outside = base / "outside.txt"
            outside.write_text("ASTRA_OUTSIDE_BASELINE_SECRET\n", encoding="utf-8")
            link = source / "linked.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")

            service = BuildAgentService(base / "hades-workspace")
            not_git = subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="")
            with patch.object(service, "_git", return_value=not_git):
                _commit, hashes = service.detect_baseline(source)

            self.assertNotIn("linked.txt", hashes)

    def test_copy_fallback_does_not_materialize_outside_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source"
            source.mkdir()
            outside = base / "outside.txt"
            outside.write_text("ASTRA_OUTSIDE_BUILD_SECRET\n", encoding="utf-8")
            link = source / "linked.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")

            service = BuildAgentService(base / "hades-workspace")
            with patch.object(service, "detect_baseline", return_value=(None, {})):
                work, _commit, _hashes = service.prepare_workspace(source)

            copied = work / "linked.txt"
            self.assertFalse(copied.exists())
            self.assertFalse(copied.is_symlink())

    def test_changed_files_ignores_outside_symlink_created_in_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source"
            source.mkdir()
            outside = base / "outside.txt"
            outside.write_text("ASTRA_OUTSIDE_CHANGED_FILE_SECRET\n", encoding="utf-8")

            service = BuildAgentService(base / "hades-workspace")
            run_id = "build-boundary"
            run_root = service.runs_root / run_id
            work = run_root / "work"
            work.mkdir(parents=True)
            link = work / "generated-link.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")

            (run_root / "meta.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "source": str(source),
                        "work_root": str(work),
                        "baseline_hashes": {},
                    }
                ),
                encoding="utf-8",
            )

            changed = service._changed_files(run_id)

            self.assertFalse(any(item.get("path") == "generated-link.txt" for item in changed))


if __name__ == "__main__":
    unittest.main()
