"""Semantic backup truth invariants.

This regression intentionally protects the release boundary: a full-workspace
backup must never report successful completion when its primary database was
requested but is absent. Keep this test red until the production backup service
fails closed for that condition; do not weaken or skip it to make CI green.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workspace_backup import WorkspaceBackupService


class WorkspaceBackupTruthInvariantTests(unittest.TestCase):
    def test_missing_primary_database_cannot_report_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            root.mkdir(parents=True, exist_ok=True)
            missing_db = root / "hades.db"
            service = WorkspaceBackupService(root, db_path=missing_db)

            result = service.create_archive(include=["database"])

            self.assertNotIn(
                result.get("phase"),
                {"completed", "completed_with_warnings"},
                "A requested primary database that does not exist must make the full-workspace backup fail closed.",
            )
            self.assertTrue(
                result.get("error") or (result.get("manifest") or {}).get("missing_required"),
                "The non-success result must expose machine-readable evidence for the missing required store.",
            )


if __name__ == "__main__":
    unittest.main()
