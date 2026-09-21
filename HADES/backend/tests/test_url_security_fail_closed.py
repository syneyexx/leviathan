from __future__ import annotations

import socket
import unittest
from unittest import mock

from url_security import UrlSecurityError, assert_public_http_url, is_private_or_local_host, safe_public_url


def _dns(*addresses: str):
    rows = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        rows.append((family, socket.SOCK_STREAM, 6, "", (address, 443)))
    return rows


class SharedUrlSecurityFailClosedTests(unittest.TestCase):
    def test_unresolvable_host_is_blocked(self) -> None:
        with mock.patch("url_security.socket.getaddrinfo", side_effect=socket.gaierror("dns down")):
            self.assertTrue(is_private_or_local_host("example.invalid"))
            with self.assertRaises(UrlSecurityError):
                assert_public_http_url("https://example.invalid/path")
            self.assertIsNone(safe_public_url("https://example.invalid/path"))

    def test_mixed_public_and_private_dns_answers_are_blocked(self) -> None:
        with mock.patch(
            "url_security.socket.getaddrinfo",
            return_value=_dns("93.184.216.34", "10.0.0.4"),
        ):
            with self.assertRaises(UrlSecurityError):
                assert_public_http_url("https://mixed.example/")

    def test_all_public_dns_answers_are_allowed(self) -> None:
        with mock.patch(
            "url_security.socket.getaddrinfo",
            return_value=_dns("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
        ):
            parsed = assert_public_http_url("https://example.com/path")
        self.assertEqual(parsed.hostname, "example.com")

    def test_cgnat_shared_space_is_not_considered_public(self) -> None:
        self.assertTrue(is_private_or_local_host("100.64.0.1"))
        with self.assertRaises(UrlSecurityError):
            assert_public_http_url("http://100.64.0.1/")

    def test_documentation_and_unspecified_ranges_are_blocked(self) -> None:
        for address in ("192.0.2.10", "198.51.100.7", "203.0.113.9", "0.0.0.0", "::"):
            with self.subTest(address=address):
                self.assertTrue(is_private_or_local_host(address))

    def test_invalid_port_is_rejected_before_downstream_client(self) -> None:
        with mock.patch("url_security.socket.getaddrinfo", return_value=_dns("93.184.216.34")):
            with self.assertRaises(UrlSecurityError):
                assert_public_http_url("https://example.com:99999/")

    def test_allow_private_explicitly_preserves_local_provider_use_case(self) -> None:
        parsed = assert_public_http_url(
            "http://127.0.0.1:1234/v1",
            allow_private=True,
            purpose="explicit_local_test",
        )
        self.assertEqual(parsed.hostname, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
