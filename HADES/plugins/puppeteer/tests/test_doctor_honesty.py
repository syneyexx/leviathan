#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PuppeteerDoctorTests(unittest.TestCase):
    def test_doctor_without_puppeteer_is_nonzero(self) -> None:
        proc = subprocess.run(
            ["node", str(ROOT / "hades_bridge.mjs"), "doctor"],
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        if payload.get("puppeteer_importable"):
            self.assertTrue(payload.get("ok"))
            self.assertEqual(proc.returncode, 0)
        else:
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(proc.returncode, 0)

    def test_screenshot_checks_http_status(self) -> None:
        source = (ROOT / "hades_bridge.mjs").read_text(encoding="utf-8")
        # screenshot path must fail closed on HTTP >=400 like fetch.
        shot = source.split('if (cmd === "screenshot")')[1].split("console.error(`unknown")[0]
        self.assertIn("status >= 400", shot)
        self.assertIn("result.ok === false", shot)


if __name__ == "__main__":
    unittest.main()
