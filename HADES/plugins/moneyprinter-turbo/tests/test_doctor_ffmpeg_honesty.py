#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class MoneyPrinterDoctorHonestyTests(unittest.TestCase):
    def test_missing_ffmpeg_is_not_ok(self) -> None:
        with mock.patch.object(hades_bridge.Path, "is_file", return_value=True):
            with mock.patch.object(hades_bridge.shutil, "which", return_value=None):
                out = hades_bridge.doctor()
        self.assertFalse(out.get("ok"))
        self.assertIn("ffmpeg", str(out.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
