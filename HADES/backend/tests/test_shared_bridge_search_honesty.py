"""Shared skill/catalog bridges fail closed on empty search."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[2] / "plugins" / "_shared"


class SharedBridgeSearchHonestyTests(unittest.TestCase):
    def test_skill_search_empty_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge = root / "skill_bridge.py"
            bridge.write_text((SHARED / "skill_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(bridge), "search", "--query", "definitely-missing-xyz-42"],
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("count"), 0)
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(proc.returncode, 0)

    def test_catalog_search_empty_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge = root / "catalog_bridge.py"
            bridge.write_text((SHARED / "catalog_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(bridge), "search", "--query", "definitely-missing-xyz-42"],
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("count"), 0)
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
