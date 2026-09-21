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


class AgentReachBridgeTests(unittest.TestCase):
    def test_install_check_propagates_nested_exit(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "run",
            return_value={
                "command": ["agent-reach", "install", "--env=auto", "--safe", "--dry-run"],
                "exit_code": 7,
                "stdout": "",
                "stderr": "boom",
            },
        ):
            with mock.patch.object(sys, "argv", ["hades_bridge.py", "install_check", "--env", "auto"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    code = hades_bridge.main()
        self.assertEqual(code, 1)

    def test_doctor_propagates_nested_cli_exit(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "doctor",
            return_value={
                "cli": {"exit_code": 3, "stdout": "", "stderr": "doctor failed"},
            },
        ):
            with mock.patch.object(sys, "argv", ["hades_bridge.py", "doctor"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    code = hades_bridge.main()
        self.assertNotEqual(code, 0)

    def test_doctor_module_ok_false_exits_nonzero(self) -> None:
        with mock.patch.object(
            hades_bridge,
            "doctor",
            return_value={
                "ok": False,
                "error": "missing_modules:agent_reach",
                "cli": {"exit_code": 0, "stdout": "ok", "stderr": ""},
            },
        ):
            with mock.patch.object(sys, "argv", ["hades_bridge.py", "doctor"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    code = hades_bridge.main()
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
