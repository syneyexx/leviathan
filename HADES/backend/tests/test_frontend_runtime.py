from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.frontend_runtime import frontend_shell_command, resolve_frontend_mode


class FrontendRuntimeTests(unittest.TestCase):
    def test_defaults_to_dev_without_dist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve_frontend_mode(root), "dev")
            self.assertIn("npm run dev", " ".join(frontend_shell_command(root)))

    def test_prefers_production_when_dist_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dist").mkdir()
            (root / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            self.assertEqual(resolve_frontend_mode(root), "production")
            self.assertIn("npm run start", " ".join(frontend_shell_command(root)))

    def test_explicit_dev_mode_overrides_dist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dist").mkdir()
            (root / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            with mock.patch.dict("os.environ", {"HADES_FRONTEND_MODE": "dev"}, clear=False):
                self.assertEqual(resolve_frontend_mode(root), "dev")


if __name__ == "__main__":
    unittest.main()
