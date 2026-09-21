"""Tests for terminal, practice, LSP-light, voice, debug, release, tool cards."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from debug_agent import diagnose_failure
from lsp_light import find_definition, find_references
from practice_api import run_all, run_scenario
from release_confidence import inventory_gates
from terminal_tool import PolicyTerminalService, TerminalPolicyError
from tool_result_cards import build_tool_result_cards
from voice_tasks import transcript_to_task
from workspace_symbols import index_workspace_symbols


class PracticeApiTests(unittest.TestCase):
    def test_all_scenarios_pass(self) -> None:
        report = run_all()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["summary"]["failed"], 0)

    def test_scenario_a(self) -> None:
        result = run_scenario("A")
        self.assertTrue(result["passed"], result)


class TerminalToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        from artifacts import ArtifactService
        from platform_db import PlatformDatabase

        db_path = str(self.root / "hades.db")
        core = Database(db_path)
        core.initialize()
        self.pdb = PlatformDatabase(db_path)
        self.pdb.initialize()
        self.artifacts = ArtifactService(self.pdb, self.root)
        self.service = PolicyTerminalService(self.artifacts, self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_allowlist_and_jail(self) -> None:
        with self.assertRaises(TerminalPolicyError):
            self.service.run(["rm", "-rf", "/"], settings={"terminal_allowlist": ["python"], "file_write_policy": "allow"})
        binary = Path(sys.executable).name.lower()
        if binary.endswith(".exe"):
            binary = binary[:-4]
        result = self.service.run(
            [sys.executable, "-c", "print('HADES_OK')"],
            settings={"terminal_allowlist": ["python", "python3", binary], "file_write_policy": "allow"},
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("HADES_OK", result["stdout"])


class SymbolAndLspTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        sample = self.root / "sample.py"
        sample.write_text("def alpha_helper():\n    return 1\n\nclass BetaThing:\n    pass\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_index_and_definition(self) -> None:
        indexed = index_workspace_symbols(self.root, query="alpha", use_cache=False)
        self.assertTrue(any(item["name"] == "alpha_helper" for item in indexed["symbols"]))
        defs = find_definition(self.root, "alpha_helper")
        self.assertGreaterEqual(defs["count"], 1)
        refs = find_references(self.root, "alpha_helper")
        self.assertGreaterEqual(refs["count"], 1)

    def test_release_inventory_includes_what_broke(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        report = inventory_gates(repo)
        self.assertIn(report["overall"], {"ok", "warn", "error"})
        self.assertIn("what_broke", report)
        self.assertTrue(any(gate["id"] == "python_syntax_critical" for gate in report["gates"]))


class VoiceDebugReleaseTests(unittest.TestCase):
    def test_voice_to_task(self) -> None:
        proposal = transcript_to_task("Maak urgent een samenvatting van de Orion-notities")
        self.assertEqual(proposal["priority"], "high")
        self.assertIn("Orion", proposal["prompt"])
        self.assertIn("geen asr", proposal["note"].lower())

    def test_debug_diagnose_ts(self) -> None:
        logs = "src/pages/agents-page.tsx(142,26): error TS2322: Type 'string | undefined' is not assignable to type 'string'."
        report = diagnose_failure(logs=logs, failing_test="typecheck")
        self.assertEqual(report["status"], "diagnosed")
        self.assertTrue(report["suggestions"])
        self.assertTrue(report["what_broke"])

    def test_release_inventory(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        report = inventory_gates(repo)
        self.assertIn(report["overall"], {"ok", "warn", "error"})
        self.assertTrue(report["gates"])
        self.assertIn("what_broke", report)

    def test_tool_cards(self) -> None:
        cards = build_tool_result_cards(
            [
                {"tool_name": "harvest", "status": "completed", "output": {"documents": [{"name": "a.pdf", "uri": "u", "status": "ok"}]}},
                {"tool_name": "fail", "status": "failed", "error": "blocked"},
            ]
        )
        self.assertEqual(cards[0]["card_type"], "table")
        self.assertEqual(cards[1]["status"], "failed")


class CapabilityRouteSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        main.database = Database(str(root / "core.db"))
        main.database.initialize()
        main.runner = main.TaskRunner()
        from platform_db import PlatformDatabase

        main.platform_db = PlatformDatabase(str(root / "other.db"))
        main.ensure_platform_services()
        main.platform_db.initialize()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_practice_and_onboarding_and_mcp(self) -> None:
        scenarios = self.client.get("/api/practice/scenarios")
        self.assertEqual(scenarios.status_code, 200)
        self.assertGreaterEqual(len(scenarios.json()["scenarios"]), 5)
        run = self.client.post("/api/practice/scenarios/A/run")
        self.assertEqual(run.status_code, 200, run.text)
        self.assertTrue(run.json()["passed"])
        onboarding = self.client.get("/api/onboarding")
        self.assertEqual(onboarding.status_code, 200)
        self.assertIn("steps", onboarding.json())
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("checks", health.json())
        cards = self.client.post("/api/tools/cards", json={"observations": [{"tool_name": "x", "status": "ok", "output": "hello"}]})
        self.assertEqual(cards.status_code, 200)
        catalog = self.client.get("/api/mcp/catalog")
        self.assertEqual(catalog.status_code, 200)
        confidence = self.client.get("/api/release/confidence")
        self.assertEqual(confidence.status_code, 200)
        voice = self.client.post("/api/voice/to-task", json={"transcript": "Plan een lokale research taak", "create": False})
        self.assertEqual(voice.status_code, 200)
        self.assertFalse(voice.json()["created"])

    def test_voice_to_task_create_and_start(self) -> None:
        preview = self.client.post(
            "/api/voice/to-task",
            json={"transcript": "Maak urgent een research samenvatting van Orion\naccepteer: korte bulletlijst", "create": False},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertFalse(body["created"])
        proposal = body["proposal"]
        self.assertEqual(proposal["priority"], "high")
        self.assertEqual(proposal["agent"], "research_worker")
        self.assertTrue(any("bulletlijst" in str(item).lower() for item in proposal["acceptance_criteria"]))

        created = self.client.post(
            "/api/voice/to-task",
            json={
                "transcript": "Maak urgent een research samenvatting van Orion\naccepteer: korte bulletlijst",
                "create": True,
                "auto_start": False,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        created_body = created.json()
        self.assertTrue(created_body["created"])
        self.assertFalse(created_body.get("started"))
        task = created_body["task"]
        self.assertTrue(task["id"])
        self.assertEqual(task["status"], "queued")
        self.assertIn("Orion", task["prompt"])
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["agent"], "research_worker")

        listed = self.client.get("/api/tasks")
        self.assertEqual(listed.status_code, 200)
        ids = {item["id"] for item in listed.json()}
        self.assertIn(task["id"], ids)

        started = self.client.post(
            "/api/voice/to-task",
            json={"transcript": "Bouw een lokale helper voor voice paste", "create": True, "auto_start": True},
        )
        self.assertEqual(started.status_code, 200, started.text)
        started_body = started.json()
        self.assertTrue(started_body["created"])
        self.assertTrue(started_body.get("started"))
        self.assertTrue(started_body["task"]["id"])
        self.assertEqual(started_body["proposal"]["agent"], "builder")
        self.assertIn(started_body["task"]["status"], {"queued", "running"})


if __name__ == "__main__":
    unittest.main()
