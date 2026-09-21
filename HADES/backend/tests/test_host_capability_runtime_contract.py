from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import host_capability


class HostCapabilityRuntimeContractTests(unittest.TestCase):
    @staticmethod
    def _which(name: str) -> str | None:
        return {
            "node": "/runtime/node",
            "npm": "/runtime/npm",
            "git": "/runtime/git",
        }.get(name)

    def _report(self, *, python_version: tuple[int, int, int], node_version: str):
        completed = subprocess.CompletedProcess(
            args=["/runtime/node", "--version"],
            returncode=0,
            stdout=node_version + "\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            host_capability.sys,
            "version_info",
            python_version,
        ), patch.object(
            host_capability.shutil,
            "which",
            side_effect=self._which,
        ), patch.object(
            host_capability.subprocess,
            "run",
            return_value=completed,
        ), patch(
            "urllib.request.urlopen",
            side_effect=OSError("offline test fixture"),
        ):
            return host_capability.check_host_capabilities(workspace=Path(temp_dir))

    def test_python_310_is_not_ready(self) -> None:
        report = self._report(python_version=(3, 10, 99), node_version="v22.13.0")
        self.assertEqual(report["status"], "degraded")
        self.assertFalse(report["checks"]["python"]["available"])

    def test_node_before_22_13_is_not_ready(self) -> None:
        report = self._report(python_version=(3, 11, 0), node_version="v22.12.9")
        self.assertEqual(report["status"], "degraded")
        self.assertFalse(report["checks"]["node"]["available"])

    def test_supported_python_node_npm_git_and_workspace_are_ready(self) -> None:
        report = self._report(python_version=(3, 11, 0), node_version="v22.13.0")
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["checks"]["python"]["available"])
        self.assertTrue(report["checks"]["node"]["available"])
        self.assertTrue(report["checks"]["npm"]["available"])
        self.assertTrue(report["checks"]["git"]["available"])
        self.assertTrue(report["checks"]["write_workspace"]["available"])
        self.assertFalse(report["checks"]["model_connection"]["available"])


if __name__ == "__main__":
    unittest.main()
