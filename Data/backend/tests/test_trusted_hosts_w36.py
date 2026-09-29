"""WAVE 36 — Host-header TrustedHost allowlist (fail-closed non-loopback)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from Data.modules.common.http_auth import (
    LOOPBACK_TRUSTED_HOSTS,
    TESTCLIENT_HOST,
    TRUSTED_HOSTS_ENV,
    host_header_allowed,
    parse_trusted_hosts,
    resolve_trusted_hosts,
    validate_non_loopback_security_posture,
)
from Data.modules.host_console.launcher_cors import LAUNCHER_ALLOWED_ORIGINS


class TrustedHostsUnitTests(unittest.TestCase):
    def test_loopback_defaults_include_local_launcher(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(TRUSTED_HOSTS_ENV, None)
            hosts = resolve_trusted_hosts(loopback_only=True, bind_host="127.0.0.1")
        for expected in LOOPBACK_TRUSTED_HOSTS:
            self.assertIn(expected, hosts)
        self.assertIn(TESTCLIENT_HOST, hosts)
        self.assertNotIn("*", hosts)

    def test_non_loopback_requires_explicit_allowlist(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(TRUSTED_HOSTS_ENV, None)
            with self.assertRaises(RuntimeError) as ctx:
                resolve_trusted_hosts(loopback_only=False, bind_host="0.0.0.0")
        self.assertIn(TRUSTED_HOSTS_ENV, str(ctx.exception))

    def test_non_loopback_uses_configured_hosts_and_bind(self) -> None:
        with patch.dict(os.environ, {TRUSTED_HOSTS_ENV: "api.internal,ops.internal"}, clear=False):
            hosts = resolve_trusted_hosts(loopback_only=False, bind_host="10.0.0.5")
        self.assertEqual(hosts[0], "api.internal")
        self.assertIn("ops.internal", hosts)
        self.assertIn("10.0.0.5", hosts)
        self.assertNotIn("*", hosts)
        self.assertNotIn(TESTCLIENT_HOST, hosts)

    def test_wildcard_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_trusted_hosts("*")
        with self.assertRaises(RuntimeError):
            parse_trusted_hosts("*.example.com")

    def test_host_header_match_strips_port(self) -> None:
        allowed = ["127.0.0.1", "api.internal"]
        self.assertTrue(host_header_allowed("127.0.0.1:8765", allowed_hosts=allowed))
        self.assertTrue(host_header_allowed("api.internal", allowed_hosts=allowed))
        self.assertFalse(host_header_allowed("evil.example", allowed_hosts=allowed))
        self.assertFalse(host_header_allowed(None, allowed_hosts=allowed))

    def test_validate_non_loopback_requires_token_and_hosts(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEVIATHAN_OPERATOR_TOKEN", None)
            os.environ.pop(TRUSTED_HOSTS_ENV, None)
            with self.assertRaises(RuntimeError):
                validate_non_loopback_security_posture(
                    loopback_only=False, bind_host="0.0.0.0"
                )
        with patch.dict(
            os.environ,
            {"LEVIATHAN_OPERATOR_TOKEN": "tok", TRUSTED_HOSTS_ENV: "edge.local"},
            clear=False,
        ):
            validate_non_loopback_security_posture(
                loopback_only=False, bind_host="edge.local"
            )

    def test_cors_origins_have_no_wildcard(self) -> None:
        self.assertTrue(LAUNCHER_ALLOWED_ORIGINS)
        self.assertTrue(all("*" not in origin for origin in LAUNCHER_ALLOWED_ORIGINS))


class TrustedHostMiddlewareIntegrationTests(unittest.TestCase):
    def test_invalid_host_rejected(self) -> None:
        app = FastAPI()
        hosts = resolve_trusted_hosts(loopback_only=True, bind_host="127.0.0.1")
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)

        @app.get("/api/host/liveness")
        def liveness() -> dict:
            return {"ok": True}

        client = TestClient(app, base_url="http://127.0.0.1")
        ok = client.get("/api/host/liveness", headers={"Host": "127.0.0.1"})
        self.assertEqual(ok.status_code, 200)

        bad = client.get("/api/host/liveness", headers={"Host": "evil.example"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Invalid host", bad.text)

    def test_app_registers_trusted_host_middleware(self) -> None:
        from Data.backend.main import app

        classes = []
        for m in app.user_middleware:
            cls = getattr(m, "cls", None)
            if cls is not None:
                classes.append(getattr(cls, "__name__", str(cls)))
        self.assertIn("TrustedHostMiddleware", classes)


if __name__ == "__main__":
    unittest.main()
