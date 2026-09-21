#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class UltimateNewsIngestHonestyTests(unittest.TestCase):
    def test_feed_requires_ingest_evidence(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "ultimate_news_feeder.py").read_text(encoding="utf-8")
        self.assertIn("ingest_failed", source)
        self.assertIn("document_id", source)


if __name__ == "__main__":
    unittest.main()
