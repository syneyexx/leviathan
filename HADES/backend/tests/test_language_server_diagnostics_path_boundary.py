from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from language_servers import read_diagnostics


class LanguageServerDiagnosticsPathBoundaryTests(unittest.TestCase):
    def test_parent_relative_path_outside_workspace_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("def (\n", encoding="utf-8")

            with patch("language_servers.shutil.which", return_value=None):
                result = read_diagnostics(root, paths=["../outside.py"])

            self.assertEqual(result["issues"], [])
            self.assertNotIn("py_compile", result["method"])

    def test_outside_target_is_not_forwarded_to_pyright(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("print('outside')\n", encoding="utf-8")

            def fake_which(name: str) -> str | None:
                return "/fake/pyright" if name == "pyright" else None

            with (
                patch("language_servers.shutil.which", side_effect=fake_which),
                patch("language_servers.subprocess.run") as run,
            ):
                result = read_diagnostics(root, paths=["../outside.py"])

            run.assert_not_called()
            self.assertEqual(result["issues"], [])
            self.assertNotIn("pyright", result["method"])

    def test_symlink_to_outside_workspace_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("def (\n", encoding="utf-8")
            link = root / "linked.py"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")

            with patch("language_servers.shutil.which", return_value=None):
                result = read_diagnostics(root, paths=["linked.py"])

            self.assertEqual(result["issues"], [])
            self.assertNotIn("py_compile", result["method"])

    def test_in_workspace_python_target_is_still_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            root.mkdir()
            bad = root / "bad.py"
            bad.write_text("def (\n", encoding="utf-8")

            with patch("language_servers.shutil.which", return_value=None):
                result = read_diagnostics(root, paths=["bad.py"])

            self.assertTrue(result["issues"])
            self.assertIn("py_compile", result["method"])


if __name__ == "__main__":
    unittest.main()
