#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService, WebResearchService


class CrawlSiteHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(root / "hades.db"))
        self.db.initialize()
        self.knowledge = KnowledgeService(self.db, root / "data")
        self.web = WebResearchService(self.knowledge)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_fetch_failures_raise(self) -> None:
        self.web.fetch = AsyncMock(side_effect=RuntimeError("network down"))  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "all .* page fetches failed"):
            asyncio.run(self.web.crawl_site("https://example.com/docs", max_pages=2, max_depth=0))

    def test_pdf_only_seed_path_returns_empty_without_raise(self) -> None:
        # Seed is a PDF path — skipped before fetch; empty list is legitimate for caller fallback.
        self.web.fetch = AsyncMock(side_effect=AssertionError("fetch should not run"))  # type: ignore[method-assign]
        result = asyncio.run(self.web.crawl_site("https://example.com/book.pdf", max_pages=2, max_depth=0))
        self.assertEqual(result, [])
        self.web.fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
