#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class RtkBridgeHonestyTests(unittest.TestCase):
    def test_gain_empty_stdout_is_failure(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "run",
            return_value={"command": ["rtk", "gain"], "exit_code": 0, "stdout": "  ", "stderr": ""},
        ):
            with mock.patch.object(sys, "argv", ["hades_bridge.py", "gain"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    code = hades_bridge.main()
        self.assertNotEqual(code, 0)
        self.assertIn("empty output", out.getvalue())

    def test_gain_with_output_succeeds(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "run",
            return_value={"command": ["rtk", "gain"], "exit_code": 0, "stdout": "gain=1.2", "stderr": ""},
        ):
            with mock.patch.object(sys, "argv", ["hades_bridge.py", "gain"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    code = hades_bridge.main()
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
