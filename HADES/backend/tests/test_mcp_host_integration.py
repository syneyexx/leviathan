"""Local fixture MCP servers + integration tests (no external network)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from platform_db import PlatformDatabase


FIXTURE_STDIO = r'''
import json, sys

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def main():
    # Prefer modern discover; also answer legacy initialize.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "server/discover":
            send({"jsonrpc":"2.0","id":req_id,"result":{
                "resultType":"complete",
                "supportedVersions":["2026-07-28","2025-11-25"],
                "capabilities":{"tools":{}},
                "_meta":{"io.modelcontextprotocol/serverInfo":{"name":"fixture-stdio","version":"1"}},
                "ttlMs": 0,
                "cacheScope": "private"
            }})
        elif method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion") or "2025-03-26"
            send({"jsonrpc":"2.0","id":req_id,"result":{
                "protocolVersion": ver if ver != "2026-07-28" else "2025-11-25",
                "capabilities":{"tools":{}},
                "serverInfo":{"name":"fixture-stdio","version":"1"}
            }})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send({"jsonrpc":"2.0","id":req_id,"result":{
                "tools":[{
                    "name":"echo",
                    "description":"echo",
                    "inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":False}
                }],
                "ttlMs": 60000,
                "cacheScope": "private",
                "resultType": "complete"
            }})
        elif method == "tools/call":
            params = msg.get("params") or {}
            args = params.get("arguments") or {}
            text = args.get("text", "")
            send({"jsonrpc":"2.0","id":req_id,"result":{
                "content":[{"type":"text","text": f"echo:{text}"}],
                "isError": False,
                "resultType": "complete"
            }})
        elif method == "notifications/cancelled":
            continue
        elif req_id is not None:
            send({"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":"Method not found"}})

if __name__ == "__main__":
    main()
'''


class LegacyHttpHandler(BaseHTTPRequestHandler):
    protocol_version_negotiated = "2025-11-25"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        method = payload.get("method")
        req_id = payload.get("id")
        if method == "server/discover":
            # Legacy servers: method not found → client falls back.
            data = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        elif method == "initialize":
            data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture-http-legacy", "version": "1"},
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "legacy-session-1")
            raw = json.dumps(data).encode("utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        elif method == "tools/list":
            data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "ping",
                            "description": "ping",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                },
            }
        elif method == "tools/call":
            name = (payload.get("params") or {}).get("name")
            data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"pong:{name}"}], "isError": False},
            }
        elif method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
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


class ModernHttpHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        method = payload.get("method")
        req_id = payload.get("id")
        # Require modern routing headers.
        if not self.headers.get("Mcp-Method") or not self.headers.get("MCP-Protocol-Version"):
            self.send_response(400)
            self.end_headers()
            return
        if method == "server/discover":
            data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resultType": "complete",
                    "supportedVersions": ["2026-07-28"],
                    "capabilities": {"tools": {}},
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": "fixture-http-modern",
                            "version": "1",
                        }
                    },
                    "ttlMs": 0,
                    "cacheScope": "private",
                },
            }
        elif method == "tools/list":
            data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "add",
                            "description": "add",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                                "required": ["a", "b"],
                            },
                        }
                    ],
                    "ttlMs": 1000,
                    "cacheScope": "private",
                    "resultType": "complete",
                },
            }
        elif method == "tools/call":
            args = (payload.get("params") or {}).get("arguments") or {}
            total = float(args.get("a", 0)) + float(args.get("b", 0))
            data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(total)}],
                    "structuredContent": {"sum": total},
                    "isError": False,
                    "resultType": "complete",
                },
            }
        else:
            data = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        raw = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A003
        return


class McpStdioIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.script = Path(self.tmp.name) / "fixture_mcp.py"
        self.script.write_text(FIXTURE_STDIO, encoding="utf-8")
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        from mcp_host.manager import McpManager
        from mcp_host.secrets import secret_store

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

    def test_stdio_connect_discover_invoke_revoke(self) -> None:
        from unittest import mock

        server = self.manager.create_server(
            {
                "name": "Fixture Stdio",
                "transport": "stdio",
                "command": {"executable": sys.executable, "args": [str(self.script)], "cwd": None},
                "env": {"plain": {}, "secrets": {}},
                "auto_connect": False,
            }
        )
        connected = self.manager.connect(server["id"])
        self.assertTrue(connected.get("ok"))
        refreshed = self.manager.get_server(server["id"])
        self.assertIn(refreshed.get("connection_status"), {"connected", "ready"})
        tools = self.manager.list_tools(server_id=server["id"])
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertFalse(tool["allowed"])
        self.manager.update_tool_prefs(tool["id"], {"allowed": True, "chatbot_enabled": True, "require_approval": False})
        with mock.patch(
            "runtime.execution_gateway.enforce_policies_fail_closed",
            return_value={"allowed": True, "args": {"text": "hi"}},
        ):
            result = self.manager.invoke_tool(
                tool["id"],
                {"text": "hi"},
                invocation_type="manual",
                approved_by_user=True,
            )
        self.assertFalse(result.get("result", {}).get("isError", True))
        self.manager.update_tool_prefs(tool["id"], {"allowed": False, "chatbot_enabled": False})
        with self.assertRaises(PermissionError):
            self.manager.invoke_tool(tool["id"], {"text": "nope"}, invocation_type="autonomous", approved_by_user=False)

    def test_argument_validation_rejects_missing_required(self) -> None:
        from mcp_host.validation import validate_tool_arguments

        with self.assertRaises(ValueError):
            validate_tool_arguments(
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                {},
            )


class McpHttpIntegrationTests(unittest.TestCase):
    def _serve(self, handler_cls):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def test_modern_http_discover_and_call(self) -> None:
        from mcp_host.clients import HttpMcpClient

        http = self._serve(ModernHttpHandler)
        try:
            client = HttpMcpClient(
                f"http://127.0.0.1:{http.server_address[1]}/mcp",
                timeout=5.0,
                allow_private=True,
            )
            discovered = client.initialize()
            self.assertEqual(client.protocol_generation, "modern")
            self.assertIn("2026-07-28", json.dumps(discovered))
            listed = client.list_tools_all()
            self.assertTrue(listed["complete"])
            result = client.call_tool("add", {"a": 2, "b": 3})
            self.assertFalse(result.get("isError"))
            self.assertIn("5", json.dumps(result))
            client.close()
        finally:
            http.shutdown()

    def test_legacy_http_initialize_fallback(self) -> None:
        from mcp_host.clients import HttpMcpClient

        http = self._serve(LegacyHttpHandler)
        try:
            client = HttpMcpClient(
                f"http://127.0.0.1:{http.server_address[1]}/mcp",
                timeout=5.0,
                allow_private=True,
            )
            client.initialize()
            self.assertEqual(client.protocol_generation, "legacy")
            self.assertEqual(client.session_id, "legacy-session-1")
            result = client.call_tool("ping", {})
            self.assertFalse(result.get("isError"))
            client.close()
        finally:
            http.shutdown()


class MigrationUpgradeTests(unittest.TestCase):
    def test_upgrade_pre_v16_idempotency_schema(self) -> None:
        import sqlite3
        from mcp_host.store import ensure_mcp_schema

        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)")
        conn.executescript(
            """
            CREATE TABLE mcp_servers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                transport TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, auto_connect INTEGER NOT NULL DEFAULT 0,
                owner_kind TEXT NOT NULL DEFAULT 'managed', owner_plugin_id TEXT, catalog_id TEXT,
                command_json TEXT, env_json TEXT, endpoint_url TEXT, auth_method TEXT NOT NULL DEFAULT 'none',
                headers_json TEXT, auth_secret_ref TEXT, timeout_seconds REAL NOT NULL DEFAULT 60,
                connection_status TEXT NOT NULL DEFAULT 'configured', auth_status TEXT NOT NULL DEFAULT 'none',
                last_check_at TEXT, last_error TEXT, last_error_kind TEXT, protocol_version TEXT,
                discovery_complete INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE mcp_executions (
                id TEXT PRIMARY KEY, server_id TEXT NOT NULL, tool_id TEXT NOT NULL, tool_call_id TEXT,
                status TEXT NOT NULL, error_kind TEXT, started_at TEXT, ended_at TEXT, duration_ms REAL,
                input_json TEXT, result_json TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT, UNIQUE(idempotency_key)
            );
            """
        )
        conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(15, '2026-01-01')")
        conn.execute(
            "INSERT INTO mcp_executions(id,server_id,tool_id,status,idempotency_key) VALUES('e1','s1','t1','completed','k')"
        )
        conn.commit()
        ensure_mcp_schema(conn)
        versions = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        self.assertIn(16, versions)
        # Same key different server/tool should now be insertable.
        conn.execute(
            "INSERT INTO mcp_executions(id,server_id,tool_id,status,idempotency_key) VALUES('e2','s2','t2','completed','k')"
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM mcp_executions").fetchone()[0]
        self.assertEqual(count, 2)
        conn.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
