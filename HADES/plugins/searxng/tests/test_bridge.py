#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SearxngBridgeTests(unittest.TestCase):
    def test_empty_with_unresponsive_engines_is_not_success(self) -> None:
        body = {
            "results": [],
            "unresponsive_engines": [["google", "timeout"], ["bing", "timeout"]],
        }
        with mock.patch.object(hades_bridge.urllib.request, "urlopen", return_value=_FakeResponse(body)):
            result = hades_bridge.search("q", "en", 8, "http://127.0.0.1:8080")
        self.assertFalse(result["ok"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(len(result["unresponsive_engines"]), 2)
        self.assertIn("unresponsive engines", result["error"])

    def test_genuine_empty_hit_is_success(self) -> None:
        body = {"results": [], "unresponsive_engines": []}
        with mock.patch.object(hades_bridge.urllib.request, "urlopen", return_value=_FakeResponse(body)):
            result = hades_bridge.search("obscure", "en", 8, "http://127.0.0.1:8080")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["error"])

    def test_connection_error_is_not_success(self) -> None:
        with mock.patch.object(
            hades_bridge.urllib.request,
            "urlopen",
            side_effect=URLError("connection refused"),
        ):
            result = hades_bridge.search("q", "en", 8, "http://127.0.0.1:8080")
        self.assertFalse(result["ok"])
        self.assertIn("request failed", result["error"])

    def test_cli_exits_nonzero_on_dead_engines(self) -> None:
        body = {"results": [], "unresponsive_engines": [["google", "timeout"]]}
        with mock.patch.object(hades_bridge.urllib.request, "urlopen", return_value=_FakeResponse(body)):
            with mock.patch.object(
                sys,
                "argv",
                ["hades_bridge.py", "search", "--query", "q", "--base-url", "http://127.0.0.1:8080"],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    code = hades_bridge.main()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
