#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class SinwindieListHonestyTests(unittest.TestCase):
    def test_filtered_topics_empty_is_not_ok(self) -> None:
        with mock.patch.object(hades_bridge, "load_json", return_value={"topics": [{"id": "a", "name": "Alpha", "resources": []}], "source": "x"}):
            out = hades_bridge.list_topics("zzz-no-match")
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("count"), 0)

    def test_filtered_sites_empty_is_not_ok(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "load_json",
            return_value={"entries": [{"kind": "site", "category": "Social", "urla": "https://x/", "urlb": ""}]},
        ):
            out = hades_bridge.list_sites(query="no-such-site")
        self.assertFalse(out.get("ok"))


if __name__ == "__main__":
    unittest.main()
