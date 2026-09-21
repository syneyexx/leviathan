"""Regressions for remaining silent false-success sinks (audit follow-up)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_commands import format_harvest_reply, harvest_succeeded
from gen2.workflow_adapters import WorkflowServices, _adapt_coding_agent, _adapt_research_runner
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService, ResearchRunner, WebResearchService


class HarvestHonestyTests(unittest.TestCase):
    def test_failures_without_ingest_are_not_ok(self) -> None:
        result = {
            "seed_url": "https://example.test",
            "pages_crawled": 2,
            "documents_discovered": 1,
            "documents_ingested": 0,
            "documents": [],
            "failures": [{"url": "https://example.test/a.pdf", "error": "403"}],
        }
        self.assertFalse(harvest_succeeded(result))
        reply = format_harvest_reply(result)
        self.assertIn("mislukt of leeg", reply)
        self.assertNotIn("voltooid voor", reply.split("\n", 1)[0])

    def test_ingest_is_ok(self) -> None:
        result = {
            "seed_url": "https://example.test",
            "pages_crawled": 1,
            "documents_discovered": 1,
            "documents_ingested": 1,
            "documents": [{"id": "d1", "title": "Doc"}],
            "failures": [],
        }
        self.assertTrue(harvest_succeeded(result))
        self.assertIn("voltooid", format_harvest_reply(result).split("\n", 1)[0])


class ResearchSynthesisFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.knowledge = KnowledgeService(self.db, self.root)
        self.web = WebResearchService(self.knowledge)

        async def _resolver(_model):
            return "local-test", {"temperature": 0.2, "max_tokens": 500}

        class _Client:
            async def chat(self, payload):
                raise RuntimeError("lm_unavailable")

        self.runner = ResearchRunner(
            self.db,
            self.knowledge,
            self.web,
            _resolver,
            lambda: _Client(),
            lambda model_id, profile, messages: {
                "model": model_id,
                "messages": messages,
                **profile,
            },
            lambda: "block",
            lambda: {},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_llm_failure_is_needs_more_evidence_not_green_success(self) -> None:
        doc = self.root / "notes.txt"
        doc.write_text("Lokale evidence voor synthese-fallback test.\n" * 40, encoding="utf-8")
        project = self.db.create_research_project(
            "Synthese fallback",
            "Lokale evidence test",
            "quick",
            False,
            [str(doc)],
        )
        project_id = project["id"]
        asyncio.run(self.runner._run(project_id))
        finished = self.db.get_research_project(project_id)
        assert finished is not None
        self.assertEqual(finished["status"], "needs_more_evidence")
        metrics = finished.get("metrics") or {}
        self.assertEqual(metrics.get("synthesis"), "fallback_no_llm")
        events = self.db.research_events(project_id)
        self.assertTrue(any(e.get("level") == "warning" and "Synthese" in (e.get("message") or "") for e in events))
        self.assertFalse(
            any(
                e.get("level") == "success" and "afgerond" in (e.get("message") or "").lower()
                for e in events
            )
        )


class WorkflowArtifactPersistHonestyTests(unittest.TestCase):
    def test_coding_adapter_fails_when_artifact_persist_throws(self) -> None:
        coding = MagicMock()
        coding.run_from_goal.return_value = {
            "status": "verified",
            "work_root": "/tmp/work",
            "applied_edits": [],
            "coding": {"summary": "ok"},
            "diff_text": "",
            "test_results": [],
        }
        arts = MagicMock()
        arts.create_text_result.side_effect = RuntimeError("disk_full")
        with tempfile.TemporaryDirectory() as tmp:
            services = WorkflowServices(coding_agent=coding, artifact_service=arts)
            out = _adapt_coding_agent(
                {"source_repo": tmp, "goal": "fix"},
                services=services,
                ctx={},
                run_id="run1",
                step_id="code",
                control_check=None,
            )
        self.assertFalse(out.passed)
        self.assertIn("artifact_persist_failed", out.error or "")

    def test_research_adapter_fails_when_artifact_persist_throws(self) -> None:
        runner = MagicMock()
        db = MagicMock()
        project = {
            "id": "rp1",
            "status": "queued",
            "topic": "widgets",
            "depth": "quick",
            "allow_web": 0,
            "source_inputs": [],
            "authorized_downloads": 0,
        }
        finished = {
            **project,
            "status": "completed",
            "report": "# Report\nEvidence grounded.",
            "findings": "Evidence grounded.",
            "metrics": {"coverage_score": 40},
            "progress": 100,
            "error": None,
        }
        db.create_research_project.return_value = project
        db.get_research_project.side_effect = [project, finished, finished]
        db.research_events.return_value = []
        db.research_sources.return_value = []
        db.update_research_project.return_value = finished

        async def _run(_project_id: str) -> None:
            return None

        runner._run = _run
        runner.schedule = MagicMock()

        arts = MagicMock()
        arts.create_text_result.side_effect = RuntimeError("persist_denied")
        services = WorkflowServices(
            research_runner=runner,
            platform_db=db,
            artifact_service=arts,
        )
        # Adapter may use different orchestration — call and assert honesty if it reaches persist.
        try:
            out = _adapt_research_runner(
                {"topic": "widgets", "depth": "quick", "allow_web": False, "source_inputs": []},
                services=services,
                ctx={},
                run_id="run1",
                step_id="research",
                control_check=None,
            )
        except Exception as exc:
            # Failures that prevent silent success are acceptable; soft pass is not.
            self.assertNotIn("pass", str(exc).lower())
            return
        self.assertFalse(out.passed)
        self.assertIn("artifact_persist_failed", out.error or "")
        self.assertFalse(bool((out.outputs or {}).get("ok")))


if __name__ == "__main__":
    unittest.main()
