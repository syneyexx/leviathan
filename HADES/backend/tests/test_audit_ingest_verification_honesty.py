"""Unverified knowledge ingest must not mark files ready or greenwash agents/UI."""

from __future__ import annotations

import asyncio
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class IngestVerificationHonestyTests(unittest.TestCase):
    def test_ingest_file_marks_unverified_as_error(self) -> None:
        import platform_services_core as core

        source = inspect.getsource(core.KnowledgeService.ingest_file)
        self.assertIn("verification_failed", source)
        self.assertIn('status="ready" if verified else "error"', source)
        self.assertIn("knowledge_verification_failed", source)

    def test_research_crawl_skips_unverified_sources(self) -> None:
        import platform_services_core as core

        source = inspect.getsource(core.ResearchRunner)
        self.assertIn("verified_sources", source)
        self.assertIn("Webbron/crawl zonder geverifieerde bronnen", source)
        self.assertIn("verification_failed", source)

    def test_web_scout_rejects_unverified_ingest(self) -> None:
        import agent_runtimes as runtimes

        self.assertFalse(
            runtimes._ingest_result_verified(
                {"id": "s1", "status": "verification_failed", "persistence": {"verification_passed": False}}
            )
        )
        self.assertTrue(runtimes._ingest_result_verified({"id": "s1", "status": "ready"}))

        async def _run() -> object:
            web = MagicMock()
            web.ingest_url = AsyncMock(
                return_value={
                    "id": "src-1",
                    "status": "verification_failed",
                    "persistence": {"verification_passed": False},
                }
            )
            deps = runtimes.AgentRuntimeDeps(
                settings={"network_policy": "allow"},
                web_research=web,
            )
            return await runtimes.run_web_scout("https://example.test/a", deps)

        result = asyncio.run(_run())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "ingest_unverified")

    def test_knowledge_builder_rejects_unverified_ingest(self) -> None:
        import agent_runtimes as runtimes

        knowledge = MagicMock()
        knowledge.ingest_text.return_value = {
            "id": "k1",
            "chunks": 2,
            "status": "verification_failed",
            "persistence": {"verification_passed": False},
        }
        deps = runtimes.AgentRuntimeDeps(
            settings={},
            knowledge=knowledge,
            platform_db=None,
            prior_outputs=[{"knowledge_items": [{"title": "t", "content": "body text", "uri": "plugin://t"}]}],
            step_title="persist knowledge",
        )
        result = runtimes.run_knowledge_builder("persist and verify knowledge items", deps)
        self.assertFalse(result.ok)


class FrontendIngestToastHonestyTests(unittest.TestCase):
    def test_research_upload_and_harvest_gate_toasts(self) -> None:
        root = Path(__file__).resolve().parents[2]
        page = (root / "components" / "hades" / "pages" / "research-page.tsx").read_text(encoding="utf-8")
        self.assertIn('status === "ready"', page)
        self.assertIn("Geen documenten konden worden geïndexeerd", page)
        self.assertIn("ingested <= 0", page)

    def test_files_page_gates_workspace_rescan_reindex(self) -> None:
        root = Path(__file__).resolve().parents[2]
        page = (root / "components" / "hades" / "pages" / "files-page.tsx").read_text(encoding="utf-8")
        self.assertIn("ready <= 0 && (failed > 0 || unsupported > 0)", page)
        self.assertIn("if (ready > 0)", page)
        self.assertIn('result.file.status === "ready"', page)
        self.assertIn("Opnieuw indexeren mislukt", page)


if __name__ == "__main__":
    unittest.main()
