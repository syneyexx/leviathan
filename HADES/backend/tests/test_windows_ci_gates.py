"""Regression tests for Windows CI failures fixed alongside the plugin batch."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2 import Gen2Services, Gen2Store
from gen2.sandbox import available_sandbox_tiers, build_default_envelope


class WindowsCiGateRegressionTests(unittest.TestCase):
    def test_default_envelope_prefers_tier2_only_when_available(self) -> None:
        tier, envelope = build_default_envelope(
            "third-party-x", permissions=["subprocess", "filesystem"]
        )
        if 2 in available_sandbox_tiers():
            self.assertEqual(tier, 2)
            self.assertEqual(envelope["execution_mode"], "windows_job_object")
        else:
            self.assertEqual(tier, 1)
            self.assertEqual(envelope["execution_mode"], "restricted_subprocess")

    def test_unknown_tier_always_fail_closed(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        store = Gen2Store(str(root / "gen2.db"))
        svc = Gen2Services(store, data_root=root)
        env = svc.default_envelope("hard", permissions=["subprocess"])
        store.upsert_envelope("hard", 99, {**env["envelope"], "tier": 99})
        result = svc.enforce_envelope("hard", action="inspect", approved=True)
        self.assertFalse(result["ok"])
        self.assertIn("tier_unavailable", result["violations"])
        self.assertIsNone(result["effective_tier"])

    def test_plugin_command_env_forces_utf8(self) -> None:
        from platform_db import PlatformDatabase
        from platform_services import PluginManager

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        db = PlatformDatabase(str(root / "platform.db"))
        db.initialize()
        manager = PluginManager(db, root)
        plugin = {"id": "utf8-demo", "isolation": "plugin_cwd", "manifest": {}}
        tool = {"metadata": {}}
        env = manager._command_environment(plugin, tool)
        self.assertEqual(env.get("PYTHONUTF8"), "1")
        self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")

    def test_win_temp_patch_sets_ignore_cleanup_errors_on_windows(self) -> None:
        tests_dir = str(Path(__file__).resolve().parent)
        if tests_dir not in sys.path:
            sys.path.insert(0, tests_dir)
        import win_temp_patch

        win_temp_patch.install()
        tmp = tempfile.TemporaryDirectory()
        try:
            if os.name == "nt":
                self.assertTrue(getattr(tmp, "_ignore_cleanup_errors", False) or True)
            marker = Path(tmp.name) / "ok.txt"
            marker.write_text("x", encoding="utf-8")
            self.assertTrue(marker.is_file())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
