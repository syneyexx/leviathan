from __future__ import annotations

import socket
import unittest
from unittest import mock

import httpx

from mcp_host import oauth


def _public_dns(host: str, *_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class _RedirectClient:
    def __init__(self, location: str) -> None:
        self.location = location
        self.calls: list[str] = []

    def get(self, url: str, *, headers=None):
        self.calls.append(url)
        return httpx.Response(
            302,
            headers={"Location": self.location},
            request=httpx.Request("GET", url),
        )


class McpOAuthNetworkBoundaryTests(unittest.TestCase):
    def test_loopback_requires_explicit_local_context(self) -> None:
        self.assertIsNone(
            oauth._safe_fetch_url(
                "http://127.0.0.1:8765/.well-known/oauth-protected-resource",
                allow_private=False,
                purpose="test",
            )
        )
        self.assertEqual(
            oauth._safe_fetch_url(
                "http://127.0.0.1:8765/.well-known/oauth-protected-resource",
                allow_private=True,
                purpose="test",
            ),
            "http://127.0.0.1:8765/.well-known/oauth-protected-resource",
        )

    def test_private_flag_does_not_allow_lan_metadata_or_cgnat(self) -> None:
        for url in (
            "http://10.0.0.1/oauth",
            "https://192.168.1.10/oauth",
            "http://169.254.169.254/latest/meta-data",
            "https://100.64.0.1/oauth",
        ):
            with self.subTest(url=url):
                self.assertIsNone(oauth._safe_fetch_url(url, allow_private=True, purpose="test"))

    def test_public_oauth_requires_https(self) -> None:
        with mock.patch("url_security.socket.getaddrinfo", side_effect=_public_dns):
            self.assertIsNone(oauth._safe_fetch_url("http://example.com/oauth", allow_private=False, purpose="test"))
            self.assertEqual(
                oauth._safe_fetch_url("https://example.com/oauth", allow_private=False, purpose="test"),
                "https://example.com/oauth",
            )

    def test_public_metadata_redirect_cannot_reach_loopback(self) -> None:
        client = _RedirectClient("http://127.0.0.1:9999/private")
        findings: list[str] = []
        with mock.patch("url_security.socket.getaddrinfo", side_effect=_public_dns):
            result = oauth._get_json(
                client,  # type: ignore[arg-type]
                "https://example.com/.well-known/oauth-protected-resource",
                allow_private=False,
                purpose="test",
                findings=findings,
            )
        self.assertIsNone(result)
        self.assertEqual(client.calls, ["https://example.com/.well-known/oauth-protected-resource"])
        self.assertTrue(any("blocked" in row.lower() for row in findings))

    def test_supplied_as_metadata_is_revalidated(self) -> None:
        resource_metadata = {
            "authorization_servers": ["https://issuer.example"],
            "resource": "https://mcp.example/mcp",
        }
        bad_as = {
            "issuer": "https://issuer.example",
            "authorization_endpoint": "https://issuer.example/authorize",
            "token_endpoint": "http://169.254.169.254/token",
            "code_challenge_methods_supported": ["S256"],
        }
        with mock.patch("url_security.socket.getaddrinfo", side_effect=_public_dns):
            result = oauth.start_oauth_flow(
                server_id="srv-1",
                endpoint_url="https://mcp.example/mcp",
                redirect_uri="http://127.0.0.1:8000/api/mcp/oauth/callback",
                client_id="client-1",
                authorization_server_metadata=bad_as,
                resource_metadata=resource_metadata,
            )
        self.assertFalse(result.get("ok"))
        self.assertIn("token_endpoint", str(result.get("error") or ""))

    def test_redirect_uri_rejects_public_http_credentials_and_fragments(self) -> None:
        for uri in (
            "http://example.com/callback",
            "https://user:pass@example.com/callback",
            "https://example.com/callback#fragment",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                oauth.assert_redirect_uri_valid(uri)
        oauth.assert_redirect_uri_valid("http://127.0.0.1:8000/callback")
        oauth.assert_redirect_uri_valid("https://example.com/callback")


if __name__ == "__main__":
    unittest.main()
