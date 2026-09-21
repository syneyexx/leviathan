from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPO_ROOT / "HADES_LAUNCHER.py"


def load_launcher_module():
    root_text = str(REPO_ROOT)
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        spec = importlib.util.spec_from_file_location("hades_launcher_packaging_test", LAUNCHER_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load HADES_LAUNCHER.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            try:
                sys.path.remove(root_text)
            except ValueError:
                pass


class LauncherPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launcher = load_launcher_module()

    def test_source_mode_uses_launcher_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "HADES_LAUNCHER.py"
            resolved = self.launcher.application_root(frozen=False, script_file=script)
            self.assertEqual(resolved, root.resolve())

    def test_frozen_mode_uses_executable_directory_not_bundle_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            install_root = base / "install"
            bundle_root = base / "_MEI12345"
            executable = install_root / "HADES.exe"
            bundled_script = bundle_root / "HADES_LAUNCHER.py"

            resolved = self.launcher.application_root(
                frozen=True,
                executable=executable,
                script_file=bundled_script,
            )

            self.assertEqual(resolved, install_root.resolve())
            self.assertNotEqual(resolved, bundle_root.resolve())


if __name__ == "__main__":
    unittest.main()
