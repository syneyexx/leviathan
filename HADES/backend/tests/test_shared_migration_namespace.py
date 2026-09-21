from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from gen2.store import Gen2Store
from platform_db import PlatformDatabase


class SharedMigrationNamespaceTests(unittest.TestCase):
    def _platform_then_gen2(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "shared.db"

        platform = PlatformDatabase(str(path))
        platform.initialize()
        Gen2Store(str(path))
        return path

    @staticmethod
    def _tables(path: Path) -> set[str]:
        with sqlite3.connect(path) as db:
            return {
                str(row[0])
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

    def test_platform_first_does_not_skip_gen2_migration_8(self) -> None:
        """Known defect: Platform migration id 8 can mask Gen2 migration 8."""
        path = self._platform_then_gen2()
        tables = self._tables(path)
        self.assertIn("gen2_mission_executions", tables)
        with sqlite3.connect(path) as db:
            mission_columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(gen2_missions)")
            }
        self.assertIn("execution_id", mission_columns)
        self.assertIn("executions_json", mission_columns)

    def test_platform_first_does_not_skip_gen2_migration_10(self) -> None:
        """Known defect: Platform migration id 10 can mask Gen2 migration 10."""
        path = self._platform_then_gen2()
        tables = self._tables(path)
        self.assertIn("gen2_workflows", tables)
        self.assertIn("gen2_workflow_revisions", tables)
        self.assertIn("gen2_workflow_runs", tables)

    def test_platform_first_does_not_skip_gen2_migration_11(self) -> None:
        """Known defect: Platform migration id 11 can mask Gen2 migration 11."""
        path = self._platform_then_gen2()
        tables = self._tables(path)
        self.assertIn("gen2_jit_grants", tables)
        self.assertIn("gen2_plugin_integrity", tables)


if __name__ == "__main__":
    unittest.main()
