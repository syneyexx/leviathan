"""PluginManager must not complete tool runs with empty stdout."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _mgr_with_stdout(stdout: str, exit_code: int = 0):
    from platform_services_core import PluginManager

    mgr = PluginManager.__new__(PluginManager)
    mgr.db = MagicMock()
    mgr._envelope_gate = None
    mgr._policy_settings = {}
    mgr._policy_settings_provider = None
    mgr._artifact_hook = None
    mgr.db.get_plugin = MagicMock(
        return_value={
            "id": "plug_test",
            "name": "Test",
            "enabled": True,
            "status": "ready",
            "trust": "untrusted",
            "plugin_type": "Tool",
            "manifest": {},
            "capabilities": {},
            "failure_state": None,
            "health": "unknown",
        }
    )
    mgr.db.plugin_tools = MagicMock(
        return_value=[
            {
                "name": "run",
                "enabled": True,
                "input_schema": {"type": "object"},
                "command": "python",
                "metadata": {},
            }
        ]
    )
    mgr.db.create_tool_call = MagicMock(return_value="tc_empty")
    finished: dict = {}

    def _finish(call_id, plugin, tool, status="completed", started=0, metadata=None, health=None, **result):
        finished.update(
            {
                "status": status,
                "exit_code": result.get("exit_code"),
                "error": result.get("error"),
                "metadata": metadata or {},
                "health": health,
            }
        )
        return finished

    mgr._finish_invocation = _finish  # type: ignore
    mgr._tool_action = MagicMock(return_value="run")  # type: ignore
    mgr._validate_tool_input = MagicMock(side_effect=lambda schema, data: data)  # type: ignore
    mgr._command_argv = MagicMock(return_value=["python", "-c", "print(1)"])  # type: ignore
    mgr._plugin_workdir = MagicMock(return_value=Path("."))  # type: ignore
    mgr._command_environment = MagicMock(return_value={})  # type: ignore
    mgr._run_command = MagicMock(  # type: ignore
        return_value={"stdout": stdout, "stderr": "", "exit_code": exit_code, "error": None}
    )
    mgr._explicit_healthcheck = MagicMock(return_value=None)  # type: ignore
    mgr._ledger_finalize = MagicMock()  # type: ignore
    return mgr, finished


class EmptyStdoutHonestyTests(unittest.TestCase):
    def test_empty_stdout_exit_zero_is_failed(self) -> None:
        mgr, _finished = _mgr_with_stdout("   ", exit_code=0)
        out = mgr.invoke(
            "plug_test",
            "run",
            {},
            invocation_type="install",
            approved_by_user=True,
            privileged_policy_skip=True,
            timeout=5,
        )
        self.assertEqual(out.get("status"), "failed")
        self.assertNotEqual(int(out.get("exit_code") or 0), 0)
        self.assertIn("empty", str(out.get("error") or "").lower())

    def test_nonempty_json_still_completes(self) -> None:
        mgr, _finished = _mgr_with_stdout('{"ok": true}', exit_code=0)
        out = mgr.invoke(
            "plug_test",
            "run",
            {},
            invocation_type="install",
            approved_by_user=True,
            privileged_policy_skip=True,
            timeout=5,
        )
        self.assertEqual(out.get("status"), "completed")


if __name__ == "__main__":
    unittest.main()
