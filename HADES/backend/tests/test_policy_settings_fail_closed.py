#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from platform_services_core import PluginManager  # noqa: E402


class PolicySettingsFailClosedTests(unittest.TestCase):
    def test_mcp_provider_failure_blocks(self) -> None:
        db = MagicMock()
        db.get_plugin.return_value = {
            "id": "p1",
            "enabled": True,
            "status": "ready",
            "failure_state": None,
            "trust": "manual",
            "plugin_type": "mcp",
            "capabilities": {},
        }
        db.plugin_tools.return_value = [
            {
                "name": "mcp.demo",
                "enabled": True,
                "input_schema": {"type": "object"},
                "metadata": {"mcp": True},
            }
        ]
        db.create_tool_call.return_value = "call-1"
        manager = PluginManager(db, Path("/tmp"))
        manager.set_policy_settings_provider(lambda: (_ for _ in ()).throw(RuntimeError("settings boom")))
        manager._finish_invocation = MagicMock(return_value={"status": "blocked", "error": "x"})  # type: ignore[method-assign]
        manager._tool_action = MagicMock(return_value="invoke")  # type: ignore[method-assign]

        result = manager.invoke("p1", "mcp.demo", {})
        self.assertEqual(result["status"], "blocked")
        kwargs = manager._finish_invocation.call_args.kwargs
        self.assertEqual(kwargs.get("status"), "blocked")
        self.assertIn("settings", (kwargs.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
