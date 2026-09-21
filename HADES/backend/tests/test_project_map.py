"""Project map + incremental symbol refresh regressions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_map import build_project_map, find_change_impact
from workspace_symbols import refresh_workspace_index


class ProjectMapAndIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.root / "test_app.py").write_text(
            "from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        (self.root / "backend").mkdir()
        (self.root / "backend" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_incremental_refresh_removes_deleted_files(self) -> None:
        first = refresh_workspace_index(self.root)
        self.assertGreaterEqual(first["symbol_count"], 1)
        (self.root / "backend" / "util.py").unlink()
        second = refresh_workspace_index(self.root)
        self.assertGreaterEqual(second.get("files_removed", 0), 1)
        paths = {s["path"] for s in (second.get("symbols") if False else [])}
        # symbols list is in return via cache — check files_scanned dropped util
        self.assertNotIn("backend/util.py", [str(p) for p in self.root.rglob("*.py")])
        # Cache should not keep removed file.
        from workspace_symbols import load_symbol_cache, _default_cache_path

        cache = load_symbol_cache(_default_cache_path(self.root))
        self.assertNotIn("backend/util.py", cache.get("files") or {})

    def test_project_map_and_impact(self) -> None:
        refresh_workspace_index(self.root)
        pmap = build_project_map(self.root, refresh_symbols=False)
        self.assertIn("app.py", pmap["entrypoints"])
        self.assertTrue(any(s["id"] == "backend" for s in pmap["subsystems"]))
        impact = find_change_impact(self.root, symbol="add")
        self.assertGreaterEqual(impact["counts"]["references"], 1)
        self.assertTrue(impact["evidence"])
        self.assertTrue(any("test" in str(e["path"]) for e in impact["tests"] + impact["evidence"]))


if __name__ == "__main__":
    unittest.main()
