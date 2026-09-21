from __future__ import annotations

import unittest

from capability_intel.taxonomy import CAPABILITY_KINDS
from mcpmarket.connector import MCPMarketConnector, reset_connector
from mcpmarket.handoff import prepare_connection
from mcpmarket.normalize import listing_to_capabilities
from mcpmarket.official import UNSUPPORTED_APIS, official_surface
from mcpmarket.parse import parse_listing_page, parse_skill_page
from mcpmarket.trust import inspect_listing


CONTEXT7_HTML = """
<html>
  <head>
    <title>Context7: Up-to-Date Docs in Your LLM Prompts</title>
    <script type="application/ld+json">{"@type":"SoftwareApplication","name":"Context7","description":"Up-to-date docs","codeRepository":"https://github.com/upstash/context7"}</script>
  </head>
  <body>
    <h1>Context7</h1>
    <p>by upstash</p>
    <p>Context7 empowers LLMs with current, version-specific documentation and code examples.</p>
  </body>
</html>
"""

SKILL_HTML = """
<html>
  <h1>What Are Claude Skills?</h1>
  <p>Skills are organized folders of instructions, scripts, and resources that Claude loads dynamically.</p>
  <p>Unlike MCP servers, Skills teach how to do things.</p>
</html>
"""

TOOLKIT_HTML = """
<html>
  <h1>Audio Toolkit</h1>
  <p>by vendor</p>
  <p>A focused toolkit of contained tools for speech.</p>
  <p>toolkit tool group: tts, stt</p>
</html>
"""


class MCPMarketConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_connector()
        self.pages = {
            "https://mcpmarket.com/server/context7": (200, CONTEXT7_HTML),
            "https://mcpmarket.com/tools/skills/what-are-skills": (200, SKILL_HTML),
            "https://mcpmarket.com/server/audio-toolkit": (200, TOOLKIT_HTML),
        }

        def fetch(url: str) -> tuple[int, str]:
            return self.pages.get(url, (404, "missing"))

        self.connector = MCPMarketConnector(fetch=fetch)

    def tearDown(self) -> None:
        reset_connector()

    def test_official_surface_does_not_invent_management_apis(self) -> None:
        surface = official_surface()
        self.assertEqual(surface["base_url"], "https://mcpmarket.com")
        self.assertFalse(surface["executes_tools"])
        self.assertFalse(surface["grants_trust"])
        self.assertFalse(surface["required_for_hades_startup"])
        self.assertIn("official_rest_catalog_api", UNSUPPORTED_APIS)
        self.assertIn("official_toolkit_catalog_api", UNSUPPORTED_APIS)

    def test_catalog_normalization(self) -> None:
        result = self.connector.fetch_server("context7")
        self.assertEqual(result["status"], "available")
        caps = result["normalized"]["capabilities"]
        kinds = {item.kind for item in caps}
        self.assertIn("mcp_provider", kinds)
        provider = next(item for item in caps if item.kind == "mcp_provider")
        self.assertEqual(provider.trust_requirements, "untrusted")
        self.assertFalse(provider.availability)
        self.assertEqual(provider.extras["provenance"]["marketplace"], "mcpmarket")
        self.assertIn(provider.kind, CAPABILITY_KINDS)

    def test_unknown_metadata_is_preserved(self) -> None:
        listing = parse_listing_page(CONTEXT7_HTML, url="https://mcpmarket.com/server/context7")
        listing["claimed_kind"] = "sparkle_orb"
        listing["extensions"] = {"sparkle_orb": {"color": "blue"}}
        listing["slug"] = "context7"
        adapted = listing_to_capabilities(listing)
        self.assertTrue(any(item["reason"] == "unknown_extension" for item in adapted["unsupported"]))

    def test_toolkit_shaped_listing_normalizes_as_mcp_provider(self) -> None:
        result = self.connector.fetch_server("audio-toolkit")
        listing = result["listing"]
        self.assertTrue(listing.get("toolkit_shaped"))
        provider = next(item for item in result["normalized"]["capabilities"] if item.kind == "mcp_provider")
        self.assertEqual(provider.extras.get("normalized_from"), "toolkit")
        self.assertTrue(provider.extras.get("prefer_focused_surface"))

    def test_skill_normalization_is_not_an_executable_tool(self) -> None:
        result = self.connector.fetch_skill("what-are-skills")
        caps = result["normalized"]["capabilities"]
        self.assertTrue(caps)
        skill = caps[0]
        self.assertEqual(skill.kind, "skill")
        self.assertEqual(skill.side_effect_class, "none")
        self.assertFalse(skill.extras.get("instruction_authority"))
        parsed = parse_skill_page(SKILL_HTML, url="https://mcpmarket.com/tools/skills/what-are-skills")
        self.assertFalse(parsed["system_authority"])

    def test_auth_required_http(self) -> None:
        connector = MCPMarketConnector(fetch=lambda _url: (401, "login"))
        result = connector.fetch_server("secret")
        self.assertEqual(result["status"], "auth_required")

    def test_market_unavailable_does_not_raise(self) -> None:
        connector = MCPMarketConnector(fetch=lambda _url: (0, ""))
        result = connector.search("anything", mission_id="m")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["proposal"]["candidates"], [])
        self.assertFalse(result["model_called"])

    def test_malformed_metadata(self) -> None:
        html = "<html><h1>Broken"
        listing = parse_listing_page(html, url="https://mcpmarket.com/server/broken")
        listing["slug"] = "broken"
        adapted = listing_to_capabilities(listing)
        self.assertTrue(adapted["capabilities"] or adapted["unsupported"] == adapted["unsupported"])
        provider = adapted["capabilities"][0]
        self.assertEqual(provider.trust_requirements, "untrusted")

    def test_connection_handoff_does_not_execute(self) -> None:
        listing = self.connector.fetch_server("context7")["listing"]
        denied = prepare_connection(listing, operator_approved=False)
        self.assertFalse(denied["allowed"])
        self.assertFalse(denied["executes"])
        self.assertFalse(denied["installs"])
        listing["endpoint_url"] = "https://example.invalid/mcp"
        approved = prepare_connection(listing, operator_approved=True)
        self.assertTrue(approved["allowed"])
        self.assertEqual(approved["draft"]["transport"], "streamable_http")
        self.assertFalse(approved["draft"]["auto_connect"])
        self.assertFalse(approved["executes"])

    def test_tool_schema_cache_is_connector_independent(self) -> None:
        from hades_brain.tool_context import bound_tools_for_model, cache_key, get_cached_schema, reset_schema_cache

        reset_schema_cache()
        tools = [{"plugin_id": "mcp:x", "name": "alpha", "version": "1", "description": "alpha", "input_schema": {"type": "object"}}]
        bound_tools_for_model(tools, query="alpha")
        key = cache_key(server_id="mcp:x", version="1", session="", tool_name="alpha")
        self.assertIsNotNone(get_cached_schema(key))

    def test_startup_independence(self) -> None:
        self.assertFalse(self.connector.status()["required_for_startup"])
        self.assertFalse(self.connector.status()["executes_tools"])


if __name__ == "__main__":
    unittest.main()
