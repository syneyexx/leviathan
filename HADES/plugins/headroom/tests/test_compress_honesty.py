
"""Headroom compress must fail closed on empty/null payloads."""
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
    spec = importlib.util.spec_from_file_location("headroom_hades_bridge", ROOT / "hades_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class HeadroomCompressHonestyTests(unittest.TestCase):
    def test_empty_dict_result_is_not_ok(self) -> None:
        bridge = load_bridge()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.txt"
            src.write_text("hello", encoding="utf-8")
            fake = ModuleType("headroom")
            fake.compress = mock.Mock(return_value={})
            with mock.patch.dict(sys.modules, {"headroom": fake}):
                payload = bridge.compress(str(src), "gpt-4o", 2000)
            self.assertFalse(payload.get("ok"))
            self.assertIn("empty", payload.get("error") or "")

    def test_null_result_wrapper_is_not_ok(self) -> None:
        bridge = load_bridge()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.txt"
            src.write_text("hello", encoding="utf-8")
            fake = ModuleType("headroom")
            fake.compress = mock.Mock(return_value={"result": None})
            with mock.patch.dict(sys.modules, {"headroom": fake}):
                payload = bridge.compress(str(src), "gpt-4o", 2000)
            self.assertFalse(payload.get("ok"))


if __name__ == "__main__":
    unittest.main()
