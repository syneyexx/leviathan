"""Focused MCP host regressions.

Covers: name conflicts, paginated discovery / repeated cursors, schema changes,
permission change between select and execute, isError vs transport errors,
timeout unknown outcome, no auto double-write, token redaction, safe export,
restart recovery status, concurrent connect without duplicate processes,
plugin-owned backwards compatibility markers.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from platform_db import PlatformDatabase


class McpHostProtocolTests(unittest.TestCase):
    def test_model_tool_name_namespaces_collisions(self) -> None:
        from mcp_host.protocol import model_tool_name

        a = model_tool_name("github", "search")
        b = model_tool_name("huggingface", "search")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("mcp__"))
        self.assertIn("github", a)
        self.assertIn("huggingface", b)

    def test_discovery_repeated_cursor(self) -> None:
        from mcp_host.protocol import discovery_cursor_loop

        seen: set[str] = set()
        self.assertFalse(discovery_cursor_loop(seen, "c1"))
        self.assertTrue(discovery_cursor_loop(seen, "c1"))

    def test_export_safe_server_redacts_secrets(self) -> None:
        from mcp_host.protocol import export_safe_server

        exported = export_safe_server(
            {
                "id": "s1",
                "name": "GitHub",
                "transport": "streamable_http",
                "endpoint_url": "https://api.githubcopilot.com/mcp/",
                "auth_method": "bearer",
                "headers": {"Authorization": "Bearer SECRET", "X-Extra": "ok"},
                "env": {"plain": {"FOO": "1"}, "secret_refs": {"TOKEN": "ref1"}},
                "metadata": {"oauth_refresh_ref": "r", "note": "x"},
            }
        )
        self.assertNotIn("Authorization", exported.get("headers") or {})
        self.assertEqual(exported["headers"].get("X-Extra"), "ok")
        self.assertEqual(exported["env"]["secret_keys"], ["TOKEN"])
        self.assertNotIn("secret_refs", exported["env"])


class McpHostStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        from mcp_host.store import McpStore

        self.store = McpStore(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_name_conflict(self) -> None:
        self.store.upsert_server(
            {
                "name": "Alpha",
                "transport": "stdio",
                "command": {"executable": "npx", "args": ["x"], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
            }
        )
        with self.assertRaises(ValueError):
            self.store.upsert_server(
                {
                    "name": "Alpha",
                    "transport": "stdio",
                    "command": {"executable": "npx", "args": ["y"], "cwd": None},
                    "env": {"plain": {}, "secret_refs": {}},
                }
            )

    def test_discovery_does_not_expand_rights_on_new_tools(self) -> None:
        server = self.store.upsert_server(
            {
                "name": "S",
                "transport": "stdio",
                "command": {"executable": "npx", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
            }
        )
        self.store.replace_discovered_tools(
            server["id"],
            [{"name": "old", "description": "d", "inputSchema": {"type": "object", "properties": {}}}],
        )
        tools = self.store.list_tools(server["id"])
        self.store.update_tool_prefs(tools[0]["id"], {"allowed": True, "chatbot_enabled": True})
        self.store.replace_discovered_tools(
            server["id"],
            [
                {"name": "old", "description": "d2", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}}},
                {"name": "new", "description": "n", "inputSchema": {"type": "object"}},
            ],
        )
        by_name = {t["remote_name"]: t for t in self.store.list_tools(server["id"])}
        self.assertTrue(by_name["old"]["allowed"])
        self.assertTrue(by_name["old"]["chatbot_enabled"])
        self.assertFalse(by_name["new"]["allowed"])
        self.assertFalse(by_name["new"]["chatbot_enabled"])
        self.assertTrue(by_name["new"]["require_approval"])

    def test_schema_change_preserved_and_flagged(self) -> None:
        from mcp_host.protocol import validate_input_schema

        issue = validate_input_schema({"type": "string"})
        self.assertIsNotNone(issue)
        server = self.store.upsert_server(
            {
                "name": "Schema",
                "transport": "stdio",
                "command": {"executable": "npx", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
            }
        )
        self.store.replace_discovered_tools(
            server["id"],
            [{"name": "t", "inputSchema": {"type": "string"}}],
        )
        tool = self.store.list_tools(server["id"])[0]
        self.assertIsNotNone(tool["schema_issue"])


class McpHostSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        from mcp_host.manager import McpManager
        from mcp_host.secrets import secret_store

        secret_store.enable_memory_backend_for_tests()
        self.manager = McpManager(self.db, settings_provider=lambda: {"mcp.enabled": True, "mcp.max_connections": 2})

    def tearDown(self) -> None:
        self.manager.on_shutdown()
        self.tmp.cleanup()

    def test_restart_does_not_blindly_restore_connected(self) -> None:
        server = self.manager.store.upsert_server(
            {
                "name": "Local",
                "transport": "stdio",
                "command": {"executable": "npx", "args": ["-y", "demo"], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
                "connection_status": "connected",
                "enabled": True,
            }
        )
        notes = self.manager.on_startup()
        refreshed = self.manager.store.get_server(server["id"])
        self.assertNotEqual(refreshed["connection_status"], "connected")
        self.assertTrue(any(str(n).startswith("reset_status:") for n in notes["notes"]) or refreshed["connection_status"] in {"disconnected", "configured", "error"})

    def test_concurrent_connect_rejects_duplicate(self) -> None:
        server = self.manager.create_server(
            {
                "name": "Race",
                "transport": "stdio",
                "command": {"executable": "npx", "args": ["-y", "demo"], "cwd": None},
                "env": {"plain": {}, "secrets": {}},
                "auto_connect": False,
            }
        )
        started = threading.Event()
        release = threading.Event()
        errors: list[str] = []

        def fake_build(server_row, *, approval_id=None):
            started.set()
            release.wait(2)
            raise RuntimeError("stop")

        with mock.patch.object(self.manager, "_build_client", side_effect=fake_build):
            def worker():
                try:
                    self.manager.connect(server["id"])
                except Exception as exc:
                    errors.append(str(exc))

            t1 = threading.Thread(target=worker)
            t1.start()
            self.assertTrue(started.wait(2))
            with self.assertRaises(RuntimeError):
                self.manager.connect(server["id"])
            release.set()
            t1.join(timeout=3)

    def test_timeout_marked_unknown_outcome_not_auto_retry(self) -> None:
        from mcp_host.clients import McpClientError

        class FakeClient:
            transport = "streamable_http"
            alive = True
            protocol_version = "2024-11-05"

            def call_tool(self, name, arguments):
                return {
                    "tool": name,
                    "isError": True,
                    "error_kind": "unknown_outcome",
                    "timeout": True,
                    "may_have_side_effects": True,
                    "transport": "streamable_http",
                }

            def close(self):
                return None

        server = self.manager.store.upsert_server(
            {
                "name": "HTTP",
                "transport": "streamable_http",
                "endpoint_url": "http://127.0.0.1:9/mcp",
                "auth_method": "none",
                "enabled": True,
                "connection_status": "connected",
                "env": {"plain": {}, "secret_refs": {}},
                "headers": {},
            }
        )
        self.manager.store.replace_discovered_tools(
            server["id"],
            [{"name": "write_thing", "inputSchema": {"type": "object", "properties": {}}}],
        )
        tool = self.manager.store.list_tools(server["id"])[0]
        self.manager.store.update_tool_prefs(tool["id"], {"allowed": True})
        with self.manager._session_lock:
            self.manager._sessions[server["id"]] = FakeClient()
        with mock.patch("runtime.execution_gateway.enforce_policies_fail_closed", return_value={"allowed": True, "args": {}}):
            result = self.manager._invoke_direct(
                self.manager.store.get_server(server["id"]),
                self.manager.store.get_tool(tool["id"]),
                {},
                invocation_type="manual",
                approved_by_user=True,
                idempotency_key="once-1",
            )
        self.assertEqual(result.get("error_kind"), "unknown_outcome")
        # Idempotent second call with same key must not create a second execution write automatically via reconnect logic.
        again = self.manager.store.create_execution(
            {
                "server_id": server["id"],
                "tool_id": tool["id"],
                "status": "running",
                "input": {},
                "idempotency_key": "once-1",
            }
        )
        self.assertEqual(again["id"], result["execution"]["id"])

    def test_permission_change_between_select_and_execute(self) -> None:
        server = self.manager.store.upsert_server(
            {
                "name": "Perm",
                "transport": "streamable_http",
                "endpoint_url": "http://127.0.0.1:9/mcp",
                "auth_method": "none",
                "enabled": True,
                "connection_status": "connected",
                "env": {"plain": {}, "secret_refs": {}},
                "headers": {},
            }
        )
        self.manager.store.replace_discovered_tools(
            server["id"],
            [{"name": "t", "inputSchema": {"type": "object", "properties": {}}}],
        )
        tool = self.manager.store.list_tools(server["id"])[0]
        self.manager.store.update_tool_prefs(tool["id"], {"allowed": True, "chatbot_enabled": True})
        # Revoke before execute
        self.manager.store.update_tool_prefs(tool["id"], {"allowed": False, "chatbot_enabled": False})
        with mock.patch("runtime.execution_gateway.enforce_policies_fail_closed", return_value={"allowed": False, "reason": "denied"}):
            with self.assertRaises(PermissionError):
                self.manager._invoke_direct(
                    self.manager.store.get_server(server["id"]),
                    self.manager.store.get_tool(tool["id"]),
                    {},
                    invocation_type="autonomous",
                    approved_by_user=False,
                    idempotency_key=None,
                )

    def test_plugin_owned_marker_prevents_delete(self) -> None:
        server = self.manager.store.upsert_server(
            {
                "name": "Chrome DevTools MCP",
                "transport": "stdio",
                "owner_kind": "plugin",
                "owner_plugin_id": "chrome-devtools-mcp",
                "command": {"executable": "plugin-managed", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
                "catalog_id": "chrome-devtools-mcp",
            }
        )
        with self.assertRaises(PermissionError):
            self.manager.delete_server(server["id"])

    def test_token_never_returned_from_auth_apis(self) -> None:
        from mcp_host.secrets import secret_store

        ref = secret_store.new_ref("srv", "bearer")
        secret_store.store(ref, "super-secret-token")
        server = self.manager.store.upsert_server(
            {
                "name": "Sec",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "bearer",
                "auth_secret_ref": ref,
                "env": {"plain": {}, "secret_refs": {}},
                "headers": {},
            }
        )
        exported = self.manager.export_config()
        blob = json.dumps(exported)
        self.assertNotIn("super-secret-token", blob)
        public = self.manager.get_server(server["id"])
        self.assertNotIn("super-secret-token", json.dumps(public))


class McpIsErrorClassificationTests(unittest.TestCase):
    def test_tool_error_vs_transport(self) -> None:
        from mcp_host.clients import McpClientError

        self.assertEqual(McpClientError("x", kind="transport").kind, "transport")
        self.assertEqual(McpClientError("x", kind="protocol").kind, "protocol")


if __name__ == "__main__":
    unittest.main()
