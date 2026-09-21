#!/usr/bin/env python3
"""Unit tests for NetStrikerAI HADES bridge helpers (no nmap required)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

# Provide a fake backend/ for offline tools when packing tests run on scaffold only.
FIXTURE_BACKEND = PLUGIN / "tests" / "fixture_backend"


class NetstrikerBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        FIXTURE_BACKEND.mkdir(parents=True, exist_ok=True)
        (FIXTURE_BACKEND / "remediation.py").write_text(
            'REMEDIATION_GUIDE = {22: ("SSH exposed", "Use keys and fail2ban.")}\n'
            "GENERIC_REMEDIATION = (\"Unknown\", \"Restrict and patch.\")\n"
            "def get_remediation(port, service=\"\"):\n"
            "    return REMEDIATION_GUIDE.get(port, GENERIC_REMEDIATION)\n"
            "def get_remediation_text(port, service=\"\"):\n"
            "    return get_remediation(port, service)[1]\n",
            encoding="utf-8",
        )
        (FIXTURE_BACKEND / "compliance.py").write_text(
            "DPDP_MAPPING = {\n"
            "  'high': {'section': 'S8', 'summary': 'high', 'obligation': 'fix'},\n"
            "  'medium': {'section': 'S8', 'summary': 'medium', 'obligation': 'plan'},\n"
            "  'low': {'section': 'S4', 'summary': 'low', 'obligation': 'monitor'},\n"
            "}\n"
            "DPDP_DISCLAIMER = 'guidance only'\n"
            "def add_dpdp_section(risk_label):\n"
            "    info = DPDP_MAPPING.get(risk_label, DPDP_MAPPING['low'])\n"
            "    return {**info, 'disclaimer': DPDP_DISCLAIMER}\n",
            encoding="utf-8",
        )

    def setUp(self) -> None:
        # Point bridge at fixture backend by copying modules beside temporary cwd layout.
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        backend = root / "backend"
        shutil.copytree(FIXTURE_BACKEND, backend)
        shutil.copy2(PLUGIN / "hades_bridge.py", root / "hades_bridge.py")
        shutil.copy2(PLUGIN / "cli_bridge.py", root / "cli_bridge.py")
        self.root = root
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(backend))
        import importlib

        if "hades_bridge" in sys.modules:
            del sys.modules["hades_bridge"]
        self.bridge = importlib.import_module("hades_bridge")
        # Force backend path used by doctor layout checks.
        self.bridge.BACKEND = backend
        self.bridge.ROOT = root

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_loopback_is_safe(self) -> None:
        payload = self.bridge.cmd_resolve("127.0.0.1")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["safe_auto_target"])

    def test_public_ip_not_auto_safe(self) -> None:
        payload = self.bridge.cmd_resolve("8.8.8.8")
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["safe_auto_target"])

    def test_remediation_and_dpdp(self) -> None:
        listed = self.bridge.list_remediation(10)
        self.assertGreaterEqual(listed["count"], 1)
        got = self.bridge.get_remediation(22)
        self.assertIn("fail2ban", got["steps"])
        mapped = self.bridge.dpdp_map("high")
        self.assertEqual(mapped["risk"], "high")
        self.assertIn("disclaimer", mapped["dpdp"])

    def test_scan_requires_authorization(self) -> None:
        with self.assertRaises(ValueError):
            self.bridge.scan_local("127.0.0.1", "false")

    def test_scan_refuses_public_even_when_authorized(self) -> None:
        with self.assertRaises(ValueError):
            self.bridge.scan_local("8.8.8.8", "true")


if __name__ == "__main__":
    unittest.main()
