from __future__ import annotations

import socket
import unittest
from unittest import mock

import httpx

from mcp_host.clients import HttpMcpClient, McpClientError


def _public_dns(host: str, *_args, **_kwargs):
    # A deterministic globally-routable test address; no real network is used.
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class _RedirectingClient:
    def __init__(self, location: str) -> None:
        self.location = location
        self.builds: list[tuple[str, dict[str, str]]] = []

    def build_request(self, method: str, url: str, *, headers, content):
        self.builds.append((url, dict(headers)))
        return httpx.Request(method, url, headers=headers, content=content)

    def send(self, request: httpx.Request, *, stream: bool = False):
        return httpx.Response(302, headers={"Location": self.location}, request=request)


class McpRedirectSecurityTests(unittest.TestCase):
    def test_private_mode_is_loopback_only(self) -> None:
        for url in (
            "http://10.0.0.8:8000/mcp",
            "http://192.168.1.9:8000/mcp",
            "http://169.254.169.254/latest/meta-data",
            "http://100.64.0.1/mcp",
        ):
            with self.subTest(url=url):
                with self.assertRaises(McpClientError):
                    HttpMcpClient(url, allow_private=True)

    def test_loopback_requires_explicit_permission(self) -> None:
        with self.assertRaises(McpClientError):
            HttpMcpClient("http://127.0.0.1:8765/mcp", allow_private=False)
        client = HttpMcpClient("http://127.0.0.1:8765/mcp", allow_private=True)
        try:
            self.assertEqual(client.endpoint_url, "http://127.0.0.1:8765/mcp")
        finally:
            client.close()

    def test_same_origin_redirect_is_allowed(self) -> None:
        with mock.patch("url_security.socket.getaddrinfo", side_effect=_public_dns):
            client = HttpMcpClient("https://example.com/mcp")
            try:
                target = client._validated_redirect_target("https://example.com/mcp", "/mcp/v2")
            finally:
                client.close()
        self.assertEqual(target, "https://example.com/mcp/v2")

    def test_cross_origin_redirect_is_blocked(self) -> None:
        with mock.patch("url_security.socket.getaddrinfo", side_effect=_public_dns):
            client = HttpMcpClient("https://example.com/mcp")
            try:
                for location in (
                    "https://attacker.example/mcp",
                    "http://example.com/mcp",
                    "https://example.com:444/mcp",
                ):
                    with self.subTest(location=location), self.assertRaises(McpClientError) as caught:
                        client._validated_redirect_target("https://example.com/mcp", location)
                    self.assertEqual(caught.exception.kind, "auth")
            finally:
                client.close()

    def test_loopback_redirect_cannot_expand_to_metadata_or_lan(self) -> None:
        client = HttpMcpClient("http://127.0.0.1:8765/mcp", allow_private=True)
        try:
            for location in (
                "http://169.254.169.254/latest/meta-data",
                "http://10.0.0.10/admin",
                "http://192.168.1.1/",
            ):
                with self.subTest(location=location), self.assertRaises(McpClientError):
                    client._validated_redirect_target(client.endpoint_url, location)
        finally:
            client.close()

    def test_bearer_header_is_never_forwarded_to_cross_origin_redirect(self) -> None:
        with mock.patch("url_security.socket.getaddrinfo", side_effect=_public_dns):
            client = HttpMcpClient("https://example.com/mcp", bearer_token="top-secret-token")
            original_http = client._client
            original_http.close()
            fake = _RedirectingClient("https://attacker.example/mcp")
            client._client = fake  # type: ignore[assignment]
            with self.assertRaises(McpClientError) as caught:
                client._post_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "server/discover"})
        self.assertEqual(caught.exception.kind, "auth")
        self.assertEqual(len(fake.builds), 1, "redirect target must never receive a second request")
        self.assertEqual(fake.builds[0][0], "https://example.com/mcp")
        self.assertEqual(fake.builds[0][1].get("Authorization"), "Bearer top-secret-token")


if __name__ == "__main__":
    unittest.main()
