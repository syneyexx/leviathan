"""Discovery/harvest/PDF verify must not treat unverified ingest as success."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DiscoveryHarvestPdfHonestyTests(unittest.TestCase):
    def test_knowledge_ingest_verified_helper(self) -> None:
        from platform_services_core import knowledge_ingest_verified

        self.assertFalse(
            knowledge_ingest_verified(
                {"id": "s1", "status": "verification_failed", "persistence": {"verification_passed": False}}
            )
        )
        self.assertTrue(knowledge_ingest_verified({"id": "s1", "status": "ready"}))

    def test_research_discovery_gates_unverified(self) -> None:
        from platform_services_core import ResearchRunner

        source = inspect.getsource(ResearchRunner)
        self.assertIn("knowledge_ingest_verified(source)", source)
        self.assertIn("niet geverifieerd", source)

    def test_harvest_filters_unverified_sources(self) -> None:
        from platform_services_core import WebResearchService

        source = inspect.getsource(WebResearchService.harvest_site_documents)
        self.assertIn("knowledge_ingest_verified(page_source)", source)
        self.assertIn("knowledge_ingest_verified(source)", source)
        self.assertIn("knowledge_verification_failed", source)

    def test_harvest_succeeded_rejects_crawl_only_empty(self) -> None:
        from chat_commands import harvest_succeeded

        self.assertFalse(
            harvest_succeeded(
                {
                    "pages_crawled": 3,
                    "documents_ingested": 0,
                    "page_sources": [],
                    "failures": [],
                }
            )
        )
        self.assertTrue(
            harvest_succeeded(
                {
                    "pages_crawled": 1,
                    "documents_ingested": 1,
                    "page_sources": [],
                    "failures": [],
                }
            )
        )

    def test_pdf_verify_requires_confirmed_ok(self) -> None:
        root = Path(__file__).resolve().parents[2]
        actions = (root / "plugins" / "web-pdf-harvester" / "pdf_harvester" / "actions.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("success\": confirmed_ok > 0 if checked else False", actions)

    def test_trading_clears_unverified_knowledge(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("trading_service.py").read_text(encoding="utf-8")
        self.assertIn("_knowledge_payload_verified", source)
        self.assertIn("Knowledge-ingest niet geverifieerd", source)


if __name__ == "__main__":
    unittest.main()
