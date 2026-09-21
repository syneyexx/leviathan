#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class DeepWebPartialErrorHonestyTests(unittest.TestCase):
    def test_crawler_fails_closed_on_seed_or_error_flood(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "crawler.py").read_text(encoding="utf-8")
        self.assertIn("crawl completed with blocking errors", source)
        self.assertIn("seed_failed", source)
        self.assertIn("error_count >= max(1, pages + files)", source)


if __name__ == "__main__":
    unittest.main()
