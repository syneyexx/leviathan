"""Wave 12 — resource governor pressure states."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.workers.admission import (
    PressureState,
    ResourceAdmission,
    ResourceClass,
    classify_pressure,
)
from Data.modules.workers.settings import WorkerSettings


class ResourceGovernorTests(unittest.TestCase):
    def test_classify_pressure_thresholds(self) -> None:
        self.assertEqual(classify_pressure(ram_used_pct=40.0), PressureState.NORMAL)
        self.assertEqual(classify_pressure(ram_used_pct=75.0), PressureState.PRESSURE)
        self.assertEqual(classify_pressure(ram_used_pct=90.0), PressureState.CRITICAL)
        self.assertEqual(
            classify_pressure(ram_available_mb=3_000.0, ram_total_mb=16_384.0),
            PressureState.PRESSURE,
        )
        self.assertEqual(
            classify_pressure(vram_used_pct=80.0),
            PressureState.PRESSURE,
        )
        self.assertEqual(
            classify_pressure(vram_used_pct=95.0),
            PressureState.CRITICAL,
        )

    def test_pressure_denies_nonessential_memory_heavy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "adm.db"
            adm = ResourceAdmission(
                db,
                telemetry_reader=lambda: {
                    "ram_available_mb": 3_000.0,
                    "vram_available_mb": 8_000.0,
                    "source": "test",
                },
            )
            adm.initialize()
            denied = adm.try_reserve(
                job_id="j1",
                worker_id="w1",
                resource_class=ResourceClass.MEMORY_HEAVY,
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.pressure, PressureState.PRESSURE.value)
            self.assertIn("PRESSURE", denied.reason)

            # Protected paper / control plane still admitted.
            allowed = adm.try_reserve(
                job_id="j2",
                worker_id="w1",
                resource_class=ResourceClass.MEMORY_HEAVY,
                owner_type="paper_trading",
            )
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.pressure, PressureState.PRESSURE.value)

    def test_critical_sheds_and_protects_db_writer(self) -> None:
        shed_calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "adm.db"
            adm = ResourceAdmission(
                db,
                telemetry_reader=lambda: {
                    "ram_available_mb": 800.0,
                    "vram_available_mb": 200.0,
                    "source": "test",
                },
                cache_shed_hook=lambda: shed_calls.append("cache"),
                model_unload_hook=lambda: shed_calls.append("model"),
                pause_jobs_hook=lambda: shed_calls.append("pause"),
            )
            adm.initialize()
            denied = adm.try_reserve(
                job_id="j3",
                worker_id="w1",
                resource_class=ResourceClass.BATCH,
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.pressure, PressureState.CRITICAL.value)
            self.assertTrue(denied.governor.get("shedCaches"))
            self.assertTrue(denied.governor.get("protectDbWriter"))
            self.assertIn("cache", shed_calls)
            self.assertIn("model", shed_calls)
            self.assertIn("pause", shed_calls)

            protected = adm.try_reserve(
                job_id="j4",
                worker_id="w1",
                resource_class=ResourceClass.DB_SERIAL,
                owner_type="db_commit",
            )
            self.assertTrue(protected.allowed)
            self.assertTrue(protected.governor.get("protectDbWriter"))

    def test_observability_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "adm.db"
            adm = ResourceAdmission(
                db,
                telemetry_reader=lambda: {"ram_available_mb": 10_000.0, "source": "test"},
            )
            adm.initialize()
            snap = adm.observability_snapshot()
            self.assertEqual(snap["pressure"], PressureState.NORMAL.value)
            self.assertEqual(snap["hostProfile"]["ramMb"], 16_384.0)
            self.assertTrue(snap["truth"]["never_kill_db_writer_mid_commit"])

    def test_settings_document_scale_to_zero_and_browser_exempt(self) -> None:
        settings = WorkerSettings()
        pub = settings.public_dict()
        self.assertTrue(pub["resource"]["scale_to_zero_enabled"])
        self.assertIn("browser", pub["resource"]["scale_to_zero_exempt_pools"])
        self.assertEqual(pub["resource"]["pressure_profile"], "16GB_RAM_16_6_VRAM")


if __name__ == "__main__":
    unittest.main()
