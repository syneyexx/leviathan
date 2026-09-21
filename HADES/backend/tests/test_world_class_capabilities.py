"""Tests for site harvest, chat commands, and live Brain CRUD."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from chat_commands import detect_harvest_intent, detect_slash_command, maybe_handle_chat_command
from database import Database
from mentions import parse_mentions
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService, WebResearchService


class MentionUnitTests(unittest.TestCase):
    def test_parse_mentions(self) -> None:
        items = parse_mentions("Gebruik @memory:voorkeur en @knowledge:ebooks plus @agent")
        kinds = [item["kind"] for item in items]
        self.assertIn("memory", kinds)
        self.assertIn("knowledge", kinds)
        self.assertIn("agent", kinds)
        self.assertEqual(items[0]["ref"], "voorkeur")


class ChatCommandUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_natural_language_ebook_harvest_intent(self) -> None:
        intent = detect_harvest_intent(
            "Download elke ebook die gelinkt staat met deze website https://www.freebookcentre.net/"
        )
        assert intent is not None
        self.assertEqual(intent["kind"], "harvest")
        self.assertEqual(intent["url"], "https://www.freebookcentre.net/")
        self.assertTrue(intent["authorized_downloads"])

    def test_slash_harvest_and_help(self) -> None:
        harvest = detect_slash_command("/harvest https://example.com/books max_documents=12")
        assert harvest is not None
        self.assertEqual(harvest["kind"], "harvest")
        self.assertEqual(harvest["max_documents"], 12)
        help_cmd = detect_slash_command("/help")
        assert help_cmd is not None
        self.assertEqual(help_cmd["kind"], "help")
        remember = detect_slash_command("/remember Voorkeurstaal is Nederlands")
        assert remember is not None
        self.assertEqual(remember["kind"], "remember")

    async def test_maybe_handle_blocks_on_network_policy(self) -> None:
        result = await maybe_handle_chat_command(
            content="/harvest https://example.com",
            network_policy="block",
            harvest_fn=AsyncMock(),
        )
        assert result is not None
        self.assertTrue(result["handled"])
        self.assertFalse(result["ok"])
        self.assertIn("block", result["message"].lower())

    async def test_maybe_handle_remember(self) -> None:
        result = await maybe_handle_chat_command(
            content="/remember HADES draait lokaal",
            network_policy="allow",
            harvest_fn=AsyncMock(),
            remember_fn=lambda text: {"id": "mprop_test", "content": text},
        )
        assert result is not None
        self.assertTrue(result["handled"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "remember")

    async def test_maybe_handle_voice(self) -> None:
        result = await maybe_handle_chat_command(
            content="/voice Maak urgent een samenvatting van de Orion notities",
            network_policy="allow",
            harvest_fn=AsyncMock(),
            voice_task_fn=lambda text: {
                "created": True,
                "proposal": {"title": "Samenvatting", "priority": "high", "agent": "auto", "prompt": text},
                "task": {"id": "task_voice"},
            },
        )
        assert result is not None
        self.assertTrue(result["handled"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "voice")
        self.assertIn("task_voice", result["message"])
        # Honesty: this path never claims built-in ASR; wording may say cloud-STT or ASR.
        lowered = result["message"].lower()
        self.assertTrue(
            "geen ingebouwde asr" in lowered or "geen asr" in lowered or "geen cloud-stt" in lowered,
            result["message"],
        )
        self.assertIn("Spraak", result["message"])


class HarvestServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_harvest_site_documents_ingests_pdf_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdb = PlatformDatabase(str(root / "platform.db"))
            pdb.initialize()
            knowledge = KnowledgeService(pdb, root / "knowledge")
            web = WebResearchService(knowledge)

            class FakeCrawl:
                def __init__(self) -> None:
                    self.url = "https://books.example/index.html"
                    self.title = "Free Books"
                    self.text = "Welcome to free books"
                    self.raw_html = (
                        '<html><body><a href="/docs/guide.pdf">Guide PDF</a>'
                        '<a href="https://cdn.example/extra.epub">Extra EPUB</a></body></html>'
                    )
                    self.metadata = {"url": self.url, "content_type": "text/html"}

            async def fake_fetch(url: str, *, respect_robots: bool = True):
                return FakeCrawl()

            async def fake_ingest(url: str, *, respect_robots: bool = False):
                return knowledge.ingest_text(
                    title=Path(url).name,
                    text=f"content for {url}",
                    source_type="web_document",
                    uri=url,
                    metadata={"authorized_download": True, "source_url": url},
                    local_path=None,
                )

            with patch.object(web, "fetch", side_effect=fake_fetch), patch.object(
                web, "ingest_document_url", side_effect=fake_ingest
            ):
                result = await web.harvest_site_documents(
                    "https://books.example/index.html",
                    max_pages=5,
                    max_depth=1,
                    max_documents=10,
                    authorized_downloads=True,
                    include_html_pages=True,
                )

            self.assertEqual(result["pages_crawled"], 1)
            self.assertGreaterEqual(result["documents_ingested"], 2)
            self.assertTrue(any(doc["uri"].endswith(".pdf") for doc in result["documents"]))
            sources = pdb.list_knowledge_sources(50)
            self.assertTrue(any(item["source_type"] == "web_document" for item in sources))


class BrainAndHarvestApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        db_path = root / "hades.db"
        main.database = Database(str(db_path))
        main.database.initialize()
        main.runner = main.TaskRunner()
        # Align platform DB with core DB so ensure_platform_services rebuilds managers.
        main.platform_db = PlatformDatabase(str(root / "other.db"))
        main.ensure_platform_services()
        main.platform_db.initialize()
        main.knowledge = KnowledgeService(main.platform_db, root)
        main.web_research = WebResearchService(main.knowledge)
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_brain_crud_update_delete_and_link(self) -> None:
        created = self.client.post(
            "/api/brain/nodes",
            json={
                "label": "Live notitie",
                "kind": "note",
                "description": "Bewerkbaar",
                "tags": ["test"],
                "pos_x": 120,
                "pos_y": 220,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        node = created.json()
        self.assertEqual(node["pos_x"], 120)

        updated = self.client.put(
            f"/api/brain/nodes/{node['id']}",
            json={"label": "Live notitie v2", "description": "Geüpdatet", "pos_x": 333, "pos_y": 444},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["label"], "Live notitie v2")
        self.assertEqual(updated.json()["pos_x"], 333)

        other = self.client.post(
            "/api/brain/nodes",
            json={"label": "Tweede", "kind": "note", "description": "", "tags": []},
        ).json()
        linked = self.client.post(
            "/api/brain/links",
            json={"source_id": node["id"], "target_id": other["id"], "relation": "raakt"},
        )
        self.assertEqual(linked.status_code, 201, linked.text)

        brain = self.client.get("/api/brain").json()
        self.assertTrue(any(item["id"] == node["id"] for item in brain["nodes"]))
        self.assertTrue(
            any(link["source_id"] == node["id"] and link["target_id"] == other["id"] for link in brain["links"])
        )
        memory = self.client.post(
            "/api/memories",
            json={"title": "Brain memory", "content": "fact", "collection": "Tests", "tags": []},
        ).json()
        brain2 = self.client.get("/api/brain").json()
        mem_node = next(item for item in brain2["nodes"] if item["id"] == f"memory_{memory['id']}")
        self.assertTrue(str(mem_node["open_href"]).startswith("#/memory"))

        deleted = self.client.delete(f"/api/brain/nodes/{node['id']}")
        self.assertEqual(deleted.status_code, 204)
        blocked = self.client.delete("/api/brain/nodes/core_hades")
        self.assertEqual(blocked.status_code, 404)

    def test_knowledge_pack_export(self) -> None:
        self.client.post(
            "/api/memories",
            json={
                "title": "Pack fact",
                "content": "Lokaal feit",
                "collection": "Tests",
                "tags": ["pack"],
                "scope": "project",
            },
        )
        main.knowledge.ingest_text(
            title="Pack source",
            text="Document body",
            source_type="manual",
            uri="manual://pack",
            metadata={},
            local_path=None,
        )
        response = self.client.get("/api/knowledge/pack")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["format"], "hades.knowledge_pack.v1")
        self.assertGreaterEqual(body["memory_count"], 1)
        self.assertGreaterEqual(body["knowledge_count"], 1)
        self.assertIn("agents", body)
        self.assertIn("evidence", body)
        self.assertIn("decisions", body)
        self.assertTrue(any(item.get("scope") == "project" for item in body["memories"]))

    def test_knowledge_pack_import_roundtrip(self) -> None:
        created = self.client.post(
            "/api/memories",
            json={
                "title": "Importable",
                "content": "Feit voor pack import",
                "collection": "Tests",
                "tags": ["roundtrip"],
                "scope": "global",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        main.knowledge.ingest_text(
            title="Import source",
            text="Body",
            source_type="manual",
            uri="manual://pack-import",
            metadata={},
            local_path=None,
        )
        pack = self.client.get("/api/knowledge/pack").json()
        # Clear memories by forgetting active ones, then re-import.
        for item in main.database.list_memories(limit=500):
            main.database.forget_memory(item["id"])
        imported = self.client.post(
            "/api/knowledge/pack/import",
            json={
                "format": pack["format"],
                "memories": [
                    {
                        "title": item["title"],
                        "content": item["content"],
                        "summary": item.get("summary") or "",
                        "collection": item.get("collection") or "Algemeen",
                        "tags": item.get("tags") or [],
                        "source": item.get("source") or "Pack",
                        "scope": item.get("scope") or "project",
                    }
                    for item in pack["memories"]
                    if item.get("title") == "Importable"
                ],
                "knowledge_sources": pack["knowledge_sources"],
                "agents": pack.get("agents") or [],
                "import_memories": True,
                "import_knowledge_stubs": True,
                "import_agent_states": False,
            },
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        body = imported.json()
        self.assertGreaterEqual(body["imported_memories"], 1)
        self.assertGreaterEqual(body["imported_knowledge_stubs"], 1)
        scoped = self.client.get("/api/memories", params={"scope": "global"}).json()
        self.assertTrue(any(item["title"] == "Importable" for item in scoped["items"]))

    def test_scoped_memory_api_and_non_dumping_retrieval(self) -> None:
        session = self.client.post(
            "/api/memories",
            json={
                "title": "Session only",
                "content": "alleen in dit gesprek over retrieval-budget",
                "collection": "Tests",
                "tags": ["conv_test_scope"],
                "scope": "session",
            },
        ).json()
        project = self.client.post(
            "/api/memories",
            json={
                "title": "Project retrieval",
                "content": "project retrieval-budget feit",
                "collection": "Tests",
                "tags": [],
                "scope": "project",
            },
        ).json()
        listed = self.client.get("/api/memories", params={"scope": "session"}).json()
        self.assertTrue(any(item["id"] == session["id"] for item in listed["items"]))
        self.assertFalse(any(item["id"] == project["id"] for item in listed["items"]))

        # Seed a huge knowledge dump and ensure retrieval packs under budget with provenance labels.
        main.knowledge.ingest_text(
            title="Huge dump",
            text=("irrelevant filler " * 2_000) + " retrieval-budget " + ("tail filler " * 2_000),
            source_type="manual",
            uri="manual://huge-dump",
            metadata={},
            local_path=None,
        )
        items, meta = main.retrieval_context_items("retrieval-budget", limit=4)
        self.assertTrue(items)
        used = int((meta.get("non_dumping") or {}).get("used_chars") or 0)
        self.assertLessEqual(used, int(main.runtime_values().get("max_retrieval_chars", 6000)) + 400)
        self.assertTrue(meta.get("sources"))
        self.assertIn("rerank", str(meta.get("retrieval_method") or ""))
        self.assertTrue(any("memory ·" in src["label"] or "knowledge ·" in src["label"] for src in meta["sources"]))

        superseded = self.client.post(
            f"/api/memories/{project['id']}/supersede",
            json={
                "title": "Project retrieval",
                "content": "project retrieval-budget feit v2",
                "collection": "Tests",
                "tags": [],
                "scope": "project",
            },
        )
        self.assertEqual(superseded.status_code, 201, superseded.text)
        self.assertEqual(superseded.json()["scope"], "project")
        history = self.client.get(f"/api/memories/{superseded.json()['id']}/history").json()
        self.assertGreaterEqual(len(history["items"]), 2)
        forgotten = self.client.post(
            "/api/memory/forget",
            json={"memory_id": superseded.json()["id"], "include_derived": True, "preview_only": False},
        )
        self.assertEqual(forgotten.status_code, 200, forgotten.text)
        active = self.client.get("/api/memories", params={"q": "retrieval-budget", "scope": "project"}).json()
        self.assertFalse(any(item["id"] == superseded.json()["id"] for item in active["items"]))

    def test_knowledge_harvest_endpoint_and_chat_command(self) -> None:
        async def fake_harvest(url: str, **kwargs):
            source = main.knowledge.ingest_text(
                title="Fake Ebook",
                text="Chapter 1",
                source_type="web_document",
                uri=f"{url.rstrip('/')}/book.pdf",
                metadata={"authorized_download": True, "source_url": f"{url.rstrip('/')}/book.pdf"},
                local_path=None,
            )
            return {
                "seed_url": url,
                "pages_crawled": 1,
                "documents_discovered": 1,
                "documents_ingested": 1,
                "page_sources": [],
                "documents": [source],
                "failures": [],
                "authorized_downloads": True,
            }

        main.database.update_settings({"network_policy": "allow"})
        # runtime_values() prefers the control plane cache — keep it in sync.
        if getattr(main, "control_service", None) is not None:
            main.control_service.patch_global({"network_policy": "allow"})
        with patch.object(main.web_research, "harvest_site_documents", side_effect=fake_harvest):
            response = self.client.post(
                "/api/knowledge/harvest",
                json={
                    "url": "https://www.freebookcentre.net/",
                    "authorized_downloads": True,
                    "approved_network": True,
                    "max_documents": 5,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["documents_ingested"], 1)

            conversation = self.client.post("/api/conversations", json={"title": "Harvest chat"}).json()
            chat = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={
                    "content": "Download elke ebook die gelinkt staat met deze website https://www.freebookcentre.net/"
                },
            )
            self.assertEqual(chat.status_code, 200, chat.text)
            payload = chat.json()
            self.assertTrue(payload["command"]["ok"])
            self.assertEqual(payload["command"]["command"], "harvest")
            self.assertIn("Site-harvest", payload["assistant_message"]["content"])

        denied = self.client.post(
            "/api/knowledge/harvest",
            json={"url": "https://www.freebookcentre.net/", "authorized_downloads": False, "approved_network": True},
        )
        self.assertEqual(denied.status_code, 400)


if __name__ == "__main__":
    unittest.main()
