#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class GhostTrackBridgeTests(unittest.TestCase):
    def test_track_phone_valid_nl_number(self) -> None:
        try:
            import phonenumbers  # noqa: F401
        except ImportError:
            self.skipTest("phonenumbers not installed")
        result = hades_bridge.track_phone("+31612345678", default_region="NL")
        self.assertTrue(result["ok"])
        self.assertEqual(result["country_code"], 31)
        self.assertEqual(result["region_code"], "NL")
        self.assertIn(result["e164"], {"+31612345678"})
        self.assertIn("note", result)

    def test_track_phone_invalid_is_not_success(self) -> None:
        try:
            import phonenumbers  # noqa: F401
        except ImportError:
            self.skipTest("phonenumbers not installed")
        result = hades_bridge.track_phone("123", default_region="NL")
        self.assertFalse(result["ok"])
        self.assertFalse(result["valid"])
        self.assertIn("invalid", str(result.get("error") or "").lower())
        with mock.patch.object(sys, "argv", ["hades_bridge.py", "track_phone", "--phone", "123", "--default-region", "NL"]):
            code = hades_bridge.main()
        self.assertNotEqual(code, 0)

    def test_track_phone_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            hades_bridge.track_phone("  ")

    def test_track_username_rejects_path(self) -> None:
        with self.assertRaises(ValueError):
            hades_bridge.track_username("foo/bar")

    def test_track_ip_maps_fields(self) -> None:
        fake = {
            "success": True,
            "type": "IPv4",
            "country": "Netherlands",
            "country_code": "NL",
            "city": "Amsterdam",
            "continent": "Europe",
            "continent_code": "EU",
            "region": "North Holland",
            "region_code": "NH",
            "latitude": 52.37,
            "longitude": 4.89,
            "is_eu": True,
            "postal": "1012",
            "calling_code": "31",
            "capital": "Amsterdam",
            "borders": "BE,DE",
            "flag": {"emoji": "🇳🇱"},
            "connection": {"asn": 123, "org": "Example", "isp": "Example ISP", "domain": "example.nl"},
            "timezone": {
                "id": "Europe/Amsterdam",
                "abbr": "CEST",
                "is_dst": True,
                "offset": 7200,
                "utc": "+02:00",
                "current_time": "12:00",
            },
        }
        with mock.patch.object(hades_bridge, "http_get_json", return_value=fake):
            result = hades_bridge.track_ip("1.2.3.4")
        self.assertTrue(result["ok"])
        self.assertEqual(result["country_code"], "NL")
        self.assertEqual(result["isp"], "Example ISP")
        self.assertIn("google.com/maps", result["maps"])

    def test_track_username_classifies_status(self) -> None:
        def fake_get(url: str, timeout: float = 8.0):
            if "github.com" in url:
                return 200, "ok"
            return 404, "missing"

        with mock.patch.object(hades_bridge, "http_get_text", side_effect=fake_get):
            result = hades_bridge.track_username("octocat", max_sites=5)
        self.assertTrue(result["ok"])
        self.assertEqual(result["checked"], 5)
        names = {row["name"] for row in result["found"]}
        self.assertIn("GitHub", names)

    def test_track_username_all_network_errors_is_not_success(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "http_get_text",
            side_effect=TimeoutError("timed out"),
        ):
            result = hades_bridge.track_username("nobody", max_sites=3)
        self.assertFalse(result["ok"])
        self.assertEqual(result["found_count"], 0)
        self.assertEqual(len(result["errors"]), 3)
        self.assertIn("all username probes failed", result["error"])

        with mock.patch.object(
            hades_bridge,
            "http_get_text",
            side_effect=TimeoutError("timed out"),
        ):
            with mock.patch.object(sys, "argv", ["hades_bridge.py", "track_username", "--username", "nobody", "--max-sites", "2"]):
                code = hades_bridge.main()
        self.assertNotEqual(code, 0)

    def test_track_username_all_404_is_legitimate_empty(self) -> None:
        with mock.patch.object(hades_bridge, "http_get_text", return_value=(404, "missing")):
            result = hades_bridge.track_username("ghost", max_sites=3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["found_count"], 0)
        self.assertEqual(len(result["missing"]), 3)

    def test_cli_track_phone_json(self) -> None:
        try:
            import phonenumbers  # noqa: F401
        except ImportError:
            self.skipTest("phonenumbers not installed")
        with mock.patch.object(sys, "argv", ["hades_bridge.py", "track_phone", "--phone", "+31612345678", "--default-region", "NL"]):
            code = hades_bridge.main()
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
