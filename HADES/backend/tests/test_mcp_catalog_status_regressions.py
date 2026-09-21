from __future__ import annotations

import unittest

from mcp_host.catalog import enrich_catalog_status


class McpCatalogStatusRegressionTests(unittest.TestCase):
    def test_modern_ready_server_is_reported_as_connected(self) -> None:
        result = enrich_catalog_status(
            [{"id": "github", "name": "GitHub"}],
            [
                {
                    "id": "srv-1",
                    "name": "GitHub MCP",
                    "catalog_id": "github",
                    "connection_status": "ready",
                    "owner_kind": "managed",
                }
            ],
        )

        self.assertEqual(result[0]["status"], "connected")
        self.assertEqual(result[0]["configured_servers"][0]["connection_status"], "ready")

    def test_effective_status_overrides_stale_persisted_connected_state(self) -> None:
        result = enrich_catalog_status(
            [{"id": "github", "name": "GitHub"}],
            [
                {
                    "id": "srv-1",
                    "name": "GitHub MCP",
                    "catalog_id": "github",
                    "connection_status": "connected",
                    "connection_status_effective": "disconnected",
                    "owner_kind": "managed",
                }
            ],
        )

        self.assertEqual(result[0]["status"], "configured")
        self.assertEqual(result[0]["configured_servers"][0]["connection_status"], "disconnected")


if __name__ == "__main__":
    unittest.main()
