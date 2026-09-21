#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class DeepWebInspectHonestyTests(unittest.TestCase):
    def test_inspect_fails_on_http_error(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "crawler.py").read_text(encoding="utf-8")
        self.assertIn('payload = inspect_url', source)
        self.assertIn('"ok": ok', source)
        self.assertIn("return 0 if ok else 1", source)


if __name__ == "__main__":
    unittest.main()
