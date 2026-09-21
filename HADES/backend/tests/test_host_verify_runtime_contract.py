from __future__ import annotations

import unittest
from pathlib import Path

import host_verify_sim


class HostVerifyRuntimeContractTests(unittest.TestCase):
    @staticmethod
    def _report(*, status: str = "ready", unavailable: str | None = None) -> dict:
        checks = {}
        for name in ("python", "node", "npm", "git", "write_workspace"):
            available = name != unavailable
            checks[name] = {
                "available": available,
                "detail": "fixture" if available else "missing",
                "remediation": "fix fixture" if not available else "",
            }
        return {"status": status, "checks": checks, "isolation": {"os_job_object": False}}

    def test_required_runtime_contract_includes_node_and_npm(self) -> None:
        report = self._report(unavailable="node")
        checks = host_verify_sim._runtime_checks_from_capability_report(report)
        by_name = {item["name"]: item for item in checks}

        self.assertEqual(
            set(by_name),
            {"python", "node", "npm", "git", "write_workspace"},
        )
        self.assertFalse(by_name["node"]["passed"])
        self.assertTrue(by_name["npm"]["passed"])
        self.assertFalse(host_verify_sim._capability_report_is_ready(report))

    def test_degraded_capability_report_cannot_be_host_ready(self) -> None:
        report = self._report(status="degraded")
        self.assertFalse(host_verify_sim._capability_report_is_ready(report))

    def test_supported_required_capabilities_are_host_ready(self) -> None:
        report = self._report(status="ready")
        self.assertTrue(host_verify_sim._capability_report_is_ready(report))

    def test_windows_batch_fails_closed_on_runtime_readiness(self) -> None:
        script = Path(__file__).resolve().parents[2] / "VERIFY_HADES_HOST.bat"
        text = script.read_text(encoding="utf-8")

        self.assertIn("where node", text)
        self.assertIn("where npm", text)
        self.assertIn("Node.js 22.13+ not on PATH", text)
        self.assertIn("r.get('status')=='ready'", text)
        self.assertNotIn("Node not on PATH optional", text)
        self.assertIn("REM Also run Python simulation", text)


if __name__ == "__main__":
    unittest.main()
