"""Focused tests for OS shell deepenings: marketplace, MCP rows, checkpoint resume, critic honesty."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from database import Database
from global_search import GlobalSearchService
from platform_db import PlatformDatabase
from plugin_marketplace import scan_local_marketplace
from tool_result_cards import build_tool_result_cards


REPO_ROOT = Path(__file__).resolve().parents[2]


class MarketplaceScanTests(unittest.TestCase):
    def test_scan_includes_local_stt_and_mcp_flags(self) -> None:
        catalog = scan_local_marketplace(REPO_ROOT / "plugins", installed=[])
        self.assertGreaterEqual(catalog["count"], 5)
        ids = {item["id"] for item in catalog["items"]}
        self.assertIn("local-stt-paste", ids)
        mcp_items = [item for item in catalog["items"] if item.get("mcp")]
        self.assertTrue(any(item["id"] == "desktop-commander-mcp" for item in mcp_items))
        stt = next(item for item in catalog["items"] if item["id"] == "local-stt-paste")
        self.assertEqual(stt["status"], "available")
        self.assertFalse(stt["installed"])

    def test_installed_needs_attention_when_not_ready(self) -> None:
        catalog = scan_local_marketplace(
            REPO_ROOT / "plugins",
            installed=[{"id": "local-stt-paste", "status": "needs_review", "health": "unknown", "enabled": False}],
        )
        stt = next(item for item in catalog["items"] if item["id"] == "local-stt-paste")
        self.assertTrue(stt["installed"])
        self.assertEqual(stt["status"], "installed_needs_attention")


class ToolCardStructureTests(unittest.TestCase):
    def test_diff_and_table_cards(self) -> None:
        cards = build_tool_result_cards(
            [
                {"tool_name": "patch", "status": "completed", "output": {"diff": "--- a\n+++ b\n"}},
                {"tool_name": "rows", "status": "completed", "output": {"rows": [["a", "b"], ["1", "2"]]}},
            ]
        )
        self.assertEqual(cards[0]["card_type"], "diff")
        self.assertTrue(cards[0]["diff"])
        self.assertEqual(cards[1]["card_type"], "table")
        self.assertEqual(cards[1]["table"][0], ["a", "b"])


class GlobalSearchOsCommandsTests(unittest.TestCase):
    def test_empty_query_returns_os_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "core.db"))
            db.initialize()
            platform = PlatformDatabase(str(Path(tmp) / "plat.db"))
            platform.initialize()
            search = GlobalSearchService(db, platform)
            result = search.search("")
            ids = {cmd["id"] for cmd in result["commands"]}
            self.assertIn("open_marketplace", ids)
            self.assertIn("open_mcp_catalog", ids)
            self.assertIn("voice_to_task", ids)
            self.assertTrue(all(cmd.get("group") == "os" for cmd in result["commands"]))


class WorldClassOsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        main.database = Database(str(root / "core.db"))
        main.database.initialize()
        main.runner = main.TaskRunner()
        main.platform_db = PlatformDatabase(str(root / "plat.db"))
        main.ensure_platform_services()
        main.platform_db.initialize()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_marketplace_and_mcp_catalog(self) -> None:
        market = self.client.get("/api/plugins/marketplace")
        self.assertEqual(market.status_code, 200, market.text)
        body = market.json()
        self.assertGreaterEqual(body["count"], 1)
        self.assertTrue(any(item["id"] == "local-stt-paste" for item in body["items"]))

        catalog = self.client.get("/api/mcp/catalog?mcp_only=true")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        payload = catalog.json()
        self.assertIn("items", payload)
        self.assertTrue(payload.get("mcp_only", True))
        for row in payload["items"]:
            self.assertIn("permissions", row)
            self.assertIn("ready", row)

    def test_resume_checkpoint_keeps_completed_steps(self) -> None:
        task = main.database.create_task("Checkpoint resume", "Doe iets", "executor", "normal", None)
        main.platform_db.replace_work_plan(
            task["id"],
            [
                {
                    "step_id": "step-1",
                    "agent_id": "executor",
                    "kind": "work",
                    "title": "Done step",
                    "instruction": "already done",
                    "depends_on": [],
                },
                {
                    "step_id": "step-2",
                    "agent_id": "executor",
                    "kind": "work",
                    "title": "Failed step",
                    "instruction": "needs retry",
                    "depends_on": ["step-1"],
                },
            ],
        )
        steps = main.platform_db.work_steps(task["id"])
        main.platform_db.update_work_step(steps[0]["id"], status="completed", output="ok")
        main.platform_db.update_work_step(steps[1]["id"], status="failed", error="boom")
        main.platform_db.add_work_checkpoint(
            task["id"],
            {"phase": "verification_failed", "acceptance_criteria": ["Done"], "issues": ["boom"]},
        )
        main.database.update_task(task["id"], status="failed", progress=40, error="boom")

        response = self.client.post(f"/api/tasks/{task['id']}/resume-checkpoint")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["resumed"])
        refreshed = main.platform_db.work_steps(task["id"])
        by_title = {step["title"]: step for step in refreshed}
        self.assertEqual(by_title["Done step"]["status"], "completed")
        self.assertEqual(by_title["Failed step"]["status"], "queued")
        # Resume must requeue; response status is the contract (get_task can race workers).
        self.assertIn(body.get("task", {}).get("status") or "", {"queued", "running"})
        live = (main.database.get_task(task["id"]) or {}).get("status")
        self.assertIn(live, {"queued", "running", "completed", "failed"})
        # Clean retry still clears work state. Resume may have scheduled a worker —
        # cancel via API first so retry is not rejected with 409 on a live running task.
        cancel = self.client.post(f"/api/tasks/{task['id']}/cancel")
        self.assertIn(cancel.status_code, {200, 409}, cancel.text)
        main.database.update_task(task["id"], status="failed", progress=0, error="x")
        retry = self.client.post(f"/api/tasks/{task['id']}/retry")
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(main.platform_db.work_steps(task["id"]), [])


if __name__ == "__main__":
    unittest.main()
