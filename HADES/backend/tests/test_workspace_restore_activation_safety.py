from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workspace_backup import WorkspaceBackupService


class WorkspaceRestoreActivationSafetyTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_unvalidated_directory_cannot_be_activated_as_workspace(self) -> None:
        """Known defect: activation currently trusts any directory containing a DB.

        Keep this expectedFailure while F-2026-09-13-024 is open. A repaired
        activation path must bind activation to a successful restore validation
        result rather than accepting an arbitrary caller-supplied filesystem root.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            active = base / "active"
            active.mkdir()
            (active / "hades.db").write_bytes(b"active-database")
            marker = active / "marker.txt"
            marker.write_text("keep-active", encoding="utf-8")

            arbitrary = base / "arbitrary"
            arbitrary.mkdir()
            (arbitrary / "hades.db").write_bytes(b"not-a-validated-hades-archive")

            service = WorkspaceBackupService(active, db_path=active / "hades.db")
            result = service.activate_restored(arbitrary, confirm=True, backup_current=False)

            self.assertFalse(result.get("ok"))
            self.assertTrue(result.get("active_workspace_untouched"))
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep-active")
            self.assertEqual((active / "hades.db").read_bytes(), b"active-database")


if __name__ == "__main__":
    unittest.main()
