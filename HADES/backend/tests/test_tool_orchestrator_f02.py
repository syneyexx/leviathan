"""T2/F-02: tool_orchestrator must not invent args or forge user approval."""

from __future__ import annotations

import asyncio
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtimes import AgentRuntimeDeps, run_tool_orchestrator, try_run_agent_step


class ToolOrchestratorHonestyTests(unittest.TestCase):
    def test_orchestrator_e2e_absent_outside_tests(self) -> None:
        source = Path(__file__).resolve().parents[1] / "agent_runtimes.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("orchestrator-e2e", text)
        # No forged approval call in the production handler body.
        self.assertNotIn("approved_by_user=True", text)
        self.assertNotIn('approved_by_user = True', text)

    def test_invoke_falls_through_to_tool_engine(self) -> None:
        pm = MagicMock()
        deps = AgentRuntimeDeps(
            settings={"network_policy": "block"},
            plugin_manager=pm,
            shortlist_tools=lambda q, limit=12: [
                {"plugin_id": "hades.echo", "name": "echo", "status": "Ready", "permissions": ["subprocess"]}
            ],
        )
        result = asyncio.run(try_run_agent_step("tool_orchestrator", "invoke echo now", deps=deps))
        self.assertIsNone(result)
        pm.invoke.assert_not_called()

    def test_ask_subprocess_does_not_auto_approve_via_orchestrator(self) -> None:
        """Regression: canned approved_by_user=True must not exist on the invoke path."""
        invoke = MagicMock(
            return_value={"status": "blocked", "error": "explicit approval required for subprocess_policy=ask"}
        )
        pm = MagicMock()
        pm.invoke = invoke
        # Direct call with an instruction that would previously have forged approval.
        deps = AgentRuntimeDeps(settings={"subprocess_policy": "ask"}, plugin_manager=pm)
        result = run_tool_orchestrator("execute plugin tool with args", deps)
        self.assertIsNone(result)
        invoke.assert_not_called()

    def test_resolve_still_deterministic(self) -> None:
        deps = AgentRuntimeDeps(
            settings={},
            shortlist_tools=lambda q, limit=12: [
                {"plugin_id": "hades.demo", "name": "echo", "status": "Ready"}
            ],
            platform_db=MagicMock(
                list_plugins=MagicMock(
                    return_value=[{"id": "hades.demo", "name": "Demo", "status": "Ready", "enabled": True}]
                )
            ),
        )
        result = asyncio.run(
            try_run_agent_step(
                "tool_orchestrator",
                "Resolve installed plugin 'Demo' from the local plugin registry.",
                deps=deps,
            )
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.ok)
        self.assertIn("resolved", result.output)
        self.assertIn("hades.demo", result.output)

    def test_handler_signature_allows_none_fallthrough(self) -> None:
        hint = inspect.signature(run_tool_orchestrator).return_annotation
        self.assertIn("None", str(hint))


if __name__ == "__main__":
    unittest.main()
