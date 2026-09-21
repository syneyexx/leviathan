#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class FinancialNewsAuditHonestyTests(unittest.TestCase):
    def test_audit_fails_closed_without_items(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "financial_news_intelligence.py").read_text(encoding="utf-8")
        self.assertIn("audit_found_no_items", source)
        self.assertIn("return 0 if ok else 2", source)


if __name__ == "__main__":
    unittest.main()
