from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from workspace_git import workspace_git_commit, workspace_git_status


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


class WorkspaceGitHelperTests(unittest.TestCase):
    def test_non_git_is_honest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = workspace_git_status(root)
            self.assertFalse(result["is_git"])
            self.assertEqual(result["error"], "not_a_git_repository")

    def test_status_diff_and_explicit_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _git(root, "init")
            _git(root, "config", "user.email", "hades@example.com")
            _git(root, "config", "user.name", "HADES")
            (root / "a.txt").write_text("one\n", encoding="utf-8")
            _git(root, "add", "a.txt")
            _git(root, "commit", "-m", "init")
            (root / "a.txt").write_text("two\n", encoding="utf-8")

            status = workspace_git_status(root)
            self.assertTrue(status["is_git"])
            self.assertGreaterEqual(int(status["dirty_count"]), 1)
            self.assertIn("two", status.get("diff") or "")

            with self.assertRaises(PermissionError):
                workspace_git_commit(root, message="nope", approved=False)

            committed = workspace_git_commit(root, message="wave12", approved=True)
            self.assertTrue(committed["committed"])
            clean = workspace_git_status(root)
            self.assertEqual(clean.get("dirty_count"), 0)


if __name__ == "__main__":
    unittest.main()
