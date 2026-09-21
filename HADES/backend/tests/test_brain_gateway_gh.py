"""Brain layout, relations, counts, and model-gateway capacity tests (work packages G/H)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from coding_agent import _invoke_chat_fn
from database import Database
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService, WebResearchService
from reasoning.model_gateway import ModelCapacityTimeout, ModelGateway, model_gateway
from reasoning.model_router import ModelRouter


class BrainLayoutAndRelationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db_path = root / "core.db"
        main.database = Database(str(db_path))
        main.database.initialize()
        main.runner = main.TaskRunner()
        main.platform_db = PlatformDatabase(str(root / "platform.db"))
        main.ensure_platform_services()
        main.platform_db.initialize()
        main.knowledge = KnowledgeService(main.platform_db, root)
        main.web_research = WebResearchService(main.knowledge)
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_layout_persist_by_stable_entity_id_keeps_older_positions(self) -> None:
        first = main.database.upsert_brain_layout_position("memory_abc", pos_x=10, pos_y=20, view_id="default")
        self.assertEqual(first["pos_x"], 10)
        main.database.upsert_brain_layout_position("knowledge_xyz", pos_x=100, pos_y=200, view_id="default")
        main.database.upsert_brain_layout_position("memory_abc", pos_x=15, pos_y=25, pinned=True, view_id="default")
        layout = main.database.list_brain_layout("default")
        by_id = {row["entity_id"]: row for row in layout["positions"]}
        self.assertEqual(by_id["memory_abc"]["pos_x"], 15)
        self.assertTrue(by_id["memory_abc"]["pinned"])
        self.assertEqual(by_id["knowledge_xyz"]["pos_x"], 100)

    def test_derived_node_layout_update_via_api(self) -> None:
        memory = self.client.post(
            "/api/memories",
            json={"title": "Layout mem", "content": "body", "collection": "Tests", "tags": []},
        ).json()
        node_id = f"memory_{memory['id']}"
        updated = self.client.put(
            f"/api/brain/nodes/{node_id}",
            json={"pos_x": 321, "pos_y": 654},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json().get("layout_only"))
        layout = self.client.get("/api/brain/layout").json()
        match = next(row for row in layout["positions"] if row["entity_id"] == node_id)
        self.assertEqual(match["pos_x"], 321)
        # Content edit on derived node must fail.
        blocked = self.client.put(
            f"/api/brain/nodes/{node_id}",
            json={"label": "nope"},
        )
        self.assertEqual(blocked.status_code, 400)

    def test_relation_requires_distinct_targets_and_rejects_duplicates(self) -> None:
        a = self.client.post(
            "/api/brain/nodes",
            json={"label": "A", "kind": "note", "description": "a", "tags": []},
        ).json()
        b = self.client.post(
            "/api/brain/nodes",
            json={"label": "B", "kind": "note", "description": "b", "tags": []},
        ).json()
        self_link = self.client.post("/api/brain/links", json={"source_id": a["id"], "target_id": a["id"], "relation": "x"})
        self.assertEqual(self_link.status_code, 400)
        created = self.client.post(
            "/api/brain/links",
            json={"source_id": a["id"], "target_id": b["id"], "relation": "gerelateerd aan"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json().get("provenance"), "user_explicit")
        dup = self.client.post(
            "/api/brain/links",
            json={"source_id": a["id"], "target_id": b["id"], "relation": "andere"},
        )
        self.assertEqual(dup.status_code, 400)
        updated = self.client.put(
            "/api/brain/links",
            json={"source_id": a["id"], "target_id": b["id"], "relation": "ondersteunt"},
        )
        self.assertEqual(updated.status_code, 200)
        deleted = self.client.delete(f"/api/brain/links?source_id={a['id']}&target_id={b['id']}")
        self.assertEqual(deleted.status_code, 204)

    def test_brain_counts_distinguish_available_vs_included(self) -> None:
        brain = self.client.get("/api/brain").json()
        self.assertIn("available", brain["counts"])
        self.assertIn("included", brain["counts"])
        self.assertIn("truncated", brain["counts"])
        self.assertIn("layout", brain)
        self.assertGreaterEqual(brain["counts"]["available"]["manual_nodes"], 1)


class ModelGatewayCapacityTests(unittest.TestCase):
    def test_none_means_unlimited_not_magic_number(self) -> None:
        gw = ModelGateway(global_limit=None)
        self.assertIsNone(gw.global_limit)
        snap = gw.snapshot_config(endpoint="http://local")
        self.assertIsNone(snap.global_limit)

        async def _run() -> None:
            async with gw.slot("m1", endpoint="http://local", surface="chat"):
                async with gw.slot("m1", endpoint="http://local", surface="work"):
                    overview = gw.overview()
                    self.assertEqual(overview["active_count"], 2)
                    self.assertIsNone(overview["capacity"]["global_limit"])

        asyncio.run(_run())

    def test_live_limit_change_does_not_drop_waiters(self) -> None:
        gw = ModelGateway(global_limit=1, acquire_timeout_s=2.0)

        async def _run() -> None:
            await gw.acquire("m1", endpoint="ep", surface="chat")
            waiter = asyncio.create_task(gw.acquire("m1", endpoint="ep", surface="work"))
            await asyncio.sleep(0.05)
            self.assertFalse(waiter.done())
            gw.configure(global_limit=2)
            await asyncio.sleep(0)
            await asyncio.wait_for(waiter, timeout=1.0)
            self.assertEqual(gw.overview()["active_count"], 2)
            active_ids = [item["call_id"] for item in gw.overview()["active_calls"]]
            for call_id in active_ids:
                await gw.release(call_id)
            self.assertEqual(gw.overview()["active_count"], 0)

        asyncio.run(_run())

    def test_capacity_timeout_and_always_release_on_error(self) -> None:
        gw = ModelGateway(global_limit=1, acquire_timeout_s=0.05, max_retries=0)

        async def _run() -> None:
            call_id = await gw.acquire("m1", endpoint="ep", surface="chat")

            async def _boom(_payload: dict) -> dict:
                raise RuntimeError("boom")

            with self.assertRaises(ModelCapacityTimeout):
                await gw.acquire("m1", endpoint="ep", surface="committee")
            await gw.release(call_id)

            with self.assertRaises(Exception):
                await gw.chat(_boom, {"model": "m2"}, model_id="m2", endpoint="ep2", surface="coding")
            overview = gw.overview()
            self.assertEqual(overview["active_count"], 0)
            self.assertGreaterEqual(int(overview["errors"]["calls_failed"] or 0), 1)
            self.assertGreaterEqual(int(overview["errors"]["capacity_timeouts"] or 0), 1)

        asyncio.run(_run())

    def test_model_router_live_limit_preserves_waiters(self) -> None:
        router = ModelRouter()

        async def _run() -> None:
            await router.acquire("m1", endpoint="http://local", limit=1)
            waiter = asyncio.create_task(router.acquire("m1", endpoint="http://local", limit=1))
            await asyncio.sleep(0.05)
            self.assertFalse(waiter.done())
            router._lane("http://local::m1", 2)
            await asyncio.wait_for(waiter, timeout=1)
            await router.release("m1", endpoint="http://local")
            await router.release("m1", endpoint="http://local")

        asyncio.run(_run())

    def test_invoke_chat_fn_timeout_does_not_block_on_executor_shutdown(self) -> None:
        async def _slow():
            await asyncio.sleep(5)
            return {"ok": True}

        started = time.monotonic()
        response, meta = _invoke_chat_fn(None, _slow, timeout_s=0.2)
        elapsed = time.monotonic() - started
        self.assertIsNone(response)
        self.assertIn("timeout", meta.get("note", ""))
        self.assertLess(elapsed, 2.0, "executor shutdown must not extend the deadline unboundedly")


class ModelGatewayWireSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        main.database = Database(str(root / "core.db"))
        main.database.initialize()
        main.runner = main.TaskRunner()
        main.platform_db = PlatformDatabase(str(root / "platform.db"))
        main.ensure_platform_services()
        main.platform_db.initialize()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()
        model_gateway.configure(global_limit=1)

    def test_models_endpoint_includes_gateway_overview(self) -> None:
        payload = self.client.get("/api/models").json()
        self.assertIn("gateway", payload)
        self.assertIn("active_calls", payload["gateway"])
        self.assertIn("capacity", payload["gateway"])
        overview = self.client.get("/api/models/gateway").json()
        self.assertIn("gateway", overview)
        self.assertIn("budget_pool", overview)


if __name__ == "__main__":
    unittest.main()
