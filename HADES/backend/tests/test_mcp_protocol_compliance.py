"""Strict MCP protocol fixtures and compliance regressions (spec 2026-07-28).

Fixtures validate incoming requests against normative wire rules and emit
``supportedVersions`` — never the non-standard ``protocolVersions`` alias.
"""

from __future__ import annotations

import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp_host.errors import HEADER_MISMATCH, METHOD_NOT_FOUND, UNSUPPORTED_PROTOCOL_VERSION
from mcp_host.oauth import (
    assert_redirect_uri_valid,
    authorization_server_metadata_urls,
    protected_resource_metadata_urls,
    sanitize_ui_return_url,
    validate_pkce_s256,
)
from mcp_host.param_headers import encode_mcp_param_value
from mcp_host.protocol import (
    MODERN_PROTOCOL_VERSION,
    mcp_http_headers,
    parse_discover_supported_versions,
    select_mutually_supported_version,
)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


class StrictModernHttpHandler(BaseHTTPRequestHandler):
    """Validates modern Streamable HTTP requests; rejects header mismatches with -32020."""

    tools = [
        {
            "name": "echo_region",
            "description": "echo",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "region": {"type": "string", "x-mcp-header": "Region"},
                    "text": {"type": "string"},
                },
                "required": ["region", "text"],
            },
        }
    ]
    supported_versions = [MODERN_PROTOCOL_VERSION]
    require_exact_headers = True

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            _json_response(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return
        method = payload.get("method")
        req_id = payload.get("id")
        version = self.headers.get("MCP-Protocol-Version") or self.headers.get("mcp-protocol-version")
        mcp_method = self.headers.get("Mcp-Method") or self.headers.get("mcp-method")
        mcp_name = self.headers.get("Mcp-Name") or self.headers.get("mcp-name")

        if self.require_exact_headers:
            if not version or not mcp_method:
                _json_response(
                    self,
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": HEADER_MISMATCH, "message": "missing required MCP headers"},
                    },
                )
                return
            if mcp_method != method:
                _json_response(
                    self,
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": HEADER_MISMATCH, "message": "Mcp-Method mismatch"},
                    },
                )
                return
            if method in {"tools/call", "resources/read", "prompts/get"}:
                expected_name = (payload.get("params") or {}).get("name") or (payload.get("params") or {}).get("uri")
                if mcp_name != expected_name:
                    _json_response(
                        self,
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": HEADER_MISMATCH, "message": "Mcp-Name mismatch"},
                        },
                    )
                    return
            if version != MODERN_PROTOCOL_VERSION:
                _json_response(
                    self,
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": UNSUPPORTED_PROTOCOL_VERSION,
                            "message": "Unsupported protocol version",
                            "data": {"supported": list(self.supported_versions), "requested": version},
                        },
                    },
                )
                return
            meta = ((payload.get("params") or {}).get("_meta") or {})
            if meta.get("io.modelcontextprotocol/protocolVersion") != version:
                _json_response(
                    self,
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": HEADER_MISMATCH, "message": "protocolVersion header/body mismatch"},
                    },
                )
                return

        if method == "server/discover":
            _json_response(
                self,
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "resultType": "complete",
                        "supportedVersions": list(self.supported_versions),
                        "capabilities": {"tools": {}},
                        "_meta": {
                            "io.modelcontextprotocol/serverInfo": {"name": "strict-modern", "version": "1"}
                        },
                        "ttlMs": 0,
                        "cacheScope": "private",
                    },
                },
            )
            return
        if method == "tools/list":
            _json_response(
                self,
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": self.tools, "resultType": "complete", "ttlMs": 0, "cacheScope": "private"},
                },
            )
            return
        if method == "tools/call":
            args = (payload.get("params") or {}).get("arguments") or {}
            region = args.get("region")
            header_region = self.headers.get("Mcp-Param-Region") or self.headers.get("mcp-param-region")
            if region is not None:
                if header_region is None:
                    _json_response(
                        self,
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": HEADER_MISMATCH, "message": "missing Mcp-Param-Region"},
                        },
                    )
                    return
                decoded = header_region
                if header_region.startswith("=?base64?") and header_region.endswith("?="):
                    decoded = base64.b64decode(header_region[len("=?base64?") : -2]).decode("utf-8")
                if decoded != region:
                    _json_response(
                        self,
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": HEADER_MISMATCH, "message": "Mcp-Param-Region mismatch"},
                        },
                    )
                    return
            text = f"{region}:{args.get('text')}"
            _json_response(
                self,
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": text}],
                        "structuredContent": {"echo": text},
                        "isError": False,
                        "resultType": "complete",
                    },
                },
            )
            return
        _json_response(
            self,
            404,
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": METHOD_NOT_FOUND, "message": "Method not found"}},
        )


class DiscoverParsingTests(unittest.TestCase):
    def test_normative_supported_versions(self) -> None:
        parsed = parse_discover_supported_versions(
            {"supportedVersions": ["2026-07-28"], "resultType": "complete"}
        )
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["source"], "supportedVersions")
        self.assertEqual(parsed["supported"], ["2026-07-28"])

    def test_alias_is_secondary(self) -> None:
        parsed = parse_discover_supported_versions({"protocolVersions": ["2026-07-28"]})
        self.assertEqual(parsed["source"], "alias")
        self.assertEqual(parsed["supported"], ["2026-07-28"])

    def test_missing_and_empty(self) -> None:
        empty = parse_discover_supported_versions({"supportedVersions": []})
        self.assertTrue(empty["ok"])
        self.assertEqual(empty["supported"], [])
        self.assertIsNone(select_mutually_supported_version([]))
        malformed = parse_discover_supported_versions({"supportedVersions": "2026-07-28"})
        self.assertEqual(malformed["source"], "malformed")

    def test_unknown_future_version_not_selected(self) -> None:
        chosen = select_mutually_supported_version(["2099-01-01"])
        self.assertIsNone(chosen)

    def test_legacy_only_selects_legacy(self) -> None:
        chosen = select_mutually_supported_version(["2025-11-25"])
        self.assertEqual(chosen, "2025-11-25")


class HeaderEraTests(unittest.TestCase):
    def test_modern_headers_omit_empty_mcp_name_for_discover(self) -> None:
        headers = mcp_http_headers(method="server/discover", protocol_version=MODERN_PROTOCOL_VERSION)
        self.assertEqual(headers["Mcp-Method"], "server/discover")
        self.assertNotIn("Mcp-Name", headers)

    def test_modern_tools_call_requires_name(self) -> None:
        with self.assertRaises(ValueError):
            mcp_http_headers(method="tools/call", protocol_version=MODERN_PROTOCOL_VERSION, name=None)
        headers = mcp_http_headers(method="tools/call", protocol_version=MODERN_PROTOCOL_VERSION, name="echo")
        self.assertEqual(headers["Mcp-Name"], "echo")

    def test_legacy_omits_routing_headers(self) -> None:
        headers = mcp_http_headers(method="initialize", protocol_version="2025-11-25", session_id="abc")
        self.assertNotIn("Mcp-Method", headers)
        self.assertNotIn("Mcp-Name", headers)
        self.assertEqual(headers.get("Mcp-Session-Id"), "abc")


class ParamEncodingTests(unittest.TestCase):
    def test_ascii_unicode_bool_sentinel(self) -> None:
        self.assertEqual(encode_mcp_param_value("us-west1"), "us-west1")
        self.assertTrue(encode_mcp_param_value("Hello, 世界").startswith("=?base64?"))
        self.assertEqual(encode_mcp_param_value(True), "true")
        sentinel = "=?base64?literal?="
        self.assertTrue(encode_mcp_param_value(sentinel).startswith("=?base64?"))
        self.assertNotEqual(encode_mcp_param_value(sentinel), sentinel)


class OAuthDiscoveryUrlTests(unittest.TestCase):
    def test_protected_resource_path_insertion(self) -> None:
        urls = protected_resource_metadata_urls("https://example.com/public/mcp")
        self.assertEqual(
            urls[0],
            "https://example.com/.well-known/oauth-protected-resource/public/mcp",
        )
        self.assertEqual(urls[1], "https://example.com/.well-known/oauth-protected-resource")

    def test_as_metadata_path_issuer(self) -> None:
        urls = authorization_server_metadata_urls("https://auth.example.test/tenant1")
        self.assertEqual(
            urls,
            [
                "https://auth.example.test/.well-known/oauth-authorization-server/tenant1",
                "https://auth.example.test/.well-known/openid-configuration/tenant1",
                "https://auth.example.test/tenant1/.well-known/openid-configuration",
            ],
        )

    def test_pkce_fail_closed(self) -> None:
        self.assertFalse(validate_pkce_s256({})["ok"])
        self.assertFalse(validate_pkce_s256({"code_challenge_methods_supported": ["plain"]})["ok"])
        self.assertTrue(validate_pkce_s256({"code_challenge_methods_supported": ["S256"]})["ok"])

    def test_redirect_uri_rejects_fragment(self) -> None:
        with self.assertRaises(ValueError):
            assert_redirect_uri_valid("http://127.0.0.1:3000/#/mcp?oauth=1")
        assert_redirect_uri_valid("http://127.0.0.1:8000/api/mcp/oauth/callback")

    def test_ui_return_url_loopback_only(self) -> None:
        default = "http://127.0.0.1:3000/#/mcp"
        self.assertEqual(sanitize_ui_return_url(None, default=default), default)
        self.assertEqual(
            sanitize_ui_return_url("http://127.0.0.1:3000/#/mcp", default=default),
            "http://127.0.0.1:3000/#/mcp",
        )
        self.assertEqual(
            sanitize_ui_return_url("https://evil.example/phish", default=default),
            default,
        )
        self.assertEqual(
            sanitize_ui_return_url("javascript:alert(1)", default=default),
            default,
        )


class StrictModernHttpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), StrictModernHttpHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()

    def test_http_modern_discover_and_param_headers(self) -> None:
        from mcp_host.clients import HttpMcpClient

        client = HttpMcpClient(f"http://127.0.0.1:{self.port}/mcp", allow_private=True, timeout=5)
        try:
            discovered = client.initialize()
            parsed = parse_discover_supported_versions(discovered)
            self.assertEqual(parsed["source"], "supportedVersions")
            self.assertEqual(client.protocol_generation, "modern")
            listed = client.list_tools_all()
            self.assertEqual(len(listed["tools"]), 1)
            schema = listed["tools"][0]["inputSchema"]
            result = client.call_tool("echo_region", {"region": "us-west1", "text": "hi"}, input_schema=schema)
            self.assertFalse(result.get("isError"))
            self.assertIn("us-west1:hi", str(result.get("content")))
        finally:
            client.close()

    def test_header_mismatch_is_not_legacy_fallback(self) -> None:
        from mcp_host.clients import HttpMcpClient, McpClientError
        from mcp_host.protocol import MODERN_PROTOCOL_VERSION

        class BadNameHandler(StrictModernHttpHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                _json_response(
                    self,
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "error": {"code": HEADER_MISMATCH, "message": "forced"},
                    },
                )

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), BadNameHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            client = HttpMcpClient(f"http://127.0.0.1:{httpd.server_address[1]}/mcp", allow_private=True, timeout=5)
            with self.assertRaises(McpClientError) as ctx:
                client.initialize()
            self.assertFalse(ctx.exception.legacy_evidence)
            self.assertEqual(ctx.exception.kind, "protocol")
            client.close()
        finally:
            httpd.shutdown()


class SecretDeletionTruthTests(unittest.TestCase):
    def test_delete_fails_closed_when_keyring_delete_fails(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from mcp_host.manager import McpManager
        from mcp_host.secrets import secret_store
        from platform_db import PlatformDatabase

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = PlatformDatabase(str(Path(tmp.name) / "hades.db"))
        db.initialize()
        secret_store.enable_memory_backend_for_tests()
        manager = McpManager(db, settings_provider=lambda: {"mcp.enabled": True, "network_policy": "allow", "subprocess_policy": "allow"})
        server = manager.create_server(
            {
                "name": "Sec",
                "transport": "streamable_http",
                "endpoint_url": "http://127.0.0.1:9/mcp",
                "auth_method": "bearer",
                "bearer_token": "super-secret-token-value",
                "env": {"plain": {}, "secrets": {}},
            }
        )
        with mock.patch.object(secret_store, "delete", return_value={"ok": False, "error": "boom"}):
            result = manager.delete_server(server["id"])
        self.assertFalse(result.get("ok"))
        self.assertIsNotNone(manager.get_server(server["id"]))


class OAuthResourceBindingTests(unittest.TestCase):
    def test_authorization_url_includes_resource(self) -> None:
        from mcp_host import oauth

        oauth._PENDING.clear()
        start = oauth.start_oauth_flow(
            server_id="srvA",
            endpoint_url="http://127.0.0.1:9/mcp",
            redirect_uri="http://127.0.0.1:8000/api/mcp/oauth/callback",
            client_id="client",
            allow_private=True,
            authorization_server_metadata={
                "issuer": "http://127.0.0.1:9",
                "authorization_endpoint": "http://127.0.0.1:9/authorize",
                "token_endpoint": "http://127.0.0.1:9/token",
                "code_challenge_methods_supported": ["S256"],
            },
            resource_metadata={
                "authorization_servers": ["http://127.0.0.1:9"],
                "resource": "http://127.0.0.1:9/mcp",
            },
        )
        self.assertTrue(start.get("ok"), start)
        parsed = urlparse(start["authorization_url"])
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("resource"), ["http://127.0.0.1:9/mcp"])
        self.assertEqual(qs.get("code_challenge_method"), ["S256"])
        pending = oauth.peek_oauth_pending(start["state"])
        self.assertEqual(pending["server_id"], "srvA")
        self.assertEqual(pending["resource"], "http://127.0.0.1:9/mcp")


class OAuthEndpointMismatchCleanupTests(unittest.TestCase):
    def test_endpoint_mismatch_discards_new_token_refs(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from mcp_host.manager import McpManager
        from mcp_host.secrets import secret_store
        from platform_db import PlatformDatabase

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = PlatformDatabase(str(Path(tmp.name) / "hades.db"))
        db.initialize()
        secret_store.enable_memory_backend_for_tests()
        manager = McpManager(
            db,
            settings_provider=lambda: {
                "mcp.enabled": True,
                "network_policy": "allow",
                "subprocess_policy": "allow",
            },
        )
        server = manager.create_server(
            {
                "name": "OAuthBind",
                "transport": "streamable_http",
                "endpoint_url": "http://127.0.0.1:9/mcp",
                "auth_method": "none",
                "env": {"plain": {}, "secrets": {}},
            }
        )
        access_ref = "mcp-oauth-test-access"
        refresh_ref = "mcp-oauth-test-refresh"
        secret_store.store(access_ref, "access-token-value")
        secret_store.store(refresh_ref, "refresh-token-value")
        with mock.patch(
            "mcp_host.manager.complete_oauth_flow",
            return_value={
                "ok": True,
                "server_id": server["id"],
                "auth_secret_ref": access_ref,
                "refresh_secret_ref": refresh_ref,
                "endpoint_url": "http://127.0.0.1:9/other-mcp",
                "ui_return_url": "https://evil.example/phish",
            },
        ):
            result = manager.complete_oauth(state="st", code="cd")
        self.assertFalse(result.get("ok"))
        self.assertIsNone(secret_store.get(access_ref))
        self.assertIsNone(secret_store.get(refresh_ref))
        refreshed = manager.get_server(server["id"])
        self.assertNotEqual(refreshed.get("auth_secret_ref"), access_ref)


if __name__ == "__main__":
    unittest.main()
