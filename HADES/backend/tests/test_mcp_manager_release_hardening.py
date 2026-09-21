from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from platform_db import PlatformDatabase

from mcp_host.header_secrets import HEADER_SECRET_PREFIX
from mcp_host.manager import McpManager
from mcp_host.protocol import MODERN_PROTOCOL_VERSION
from mcp_host.secrets import secret_store


class McpManagerReleaseHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        secret_store.enable_memory_backend_for_tests()
        self.manager = McpManager(
            self.db,
            settings_provider=lambda: {
                "mcp.enabled": True,
                "network_policy": "allow",
                "subprocess_policy": "allow",
            },
        )

    def tearDown(self) -> None:
        self.manager.on_shutdown()
        self.tmp.cleanup()

    def _http_server(self, **overrides):
        payload = {
            "name": "Remote",
            "transport": "streamable_http",
            "endpoint_url": "https://example.com/mcp",
            "auth_method": "none",
            "headers": {},
            "env": {"plain": {}, "secret_refs": {}},
            "enabled": True,
            "connection_status": "configured",
        }
        payload.update(overrides)
        return self.manager.store.upsert_server(payload)

    def _oauth_server(self, *, name: str = "OAuth"):
        access_ref = secret_store.new_ref("oauth", "access-old")
        refresh_ref = secret_store.new_ref("oauth", "refresh-old")
        secret_store.store(access_ref, "old-access")
        secret_store.store(refresh_ref, "old-refresh")
        server = self._http_server(
            name=name,
            auth_method="oauth",
            auth_secret_ref=access_ref,
            metadata={
                "oauth_refresh_ref": refresh_ref,
                "oauth_token_endpoint": "https://issuer.example/token",
                "oauth_client_id": "client-id",
                "oauth_expires_at": time.time() - 10,
            },
        )
        return server, access_ref, refresh_ref

    def test_catalog_downgrades_persisted_ready_without_live_client(self) -> None:
        server = self._http_server(
            catalog_id="github-mcp",
            connection_status="ready",
            protocol_version=MODERN_PROTOCOL_VERSION,
        )
        catalog = self.manager.catalog()
        item = next(row for row in catalog["items"] if row["id"] == "github-mcp")
        self.assertEqual(item["status"], "configured")
        configured = next(row for row in item["configured_servers"] if row["id"] == server["id"])
        self.assertEqual(configured["connection_status"], "disconnected")

    def test_startup_resets_stale_modern_ready(self) -> None:
        server = self._http_server(
            connection_status="ready",
            protocol_version=MODERN_PROTOCOL_VERSION,
        )
        result = self.manager.on_startup()
        raw = self.manager.store.get_server(server["id"])
        self.assertIsNotNone(raw)
        self.assertEqual(raw["connection_status"], "disconnected")
        self.assertIn(f"reset_status:{server['id']}", result["notes"])

    def test_modern_refresh_tools_persists_ready_not_legacy_connected(self) -> None:
        class FakeModernClient:
            alive = True
            protocol_version = MODERN_PROTOCOL_VERSION
            protocol_generation = "modern"
            last_transport_error = None

            def list_tools_all(self):
                return {
                    "tools": [{"name": "search", "inputSchema": {"type": "object", "properties": {}}}],
                    "complete": True,
                    "notes": [],
                    "pages": 1,
                    "protocol_version": MODERN_PROTOCOL_VERSION,
                    "protocol_generation": "modern",
                }

            def close(self):
                return None

        server = self._http_server(
            connection_status="ready",
            protocol_version=MODERN_PROTOCOL_VERSION,
        )
        with self.manager._session_lock:
            self.manager._sessions[server["id"]] = FakeModernClient()
        self.manager.refresh_tools(server["id"])
        raw = self.manager.store.get_server(server["id"])
        self.assertEqual(raw["connection_status"], "ready")

    def test_failed_plugin_expansion_cannot_be_rescued_by_stale_tools(self) -> None:
        server = self.manager.store.upsert_server(
            {
                "name": "Plugin MCP",
                "transport": "stdio",
                "owner_kind": "plugin",
                "owner_plugin_id": "demo-mcp",
                "command": {"executable": "plugin-managed", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
                "enabled": True,
                "connection_status": "configured",
            }
        )
        fake_core_result = {
            "ok": True,
            "server": {"id": server["id"]},
            "expansion": {"ok": False, "expanded": 0, "skipped": False, "error": "no_remote_mcp_tools"},
            "discovery": {"total": 3},
        }
        with mock.patch(
            "mcp_host.manager_core.McpManager._connect_plugin_owned",
            return_value=fake_core_result,
        ):
            result = self.manager._connect_plugin_owned(server)
        self.assertFalse(result["ok"])
        raw = self.manager.store.get_server(server["id"])
        self.assertEqual(raw["connection_status"], "error")
        self.assertIn("no_remote_mcp_tools", str(raw.get("last_error") or ""))

    def test_forced_oauth_refresh_ignores_future_expiry_after_401(self) -> None:
        access_ref = secret_store.new_ref("srv", "access")
        refresh_ref = secret_store.new_ref("srv", "refresh")
        secret_store.store(access_ref, "old-access")
        secret_store.store(refresh_ref, "refresh-token")
        server = self._http_server(
            auth_method="oauth",
            auth_secret_ref=access_ref,
            metadata={
                "oauth_refresh_ref": refresh_ref,
                "oauth_token_endpoint": "https://issuer.example/token",
                "oauth_client_id": "client-id",
                "oauth_expires_at": time.time() + 3600,
            },
        )
        with mock.patch(
            "mcp_host.manager.refresh_oauth_token_staged",
            return_value={
                "ok": True,
                "auth_secret_ref": access_ref,
                "refresh_secret_ref": refresh_ref,
                "expires_at": time.time() + 7200,
                "new_secret_refs": [],
                "cleanup_refs": [],
            },
        ) as refresh:
            result = self.manager._maybe_refresh_oauth(server, force=True)
        self.assertTrue(result["ok"])
        refresh.assert_called_once()

    def test_header_update_db_failure_preserves_old_secret_and_rolls_back_new_ref(self) -> None:
        created = self.manager.create_server(
            {
                "name": "Atomic header",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "headers": {"X-API-Key": "old-key"},
            }
        )
        raw = self.manager.store.get_server(created["id"])
        ref_key = next(key for key in raw["env"]["secret_refs"] if key.startswith(HEADER_SECRET_PREFIX))
        old_ref = raw["env"]["secret_refs"][ref_key]
        staged_ref = "mcp/test/header/staged"
        with mock.patch.object(secret_store, "new_ref", return_value=staged_ref):
            with mock.patch.object(self.manager.store, "upsert_server", side_effect=RuntimeError("db write failed")):
                with self.assertRaisesRegex(RuntimeError, "db write failed"):
                    self.manager.update_server(created["id"], {"headers": {"X-API-Key": "new-key"}})
        unchanged = self.manager.store.get_server(created["id"])
        self.assertEqual(unchanged["env"]["secret_refs"][ref_key], old_ref)
        self.assertEqual(secret_store.get(old_ref), "old-key")
        self.assertIsNone(secret_store.get(staged_ref))

    def test_header_update_commits_new_ref_before_old_ref_cleanup(self) -> None:
        created = self.manager.create_server(
            {
                "name": "Header rotate",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "headers": {"X-Token": "old-token"},
            }
        )
        before = self.manager.store.get_server(created["id"])
        ref_key = next(key for key in before["env"]["secret_refs"] if key.startswith(HEADER_SECRET_PREFIX))
        old_ref = before["env"]["secret_refs"][ref_key]
        self.manager.update_server(created["id"], {"headers": {"X-Token": "new-token"}})
        after = self.manager.store.get_server(created["id"])
        new_ref = after["env"]["secret_refs"][ref_key]
        self.assertNotEqual(new_ref, old_ref)
        self.assertEqual(secret_store.get(new_ref), "new-token")
        self.assertIsNone(secret_store.get(old_ref))

    def test_http_to_stdio_switch_removes_header_secret_only_after_persist(self) -> None:
        created = self.manager.create_server(
            {
                "name": "Transport switch",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "headers": {"X-API-Key": "gone-after-commit"},
            }
        )
        before = self.manager.store.get_server(created["id"])
        old_ref = next(
            ref for key, ref in before["env"]["secret_refs"].items() if key.startswith(HEADER_SECRET_PREFIX)
        )
        self.manager.update_server(
            created["id"],
            {
                "transport": "stdio",
                "command": {"executable": "python", "args": ["-V"], "cwd": None},
                "env": {"plain": {}, "secrets": {}},
            },
        )
        after = self.manager.store.get_server(created["id"])
        self.assertEqual(after["transport"], "stdio")
        self.assertFalse(any(key.startswith(HEADER_SECRET_PREFIX) for key in after["env"]["secret_refs"]))
        self.assertIsNone(secret_store.get(old_ref))

    def test_oauth_refresh_db_failure_rolls_back_new_tokens_and_keeps_old_tokens(self) -> None:
        server, old_access, old_refresh = self._oauth_server(name="Refresh rollback")
        new_access = secret_store.new_ref(server["id"], "new-access")
        new_refresh = secret_store.new_ref(server["id"], "new-refresh")
        secret_store.store(new_access, "new-access-value")
        secret_store.store(new_refresh, "new-refresh-value")
        with mock.patch(
            "mcp_host.manager.refresh_oauth_token_staged",
            return_value={
                "ok": True,
                "auth_secret_ref": new_access,
                "refresh_secret_ref": new_refresh,
                "new_secret_refs": [new_access, new_refresh],
                "cleanup_refs": [old_refresh],
                "expires_at": time.time() + 3600,
            },
        ):
            with mock.patch.object(self.manager.store, "upsert_server", side_effect=RuntimeError("db bind failed")):
                with self.assertRaisesRegex(RuntimeError, "db bind failed"):
                    self.manager._maybe_refresh_oauth(server, force=True)
        self.assertEqual(secret_store.get(old_access), "old-access")
        self.assertEqual(secret_store.get(old_refresh), "old-refresh")
        self.assertIsNone(secret_store.get(new_access))
        self.assertIsNone(secret_store.get(new_refresh))

    def test_oauth_refresh_cleans_old_refs_only_after_successful_binding(self) -> None:
        server, old_access, old_refresh = self._oauth_server(name="Refresh commit")
        new_access = secret_store.new_ref(server["id"], "new-access")
        new_refresh = secret_store.new_ref(server["id"], "new-refresh")
        secret_store.store(new_access, "new-access-value")
        secret_store.store(new_refresh, "new-refresh-value")
        original_upsert = self.manager.store.upsert_server

        def assert_old_tokens_still_exist_at_db_commit(payload):
            self.assertEqual(secret_store.get(old_access), "old-access")
            self.assertEqual(secret_store.get(old_refresh), "old-refresh")
            return original_upsert(payload)

        with mock.patch(
            "mcp_host.manager.refresh_oauth_token_staged",
            return_value={
                "ok": True,
                "auth_secret_ref": new_access,
                "refresh_secret_ref": new_refresh,
                "new_secret_refs": [new_access, new_refresh],
                "cleanup_refs": [old_refresh],
                "expires_at": time.time() + 3600,
            },
        ):
            with mock.patch.object(self.manager.store, "upsert_server", side_effect=assert_old_tokens_still_exist_at_db_commit):
                result = self.manager._maybe_refresh_oauth(server, force=True)
        self.assertTrue(result["ok"])
        raw = self.manager.store.get_server(server["id"])
        self.assertEqual(raw["auth_secret_ref"], new_access)
        self.assertEqual(raw["metadata"]["oauth_refresh_ref"], new_refresh)
        self.assertIsNone(secret_store.get(old_access))
        self.assertIsNone(secret_store.get(old_refresh))

    def test_oauth_completion_db_failure_discards_new_unbound_tokens(self) -> None:
        server, old_access, old_refresh = self._oauth_server(name="Complete rollback")
        new_access = secret_store.new_ref(server["id"], "complete-access")
        new_refresh = secret_store.new_ref(server["id"], "complete-refresh")
        secret_store.store(new_access, "complete-access-value")
        secret_store.store(new_refresh, "complete-refresh-value")
        fake_result = {
            "ok": True,
            "server_id": server["id"],
            "auth_secret_ref": new_access,
            "refresh_secret_ref": new_refresh,
            "endpoint_url": server["endpoint_url"],
            "issuer": "https://issuer.example",
            "client_id": "client-id",
            "token_endpoint": "https://issuer.example/token",
        }
        with mock.patch("mcp_host.manager.complete_oauth_flow", return_value=fake_result):
            with mock.patch.object(self.manager.store, "upsert_server", side_effect=RuntimeError("oauth db failed")):
                with self.assertRaisesRegex(RuntimeError, "oauth db failed"):
                    self.manager.complete_oauth(state="state-value", code="code-value")
        self.assertEqual(secret_store.get(old_access), "old-access")
        self.assertEqual(secret_store.get(old_refresh), "old-refresh")
        self.assertIsNone(secret_store.get(new_access))
        self.assertIsNone(secret_store.get(new_refresh))

    def test_reauth_without_refresh_token_removes_stale_refresh_ref_after_binding(self) -> None:
        server, old_access, old_refresh = self._oauth_server(name="No refresh reauth")
        new_access = secret_store.new_ref(server["id"], "reauth-access")
        secret_store.store(new_access, "reauth-access-value")
        fake_result = {
            "ok": True,
            "server_id": server["id"],
            "auth_secret_ref": new_access,
            "refresh_secret_ref": None,
            "endpoint_url": server["endpoint_url"],
            "issuer": "https://issuer.example",
            "client_id": "client-id",
            "token_endpoint": "https://issuer.example/token",
        }
        with mock.patch("mcp_host.manager.complete_oauth_flow", return_value=fake_result):
            result = self.manager.complete_oauth(state="state-value", code="code-value")
        self.assertTrue(result["ok"])
        raw = self.manager.store.get_server(server["id"])
        self.assertEqual(raw["auth_secret_ref"], new_access)
        self.assertNotIn("oauth_refresh_ref", raw["metadata"])
        self.assertIsNone(secret_store.get(old_access))
        self.assertIsNone(secret_store.get(old_refresh))

    def test_runtime_oauth_metadata_refs_cannot_be_injected_by_config_api(self) -> None:
        created = self.manager.create_server(
            {
                "name": "Metadata",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "headers": {},
                "metadata": {
                    "oauth_client_id": "allowed-client-setting",
                    "oauth_refresh_ref": "mcp/other/oauth_refresh/attacker-controlled",
                    "oauth_token_endpoint": "http://169.254.169.254/token",
                    "secret_cleanup_pending": ["other-ref"],
                    "oauth_secret_cleanup_pending": ["also-internal"],
                },
            }
        )
        raw = self.manager.store.get_server(created["id"])
        self.assertEqual(raw["metadata"].get("oauth_client_id"), "allowed-client-setting")
        self.assertNotIn("oauth_refresh_ref", raw["metadata"])
        self.assertNotIn("oauth_token_endpoint", raw["metadata"])
        self.assertNotIn("secret_cleanup_pending", raw["metadata"])
        self.assertNotIn("oauth_secret_cleanup_pending", raw["metadata"])

    def test_sensitive_custom_header_never_persists_or_returns_plaintext(self) -> None:
        created = self.manager.create_server(
            {
                "name": "Header secret",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "headers": {"X-API-Key": "api-secret", "Accept": "application/json"},
            }
        )
        raw = self.manager.store.get_server(created["id"])
        self.assertEqual(raw["headers"]["X-API-Key"], "***")
        self.assertNotIn("api-secret", repr(raw))
        public = self.manager.get_server(created["id"])
        self.assertNotIn("auth_secret_ref", public)
        self.assertNotIn("secret_refs", public["env"])
        self.assertNotIn("api-secret", repr(public))

    def test_config_export_masks_sensitive_headers_and_hides_reserved_secret_keys(self) -> None:
        created = self.manager.create_server(
            {
                "name": "Export header secret",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "headers": {"X-API-Key": "export-secret", "X-Trace": "trace-ok"},
                "metadata": {"oauth_client_id": "client-setting"},
            }
        )
        raw = self.manager.store.get_server(created["id"])
        raw_meta = dict(raw.get("metadata") or {})
        raw_meta["oauth_refresh_ref"] = "mcp/internal/refresh"
        raw_meta["oauth_token_endpoint"] = "https://issuer.example/token"
        raw["metadata"] = raw_meta
        self.manager.store.upsert_server(raw)

        exported = self.manager.export_config()
        blob = json.dumps(exported, sort_keys=True)
        self.assertNotIn("export-secret", blob)
        self.assertNotIn("__mcp_http_header__:", blob)
        self.assertNotIn("mcp/internal/refresh", blob)
        item = next(server for server in exported["servers"] if server["id"] == created["id"])
        self.assertEqual(item["headers"]["X-API-Key"], "***")
        self.assertEqual(item["headers"]["X-Trace"], "trace-ok")
        self.assertEqual(item["metadata"].get("oauth_client_id"), "client-setting")
        self.assertNotIn("oauth_refresh_ref", item["metadata"])
        self.assertNotIn("oauth_token_endpoint", item["metadata"])
        self.assertTrue(item["secrets_configured"])


if __name__ == "__main__":
    unittest.main()
