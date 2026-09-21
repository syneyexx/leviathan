from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lsp_light import find_references
from workspace_symbols import index_workspace_symbols, list_workspace_tree, preview_workspace_file


class WorkspaceSymbolsSymlinkBoundaryTests(unittest.TestCase):
    @staticmethod
    def _symlink_or_skip(testcase: unittest.TestCase, target: Path, link: Path) -> None:
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            testcase.skipTest(f"symlink unavailable on this host: {exc}")

    def test_symlinked_file_outside_workspace_is_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("def outside_secret_symbol():\n    return 1\n", encoding="utf-8")
            link = root / "linked.py"
            self._symlink_or_skip(self, outside, link)

            result = index_workspace_symbols(root, use_cache=False, query="outside_secret_symbol")

            self.assertEqual(result["symbols"], [])
            self.assertEqual(result["files_scanned"], 0)

    def test_lsp_references_do_not_follow_file_symlink_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("outside_secret_symbol()\n", encoding="utf-8")
            link = root / "linked.py"
            self._symlink_or_skip(self, outside, link)

            result = find_references(root, "outside_secret_symbol")

            self.assertEqual(result["references"], [])
            self.assertEqual(result["files_scanned"], 0)

    def test_regular_file_inside_workspace_remains_indexable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "inside.py").write_text("def inside_symbol():\n    return 1\n", encoding="utf-8")

            result = index_workspace_symbols(root, use_cache=False, query="inside_symbol")

            self.assertEqual(len(result["symbols"]), 1)
            self.assertEqual(result["symbols"][0]["name"], "inside_symbol")

    def test_tree_and_preview_respect_symlink_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            (root / "ok.py").write_text("print('ok')\n", encoding="utf-8")
            outside = base / "secret.txt"
            outside.write_text("SECRET\n", encoding="utf-8")
            link = root / "escape.txt"
            self._symlink_or_skip(self, outside, link)

            tree = list_workspace_tree(root)
            names = {entry["name"] for entry in tree["entries"]}
            self.assertIn("ok.py", names)
            self.assertNotIn("escape.txt", names)

            preview = preview_workspace_file(root, relative="ok.py")
            self.assertIn("ok", preview["content"])

            with self.assertRaises(ValueError):
                preview_workspace_file(root, relative="../secret.txt")
            with self.assertRaises(ValueError):
                preview_workspace_file(root, relative="escape.txt")


if __name__ == "__main__":
    unittest.main()
