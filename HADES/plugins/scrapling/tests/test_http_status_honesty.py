#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class _Page:
    def __init__(self, text: str, status: int) -> None:
        self.text = text
        self.status = status

    def css(self, sel: str):
        return []


class ScraplingHttpHonestyTests(unittest.TestCase):
    def test_http_error_body_is_not_ok(self) -> None:
        fake = type("F", (), {"get": staticmethod(lambda url: _Page("Forbidden", 403))})
        with mock.patch.dict("sys.modules", {"scrapling.fetchers": mock.Mock(Fetcher=fake)}):
            # Force static mode import path by patching inside fetch
            with mock.patch.object(hades_bridge, "fetch", wraps=None):
                pass
        # Call implementation with patched Fetcher import inside function via module patch
        import types
        mod = types.ModuleType("scrapling.fetchers")
        mod.Fetcher = fake
        mod.StealthyFetcher = fake
        mod.DynamicFetcher = fake
        with mock.patch.dict("sys.modules", {"scrapling": types.ModuleType("scrapling"), "scrapling.fetchers": mod}):
            out = hades_bridge.fetch("https://example.test", "static", "", 1000)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("status"), 403)


if __name__ == "__main__":
    unittest.main()
