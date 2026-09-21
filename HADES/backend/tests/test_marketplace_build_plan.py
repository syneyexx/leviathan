"""Tests for marketplace scan, build plan, and related capability wiring."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_agent import FileEdit, plan_multi_file_edits
from plugin_marketplace import scan_local_marketplace


REPO_ROOT = Path(__file__).resolve().parents[2]


class MarketplaceScanTests(unittest.TestCase):
    def test_scan_includes_local_stt_paste(self) -> None:
        catalog = scan_local_marketplace(REPO_ROOT / "plugins", installed=[])
        self.assertGreater(catalog["count"], 0)
        ids = {item["id"] for item in catalog["items"]}
        self.assertIn("local-stt-paste", ids)
        stt = next(item for item in catalog["items"] if item["id"] == "local-stt-paste")
        self.assertEqual(stt["status"], "available")
        self.assertTrue(stt["source_path"])

    def test_installed_needs_attention_when_not_ready(self) -> None:
        catalog = scan_local_marketplace(
            REPO_ROOT / "plugins",
            installed=[{"id": "local-stt-paste", "status": "error", "health": "degraded", "enabled": True}],
        )
        stt = next(item for item in catalog["items"] if item["id"] == "local-stt-paste")
        self.assertEqual(stt["status"], "installed_needs_attention")


class BuildPlanTests(unittest.TestCase):
    def test_plan_lists_files_without_apply(self) -> None:
        plan = plan_multi_file_edits(
            [
                FileEdit(path="a.py", action="create", content="print(1)\n"),
                FileEdit(path="b.py", action="replace", content="x=1\n", old_content="x=0\n"),
            ],
            goal="Composer demo",
        )
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["file_count"], 2)
        self.assertTrue(plan["approval_required"])
        self.assertIn("a.py", plan["unique_paths"])

    def test_plan_rejects_unsafe_path(self) -> None:
        with self.assertRaises(ValueError):
            plan_multi_file_edits([FileEdit(path="../evil.py", action="create", content="x")])


class SymbolCacheSmokeTests(unittest.TestCase):
    def test_index_with_cache_roundtrip(self) -> None:
        from workspace_symbols import index_workspace_symbols

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
            first = index_workspace_symbols(root, query="hello", limit=20)
            self.assertGreaterEqual(first["files_scanned"], 1)
            names = {item["name"] for item in first["symbols"]}
            self.assertIn("hello", names)
            second = index_workspace_symbols(root, query="hello", limit=20)
            self.assertGreaterEqual(second["files_scanned"], 1)


if __name__ == "__main__":
    unittest.main()
