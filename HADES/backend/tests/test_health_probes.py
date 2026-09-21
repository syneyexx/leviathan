from __future__ import annotations

import unittest
from unittest import mock

from health_probes import ProbeTTLCache


class HealthProbeCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_cached_errors_not_retained(self) -> None:
        cache = ProbeTTLCache(success_ttl=60.0)
        calls = {"n": 0}

        async def probe_ok() -> str:
            calls["n"] += 1
            return "ok"

        value, hit = await cache.get_or_probe("k", probe_ok, healthy=lambda v: v == "ok")
        self.assertEqual(value, "ok")
        self.assertFalse(hit)
        value2, hit2 = await cache.get_or_probe("k", probe_ok, healthy=lambda v: v == "ok")
        self.assertEqual(value2, "ok")
        self.assertTrue(hit2)
        self.assertEqual(calls["n"], 1)

        async def probe_fail() -> str:
            calls["n"] += 1
            return "down"

        value3, hit3 = await cache.get_or_probe("k2", probe_fail, healthy=lambda v: v == "ok")
        self.assertEqual(value3, "down")
        self.assertFalse(hit3)
        value4, hit4 = await cache.get_or_probe("k2", probe_fail, healthy=lambda v: v == "ok")
        self.assertEqual(value4, "down")
        self.assertFalse(hit4)
        self.assertEqual(calls["n"], 3)

    async def test_health_live_route_is_cheap(self) -> None:
        import main

        client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(main.app)
        with mock.patch.object(main, "discover_models", side_effect=AssertionError("lm probe")):
            live = client.get("/api/health/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json().get("backend"), "ok")


if __name__ == "__main__":
    unittest.main()
