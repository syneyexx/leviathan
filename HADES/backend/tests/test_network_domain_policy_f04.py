"""T4/F-04: network domain allowlist/denylist and redirect_limit are enforced."""

from __future__ import annotations

import socket
import unittest
from unittest import mock

from url_security import (
    UrlSecurityError,
    assert_domain_policy,
    assert_public_http_url,
    host_matches_domain_rule,
    safe_public_url,
)


def _dns(*addresses: str):
    rows = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        rows.append((family, socket.SOCK_STREAM, 6, "", (address, 443)))
    return rows


class DomainPolicyUnitTests(unittest.TestCase):
    def test_host_matches_exact_and_suffix(self) -> None:
        self.assertTrue(host_matches_domain_rule("example.com", "example.com"))
        self.assertTrue(host_matches_domain_rule("www.example.com", "example.com"))
        self.assertTrue(host_matches_domain_rule("a.b.example.com", "*.example.com"))
        self.assertFalse(host_matches_domain_rule("evil.com", "example.com"))
        self.assertFalse(host_matches_domain_rule("example.com.evil", "example.com"))

    def test_allowlist_rejects_other_domains(self) -> None:
        assert_domain_policy("allowed.example", allowlist=["allowed.example"], denylist=[])
        with self.assertRaises(UrlSecurityError):
            assert_domain_policy("other.example", allowlist=["allowed.example"], denylist=[])

    def test_denylist_blocks_even_when_allowlisted(self) -> None:
        with self.assertRaises(UrlSecurityError):
            assert_domain_policy(
                "bad.example",
                allowlist=["bad.example", "good.example"],
                denylist=["bad.example"],
            )


class DomainPolicyIntegrationTests(unittest.TestCase):
    def test_assert_public_http_url_honors_explicit_allowlist(self) -> None:
        with mock.patch(
            "url_security.socket.getaddrinfo",
            return_value=_dns("93.184.216.34"),
        ):
            assert_public_http_url(
                "https://allowed.example/path",
                domain_allowlist=["allowed.example"],
                apply_settings_domain_policy=False,
            )
            with self.assertRaises(UrlSecurityError) as ctx:
                assert_public_http_url(
                    "https://blocked.example/path",
                    domain_allowlist=["allowed.example"],
                    apply_settings_domain_policy=False,
                )
        self.assertIn("allowlist", str(ctx.exception).lower())

    def test_assert_public_http_url_honors_denylist(self) -> None:
        with mock.patch(
            "url_security.socket.getaddrinfo",
            return_value=_dns("93.184.216.34"),
        ):
            with self.assertRaises(UrlSecurityError) as ctx:
                assert_public_http_url(
                    "https://evil.example/x",
                    domain_denylist=["evil.example"],
                    apply_settings_domain_policy=False,
                )
        self.assertIn("denylist", str(ctx.exception).lower())

    def test_safe_public_url_returns_none_outside_allowlist(self) -> None:
        with mock.patch(
            "url_security.socket.getaddrinfo",
            return_value=_dns("93.184.216.34"),
        ):
            self.assertIsNone(
                safe_public_url(
                    "https://other.example/",
                    domain_allowlist=["only.example"],
                    apply_settings_domain_policy=False,
                )
            )

    def test_settings_policy_loaded_via_resolve_setting(self) -> None:
        def fake_resolve(setting_id: str, context=None, default=None):
            if setting_id == "network.domain_allowlist":
                return ["allowed.example"]
            if setting_id == "network.domain_denylist":
                return ["evil.example"]
            if setting_id == "network.redirect_limit":
                return 2
            return default

        with mock.patch("control.service.resolve_setting", side_effect=fake_resolve):
            with mock.patch(
                "url_security.socket.getaddrinfo",
                return_value=_dns("93.184.216.34"),
            ):
                assert_public_http_url("https://allowed.example/")
                with self.assertRaises(UrlSecurityError):
                    assert_public_http_url("https://other.example/")
                with self.assertRaises(UrlSecurityError):
                    assert_public_http_url("https://evil.example/")


class RedirectLimitTests(unittest.TestCase):
    def test_web_research_respects_redirect_limit(self) -> None:
        import asyncio
        from pathlib import Path
        import tempfile

        from database import Database
        from platform_db import PlatformDatabase
        from platform_services_core import KnowledgeService
        from web_research_service import WebResearchService

        class FakeResponse:
            def __init__(self, status_code: int, location: str | None = None):
                self.status_code = status_code
                self.headers = {"location": location} if location else {}
                self.text = "<html></html>"
                self.url = "https://allowed.example/"

            def raise_for_status(self) -> None:
                return None

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url: str):
                self.calls += 1
                if self.calls <= 3:
                    return FakeResponse(302, location="https://allowed.example/next")
                return FakeResponse(200)

        temp = tempfile.TemporaryDirectory()
        try:
            db = Database(str(Path(temp.name) / "core.db"))
            db.initialize()
            pdb = PlatformDatabase(str(Path(temp.name) / "core.db"))
            pdb.initialize()
            knowledge = KnowledgeService(pdb, Path(temp.name))
            web = WebResearchService(knowledge)

            with mock.patch(
                "url_security.load_network_domain_policy",
                return_value=(["allowed.example"], [], 1),
            ), mock.patch(
                "url_security.socket.getaddrinfo",
                return_value=_dns("93.184.216.34"),
            ), mock.patch("web_research_service.httpx.AsyncClient", FakeClient), mock.patch.object(
                web, "allowed_by_robots", return_value=True
            ):
                with self.assertRaises(PermissionError) as ctx:
                    asyncio.run(web._get("https://allowed.example/", respect_robots=True))
                self.assertIn("redirect limit", str(ctx.exception).lower())
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
