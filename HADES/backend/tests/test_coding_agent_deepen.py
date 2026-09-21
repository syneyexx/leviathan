"""Focused regressions for coding-agent deepen: build loop, indexer, LSP, debug, release."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_agent import BuildAgentService, FileEdit, plan_multi_file_edits
from debug_agent import diagnose_failure
from lsp_light import find_references
from release_confidence import inventory_gates, parse_what_broke
from workspace_symbols import index_workspace_symbols, refresh_workspace_index


class ComposerAndBuildLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.build = BuildAgentService(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plan_multi_file(self) -> None:
        plan = plan_multi_file_edits(
            [
                FileEdit(path="a.py", action="replace", content="x=1\n"),
                FileEdit(path="b.py", action="create", content="y=2\n"),
            ],
            goal="multi-file fix",
        )
        self.assertEqual(plan["file_count"], 2)
        self.assertEqual(plan["edit_count"], 2)
        self.assertTrue(plan["approval_required"])
        self.assertIn("multi-file fix", plan["goal"])

    def test_repair_wave_verifies_after_failure(self) -> None:
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        result = self.build.run_repair_loop(
            repo,
            [FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a - b\n")],
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=2,
            repair_waves=[[FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a + b\n")]],
            goal="fix add",
        )
        self.assertEqual(result.status, "verified", result.to_dict())
        phases = [item.get("phase") for item in result.loop_timeline]
        self.assertIn("test", phases)
        self.assertIn("diagnose", phases)
        self.assertIn("repair", phases)
        self.assertTrue(result.report.get("verified"))
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))

    def test_no_fake_retry_without_repair_wave(self) -> None:
        repo = self.root / "repo2"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        result = self.build.run_repair_loop(
            repo,
            [FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a - b\n")],
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=3,
        )
        self.assertEqual(result.status, "tests_failed")
        self.assertEqual(len(result.test_results), 1)
        blocked = [item for item in result.loop_timeline if item.get("phase") == "repair"]
        self.assertTrue(blocked)
        self.assertEqual(blocked[0].get("status"), "blocked")

    def test_preview_and_changed_only_apply(self) -> None:
        repo = self.root / "repo3"
        repo.mkdir()
        (repo / "keep.py").write_text("KEEP\n", encoding="utf-8")
        (repo / "app.py").write_text("OLD\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        result = self.build.run_repair_loop(
            repo,
            [FileEdit(path="app.py", action="replace", content="NEW\n")],
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=1,
        )
        self.assertEqual(result.status, "verified", result.to_dict())
        preview = self.build.preview_apply(result.run_id)
        self.assertGreaterEqual(preview["file_count"], 1)
        self.assertTrue(any(item["path"] == "app.py" for item in preview["files"]))
        applied = self.build.apply_to_source(result.run_id, approved=True)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "NEW\n")
        self.assertEqual((repo / "keep.py").read_text(encoding="utf-8"), "KEEP\n")
        self.assertIn("app.py", applied["files"])
        self.assertNotIn("keep.py", applied["files"])


class IndexerAndLspTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text(
            "def alpha_helper():\n    return 1\n\ndef additional():\n    return alpha_helper()\n",
            encoding="utf-8",
        )
        self.cache = self.root / "cache.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refresh_and_cache_reuse(self) -> None:
        first = refresh_workspace_index(self.root, cache_path=self.cache, force=True)
        self.assertGreaterEqual(first["symbol_count"], 2)
        self.assertGreaterEqual(first["files_rescanned"], 1)
        second = refresh_workspace_index(self.root, cache_path=self.cache, force=False)
        self.assertGreaterEqual(second["files_reused"], 1)
        indexed = index_workspace_symbols(self.root, query="alpha", cache_path=self.cache, use_cache=True)
        self.assertTrue(indexed.get("from_cache"))
        self.assertIs(indexed.get("embeddings"), False)
        self.assertIn("embeddings_note", indexed)
        self.assertTrue(any(item["name"] == "alpha_helper" for item in indexed["symbols"]))
        self.assertIn("tree", indexed)

    def test_references_use_word_boundary(self) -> None:
        refs = find_references(self.root, "alpha_helper")
        self.assertGreaterEqual(refs["count"], 1)
        noisy = find_references(self.root, "add")
        for item in noisy["references"]:
            snippet = str(item.get("snippet") or "")
            self.assertNotIn("additional", snippet)


class DebugAndReleaseTests(unittest.TestCase):
    def test_debug_what_broke_and_proposed_stub(self) -> None:
        logs = (
            "FAIL: test_add (__main__.T)\n"
            "AssertionError: -1 != 5\n"
            "app.py:2: AssertionError\n"
        )
        report = diagnose_failure(
            logs=logs,
            failing_test="test_add",
            context_files=[{"path": "app.py", "content": "def add(a, b):\n    return a - b\n"}],
        )
        self.assertEqual(report["status"], "diagnosed")
        self.assertTrue(report["what_broke"])
        self.assertTrue(report["proposed_edits"])
        self.assertEqual(report["proposed_edits"][0]["action"], "patch_lines")
        self.assertEqual(report["proposed_edits"][0]["status"], "review_required")

    def test_release_what_broke_parsing(self) -> None:
        items = parse_what_broke("FAIL: test_foo\nERROR: test_bar\nOK\n")
        self.assertEqual(items[0]["label"], "test_foo")
        self.assertEqual(items[1]["label"], "test_bar")
        repo = Path(__file__).resolve().parents[2]
        inventory = inventory_gates(repo)
        self.assertIn("what_broke", inventory)
        self.assertTrue(any(gate["id"] == "python_syntax_critical" for gate in inventory["gates"]))
        self.assertIn("verify_stages", inventory)
        if inventory["verify_stages"]:
            self.assertEqual(inventory["verify_stages"][0].get("status"), "manual")


if __name__ == "__main__":
    unittest.main()
