"""Goal-driven coding agent: explore → fix → test without pre-baked edits."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_agent import BuildAgentService, FileEdit
from coding_agent import CodingAgentService, explore_repository


class GoalDrivenCodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.build = BuildAgentService(self.root)
        self.coding = CodingAgentService(self.build)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _buggy_repo(self) -> Path:
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
        return repo

    def test_explore_finds_app_and_test(self) -> None:
        repo = self._buggy_repo()
        hits = explore_repository(repo, "Repareer de fout in add")
        paths = {h.path for h in hits}
        self.assertIn("app.py", paths)
        self.assertIn("test_app.py", paths)

    def test_goal_only_run_produces_verified_diff(self) -> None:
        repo = self._buggy_repo()
        result = self.coding.run_from_goal(
            repo,
            "Repareer de fout in add en voeg een passende regressietest toe.",
            test_suite="unittest",
            max_attempts=3,
            auto_repair=True,
        )
        self.assertEqual(result["status"], "verified", result)
        self.assertTrue(result.get("diff_text") or result.get("applied_edits"))
        coding = result.get("coding") or {}
        self.assertIn("context", coding)
        self.assertEqual(coding["context"]["config_version"], "coding_agent.v1")
        self.assertTrue(coding["explore"]["hits"])
        # Source repo must remain untouched until apply.
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))
        # Worktree should contain the fix.
        work = Path(result["work_root"])
        self.assertIn("return a + b", (work / "app.py").read_text(encoding="utf-8"))
        self.assertIn("test_add_regression", (work / "test_app.py").read_text(encoding="utf-8"))

    def test_auto_repair_without_initial_edits(self) -> None:
        repo = self._buggy_repo()
        # Force empty propose by using a goal that doesn't match heuristic keywords for initial edit,
        # then rely on repair after failing tests — use goal without fix/repareer but still explore.
        # Actually use empty heuristic path: pass edits=[] via run_repair_loop with generator only.
        result = self.build.run_repair_loop(
            repo,
            [],  # no initial edits — tests fail on buggy baseline copied to worktree
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=3,
            goal="fix add",
            repair_generator=lambda work, diagnosis, test, attempt: self.coding.propose_repair(
                work,
                goal="fix add",
                diagnosis=diagnosis,
                test_result=test,
                previous_signatures=set(),
            ),
        )
        self.assertEqual(result.status, "verified", result.to_dict())
        phases = [item.get("phase") for item in result.loop_timeline]
        self.assertIn("diagnose", phases)
        self.assertIn("repair", phases)

    def test_repeat_repair_stops_honestly(self) -> None:
        repo = self._buggy_repo()
        bad = FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a - b\n")
        calls = {"n": 0}

        def always_same(work, diagnosis, test, attempt):
            calls["n"] += 1
            return [bad], {"method": "repeat"}

        result = self.build.run_repair_loop(
            repo,
            [bad],
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=3,
            repair_generator=always_same,
        )
        self.assertEqual(result.status, "tests_failed")
        self.assertTrue(
            "Herhaalde patch" in (result.error or "") or "herhaalde dezelfde patch" in (result.error or "").lower(),
            result.error,
        )


if __name__ == "__main__":
    unittest.main()
