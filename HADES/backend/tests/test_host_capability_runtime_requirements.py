from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from host_capability import check_host_capabilities


class HostCapabilityRuntimeRequirementTests(unittest.TestCase):
    def test_python_310_is_not_reported_ready_for_current_hades_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "host_capability.sys.version_info", (3, 10, 14)
        ), patch(
            "host_capability.sys.version", "3.10.14"
        ), patch(
            "host_capability.shutil.which",
            side_effect=lambda name: f"/fake/{name}" if name in {"node", "npm", "git"} else None,
        ), patch(
            "urllib.request.urlopen", side_effect=OSError("offline probe")
        ):
            result = check_host_capabilities(workspace=Path(temp_dir))

        self.assertFalse(result["checks"]["python"]["available"])
        self.assertEqual(result["status"], "degraded")

    def test_missing_node_and_npm_cannot_still_report_host_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "host_capability.shutil.which",
            side_effect=lambda name: "/fake/git" if name == "git" else None,
        ), patch(
            "urllib.request.urlopen", side_effect=OSError("offline probe")
        ):
            result = check_host_capabilities(workspace=Path(temp_dir))

        self.assertFalse(result["checks"]["node"]["available"])
        self.assertFalse(result["checks"]["npm"]["available"])
        self.assertEqual(result["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
