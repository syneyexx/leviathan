from __future__ import annotations

import unittest

from reasoning import discover_tools


class PluginToolAutonomyTests(unittest.TestCase):
    def test_discovery_respects_per_tool_autonomous_opt_out(self) -> None:
        plugins = [
            {
                "id": "mixed-plugin",
                "name": "Mixed Plugin",
                "description": "read and write tools",
                "enabled": True,
                "status": "ready",
                "trust": "manual",
                "category": "Research",
                "manifest": {"autonomous": True, "category": "Research"},
            }
        ]
        tools = [
            {
                "plugin_id": "mixed-plugin",
                "name": "read_data",
                "description": "utility research data",
                "enabled": True,
                "input_schema": {},
                "metadata": {"autonomous": True},
            },
            {
                "plugin_id": "mixed-plugin",
                "name": "expensive_post",
                "description": "utility research data",
                "enabled": True,
                "input_schema": {},
                "metadata": {"autonomous": False},
            },
        ]
        result = discover_tools(
            query="utility research data",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _plugin, _tool: True,
            include_unscored=True,
        )
        names = {item["tool_name"] for item in result["tools"]}
        self.assertIn("read_data", names)
        self.assertNotIn("expensive_post", names)
        self.assertEqual(result["total"], 1)

    def test_discover_tools_single_mcp_shortlist_across_sources(self) -> None:
        plugins = [
            {
                "id": "bridge",
                "name": "Bridge",
                "enabled": True,
                "status": "ready",
                "trust": "verified",
                "category": "Research",
                "manifest": {"autonomous": True, "category": "Research"},
            },
            {
                "id": "mcp:srv",
                "name": "Managed",
                "enabled": True,
                "status": "ready",
                "trust": "verified",
                "plugin_type": "mcp-managed",
                "category": "Research",
                "manifest": {"autonomous": True, "category": "Research", "plugin_type": "mcp-managed"},
            },
        ]
        tools = [
            {
                "plugin_id": "bridge",
                "name": "mcp__lookup",
                "description": "lookup entity",
                "enabled": True,
                "input_schema": {},
                "metadata": {"autonomous": True, "mcp_remote": True, "mcp_tool": "lookup"},
            },
            {
                "plugin_id": "mcp:srv",
                "name": "lookup",
                "description": "lookup entity",
                "enabled": True,
                "input_schema": {},
                "metadata": {"autonomous": True, "mcp_managed": True, "mcp_tool": "lookup"},
            },
        ]
        result = discover_tools(
            query="lookup entity",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _plugin, _tool: True,
            include_unscored=True,
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["tools"][0]["plugin_id"], "mcp:srv")


if __name__ == "__main__":
    unittest.main()
