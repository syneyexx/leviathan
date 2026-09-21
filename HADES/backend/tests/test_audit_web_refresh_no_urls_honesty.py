"""Chat auto web-refresh must not treat zero discovered URLs as success."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class WebRefreshNoUrlsHonestyTests(unittest.TestCase):
    def test_no_urls_is_not_ok(self) -> None:
        import main as app_main

        source = inspect.getsource(app_main.maybe_refresh_web_knowledge)
        self.assertIn('"ok": False', source)
        self.assertIn("no_urls", source)
        # Must not keep the old true branch for empty discovery.
        self.assertNotIn('{"attempted": True, "indexed": 0, "ok": True, "note": "no_urls"}', source)


if __name__ == "__main__":
    unittest.main()
