"""Host liveness + launcher Origin CORS contracts."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.host_console import build_host_console_router
from Data.modules.host_console.launcher_cors import (
    LAUNCHER_ALLOWED_ORIGINS,
    LAUNCHER_READ_PATHS,
    LauncherReadCorsMiddleware,
    origin_is_allowed,
)
from Data.modules.host_console.liveness import build_host_liveness


class HostLivenessUnitTests(unittest.TestCase):
    def test_host_liveness_is_tiny_and_true(self) -> None:
        payload = build_host_liveness(version="test-1.0", bootstrapped=True)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["liveness"], "alive")
        self.assertTrue(payload["bootstrapped"])
        self.assertTrue(payload["started"])
        self.assertEqual(payload["version"], "test-1.0")
        # Keep the surface intentionally tiny.
        self.assertLessEqual(len(payload.keys()), 8)
        self.assertNotIn("models", payload)
        self.assertNotIn("knowledge", payload)
        self.assertNotIn("product_truth", payload)
        self.assertNotIn("llm", payload)

    def test_host_liveness_does_not_call_llm(self) -> None:
        # Builder has no LLM dependency; constructing it must not touch providers.
        payload = build_host_liveness(version="x")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["truth"]["noSubsystemAggregation"])

    def test_host_liveness_does_not_query_knowledge(self) -> None:
        payload = build_host_liveness()
        self.assertNotIn("documents", payload)
        self.assertNotIn("knowledge", payload)

    def test_host_liveness_does_not_build_product_truth(self) -> None:
        payload = build_host_liveness()
        self.assertNotIn("product_truth", payload)
        self.assertTrue(payload["truth"]["notProductTruth"])

    def test_host_liveness_does_not_probe_external_provider(self) -> None:
        payload = build_host_liveness()
        self.assertTrue(payload["truth"]["processLivenessOnly"])


class HostLivenessRouteTests(unittest.TestCase):
    def test_host_liveness_after_lifespan_ready(self) -> None:
        app = FastAPI()
        app.include_router(
            build_host_console_router(
                settings=MagicMock(),
                job_runtime=MagicMock(),
                observability=MagicMock(),
                sqlite_manager=MagicMock(),
                version="route-ver",
            )
        )
        with TestClient(app) as client:
            response = client.get("/api/host/liveness")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["liveness"], "alive")
        self.assertEqual(body["version"], "route-ver")


class LauncherCorsTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.add_middleware(LauncherReadCorsMiddleware)

        @app.get("/api/host/liveness")
        def liveness() -> dict:
            return build_host_liveness(version="cors")

        @app.get("/api/workers/dashboard")
        def dashboard() -> dict:
            return {"supervisor": {"health": "RUNNING"}}

        @app.get("/api/events/stream")
        def events() -> dict:
            return {"ok": True}

        @app.post("/api/approvals/decide")
        def mutate() -> dict:
            return {"ok": True}

        @app.get("/api/secret-internal")
        def secret() -> dict:
            return {"secret": True}

        self.client = TestClient(app)

    def test_launcher_origin_allowed_for_read_projection(self) -> None:
        for origin in (
            "http://tauri.localhost",
            "https://tauri.localhost",
            "tauri://localhost",
            "http://127.0.0.1:1420",
        ):
            with self.subTest(origin=origin):
                response = self.client.get(
                    "/api/host/liveness",
                    headers={"Origin": origin},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("access-control-allow-origin"), origin)
                self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_unapproved_origin_not_granted_cors(self) -> None:
        response = self.client.get(
            "/api/host/liveness",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_cors_does_not_grant_mutation_surface(self) -> None:
        origin = "http://tauri.localhost"
        # OPTIONS on mutation path must not be granted even with launcher origin.
        options = self.client.options(
            "/api/approvals/decide",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertNotEqual(options.headers.get("access-control-allow-origin"), origin)

        post = self.client.post(
            "/api/approvals/decide",
            headers={"Origin": origin},
        )
        self.assertEqual(post.status_code, 200)
        self.assertIsNone(post.headers.get("access-control-allow-origin"))

        # Non-allowlisted GET must not receive CORS.
        secret = self.client.get(
            "/api/secret-internal",
            headers={"Origin": origin},
        )
        self.assertIsNone(secret.headers.get("access-control-allow-origin"))

    def test_events_stream_launcher_origin(self) -> None:
        origin = "http://127.0.0.1:1420"
        response = self.client.get(
            "/api/events/stream",
            headers={"Origin": origin},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_options_preflight_for_read_path(self) -> None:
        origin = "http://tauri.localhost"
        response = self.client.options(
            "/api/workers/dashboard",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)
        methods = response.headers.get("access-control-allow-methods", "")
        self.assertIn("GET", methods)
        self.assertNotIn("POST", methods)

    def test_allowlists_are_exact(self) -> None:
        self.assertFalse(origin_is_allowed("*"))
        self.assertFalse(origin_is_allowed("http://127.0.0.1:9999"))
        self.assertIn("/api/host/liveness", LAUNCHER_READ_PATHS)
        self.assertTrue(all(not o.endswith("*") for o in LAUNCHER_ALLOWED_ORIGINS))


class HostOverviewContractRegression(unittest.TestCase):
    def test_host_overview_three_databases_shape(self) -> None:
        from Data.modules.host_console.read_model import build_host_overview

        class _Runtime:
            host = "127.0.0.1"
            port = 8765
            loopback_only = True

        class _Settings:
            def __init__(self, root: Path) -> None:
                self.runtime = _Runtime()
                self.database_path = root / "control.db"
                self.knowledge_database_path = root / "knowledge.db"
                self.control_database_path = self.database_path

        class _Manager:
            def list_databases(self) -> list[dict]:
                return [
                    {"domain": "CONTROL", "health": "OK", "readiness": "READY", "tableCount": 2},
                    {"domain": "KNOWLEDGE", "health": "OK", "readiness": "READY", "tableCount": 3},
                    {"domain": "MARKET", "health": "OK", "readiness": "READY", "tableCount": 1},
                ]

        with TemporaryDirectory() as tmp:
            settings = _Settings(Path(tmp))
            overview = build_host_overview(
                settings=settings,
                sqlite_manager=_Manager(),
                job_runtime=MagicMock(get=lambda *_: None),
                probe_fn=lambda: {
                    "status": "BUILD_MISSING",
                    "protocol_version": None,
                    "operations": [],
                    "binary_path": None,
                    "detail": "missing",
                },
                version="t",
            )
        domains = {row["domain"] for row in overview["databases"]}
        self.assertEqual(domains, {"CONTROL", "KNOWLEDGE", "MARKET"})


if __name__ == "__main__":
    unittest.main()
