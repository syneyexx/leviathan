from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workspace_open import open_in_external_editor, resolve_editor_binary


class WorkspaceOpenExternalTests(unittest.TestCase):
    def test_missing_editor_is_visible_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x=1\n", encoding="utf-8")
            with mock.patch("workspace_open.resolve_editor_binary", return_value=None):
                result = open_in_external_editor(root, relative="a.py")
            self.assertFalse(result["opened"])
            self.assertEqual(result["error"], "editor_not_found")

    def test_path_escape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ws"
            root.mkdir()
            (root / "a.py").write_text("x=1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                open_in_external_editor(root, relative="../a.py")

    def test_opens_with_argv_shell_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "a.py"
            target.write_text("x=1\n", encoding="utf-8")
            with mock.patch("workspace_open.resolve_editor_binary", return_value="/usr/bin/code"), mock.patch(
                "workspace_open.subprocess.Popen"
            ) as popen:
                result = open_in_external_editor(root, relative="a.py")
            self.assertTrue(result["opened"])
            popen.assert_called_once()
            args, kwargs = popen.call_args
            self.assertEqual(args[0], ["/usr/bin/code", str(target.resolve())])
            self.assertFalse(kwargs.get("shell"))


if __name__ == "__main__":
    unittest.main()
