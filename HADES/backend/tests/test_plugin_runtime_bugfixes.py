"""Regression tests for Plugin Manager / Runtime bugfixes (2026-09-10)."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from platform_db import PlatformDatabase
from platform_services_core import PluginManager
from plugin_runtime_v2 import eligible_for_autonomous, eligible_for_manual


class PluginRuntimeBugfixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db = PlatformDatabase(root / "platform.db")
        self.db.initialize()
        self.manager = PluginManager(self.db, root / "data")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_echo(self, name: str = "echo-bugfix", *, permissions: list[str] | None = None) -> Path:
        folder = Path(self.temp_dir.name) / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "echo.py").write_text(
            "import sys\nprint('ECHO ' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        manifest = {
            "format": 1,
            "id": name,
            "name": name,
            "version": "1.0.0",
            "runtime_type": "python",
            "permissions": permissions or ["subprocess"],
            "autonomous": True,
            "tools": [
                {
                    "name": "echo",
                    "description": "echo",
                    "command": ["{python}", "echo.py", "{args}"],
                    "input_schema": {
                        "type": "object",
                        "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                    },
                }
            ],
        }
        (folder / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder

    def test_ready_convert_stays_disabled_until_user_enables(self) -> None:
        folder = self._write_echo("convert-disabled")
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin = result["plugin"]
        self.assertEqual(plugin["status"], "ready")
        self.assertEqual(plugin["trust"], "verified")
        self.assertFalse(plugin["enabled"])
        with self.assertRaises(RuntimeError):
            self.manager.invoke(plugin["id"], "echo", {"args": ["no"]}, approved_by_user=True)
        self.db.set_plugin_state(plugin["id"], enabled=True)
        out = self.manager.invoke(plugin["id"], "echo", {"args": ["yes"]}, approved_by_user=True)
        self.assertEqual(out["status"], "completed")
        self.assertIn("ECHO yes", out["stdout"])

    def test_replace_plugin_tools_preserves_disabled_flag(self) -> None:
        folder = self._write_echo("tool-enabled-bit")
        plugin = self.manager.import_local_folder(folder, install_dependencies=False)["plugin"]
        tools = self.db.plugin_tools(plugin["id"])
        payload = []
        for tool in tools:
            payload.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {}),
                    "output_schema": tool.get("output_schema", {}),
                    "command": tool.get("command", ""),
                    **(tool.get("metadata") or {}),
                    "enabled": False,
                }
            )
        self.db.replace_plugin_tools(plugin["id"], payload)
        refreshed = self.db.plugin_tools(plugin["id"])
        self.assertTrue(refreshed)
        self.assertFalse(refreshed[0]["enabled"])

    def test_hadesplugin_without_integrity_is_rejected(self) -> None:
        source = self._write_echo("integrity-pack")
        archive = Path(self.temp_dir.name) / "bad.HadesPlugin"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(
                "hades-plugin.json",
                json.dumps(
                    {
                        "format": 1,
                        "id": "integrity-pack",
                        "name": "integrity-pack",
                        "version": "1.0.0",
                        "runtime_type": "python",
                        "tools": [],
                        "integrity": {},
                    }
                ),
            )
            zf.write(source / "echo.py", "source/echo.py")
        with self.assertRaises(ValueError) as ctx:
            self.manager.import_zip(archive, install_dependencies=False)
        self.assertIn("integrity", str(ctx.exception).lower())

    def test_container_isolation_fails_closed_when_not_implemented(self) -> None:
        folder = self._write_echo("container-iso")
        manifest = json.loads((folder / "hades-plugin.json").read_text(encoding="utf-8"))
        manifest["isolation"] = "container"
        (folder / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = self.manager.import_local_folder(folder, install_dependencies=False)["plugin"]
        tool = self.db.plugin_tools(plugin["id"])[0]
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            env = self.manager._command_environment(plugin, tool)
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION"), "container")
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION_NOTE"), "container_not_implemented")
        self.assertNotEqual(env.get("HADES_PLUGIN_EFFECTIVE_ISOLATION"), "container")
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=Path(plugin["local_path"]),
                env=env,
                timeout=5,
            )
            run_mock.assert_not_called()
        self.assertEqual(result.get("error_code"), "container_not_implemented")

    def test_missing_trust_defaults_to_untrusted_for_eligibility(self) -> None:
        plugin = {"enabled": True, "status": "ready", "trust": None, "manifest": {"autonomous": True}}
        tool = {"name": "echo", "enabled": True, "metadata": {"autonomous": True}}
        ok_manual, reason_manual = eligible_for_manual(plugin)
        ok_auto, reason_auto = eligible_for_autonomous(plugin, tool)
        self.assertFalse(ok_manual)
        self.assertIn("untrusted", reason_manual)
        self.assertFalse(ok_auto)
        self.assertIn("untrusted", reason_auto)

    def test_finish_tool_call_merges_metadata(self) -> None:
        folder = self._write_echo("meta-merge")
        plugin = self.manager.import_local_folder(folder, install_dependencies=False)["plugin"]
        call_id = self.db.create_tool_call(
            plugin["id"],
            "echo",
            {},
            invocation_type="manual",
            approved_by_user=True,
            metadata={"seed": True, "keep": "yes"},
        )
        finished = self.db.finish_tool_call(call_id, "completed", stdout="ok", metadata={"seed": False, "extra": 1})
        assert finished is not None
        self.assertEqual(finished["metadata"]["keep"], "yes")
        self.assertEqual(finished["metadata"]["seed"], False)
        self.assertEqual(finished["metadata"]["extra"], 1)

    def test_expand_mcp_does_not_mutate_disabled_ready_state(self) -> None:
        folder = self._write_echo("mcp-no-mutate")
        manifest = json.loads((folder / "hades-plugin.json").read_text(encoding="utf-8"))
        manifest["tools"] = [
            {
                "name": "list_tools",
                "command": ["{python}", "-c", "print('{\"tools\":[]}')"],
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "call_tool",
                "command": ["{python}", "-c", "print('{}')"],
                "input_schema": {"type": "object", "properties": {}},
            },
        ]
        manifest["mcp"] = {"expand_tools": True}
        (folder / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = self.manager.import_local_folder(folder, install_dependencies=False)["plugin"]
        self.assertFalse(plugin["enabled"])
        self.assertEqual(plugin["status"], "ready")
        before = self.db.get_plugin(plugin["id"])
        expansion = self.manager.expand_mcp_tools(plugin["id"])
        after = self.db.get_plugin(plugin["id"])
        self.assertFalse(expansion.get("skipped") and expansion.get("reason") == "not_ready")
        self.assertEqual(bool(after["enabled"]), bool(before["enabled"]))
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after.get("failure_state"), before.get("failure_state"))

    def test_service_lock_serializes_concurrent_starts(self) -> None:
        lock = self.manager._service_lock_for("p1")
        held = []

        def worker() -> None:
            with self.manager._service_lock_for("p1"):
                held.append(threading.current_thread().name)

        t1 = threading.Thread(target=worker, name="a")
        t2 = threading.Thread(target=worker, name="b")
        with lock:
            t1.start()
            t2.start()
            self.assertEqual(held, [])
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(sorted(held), ["a", "b"])


class PluginRuntimeApiBugfixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        main.database = Database(str(Path(self.temp_dir.name) / "api-bugfix.db"))
        main.runner = main.TaskRunner()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def _install(self, plugin_id: str, permissions: list[str] | None = None) -> dict:
        source = Path(self.temp_dir.name) / plugin_id
        source.mkdir()
        (source / "echo.py").write_text(
            "import sys\nprint('ECHO ' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        manifest = {
            "format": 1,
            "id": plugin_id,
            "name": plugin_id,
            "version": "1.0.0",
            "runtime_type": "python",
            "permissions": permissions or ["subprocess"],
            "autonomous": True,
            "tools": [
                {
                    "name": "echo",
                    "command": ["{python}", "echo.py", "{args}"],
                    "input_schema": {
                        "type": "object",
                        "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                    },
                }
            ],
        }
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = main.plugin_manager.import_local_folder(source, install_dependencies=False)["plugin"]
        return main.platform_db.set_plugin_state(plugin["id"], enabled=True) or main.platform_db.get_plugin(plugin["id"])

    def test_manual_run_does_not_blanket_approve_ask_capabilities(self) -> None:
        plugin = self._install("ask-net", ["subprocess", "network"])
        settings = self.client.put("/api/settings", json={"network_policy": "ask"})
        self.assertEqual(settings.status_code, 200, settings.text)
        response = self.client.post(
            f"/api/plugins/{plugin['id']}/invoke",
            json={"tool_name": "echo", "input": {"args": ["x"]}, "approved_by_user": True},
        )
        self.assertEqual(response.status_code, 428, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["tool_call"]["status"], "approval_required")
        self.assertIn("approval", detail)

    def test_manual_run_with_explicit_capability_approval_succeeds(self) -> None:
        plugin = self._install("ask-net-ok", ["subprocess", "network"])
        settings = self.client.put("/api/settings", json={"network_policy": "ask", "subprocess_policy": "allow"})
        self.assertEqual(settings.status_code, 200, settings.text)
        response = self.client.post(
            f"/api/plugins/{plugin['id']}/invoke",
            json={
                "tool_name": "echo",
                "input": {"args": ["ok"]},
                "approved_by_user": True,
                "approved_network": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")

    def test_envelope_gate_defaults_ordinary_tools_to_subprocess(self) -> None:
        plugin = {
            "id": "env-demo",
            "manifest": {"capabilities": {"effects": ["subprocess"]}},
            "capabilities": {"effects": ["subprocess"]},
        }
        tool = {"name": "echo", "metadata": {"action": "run"}}
        with mock.patch.object(main.gen2, "default_envelope", return_value=None) as default_env, mock.patch.object(
            main.gen2, "enforce_envelope", return_value={"allowed": True, "violations": []}
        ) as enforce:
            main._plugin_envelope_gate(plugin, tool, {}, invocation_type="manual", approved_by_user=True)
        self.assertTrue(default_env.called)
        kwargs = enforce.call_args.kwargs if enforce.call_args.kwargs else {}
        action = kwargs.get("action")
        if action is None and enforce.call_args.args:
            action = enforce.call_args.args[1] if len(enforce.call_args.args) > 1 else None
        self.assertEqual(action, "subprocess")

    def test_update_without_approvals_respects_ask_policy(self) -> None:
        plugin = self._install("upd")
        settings = self.client.put("/api/settings", json={"network_policy": "ask", "file_write_policy": "ask"})
        self.assertEqual(settings.status_code, 200, settings.text)
        response = self.client.post(f"/api/plugins/{plugin['id']}/update", json={})
        self.assertEqual(response.status_code, 428, response.text)


if __name__ == "__main__":
    unittest.main()
