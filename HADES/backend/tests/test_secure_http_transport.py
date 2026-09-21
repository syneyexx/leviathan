from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

import httpcore

from secure_http_transport import SafeSyncNetworkBackend, create_safe_http_client
from url_security import (
    UrlSecurityError,
    assert_public_http_url,
    resolve_safe_host_addresses,
    safe_public_url,
)


class _FakeStream(httpcore.NetworkStream):
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.tls_server_names: list[str | None] = []
        self._response = bytearray(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._response:
            return b""
        chunk = bytes(self._response[:max_bytes])
        del self._response[:max_bytes]
        return chunk

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.writes.append(bytes(buffer))

    def close(self) -> None:
        return None

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_server_names.append(server_hostname)
        return self

    def get_extra_info(self, info: str):
        if info == "is_readable":
            return False
        return None


class _FakeBackend(httpcore.NetworkBackend):
    def __init__(self, stream: _FakeStream | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.stream = stream or _FakeStream()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append({"host": host, "port": port})
        return self.stream

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("unexpected unix socket")

    def sleep(self, seconds):
        return None


def _addr(ip: str, port: int = 443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return (family, socket.SOCK_STREAM, 6, "", sockaddr)


class SafeResolutionTests(unittest.TestCase):
    def test_resolves_public_addresses_and_deduplicates(self):
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("93.184.216.34"), _addr("93.184.216.34")],
        ):
            self.assertEqual(
                resolve_safe_host_addresses("example.com", 443),
                ("93.184.216.34",),
            )

    def test_mixed_public_private_answers_fail_closed(self):
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("93.184.216.34"), _addr("127.0.0.1")],
        ):
            with self.assertRaises(UrlSecurityError):
                resolve_safe_host_addresses("example.com", 443)

    def test_azure_platform_metadata_ip_is_blocked(self):
        with self.assertRaises(UrlSecurityError):
            resolve_safe_host_addresses("168.63.129.16", 80)

    def test_loopback_mode_only_applies_to_explicit_loopback_host(self):
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("127.0.0.1", 8765)],
        ):
            with self.assertRaises(UrlSecurityError):
                resolve_safe_host_addresses(
                    "example.com",
                    8765,
                    allow_loopback=True,
                )

    def test_explicit_localhost_requires_only_loopback_answers(self):
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("127.0.0.1", 8765), _addr("10.0.0.8", 8765)],
        ):
            with self.assertRaises(UrlSecurityError):
                resolve_safe_host_addresses(
                    "localhost",
                    8765,
                    allow_loopback=True,
                )

    def test_ipv6_url_normalization_preserves_brackets(self):
        self.assertEqual(
            safe_public_url("https://[2606:4700:4700::1111]:8443/path?q=1"),
            "https://[2606:4700:4700::1111]:8443/path?q=1",
        )


class SafeNetworkBackendTests(unittest.TestCase):
    def test_dials_numeric_validated_address_not_hostname(self):
        fake = _FakeBackend()
        backend = SafeSyncNetworkBackend(fake)
        with patch(
            "secure_http_transport.resolve_safe_host_addresses",
            return_value=("93.184.216.34",),
        ):
            backend.connect_tcp("example.com", 443)
        self.assertEqual(fake.calls, [{"host": "93.184.216.34", "port": 443}])

    def test_rebinding_is_blocked_before_socket_dial(self):
        fake = _FakeBackend()
        backend = SafeSyncNetworkBackend(fake)

        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("93.184.216.34")],
        ):
            parsed = assert_public_http_url("https://example.com")
            self.assertEqual(parsed.hostname, "example.com")

        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("127.0.0.1")],
        ):
            with self.assertRaises(UrlSecurityError):
                backend.connect_tcp("example.com", 443)
        self.assertEqual(fake.calls, [])

    def test_loopback_mode_dials_explicit_localhost(self):
        fake = _FakeBackend()
        backend = SafeSyncNetworkBackend(fake, allow_loopback=True)
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("127.0.0.1", 8765)],
        ):
            backend.connect_tcp("localhost", 8765)
        self.assertEqual(fake.calls, [{"host": "127.0.0.1", "port": 8765}])

    def test_loopback_mode_does_not_allow_public_hostname_rebind(self):
        fake = _FakeBackend()
        backend = SafeSyncNetworkBackend(fake, allow_loopback=True)
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("127.0.0.1")],
        ):
            with self.assertRaises(UrlSecurityError):
                backend.connect_tcp("example.com", 443)
        self.assertEqual(fake.calls, [])

    def test_allow_private_is_explicit_and_connect_time_bound(self):
        fake = _FakeBackend()
        backend = SafeSyncNetworkBackend(fake, allow_private=True)
        with patch(
            "url_security.socket.getaddrinfo",
            return_value=[_addr("10.0.0.8", 8765)],
        ):
            backend.connect_tcp("dev.internal", 8765)
        self.assertEqual(fake.calls[0]["host"], "10.0.0.8")


class HTTPXIntegrationTests(unittest.TestCase):
    def test_http_preserves_original_host_header_while_dialing_ip(self):
        client = create_safe_http_client()
        pool = client._transport._pool
        safe_backend = pool._network_backend
        fake = _FakeBackend()
        safe_backend._backend = fake
        try:
            with patch(
                "secure_http_transport.resolve_safe_host_addresses",
                return_value=("93.184.216.34",),
            ):
                response = client.get("http://example.com/path")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(fake.calls[0]["host"], "93.184.216.34")
            wire = b"".join(fake.stream.writes)
            self.assertIn(b"Host: example.com\r\n", wire)
        finally:
            client.close()

    def test_https_preserves_original_sni_while_dialing_ip(self):
        client = create_safe_http_client()
        pool = client._transport._pool
        safe_backend = pool._network_backend
        fake = _FakeBackend()
        safe_backend._backend = fake
        try:
            with patch(
                "secure_http_transport.resolve_safe_host_addresses",
                return_value=("93.184.216.34",),
            ):
                response = client.get("https://example.com/path")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(fake.calls[0]["host"], "93.184.216.34")
            self.assertEqual(fake.stream.tls_server_names, ["example.com"])
            wire = b"".join(fake.stream.writes)
            self.assertIn(b"Host: example.com\r\n", wire)
        finally:
            client.close()

    def test_safe_client_uses_guarded_direct_connection_pool(self):
        client = create_safe_http_client()
        try:
            self.assertIsInstance(client._transport._pool, httpcore.ConnectionPool)
            self.assertIsInstance(
                client._transport._pool._network_backend,
                SafeSyncNetworkBackend,
            )
        finally:
            client.close()

    def test_safe_client_rejects_ambiguous_private_policy(self):
        with self.assertRaises(ValueError):
            create_safe_http_client(allow_private=True, allow_loopback=True)


if __name__ == "__main__":
    unittest.main()
