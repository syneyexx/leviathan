#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fincept_hades  # noqa: E402


class FinceptHonestyTests(unittest.TestCase):
    def test_catalog_query_without_matches_is_not_ok(self) -> None:
        with mock.patch.object(fincept_hades, "_fetch_docs_index", return_value="alpha\nbeta\n"):
            out = fincept_hades.command_catalog(Namespace(query="zzz", limit=10, timeout=5))
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("match_count_returned"), 0)

    def test_batch_get_aggregates_child_failures(self) -> None:
        calls = [
            {"ok": True, "hades_knowledge": [], "rate_limit": {"remaining": 10}},
            {"ok": False, "error": "boom", "hades_knowledge": [], "rate_limit": {"remaining": 10}},
        ]

        def _api(**kwargs):
            return calls.pop(0)

        with mock.patch.object(fincept_hades, "_api_request", side_effect=_api):
            out = fincept_hades.command_batch_get(
                Namespace(
                    batch='{"requests":[{"path":"/a"},{"path":"/b"}],"delay_ms":0}',
                    max_bytes=100000,
                    timeout=5,
                )
            )
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("count"), 2)


if __name__ == "__main__":
    unittest.main()
