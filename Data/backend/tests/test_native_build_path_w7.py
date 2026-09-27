"""Platform-aware native data-plane binary path resolution."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "build_native_data_plane.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_native_data_plane", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NativeBuildPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_build_module()

    def test_windows_binary_names(self) -> None:
        self.assertEqual(self.mod.binary_filename(windows=True), "leviathan-data-plane.exe")
        native = Path("/tmp/native")
        built = self.mod.built_binary_path(native, release=True, windows=True)
        self.assertEqual(built.name, "leviathan-data-plane.exe")
        self.assertTrue(str(built).endswith("target/release/leviathan-data-plane.exe"))
        dest = self.mod.install_binary_path(native, windows=True)
        self.assertEqual(dest, native / "bin" / "leviathan-data-plane.exe")

    def test_unix_binary_names(self) -> None:
        self.assertEqual(self.mod.binary_filename(windows=False), "leviathan-data-plane")
        native = Path("/tmp/native")
        built = self.mod.built_binary_path(native, release=False, windows=False)
        self.assertEqual(built.name, "leviathan-data-plane")
        self.assertTrue(str(built).endswith("target/debug/leviathan-data-plane"))
        dest = self.mod.install_binary_path(native, windows=False)
        self.assertEqual(dest, native / "bin" / "leviathan-data-plane")

    def test_current_platform_matches_sys(self) -> None:
        expected_exe = sys.platform.startswith("win")
        name = self.mod.binary_filename()
        if expected_exe:
            self.assertTrue(name.endswith(".exe"))
        else:
            self.assertFalse(name.endswith(".exe"))

    def test_installed_unix_binary_exists_after_build_when_present(self) -> None:
        """Live artifact from scripts/build_native_data_plane.py on Unix hosts."""
        if sys.platform.startswith("win"):
            self.skipTest("unix-only live path check")
        dest = (
            Path(__file__).resolve().parents[2]
            / "native"
            / "bin"
            / self.mod.binary_filename(windows=False)
        )
        if not dest.is_file():
            self.skipTest(f"native binary not installed at {dest}")
        self.assertFalse(dest.name.endswith(".exe"))
        self.assertEqual(dest.name, "leviathan-data-plane")


if __name__ == "__main__":
    unittest.main()
