from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_agent import BuildAgentService


class BuildAgentTestTargetBoundaryTests(unittest.TestCase):
    def test_pytest_parent_relative_target_outside_worktree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            work = base / "work"
            work.mkdir()
            outside = base / "outside_test.py"
            outside.write_text("def test_outside():\n    assert True\n", encoding="utf-8")
            service = BuildAgentService(base / "hades-workspace")
            fake = subprocess.CompletedProcess(
                args=["python", "-m", "pytest", "../outside_test.py"],
                returncode=0,
                stdout="",
                stderr="",
            )

            with patch("build_agent.subprocess.run", return_value=fake) as run:
                with self.assertRaises(ValueError):
                    service.run_tests(work, suite="pytest", extra_args=["../outside_test.py"])

            run.assert_not_called()

    def test_in_worktree_relative_pytest_target_remains_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            work = base / "work"
            tests = work / "tests"
            tests.mkdir(parents=True)
            target = tests / "test_ok.py"
            target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            service = BuildAgentService(base / "hades-workspace")
            fake = subprocess.CompletedProcess(
                args=["python", "-m", "pytest", "tests/test_ok.py"],
                returncode=0,
                stdout="",
                stderr="",
            )

            with patch("build_agent.subprocess.run", return_value=fake) as run:
                result = service.run_tests(work, suite="pytest", extra_args=["tests/test_ok.py"])

            self.assertEqual(result["status"], "passed")
            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
