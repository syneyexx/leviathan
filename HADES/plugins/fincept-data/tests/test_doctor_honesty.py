#!/usr/bin/env python3
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fincept_hades as fh


class FinceptDoctorHonestyTests(unittest.TestCase):
    def test_doctor_without_key_exits_nonzero(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in {"FINCEPT_API_KEY", "FINCEPT_SESSION_TOKEN"}}
        with mock.patch.dict(os.environ, env, clear=True):
            code = fh.main(["doctor"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
