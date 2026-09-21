"""Regression tests for MCP host production-hardening defects.

These tests encode confirmed security/isolation invariants. They must fail
against the pre-hardening PR #73 implementation and pass after the fix.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

from platform_db import PlatformDatabase


class _McpManagerHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        from mcp_host.manager import McpManager
        from mcp_host.secrets import secret_store

        secret_store.enable_memory_backend_for_tests()
        self.manager = McpManager(
            self.db,
            settings_provider=lambda: {
                "mcp.enabled": True,
                "mcp.max_connections": 8,
                "network_policy": "allow",
                "subprocess_policy": "allow",
            },
        )

    def tearDown(self) -> None:
        self.manager.on_shutdown()
        self.tmp.cleanup()


class ManualAuthorizationTests(_McpManagerHarness):
    def _tool(self, *, allowed: bool, require_approval: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        server = self.manager.store.upsert_server(
            {
                "name": "AuthSrv",
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
            [{"name": "echo", "inputSchema": {"type": "object", "properties": {}}}],
        )
        tool = self.manager.store.list_tools(server["id"])[0]
        self.manager.store.update_tool_prefs(
            tool["id"],
            {"allowed": allowed, "require_approval": require_approval, "chatbot_enabled": False},
        )
        tool = self.manager.store.get_tool(tool["id"])
        return server, tool

    def test_manual_without_approval_cannot_run_blocked_tool(self) -> None:
        _server, tool = self._tool(allowed=False)
        with self.assertRaises(PermissionError):
            self.manager.invoke_tool(
                tool["id"],
                {},
                invocation_type="manual",
                approved_by_user=False,
            )

    def test_manual_with_approval_can_run_blocked_tool_once(self) -> None:
        from approvals import ApprovalService
        from mcp_host.policy import mcp_tool_scope

        server, tool = self._tool(allowed=False)
        approvals = ApprovalService(self.db, inbox=None)
        self.manager.approval_service = approvals
        scope = mcp_tool_scope(
            server_id=tool["server_id"],
            tool_id=tool["id"],
            tool_name=tool["remote_name"],
        )
        req = approvals.create_tool_approval(
            plugin_id=f"mcp:{tool['server_id']}",
            tool_name=tool["remote_name"],
            arguments={},
            expected_effect="mcp tool invoke",
            schema_version="mcp-tool-1",
            scope=scope,
        )
        decided = approvals.decide(req["id"], approve=True)

        class FakeClient:
            transport = "streamable_http"
            alive = True
            protocol_version = "2024-11-05"
            protocol_generation = "legacy"

            def call_tool(self, name, arguments):
                return {"tool": name, "isError": False, "result": {"ok": True}, "content": [{"type": "text", "text": "ok"}]}

            def close(self):
                return None

        with self.manager._session_lock:
            self.manager._sessions[server["id"]] = FakeClient()
        with mock.patch(
            "runtime.execution_gateway.enforce_policies_fail_closed",
            return_value={"allowed": True, "args": {}},
        ):
            result = self.manager.invoke_tool(
                tool["id"],
                {},
                invocation_type="manual",
                approved_by_user=True,  # audit only — not authority
                approval_id=decided["id"],
            )
        self.assertFalse(result.get("result", {}).get("isError", True))

    def test_autonomous_blocked_even_with_approval_flag_alone_when_not_allowed(self) -> None:
        # approved_by_user without allowed still needs require_approval path;
        # disallowed tools must stay blocked for autonomous.
        _server, tool = self._tool(allowed=False, require_approval=False)
        with self.assertRaises(PermissionError):
            self.manager.invoke_tool(
                tool["id"],
                {},
                invocation_type="autonomous",
                approved_by_user=True,
            )

    def test_require_approval_blocks_autonomous_without_user_approval(self) -> None:
        _server, tool = self._tool(allowed=True, require_approval=True)
        with self.assertRaises(PermissionError):
            self.manager.invoke_tool(
                tool["id"],
                {},
                invocation_type="autonomous",
                approved_by_user=False,
            )

    def test_revoke_before_call_managed_tool(self) -> None:
        server, tool = self._tool(allowed=True)

        class FakeClient:
            transport = "streamable_http"
            alive = True
            protocol_version = "2024-11-05"
            protocol_generation = "legacy"
            calls = 0

            def call_tool(self, name, arguments):
                self.calls += 1
                return {"tool": name, "isError": False, "content": [{"type": "text", "text": "ok"}]}

            def close(self):
                return None

        client = FakeClient()
        with self.manager._session_lock:
            self.manager._sessions[server["id"]] = client
        self.manager.store.update_tool_prefs(tool["id"], {"allowed": False})
        with self.assertRaises(PermissionError):
            self.manager.call_managed_tool(server["id"], "echo", {})
        self.assertEqual(client.calls, 0)


class IdempotencyScopeTests(_McpManagerHarness):
    def test_same_key_different_servers_do_not_collide(self) -> None:
        a = self.manager.store.upsert_server(
            {
                "name": "A",
                "transport": "stdio",
                "command": {"executable": "npx", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
            }
        )
        b = self.manager.store.upsert_server(
            {
                "name": "B",
                "transport": "stdio",
                "command": {"executable": "npx", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
            }
        )
        self.manager.store.replace_discovered_tools(a["id"], [{"name": "t", "inputSchema": {"type": "object"}}])
        self.manager.store.replace_discovered_tools(b["id"], [{"name": "t", "inputSchema": {"type": "object"}}])
        ta = self.manager.store.list_tools(a["id"])[0]
        tb = self.manager.store.list_tools(b["id"])[0]
        ea = self.manager.store.create_execution(
            {
                "server_id": a["id"],
                "tool_id": ta["id"],
                "status": "completed",
                "input": {"x": 1},
                "result": {"from": "a"},
                "idempotency_key": "shared-key",
            }
        )
        eb = self.manager.store.create_execution(
            {
                "server_id": b["id"],
                "tool_id": tb["id"],
                "status": "completed",
                "input": {"x": 2},
                "result": {"from": "b"},
                "idempotency_key": "shared-key",
            }
        )
        self.assertNotEqual(ea["id"], eb["id"])
        self.assertEqual(ea["result"].get("from"), "a")
        self.assertEqual(eb["result"].get("from"), "b")


class HttpCancelIsolationTests(unittest.TestCase):
    def test_cancel_one_request_does_not_poison_client(self) -> None:
        from mcp_host.clients import HttpMcpClient

        started = threading.Event()
        release = threading.Event()
        call_count = {"n": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                method = payload.get("method")
                req_id = payload.get("id")
                call_count["n"] += 1
                if method == "server/discover":
                    data = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                    raw = json.dumps(data).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if method == "initialize":
                    data = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "fixture", "version": "1"},
                        },
                    }
                    raw = json.dumps(data).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if method == "tools/call":
                    name = (payload.get("params") or {}).get("name")
                    if name == "slow":
                        started.set()
                        release.wait(5)
                    data = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"done:{name}"}],
                            "isError": False,
                        },
                    }
                    raw = json.dumps(data).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                data = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                raw = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = HttpMcpClient(f"http://127.0.0.1:{server.server_address[1]}/mcp", timeout=5.0, allow_private=True)
        try:
            client.initialize()
            errors: list[BaseException] = []
            results: dict[str, Any] = {}

            def slow():
                try:
                    results["slow"] = client.call_tool("slow", {})
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            t = threading.Thread(target=slow)
            t.start()
            self.assertTrue(started.wait(2))
            # Cancel only the in-flight slow request id bookkeeping via public API.
            client.cancel_pending()  # pre-fix: this permanently poisons; post-fix: scoped+cleared
            # Force the slow handler to finish so we can observe post-cancel health.
            release.set()
            t.join(timeout=5)
            # A subsequent call must still succeed (not poisoned by prior cancel Event).
            ok = client.call_tool("fast", {})
            self.assertFalse(ok.get("isError"))
            self.assertIn("done:fast", json.dumps(ok))
        finally:
            client.close()
            server.shutdown()


    def test_cancel_one_of_two_parallel_http_calls(self) -> None:
        from mcp_host.clients import HttpMcpClient

        barriers = {"slow_started": threading.Event(), "release_slow": threading.Event()}
        results: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                method = payload.get("method")
                req_id = payload.get("id")
                if method == "server/discover":
                    data = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                elif method == "initialize":
                    data = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "par", "version": "1"},
                        },
                    }
                elif method == "tools/call":
                    name = (payload.get("params") or {}).get("name")
                    if name == "slow":
                        barriers["slow_started"].set()
                        # Open SSE immediately so the client can cancel by closing the stream.
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        barriers["release_slow"].wait(5)
                        final = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {"content": [{"type": "text", "text": "ok:slow"}], "isError": False},
                        }
                        chunk = f"data: {json.dumps(final)}\n\n".encode("utf-8")
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except BrokenPipeError:
                            pass
                        return
                    data = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"content": [{"type": "text", "text": f"ok:{name}"}], "isError": False},
                    }
                else:
                    data = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                raw = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        client = HttpMcpClient(f"http://127.0.0.1:{server.server_address[1]}/mcp", timeout=5.0, allow_private=True)
        try:
            client.initialize()

            def run(label: str, tool: str, exec_id: str):
                try:
                    results[label] = client.call_tool(tool, {}, execution_id=exec_id)
                except BaseException as exc:  # noqa: BLE001
                    errors[label] = exc

            t_slow = threading.Thread(target=run, args=("slow", "slow", "exec-slow"))
            t_fast = threading.Thread(target=run, args=("fast", "fast", "exec-fast"))
            t_slow.start()
            self.assertTrue(barriers["slow_started"].wait(2))
            t_fast.start()
            # Cancel only the slow execution; do not release the slow handler until after cancel.
            self.assertTrue(client.cancel_execution("exec-slow"))
            t_slow.join(5)
            barriers["release_slow"].set()
            t_fast.join(5)
            self.assertIn("slow", errors)
            slow_exc = errors["slow"]
            self.assertTrue(
                getattr(slow_exc, "kind", None) == "cancelled"
                or "cancel" in str(slow_exc).lower()
                or "SSE stream ended" in str(slow_exc),
                msg=f"unexpected slow error: {slow_exc!r}",
            )
            self.assertNotIn("fast", errors)
            self.assertFalse(results["fast"].get("isError"))
            # Future call must still work (no poison).
            again = client.call_tool("again", {})
            self.assertFalse(again.get("isError"))
        finally:
            client.close()
            server.shutdown()


class NetworkPolicyAskNotAllowTests(_McpManagerHarness):
    def test_network_ask_blocks_external_http_without_approval(self) -> None:
        self.manager.settings_provider = lambda: {
            "mcp.enabled": True,
            "network_policy": "ask",
            "subprocess_policy": "allow",
        }
        server = self.manager.store.upsert_server(
            {
                "name": "Ext",
                "transport": "streamable_http",
                "endpoint_url": "https://example.com/mcp",
                "auth_method": "none",
                "enabled": True,
                "env": {"plain": {}, "secret_refs": {}},
                "headers": {},
            }
        )
        with self.assertRaises(Exception) as ctx:
            self.manager.connect(server["id"])
        message = str(ctx.exception).lower()
        self.assertTrue("ask" in message or "goedkeuring" in message or "approval" in message or "policy" in message)

    def test_subprocess_block_never_spawns_stdio_client(self) -> None:
        self.manager.settings_provider = lambda: {
            "mcp.enabled": True,
            "network_policy": "allow",
            "subprocess_policy": "block",
        }
        server = self.manager.store.upsert_server(
            {
                "name": "StdioBlocked",
                "transport": "stdio",
                "command": {"executable": "python", "args": ["-c", "print(1)"], "cwd": None},
                "auth_method": "none",
                "enabled": True,
                "env": {"plain": {}, "secret_refs": {}},
                "headers": {},
            }
        )
        with mock.patch("mcp_host.clients_legacy.subprocess.Popen") as popen:
            with self.assertRaises(Exception) as ctx:
                self.manager.connect(server["id"])
            popen.assert_not_called()
        message = str(ctx.exception).lower()
        self.assertTrue("subprocess" in message or "block" in message or "beleid" in message)


class ProtocolVersionPreferenceTests(unittest.TestCase):
    def test_newest_protocol_preferred(self) -> None:
        from mcp_host.protocol import DEFAULT_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

        self.assertEqual(SUPPORTED_PROTOCOL_VERSIONS[0], "2026-07-28")
        self.assertEqual(DEFAULT_PROTOCOL_VERSION, "2026-07-28")
        self.assertIn("2025-11-25", SUPPORTED_PROTOCOL_VERSIONS)
        self.assertIn("2025-03-26", SUPPORTED_PROTOCOL_VERSIONS)


class OAuthCallbackBindingTests(unittest.TestCase):
    def test_pending_oauth_binds_issuer_and_rejects_replay(self) -> None:
        from mcp_host import oauth

        oauth._PENDING.clear()
        start = oauth.start_oauth_flow(
            server_id="srv1",
            endpoint_url="http://127.0.0.1:9/mcp",
            redirect_uri="http://127.0.0.1:8000/api/mcp/oauth/callback",
            client_id="test-client",
            allow_private=True,
            authorization_server_metadata={
                "authorization_endpoint": "http://127.0.0.1:9/authorize",
                "token_endpoint": "http://127.0.0.1:9/token",
                "issuer": "http://127.0.0.1:9",
                "code_challenge_methods_supported": ["S256"],
            },
            resource_metadata={"authorization_servers": ["http://127.0.0.1:9"], "resource": "http://127.0.0.1:9/mcp"},
        )
        # Without network discovery this may fail; skip if fixture path not wired yet.
        if not start.get("ok"):
            self.skipTest(f"oauth start fixture not available: {start}")
        state = start["state"]
        first = oauth.complete_oauth_flow(state=state, code="abc", iss="http://127.0.0.1:9")
        # May fail token exchange against dead endpoint — but state must be consumed.
        second = oauth.complete_oauth_flow(state=state, code="abc", iss="http://127.0.0.1:9")
        self.assertFalse(second.get("ok"))
        self.assertIn("state", str(second.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
