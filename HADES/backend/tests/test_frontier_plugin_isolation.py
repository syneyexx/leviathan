"""Focused tests: PluginManager secured isolation via execution_isolation.

Preserves:
- trusted / restricted_env / plugin_cwd unbounded subprocess path
- fail-closed secured (no fallback to subprocess/native)
- Windows honesty (Job Objects ≠ FS isolation; IsolationUnavailable)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution_isolation import IsolationResult, IsolationUnavailable, SECURED_MODE
from platform_db import PlatformDatabase
from platform_services import PluginManager
from plugin_runtime_v2 import normalize_isolation


class NormalizeSecuredIsolationTests(unittest.TestCase):
    def test_secured_tier_recognized(self) -> None:
        self.assertEqual(normalize_isolation("secured"), "secured")
        self.assertEqual(normalize_isolation("SECURED"), "secured")
        self.assertEqual(normalize_isolation("plugin_cwd"), "plugin_cwd")
        self.assertEqual(normalize_isolation("restricted_env"), "restricted_env")


class PluginRunCommandIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.manager = PluginManager(self.db, self.root / "data")
        self.workdir = self.root / "plugin_work"
        self.workdir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_restricted_env_keeps_subprocess_path(self) -> None:
        env = {
            "HADES_PLUGIN_ISOLATION": "restricted_env",
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUTF8": "1",
        }
        with patch("platform_services_core.subprocess.run") as run_mock, patch(
            "platform_services_core.run_isolated", create=True
        ) as iso_mock:
            run_mock.return_value = MagicMock(stdout="ok\n", stderr="", returncode=0)
            result = self.manager._run_command(
                [sys.executable, "-c", "print('ok')"],
                root=self.workdir,
                env=env,
                timeout=10,
            )
            run_mock.assert_called_once()
            iso_mock.assert_not_called()
            self.assertEqual(result["exit_code"], 0)
            self.assertIsNone(result.get("error"))

    def test_plugin_cwd_keeps_subprocess_path(self) -> None:
        env = {"HADES_PLUGIN_ISOLATION": "plugin_cwd", "PATH": os.environ.get("PATH", "")}
        with patch("platform_services_core.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(stdout="", stderr="", returncode=0)
            self.manager._run_command(
                [sys.executable, "-c", "pass"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_called_once()

    def test_secured_calls_run_isolated_with_workdir_roots(self) -> None:
        env = {
            "HADES_PLUGIN_ISOLATION": "secured",
            "HADES_PLUGIN_ID": "demo",
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUTF8": "1",
        }
        fake = IsolationResult(
            ok=True,
            adapter="linux_userns_mount",
            mode=SECURED_MODE,
            exit_code=0,
            stdout="isolated-ok\n",
            stderr="",
            duration_ms=12,
            isolation_enforced=True,
            fs_isolation=True,
            network_isolation=True,
            env_filtered=True,
        )
        with patch("platform_services_core.subprocess.run") as run_mock, patch(
            "execution_isolation.run_isolated", return_value=fake
        ) as iso_mock:
            result = self.manager._run_command(
                [sys.executable, "-c", "print('isolated-ok')"],
                root=self.workdir,
                env=env,
                timeout=15,
            )
            run_mock.assert_not_called()
            iso_mock.assert_called_once()
            kwargs = iso_mock.call_args.kwargs
            self.assertEqual(kwargs["policy"].mode, SECURED_MODE)
            resolved = self.workdir.resolve()
            self.assertIn(resolved, [Path(p).resolve() for p in kwargs["policy"].read_roots])
            self.assertIn(resolved, [Path(p).resolve() for p in kwargs["policy"].write_roots])
            self.assertEqual(result["exit_code"], 0)
            self.assertIn("isolated-ok", result["stdout"])
            self.assertTrue(result.get("fs_isolation"))
            self.assertTrue(result.get("isolation_enforced"))

    def test_secured_isolation_unavailable_fail_closed_no_subprocess(self) -> None:
        env = {"HADES_PLUGIN_ISOLATION": "secured", "PATH": os.environ.get("PATH", "")}
        with patch("platform_services_core.subprocess.run") as run_mock, patch(
            "execution_isolation.run_isolated",
            side_effect=IsolationUnavailable(
                "Secured filesystem isolation is unavailable on this Windows host. "
                "Job Objects alone are not FS/network isolation."
            ),
        ):
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_not_called()
            self.assertIsNotNone(result.get("error"))
            self.assertIn("refusing unbounded execution", result["error"])
            self.assertIn("Job Objects", result["error"])
            self.assertIsNone(result.get("exit_code"))
            self.assertFalse(result.get("isolation_enforced"))
            self.assertFalse(result.get("fs_isolation"))

    def test_secured_skips_native_runtime(self) -> None:
        env = {"HADES_PLUGIN_ISOLATION": "secured", "PATH": os.environ.get("PATH", "")}
        native = MagicMock()
        native.status.return_value = MagicMock(connected=True, fallback_active=False)
        self.manager.set_native_runtime(native)
        with patch(
            "execution_isolation.run_isolated",
            side_effect=IsolationUnavailable("no fs isolation"),
        ):
            result = self.manager._run_command(
                [sys.executable, "-c", "pass"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
        native.process_run.assert_not_called()
        self.assertIn("refusing unbounded execution", result["error"] or "")

    def test_command_environment_marks_secured(self) -> None:
        plugin = {
            "id": "iso-demo",
            "isolation": "secured",
            "local_path": str(self.workdir),
            "manifest": {},
        }
        tool = {"metadata": {}}
        env = self.manager._command_environment(plugin, tool)
        self.assertEqual(env["HADES_PLUGIN_ISOLATION"], "secured")
        self.assertEqual(env["HADES_PLUGIN_ID"], "iso-demo")

    def test_process_env_secured_override(self) -> None:
        plugin = {
            "id": "iso-demo",
            "isolation": "plugin_cwd",
            "local_path": str(self.workdir),
            "manifest": {},
        }
        with patch.dict(os.environ, {"HADES_PLUGIN_ISOLATION": "secured"}, clear=False):
            self.assertEqual(self.manager._plugin_isolation_tier(plugin), "secured")
            env = self.manager._command_environment(plugin, {"metadata": {}})
            self.assertEqual(env["HADES_PLUGIN_ISOLATION"], "secured")


class PluginSecuredLiveIsolationTests(unittest.TestCase):
    """Optional live check when linux userns is available (same host gate as A02)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.manager = PluginManager(self.db, self.root / "data")
        self.workdir = self.root / "data" / "plugins" / "sources" / "live"
        self.workdir.mkdir(parents=True)
        (self.workdir / "marker.txt").write_text("PLUGIN_OK", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_secured_live_can_read_workdir(self) -> None:
        from execution_isolation import detect_isolation_capabilities

        caps = detect_isolation_capabilities()
        if not caps.get("secured_fs_isolation_available"):
            self.skipTest(f"secured FS isolation unavailable: {caps.get('linux_userns_reason')}")
        marker = self.workdir / "marker.txt"
        env = {
            "HADES_PLUGIN_ISOLATION": "secured",
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        result = self.manager._run_command(
            [sys.executable, "-c", f"print(open({str(marker)!r}).read())"],
            root=self.workdir,
            env=env,
            timeout=20,
        )
        self.assertEqual(result.get("exit_code"), 0, result)
        self.assertIn("PLUGIN_OK", result.get("stdout") or "")
        self.assertTrue(result.get("fs_isolation"))


if __name__ == "__main__":
    unittest.main()
