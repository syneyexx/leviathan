"""Characterization tests for Gen2 dashboard extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.dashboard import build_dashboard, capability_status_fields
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class DashboardModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name)
        self.store = Gen2Store(str(self.data_root / "dash.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_capability_status_fields_shape(self) -> None:
        row = capability_status_fields(
            implemented=True,
            available=True,
            tested=False,
            quality=False,
            note="probe",
        )
        self.assertEqual(
            set(row),
            {
                "implemented",
                "available_on_host",
                "operationally_tested",
                "quality_evaluated",
                "simulated",
                "degraded",
                "blocked",
                "unverified_on_host",
                "note",
            },
        )
        self.assertTrue(row["implemented"])
        self.assertFalse(row["operationally_tested"])
        self.assertFalse(row["simulated"])
        self.assertEqual(row["note"], "probe")

    def test_build_dashboard_honest_defaults(self) -> None:
        dash = build_dashboard(self.store)
        self.assertIn("capability_status", dash)
        self.assertIn("phase", dash)
        self.assertIn("readiness_note", dash)
        self.assertFalse(dash["live_model_smoke_seen"])
        self.assertFalse(dash["live_model_quality_seen"])
        compute = dash["capability_status"]["5_compute_fabric"]
        self.assertIn("LAN worker MVP", compute["note"])
        self.assertNotIn("remote_dispatch_not_implemented", compute["note"])
        self.assertTrue(dash["phase"]["5_compute_fabric"])
        sandbox = dash["capability_status"]["3_sandbox"]
        self.assertTrue(sandbox["implemented"])
        self.assertTrue(sandbox["available_on_host"])
        self.assertFalse(sandbox["quality_evaluated"])
        self.assertFalse(sandbox["operationally_tested"])
        self.assertFalse(sandbox.get("os_isolation_enforced"))
        # Unit-characterized packages must not auto-claim operationally_tested.
        self.assertFalse(dash["capability_status"]["1_context_compiler"]["operationally_tested"])
        self.assertFalse(dash["capability_status"]["1_flight_recorder"]["operationally_tested"])
        self.assertFalse(dash["capability_status"]["4_finance_fusion"]["operationally_tested"])

    def test_services_dashboard_delegates(self) -> None:
        svc = Gen2Services(self.store, data_root=self.data_root)
        dash = svc.dashboard()
        self.assertIn("nodes", dash)
        self.assertTrue(any(n.get("id") == "node_local" for n in dash["nodes"]))


if __name__ == "__main__":
    unittest.main()
