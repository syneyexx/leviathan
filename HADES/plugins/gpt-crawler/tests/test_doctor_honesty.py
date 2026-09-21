#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GptCrawlerDoctorTests(unittest.TestCase):
    def test_packaged_stub_doctor_is_nonzero(self) -> None:
        proc = subprocess.run(["node", str(ROOT / "hades_bridge.mjs"), "doctor"], capture_output=True, text=True)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertTrue(payload.get("stubStart"))
        self.assertNotEqual(proc.returncode, 0)

    def test_real_start_script_doctor_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"name": "gpt-crawler", "scripts": {"start": "node dist/index.js"}}),
                encoding="utf-8",
            )
            bridge = root / "hades_bridge.mjs"
            bridge.write_text((ROOT / "hades_bridge.mjs").read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run(["node", str(bridge), "doctor"], capture_output=True, text=True)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
