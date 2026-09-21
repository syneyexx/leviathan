
"""Scrapling fetch/extract must not false-succeed on empty content."""
from __future__ import annotations
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_bridge():
    spec = importlib.util.spec_from_file_location("scrapling_hades_bridge", ROOT / "hades_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakePage:
    def __init__(self, text="", body=None, css_raise: Exception | None = None):
        self.text = text
        self.body = body
        self._css_raise = css_raise

    def css(self, _selector):
        if self._css_raise:
            raise self._css_raise
        return []


class ScraplingHonestyTests(unittest.TestCase):
    def test_empty_page_is_not_ok(self) -> None:
        bridge = load_bridge()
        fake_fetchers = ModuleType("scrapling.fetchers")
        fake_fetchers.Fetcher = mock.Mock()
        fake_fetchers.Fetcher.get.return_value = _FakePage(text="", body=None)
        with mock.patch.dict(sys.modules, {"scrapling": ModuleType("scrapling"), "scrapling.fetchers": fake_fetchers}):
            payload = bridge.fetch("https://example.test", "basic", "", 1000)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "empty fetch result")
        self.assertEqual(payload.get("text"), "")

    def test_css_error_is_not_ok(self) -> None:
        bridge = load_bridge()
        fake_fetchers = ModuleType("scrapling.fetchers")
        fake_fetchers.Fetcher = mock.Mock()
        fake_fetchers.Fetcher.get.return_value = _FakePage(text="hello", css_raise=RuntimeError("bad selector"))
        with mock.patch.dict(sys.modules, {"scrapling": ModuleType("scrapling"), "scrapling.fetchers": fake_fetchers}):
            payload = bridge.fetch("https://example.test", "basic", "div.x", 1000)
        self.assertFalse(payload.get("ok"))
        self.assertIn("css_error", payload.get("error") or "")

    def test_extract_empty_output_fails(self) -> None:
        bridge = load_bridge()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "empty.json"
            out.write_text("", encoding="utf-8")
            with mock.patch.object(bridge.shutil, "which", return_value="scrapling"), mock.patch.object(
                bridge.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="ok", stderr="")
            ):
                payload = bridge.extract("https://example.test", str(out))
            self.assertFalse(payload.get("ok"))
            self.assertIn("empty", (payload.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
