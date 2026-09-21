"""Model discovery TTL/request cache used by Chat resolve_model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_discovery
import perf


class ModelDiscoveryCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        model_discovery.cache.clear()
        model_discovery.begin_request_discovery()
        perf.reset()

    async def asyncTearDown(self) -> None:
        model_discovery.end_request_discovery()
        model_discovery.cache.clear()

    async def test_ttl_and_request_scope_avoid_duplicate_upstream(self) -> None:
        calls = {"n": 0}

        async def fetch():
            calls["n"] += 1
            return [{"id": "local-a"}], 12.0

        first, lat, hit, up = await model_discovery.cache.get("http://lm", fetch, ttl_s=60)
        self.assertFalse(hit)
        self.assertTrue(up)
        self.assertEqual(first[0]["id"], "local-a")
        second, _, hit2, up2 = await model_discovery.cache.get("http://lm", fetch, ttl_s=60)
        self.assertTrue(hit2)
        self.assertFalse(up2)
        self.assertEqual(calls["n"], 1)
        snap = perf.snapshot()["discovery"]
        self.assertEqual(snap["upstream"], 1)
        self.assertGreaterEqual(snap["hits"], 1)

    async def test_empty_result_is_not_sticky_success(self) -> None:
        calls = {"n": 0}

        async def fetch():
            calls["n"] += 1
            return [], 3.0

        await model_discovery.cache.get("http://lm", fetch, ttl_s=60)
        await model_discovery.cache.get("http://lm", fetch, ttl_s=60)
        self.assertEqual(calls["n"], 2)

    async def test_force_bypasses_ttl(self) -> None:
        calls = {"n": 0}

        async def fetch():
            calls["n"] += 1
            return [{"id": "m"}], 1.0

        await model_discovery.cache.get("http://lm", fetch, ttl_s=60)
        await model_discovery.cache.get("http://lm", fetch, ttl_s=60, force=True)
        self.assertEqual(calls["n"], 2)

    def test_resolve_model_attaches_discovered_list(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("_discovered_models", source)
        self.assertIn("model_discovery_cache.get", source)


if __name__ == "__main__":
    unittest.main()
