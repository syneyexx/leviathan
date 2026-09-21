"""T6/F-03: per-kind capability approvals at the PluginManager boundary.

``approved_by_user`` alone must not satisfy a side-effect ``ask`` policy.
Each call path (PM, broker, MCP, coding/omniroute, agent-runtime) is covered.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from capability_intel.broker import CapabilityBroker
from platform_db import PlatformDatabase
from platform_services import PluginManager
from plugin_runtime_v2 import (
    build_capability_contract,
    evaluate_global_side_effect_policies,
    normalize_capability_approvals,
)
import platform_services_core as psc


def _subprocess_contract() -> dict:
    return build_capability_contract({"permissions": ["subprocess"]})


class EvaluatePerKindApprovalsTests(unittest.TestCase):
    def test_approved_by_user_alone_does_not_satisfy_ask(self) -> None:
        denied = evaluate_global_side_effect_policies(
            contract=_subprocess_contract(),
            settings={"subprocess_policy": "ask"},
            invocation_type="manual",
            approved_by_user=True,
            approvals=normalize_capability_approvals(),
        )
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied.get("kind"), "subprocess")
        self.assertIn("ask", denied["reason"])

    def test_approved_subprocess_satisfies_ask(self) -> None:
        allowed = evaluate_global_side_effect_policies(
            contract=_subprocess_contract(),
            settings={"subprocess_policy": "ask"},
            invocation_type="manual",
            approved_by_user=False,
            approvals=normalize_capability_approvals(approved_subprocess=True),
        )
        self.assertTrue(allowed["allowed"])

    def test_autonomous_still_cannot_promote_ask(self) -> None:
        denied = evaluate_global_side_effect_policies(
            contract=_subprocess_contract(),
            settings={"subprocess_policy": "ask"},
            invocation_type="autonomous",
            approved_by_user=True,
            approvals=normalize_capability_approvals(approved_subprocess=True),
        )
        self.assertFalse(denied["allowed"])
        self.assertIn("autonomous", denied["reason"])


class PluginManagerPerKindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.manager = PluginManager(self.db, self.root / "data")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _import_echo(self) -> str:
        folder = self.root / "src" / "echo-ask"
        folder.mkdir(parents=True)
        manifest = {
            "format": 1,
            "id": "echo-ask",
            "name": "echo-ask",
            "version": "0.1.0",
            "description": "echo plugin",
            "runtime_type": "python",
            "entrypoint": "echo",
            "plugin_type": "tool",
            "permissions": ["subprocess"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "tools": [
                {
                    "name": "echo",
                    "action": "echo",
                    "command": ["{python}", "-c", "import json; print(json.dumps({'ok': True}))"],
                    "description": "Echo tool for tests",
                    "input_schema": {"type": "object", "properties": {}},
                    "autonomous": True,
                }
            ],
        }
        (folder / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin_id = result["plugin"]["id"]
        self.db.set_plugin_state(plugin_id, enabled=True, trust="verified", status="ready")
        return plugin_id

    def test_pm_blocks_ask_without_approved_subprocess(self) -> None:
        plugin_id = self._import_echo()
        self.manager.set_policy_settings({"subprocess_policy": "ask", "network_policy": "allow"})
        spawned: list[object] = []

        def _fake_run(*_a, **_k):
            spawned.append(1)

            class _R:
                stdout = "SHOULD_NOT"
                stderr = ""
                returncode = 0

            return _R()

        with mock.patch.object(psc.subprocess, "run", side_effect=_fake_run):
            out = self.manager.invoke(
                plugin_id,
                "echo",
                {},
                invocation_type="manual",
                approved_by_user=True,
            )
        self.assertEqual(out.get("status"), "blocked")
        self.assertEqual(spawned, [])
        self.assertIn("subprocess", str(out.get("error") or "").lower())

    def test_pm_runs_when_approved_subprocess(self) -> None:
        plugin_id = self._import_echo()
        self.manager.set_policy_settings({"subprocess_policy": "ask", "network_policy": "allow"})
        spawned: list[object] = []

        def _fake_run(*_a, **_k):
            spawned.append(1)

            class _R:
                stdout = "ok"
                stderr = ""
                returncode = 0

            return _R()

        with mock.patch.object(psc.subprocess, "run", side_effect=_fake_run):
            out = self.manager.invoke(
                plugin_id,
                "echo",
                {},
                invocation_type="manual",
                approved_by_user=True,
                approved_subprocess=True,
            )
        self.assertEqual(out.get("status"), "completed")
        self.assertEqual(len(spawned), 1)


class BrokerPerKindTests(unittest.TestCase):
    def _broker(self, invoke_fn):
        return CapabilityBroker(
            plugins_by_id={
                "p1": {
                    "id": "p1",
                    "enabled": True,
                    "status": "ready",
                    "trust": "verified",
                    "permissions": ["subprocess"],
                    "manifest": {"autonomous": True, "permissions": ["subprocess"]},
                }
            },
            tools_by_key={
                ("p1", "echo"): {
                    "name": "echo",
                    "enabled": True,
                    "metadata": {"autonomous": True, "permissions": ["subprocess"]},
                    "input_schema": {"type": "object", "properties": {}},
                }
            },
            settings={"subprocess_policy": "ask", "network_policy": "allow"},
            invoke_fn=invoke_fn,
        )

    def test_broker_blocks_ask_without_approved_subprocess(self) -> None:
        calls: list[dict] = []

        def invoke_fn(pid, tname, args, **kwargs):
            calls.append({"pid": pid, "kwargs": kwargs})
            return {"status": "completed", "stdout": "nope"}

        broker = self._broker(invoke_fn)
        ids = list(broker.indexed_ids()) if hasattr(broker, "indexed_ids") else list(broker._index)
        self.assertTrue(ids)
        result = broker.invoke(str(ids[0]), {}, approved_by_user=True)
        self.assertIn(result.get("status"), {"blocked", "approval_required"})
        self.assertEqual(calls, [])

    def test_broker_forwards_approved_subprocess(self) -> None:
        calls: list[dict] = []

        def invoke_fn(pid, tname, args, **kwargs):
            calls.append({"pid": pid, "kwargs": kwargs})
            return {"status": "completed", "stdout": "ok"}

        broker = self._broker(invoke_fn)
        ids = list(broker.indexed_ids()) if hasattr(broker, "indexed_ids") else list(broker._index)
        self.assertTrue(ids)
        result = broker.invoke(str(ids[0]), {}, approved_subprocess=True)
        self.assertEqual(result.get("status"), "completed")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["kwargs"].get("approved_subprocess"))


class McpMirrorPerKindTests(unittest.TestCase):
    def test_mcp_mirror_passes_approvals_not_bare_user_flag(self) -> None:
        from mcp_host.manager_core import McpManager

        captured: dict[str, object] = {}

        class FakePM:
            def invoke(self, plugin_id, tool_name, arguments, **kwargs):
                captured.update(kwargs)
                captured["plugin_id"] = plugin_id
                return {
                    "status": "blocked",
                    "error": "explicit approval required for subprocess_policy=ask",
                    "id": "c1",
                }

        class FakeStore:
            def mark_tool_execution(self, *_a, **_k):
                return None

            def create_execution(self, payload):
                return {"id": "e1", **payload}

            def finish_execution(self, execution_id, **kwargs):
                return {"id": execution_id, **kwargs}

        mgr = object.__new__(McpManager)
        mgr.plugin_manager = FakePM()
        mgr.store = FakeStore()
        mgr._mirror_to_plugin = lambda *_a, **_k: None  # type: ignore[method-assign]

        out = McpManager._invoke_via_mirror(
            mgr,
            {"id": "mcp:s1"},
            {"server_id": "s1", "id": "t1", "model_name": "remote.echo"},
            {},
            invocation_type="manual",
            approved_by_user=True,
            idempotency_key=None,
            approvals={"subprocess": False, "network": False, "file_read": False, "file_write": False},
        )
        self.assertEqual(out["result"]["status"], "blocked")
        self.assertIn("approvals", captured)
        self.assertFalse((captured.get("approvals") or {}).get("subprocess"))


class CodingOmniroutePerKindTests(unittest.TestCase):
    def test_omniroute_provider_forwards_kwargs_to_pm(self) -> None:
        from coding_omniroute import provider_from_plugin_manager

        class FakeDB:
            def get_plugin(self, plugin_id):
                return {"id": plugin_id}

            def plugin_tools(self, plugin_id):
                return [{"name": "run"}]

        class FakePM:
            def __init__(self):
                self.db = FakeDB()
                self.calls = []

            def invoke(self, plugin_id, tool_name, input_data, **kwargs):
                self.calls.append(kwargs)
                return {"status": "blocked", "error": "explicit approval required for subprocess_policy=ask"}

        pm = FakePM()
        provider = provider_from_plugin_manager(pm)
        result = provider._invoke("p1", "run", {}, approved_by_user=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(pm.calls), 1)
        self.assertFalse(pm.calls[0].get("approved_subprocess", False))


class AgentRuntimePerKindTests(unittest.TestCase):
    def test_agent_runtimes_has_no_forged_approved_by_user_invoke(self) -> None:
        text = Path(__file__).resolve().parents[1].joinpath("agent_runtimes.py").read_text(encoding="utf-8")
        self.assertNotIn("approved_by_user=True", text)
        self.assertNotIn("approved_by_user = True", text)


if __name__ == "__main__":
    unittest.main()
