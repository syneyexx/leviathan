from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import Migration, MigrationError, MigrationRunner


class MigrationRunnerTests(unittest.TestCase):
    def test_applies_baseline_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite"
            runner = MigrationRunner(path)
            first = runner.apply_all()
            second = runner.apply_all()
            self.assertEqual(first, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22])
            self.assertEqual(second, [])
            conn_version = MigrationRunner(path)
            import sqlite3

            with sqlite3.connect(path) as conn:
                self.assertEqual(conn_version.current_version(conn), 22)

    def test_rejects_non_contiguous_versions(self) -> None:
        with self.assertRaises(MigrationError):
            MigrationRunner(
                Path("unused.db"),
                migrations=(
                    Migration(version=1, name="a", apply=lambda c: None),
                    Migration(version=3, name="b", apply=lambda c: None),
                ),
            )


if __name__ == "__main__":
    unittest.main()
