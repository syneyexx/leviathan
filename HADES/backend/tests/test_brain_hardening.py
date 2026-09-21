from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from platform_db import PlatformDatabase


class BrainHardeningApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        main.database = Database(str(root / "hades.db"))
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

    def test_graph_never_exposes_dangling_links_and_normalizes_permissions(self) -> None:
        created = self.client.post(
            "/api/brain/nodes",
            json={"label": "Handmatig", "kind": "note", "description": "test", "tags": []},
        )
        self.assertEqual(created.status_code, 201, created.text)
        manual_id = created.json()["id"]

        # External links intentionally have no FK because their endpoints can live
        # in other stores. A stale persisted row must never leak into the UI graph.
        stale = main.platform_db.add_brain_external_link("core_hades", "memory_missing", "stale")
        self.assertIsNotNone(stale)

        response = self.client.get("/api/brain")
        self.assertEqual(response.status_code, 200, response.text)
        graph = response.json()
        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertIn(manual_id, node_ids)
        self.assertTrue(
            all(link["source_id"] in node_ids and link["target_id"] in node_ids for link in graph["links"]),
            graph["links"],
        )
        self.assertFalse(any(link["target_id"] == "memory_missing" for link in graph["links"]))
        self.assertEqual(graph["counts"]["links"], len(graph["links"]))

        core = next(node for node in graph["nodes"] if node["id"] == "core_hades")
        manual = next(node for node in graph["nodes"] if node["id"] == manual_id)
        self.assertFalse(core["content_editable"])
        self.assertTrue(core["layout_movable"])
        self.assertTrue(manual["content_editable"])
        self.assertTrue(manual["layout_movable"])
        self.assertIsInstance(core["pinned"], bool)
        self.assertIsInstance(manual["pinned"], bool)

    def test_create_link_rejects_unknown_endpoint_without_persisting_garbage(self) -> None:
        response = self.client.post(
            "/api/brain/links",
            json={"source_id": "core_hades", "target_id": "memory_missing", "relation": "test"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(
            any(
                row["source_id"] == "core_hades" and row["target_id"] == "memory_missing"
                for row in main.platform_db.list_brain_external_links()
            )
        )

    def test_new_manual_node_can_connect_to_derived_conversation(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "Brain target"})
        self.assertEqual(conversation.status_code, 201, conversation.text)
        target_id = f"conversation_{conversation.json()['id']}"

        created = self.client.post(
            "/api/brain/nodes",
            json={
                "label": "Conversation note",
                "kind": "note",
                "description": "gekoppeld",
                "tags": ["brain"],
                "connect_to": target_id,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        node_id = created.json()["id"]

        graph = self.client.get("/api/brain").json()
        self.assertTrue(
            any(
                link["source_id"] == node_id
                and link["target_id"] == target_id
                and link.get("external") is True
                for link in graph["links"]
            ),
            graph["links"],
        )

    def test_create_node_rejects_unknown_connect_target_atomically(self) -> None:
        before = {node["id"] for node in self.client.get("/api/brain").json()["nodes"]}
        response = self.client.post(
            "/api/brain/nodes",
            json={
                "label": "Mag niet blijven staan",
                "kind": "note",
                "description": "",
                "tags": [],
                "connect_to": "task_missing",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        after_graph = self.client.get("/api/brain").json()
        after = {node["id"] for node in after_graph["nodes"]}
        self.assertEqual(before, after)
        self.assertFalse(any(node["label"] == "Mag niet blijven staan" for node in after_graph["nodes"]))


if __name__ == "__main__":
    unittest.main()
