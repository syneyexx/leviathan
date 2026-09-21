
"""Unsloth info must not exit success when modules are missing."""
from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_bridge():
    spec = importlib.util.spec_from_file_location("unsloth_hades_bridge", ROOT / "hades_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class UnslothInfoHonestyTests(unittest.TestCase):
    def test_info_false_when_modules_missing(self) -> None:
        bridge = load_bridge()
        fake = ModuleType("cli_bridge")
        fake.module_status = lambda name: {"module": name, "available": False}
        fake.doctor = lambda modules, binaries: {"ok": False}
        with mock.patch.dict(sys.modules, {"cli_bridge": fake}):
            payload = bridge.info()
        self.assertFalse(payload.get("ok"))
        self.assertIn("missing_modules", payload.get("error") or "")

    def test_info_cli_exits_nonzero_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "hades_bridge.py"
            bridge.write_text((ROOT / "hades_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            (Path(tmp) / "cli_bridge.py").write_text(
                "def doctor(modules, binaries):\n    return {'ok': False}\n"
                "def module_status(name):\n    return {'module': name, 'available': False}\n",
                encoding="utf-8",
            )
            proc = subprocess.run([sys.executable, str(bridge), "info"], capture_output=True, text=True, check=False)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
