from __future__ import annotations

import unittest
from typing import Any

try:
    import pytest
except ImportError:  # pragma: no cover - exercised under unittest discovery without pytest
    pytest = None  # type: ignore[assignment]

from mcp_host import clients as mcp_clients
from mcp_host import oauth as mcp_oauth


class _DummyHttpClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def delete(self, *args: Any, **kwargs: Any) -> None:
        return None


@unittest.skipUnless(pytest is not None, "pytest required for MCP secure egress fixtures")
class McpSecureEgressRequiresPytest(unittest.TestCase):
    def test_pytest_available_for_secure_egress_module(self) -> None:
        self.assertIsNotNone(pytest)


if pytest is not None:

    @pytest.fixture
    def no_legacy_network_client(monkeypatch: pytest.MonkeyPatch) -> list[_DummyHttpClient]:
        created: list[_DummyHttpClient] = []

        def _make_client(*args: Any, **kwargs: Any) -> _DummyHttpClient:
            client = _DummyHttpClient()
            created.append(client)
            return client

        monkeypatch.setattr(mcp_clients._legacy.httpx, "Client", _make_client)
        return created

    def test_public_mcp_client_replaces_legacy_client_with_safe_transport(
        monkeypatch: pytest.MonkeyPatch,
        no_legacy_network_client: list[_DummyHttpClient],
    ) -> None:
        safe_calls: list[dict[str, Any]] = []
        secure_client = _DummyHttpClient()

        monkeypatch.setattr(mcp_clients, "assert_public_http_url", lambda *args, **kwargs: None)

        def _safe_factory(**kwargs: Any) -> _DummyHttpClient:
            safe_calls.append(kwargs)
            return secure_client

        monkeypatch.setattr(mcp_clients, "create_safe_http_client", _safe_factory)

        client = mcp_clients.HttpMcpClient("https://example.com/mcp", timeout=17.0)

        assert client._client is secure_client
        assert safe_calls == [
            {
                "timeout": 17.0,
                "follow_redirects": False,
                "allow_loopback": False,
            }
        ]
        assert len(no_legacy_network_client) == 1
        assert no_legacy_network_client[0].closed is True

    def test_local_mcp_client_uses_narrow_loopback_transport(
        monkeypatch: pytest.MonkeyPatch,
        no_legacy_network_client: list[_DummyHttpClient],
    ) -> None:
        safe_calls: list[dict[str, Any]] = []
        secure_client = _DummyHttpClient()

        monkeypatch.setattr(mcp_clients, "assert_public_http_url", lambda *args, **kwargs: None)

        def _safe_factory(**kwargs: Any) -> _DummyHttpClient:
            safe_calls.append(kwargs)
            return secure_client

        monkeypatch.setattr(mcp_clients, "create_safe_http_client", _safe_factory)

        client = mcp_clients.HttpMcpClient(
            "http://127.0.0.1:8765/mcp",
            timeout=3.0,
            allow_private=True,
        )

        assert client._client is secure_client
        assert safe_calls[-1]["allow_loopback"] is True
        assert "allow_private" not in safe_calls[-1]

    def test_local_relative_redirect_is_revalidated_after_join(
        monkeypatch: pytest.MonkeyPatch,
        no_legacy_network_client: list[_DummyHttpClient],
    ) -> None:
        monkeypatch.setattr(mcp_clients, "assert_public_http_url", lambda *args, **kwargs: None)
        monkeypatch.setattr(mcp_clients, "create_safe_http_client", lambda **kwargs: _DummyHttpClient())

        client = mcp_clients.HttpMcpClient(
            "http://127.0.0.1:8765/mcp",
            allow_private=True,
        )
        target = client._validated_redirect_target("http://127.0.0.1:8765/mcp", "/next")

        assert target == "http://127.0.0.1:8765/next"

    def test_local_cross_origin_redirect_remains_blocked(
        monkeypatch: pytest.MonkeyPatch,
        no_legacy_network_client: list[_DummyHttpClient],
    ) -> None:
        monkeypatch.setattr(mcp_clients, "assert_public_http_url", lambda *args, **kwargs: None)
        monkeypatch.setattr(mcp_clients, "create_safe_http_client", lambda **kwargs: _DummyHttpClient())

        client = mcp_clients.HttpMcpClient(
            "http://127.0.0.1:8765/mcp",
            allow_private=True,
        )

        with pytest.raises(mcp_clients.McpClientError, match="Cross-origin MCP redirect"):
            client._validated_redirect_target(
                "http://127.0.0.1:8765/mcp",
                "http://127.0.0.1:9999/next",
            )

    def test_oauth_httpx_facade_routes_clients_through_safe_factory(monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []
        sentinel = _DummyHttpClient()

        def _safe_factory(**kwargs: Any) -> _DummyHttpClient:
            calls.append(kwargs)
            return sentinel

        monkeypatch.setattr(mcp_oauth, "create_safe_http_client", _safe_factory)

        client = mcp_oauth._legacy.httpx.Client(timeout=9.0, follow_redirects=False)

        assert client is sentinel
        assert calls == [
            {
                "allow_loopback": True,
                "timeout": 9.0,
                "follow_redirects": False,
            }
        ]

    def test_oauth_httpx_facade_fails_closed_for_custom_transport() -> None:
        with pytest.raises(ValueError, match="Custom OAuth HTTP transports"):
            mcp_oauth._legacy.httpx.Client(transport=object())
