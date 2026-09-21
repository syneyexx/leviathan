#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class SinwindieOsintBridgeTests(unittest.TestCase):
    def test_list_sites_has_social_media(self) -> None:
        result = hades_bridge.list_sites(category="Social Media")
        self.assertTrue(result["ok"])
        self.assertGreater(result["count"], 5)
        self.assertTrue(any("twitter" in item["url_template"].lower() for item in result["sites"]))

    def test_list_topics_filters(self) -> None:
        result = hades_bridge.list_topics(query="email")
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 1)
        self.assertTrue(any("email" in str(topic["name"]).lower() for topic in result["topics"]))

    def test_list_and_get_bookmarklet(self) -> None:
        listed = hades_bridge.list_bookmarklets()
        self.assertTrue(listed["ok"])
        self.assertGreaterEqual(listed["count"], 1)
        first = listed["bookmarklets"][0]["id"]
        got = hades_bridge.get_bookmarklet(first)
        self.assertTrue(got["ok"])
        self.assertIn("content", got["bookmarklet"])

    def test_search_username_classifies(self) -> None:
        def fake_fetch(url: str, error_text: str, timeout: float):
            if "twitter.com" in url:
                return {"url": url, "found": True, "status": 200}
            return {"url": url, "found": False, "status": 404}

        with mock.patch.object(hades_bridge, "_fetch", side_effect=fake_fetch):
            result = hades_bridge.search_username("torvalds", category="Social Media", max_sites=5, workers=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["username"], "torvalds")
        self.assertGreaterEqual(result["found_count"], 1)

    def test_search_username_all_errors_is_not_success(self) -> None:
        def fake_fetch(url: str, error_text: str, timeout: float):
            return {"url": url, "found": False, "error": "timed out"}

        with mock.patch.object(hades_bridge, "_fetch", side_effect=fake_fetch):
            result = hades_bridge.search_username("nobody", category="Social Media", max_sites=4, workers=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["found_count"], 0)
        self.assertEqual(len(result["errors"]), 4)
        self.assertIn("all username probes failed", result["error"])

    def test_search_rejects_path(self) -> None:
        with self.assertRaises(ValueError):
            hades_bridge.search_username("a/b")


if __name__ == "__main__":
    unittest.main()
