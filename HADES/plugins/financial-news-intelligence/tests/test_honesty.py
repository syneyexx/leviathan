#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import financial_news_intelligence as fni  # noqa: E402


class FinancialNewsHonestyTests(unittest.TestCase):
    def test_fetch_all_empty_is_nonzero(self) -> None:
        empty = {
            "article_count": 0,
            "articles": [],
            "health": {"succeeded_with_items": 0, "attempted": 3},
        }
        with patch.object(fni, "collect", return_value=empty):
            with patch.object(fni, "write_outputs", return_value={"markdown": "/tmp/x.md"}):
                with tempfile.TemporaryDirectory() as tmp:
                    code = fni.cmd_fetch(
                        type("A", (), {"output_dir": tmp})()
                    )
        self.assertEqual(code, 2)

    def test_robots_fail_closed_on_network_error(self) -> None:
        cache = fni.RobotsCache(timeout=1.0)
        with patch("urllib.request.urlopen", side_effect=TimeoutError("down")):
            self.assertFalse(cache.allowed("https://example.com/story"))


if __name__ == "__main__":
    unittest.main()
