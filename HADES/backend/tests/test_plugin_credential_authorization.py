"""Regression matrix: plugin child env must not inherit unrelated ambient credentials."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from platform_services import PluginManager
from plugin_runtime_v2 import authorized_plugin_environment, restricted_environment


class PluginCredentialAuthorizationTests(unittest.TestCase):
    AMBIENT_SECRET = "UNRELATED-AMBIENT-SECRET"

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

    def _plugin(self, *, isolation: str, required_env: list[str] | None = None) -> dict:
        manifest: dict = {"isolation": isolation}
        if required_env is not None:
            manifest["required_env"] = required_env
        return {
            "id": "cred-demo",
            "isolation": isolation,
            "local_path": str(self.workdir),
            "manifest": manifest,
        }

    def test_restricted_environment_strips_secret_shaped_hades_keys(self) -> None:
        base = {
            "HADES_LM_STUDIO_API_KEY": self.AMBIENT_SECRET,
            "HADES_DATA_DIR": "/tmp/hades-data",
            "PATH": "/usr/bin",
        }
        env = restricted_environment(base)
        self.assertNotIn("HADES_LM_STUDIO_API_KEY", env)
        self.assertIn("HADES_DATA_DIR", env)
        self.assertIn("PATH", env)

    def test_plugin_cwd_does_not_inherit_unauthorized_ambient_secret(self) -> None:
        plugin = self._plugin(isolation="plugin_cwd")
        tool = {"metadata": {}}
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": self.AMBIENT_SECRET,
                "HADES_DATA_DIR": "/var/hades",
            },
            clear=False,
        ):
            env = self.manager._command_environment(plugin, tool)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertIn("HADES_DATA_DIR", env)

    def test_manifest_required_env_readmits_declared_credential(self) -> None:
        plugin = self._plugin(isolation="plugin_cwd", required_env=["FINCEPT_API_KEY"])
        tool = {"metadata": {}}
        with mock.patch.dict(os.environ, {"FINCEPT_API_KEY": "fincept-declared"}, clear=False):
            env = self.manager._command_environment(plugin, tool)
        self.assertEqual(env.get("FINCEPT_API_KEY"), "fincept-declared")

    def test_isolation_tiers_scrub_unauthorized_secrets(self) -> None:
        for isolation in ("restricted_env", "temp_workspace", "secured"):
            with self.subTest(isolation=isolation):
                plugin = self._plugin(isolation=isolation)
                tool = {"metadata": {}}
                with mock.patch.dict(
                    os.environ,
                    {"GITHUB_TOKEN": self.AMBIENT_SECRET, "PATH": os.environ.get("PATH", "")},
                    clear=False,
                ):
                    env = self.manager._command_environment(plugin, tool)
                self.assertNotIn("GITHUB_TOKEN", env)
                self.assertIn("PATH", env)

    def test_tool_metadata_env_may_supply_explicit_values(self) -> None:
        plugin = self._plugin(isolation="plugin_cwd")
        tool = {"metadata": {"env": {"PLUGIN_LOCAL_TOKEN": "from-tool-metadata"}}}
        env = self.manager._command_environment(plugin, tool)
        self.assertEqual(env.get("PLUGIN_LOCAL_TOKEN"), "from-tool-metadata")

    def test_authorized_plugin_environment_allowlist(self) -> None:
        base = {"HADES_REPO_ROOT": "/repo", "HADES_LM_STUDIO_API_KEY": self.AMBIENT_SECRET}
        env = authorized_plugin_environment(base, self._plugin(isolation="plugin_cwd"), None)
        self.assertEqual(env.get("HADES_REPO_ROOT"), "/repo")
        self.assertNotIn("HADES_LM_STUDIO_API_KEY", env)


if __name__ == "__main__":
    unittest.main()
