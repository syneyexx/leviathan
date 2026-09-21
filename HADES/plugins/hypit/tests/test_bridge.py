#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class HypitBridgeTests(unittest.TestCase):
    def test_doctor_ok_when_skill_present(self) -> None:
        payload = hades_bridge.doctor()
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["skills"]["present"])
        self.assertGreater(payload["skills"]["file_count"], 0)
        self.assertTrue((ROOT / "skills" / "hypit" / "SKILL.md").is_file())

    def test_list_examples_includes_fixture(self) -> None:
        payload = hades_bridge.list_examples(limit=20)
        self.assertTrue(payload["ok"], payload)
        paths = {row["path"] for row in payload["examples"]}
        self.assertTrue(any(path.endswith("chat.svml") for path in paths), paths)

    def test_inspect_fixture_svml(self) -> None:
        path = ROOT / "fixtures" / "chat.svml"
        payload = hades_bridge.inspect_source(str(path))
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["kind"], "author")
        self.assertIn("@hypit/markup", str(payload.get("using") or ""))
        self.assertFalse(payload["compiled"])
        self.assertIn("Launch crew", " ".join(payload.get("sample_text") or []))

    def test_inspect_empty_file_is_not_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "blank.svml"
            empty.write_text("   \n", encoding="utf-8")
            payload = hades_bridge.inspect_source(str(empty))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "empty_source")

    def test_inspect_missing_is_not_ok(self) -> None:
        payload = hades_bridge.inspect_source("/no/such/hypit-file.svml")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "source_not_found")

    def test_version_without_cli_is_not_ok(self) -> None:
        with mock.patch.object(hades_bridge, "hypit_launcher", return_value={"ok": False, "error": "hypit_cli_missing"}):
            payload = hades_bridge.hypit_version()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "hypit_cli_missing")

    def test_prepare_without_npm_is_not_ok(self) -> None:
        with mock.patch.object(hades_bridge, "hypit_launcher", return_value={"ok": False, "error": "hypit_cli_missing"}):
            with mock.patch.object(hades_bridge, "node_binary", return_value={"ok": True, "path": "/usr/bin/node"}):
                with mock.patch.object(hades_bridge, "npm_binary", return_value=None):
                    payload = hades_bridge.prepare()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "npm_missing")

    def test_media_fetch_rejects_non_http(self) -> None:
        payload = hades_bridge.hypit_media_fetch("file:///etc/passwd", "out.mp4")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "http_url_required")

    def test_cli_doctor_json(self) -> None:
        with mock.patch.object(sys, "argv", ["hades_bridge.py", "doctor"]):
            code = hades_bridge.main()
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
