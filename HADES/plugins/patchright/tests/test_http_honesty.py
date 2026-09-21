#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class _Resp:
    def __init__(self, status: int) -> None:
        self.status = status


class _Page:
    def __init__(self, status: int, text: str = "hello") -> None:
        self._status = status
        self._text = text

    def goto(self, *args, **kwargs):
        return _Resp(self._status)

    def title(self) -> str:
        return "t"

    def inner_text(self, sel: str) -> str:
        return self._text

    def screenshot(self, **kwargs) -> None:
        path = Path(kwargs["path"])
        path.write_bytes(b"png")


class _Browser:
    def __init__(self, page: _Page) -> None:
        self._page = page

    def new_page(self, **kwargs):
        return self._page

    def close(self) -> None:
        return None


class _Chromium:
    def __init__(self, page: _Page) -> None:
        self._page = page

    def launch(self, **kwargs):
        return _Browser(self._page)


class _Pw:
    def __init__(self, page: _Page) -> None:
        self.chromium = _Chromium(page)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PatchrightHttpHonestyTests(unittest.TestCase):
    def test_fetch_http_error_is_not_ok(self) -> None:
        with mock.patch.object(hades_bridge, "_launch", return_value=_Pw(_Page(404, text="<html>nope</html>"))):
            out = hades_bridge.fetch("https://example.test/missing", 1000)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("status"), 404)

    def test_screenshot_http_error_is_not_ok(self) -> None:
        with mock.patch.object(hades_bridge, "_launch", return_value=_Pw(_Page(500))):
            out = hades_bridge.screenshot("https://example.test/err", "/tmp/patchright-test.png")
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("status"), 500)


if __name__ == "__main__":
    unittest.main()
