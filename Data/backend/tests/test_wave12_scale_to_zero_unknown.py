"""Wave 12 follow-up — PressureState.UNKNOWN, settings env, scale-to-zero desired."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.workers.admission import (
    PressureState,
    ResourceAdmission,
    ResourceClass,
    classify_pressure,
)
from Data.modules.workers.pools import POOL_CATALOG
from Data.modules.workers.settings import (
    ESSENTIAL_WARM_POOLS,
    WorkerSettings,
    load_worker_settings,
)
from Data.modules.workers.supervisor import WorkerSupervisor


class PressureStateUnknownTests(unittest.TestCase):
    def test_classify_unknown_when_no_telemetry(self) -> None:
        self.assertEqual(classify_pressure(), PressureState.UNKNOWN)
        self.assertEqual(
            classify_pressure(ram_used_pct=None, ram_available_mb=None),
            PressureState.UNKNOWN,
        )

    def test_unknown_is_not_normal(self) -> None:
        self.assertNotEqual(PressureState.UNKNOWN, PressureState.NORMAL)
        self.assertEqual(classify_pressure(ram_used_pct=40.0), PressureState.NORMAL)
        self.assertEqual(classify_pressure(), PressureState.UNKNOWN)

    def test_current_pressure_unknown_without_telemetry_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adm = ResourceAdmission(Path(tmp) / "a.db")
            adm.initialize()
            self.assertEqual(adm.current_pressure(), PressureState.UNKNOWN)
            snap = adm.observability_snapshot()
            self.assertEqual(snap["pressure"], PressureState.UNKNOWN.value)
            self.assertTrue(snap["truth"]["unknown_pressure_is_not_normal"])

    def test_unknown_denies_nonessential_memory_heavy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adm = ResourceAdmission(
                Path(tmp) / "a.db",
                telemetry_reader=lambda: {"source": "none"},
            )
            adm.initialize()
            denied = adm.try_reserve(
                job_id="j-unk",
                worker_id="w1",
                resource_class=ResourceClass.MEMORY_HEAVY,
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.pressure, PressureState.UNKNOWN.value)
            self.assertIn("UNKNOWN", denied.reason)

            protected = adm.try_reserve(
                job_id="j-prot",
                worker_id="w1",
                resource_class=ResourceClass.MEMORY_HEAVY,
                owner_type="paper_trading",
            )
            self.assertTrue(protected.allowed)
            self.assertEqual(protected.pressure, PressureState.UNKNOWN.value)


class WorkerSettingsEnvLoadingTests(unittest.TestCase):
    def test_load_host_profile_and_scale_to_zero_from_env(self) -> None:
        env = {
            "LEVIATHAN_HOST_RAM_MB": "8192",
            "LEVIATHAN_VRAM_PRIMARY_MB": "12288",
            "LEVIATHAN_VRAM_SECONDARY_MB": "4096",
            "LEVIATHAN_RESOURCE_BACKGROUND_RAM_HEADROOM": "256",
            "LEVIATHAN_RESOURCE_BACKGROUND_VRAM_HEADROOM": "128",
            "LEVIATHAN_WORKERS_SCALE_TO_ZERO_ENABLED": "0",
            "LEVIATHAN_WORKERS_SCALE_TO_ZERO_IDLE_SECONDS": "45",
            "LEVIATHAN_WORKERS_SCALE_TO_ZERO_EXEMPT_POOLS": "browser,voice",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            settings = load_worker_settings()
        self.assertEqual(settings.host_ram_mb, 8192.0)
        self.assertEqual(settings.vram_primary_mb, 12288.0)
        self.assertEqual(settings.vram_secondary_mb, 4096.0)
        self.assertEqual(settings.ram_headroom_mb, 256.0)
        self.assertEqual(settings.vram_headroom_mb, 128.0)
        self.assertFalse(settings.scale_to_zero_enabled)
        self.assertEqual(settings.scale_to_zero_idle_seconds, 45.0)
        self.assertEqual(settings.scale_to_zero_exempt_pools, ("browser", "voice"))
        pub = settings.public_dict()["resource"]
        self.assertEqual(pub["host_ram_mb"], 8192.0)
        self.assertIn("db_commit", pub["essential_warm_pools"])

    def test_defaults_match_16_6_profile(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_worker_settings()
        self.assertEqual(settings.host_ram_mb, 16_384.0)
        self.assertEqual(settings.vram_primary_mb, 16_384.0)
        self.assertEqual(settings.vram_secondary_mb, 6_144.0)
        self.assertTrue(settings.scale_to_zero_enabled)


class ScaleToZeroDesiredTests(unittest.TestCase):
    def test_essential_pools_stay_warm(self) -> None:
        settings = WorkerSettings(scale_to_zero_enabled=True)
        for pid in ESSENTIAL_WARM_POOLS:
            self.assertFalse(settings.is_scale_to_zero_eligible(pid))
            self.assertEqual(
                settings.scale_to_zero_desired(pid, queued=0, busy=0, idle_seconds=9999),
                settings.desired_count(pid),
            )

    def test_browser_exempt_stays_warm(self) -> None:
        settings = WorkerSettings(scale_to_zero_enabled=True)
        self.assertFalse(settings.is_scale_to_zero_eligible("browser"))
        self.assertEqual(
            settings.scale_to_zero_desired("browser", queued=0, idle_seconds=9999),
            settings.desired_count("browser"),
        )

    def test_eligible_pool_scales_with_queue_and_idle(self) -> None:
        settings = WorkerSettings(
            scale_to_zero_enabled=True,
            scale_to_zero_idle_seconds=60.0,
            pool_counts={**{p: 0 for p in POOL_CATALOG}, "research": 2},
        )
        self.assertTrue(settings.is_scale_to_zero_eligible("research"))
        self.assertEqual(
            settings.scale_to_zero_desired("research", queued=0, busy=0, idle_seconds=120),
            0,
        )
        self.assertEqual(
            settings.scale_to_zero_desired("research", queued=3, busy=0, idle_seconds=0),
            2,
        )
        self.assertEqual(
            settings.scale_to_zero_desired("research", queued=1, busy=0, idle_seconds=0),
            1,
        )
        # Grace window keeps one warm to prevent thrashing.
        self.assertEqual(
            settings.scale_to_zero_desired("research", queued=0, busy=0, idle_seconds=10),
            1,
        )

    def test_supervisor_does_not_blindly_warm_all_pools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "s.db"
            settings = WorkerSettings(
                scale_to_zero_enabled=True,
                scale_to_zero_idle_seconds=30.0,
                pool_counts={p: 1 for p in POOL_CATALOG},
            )
            queues: dict[str, int] = {}
            supervisor = WorkerSupervisor(
                db,
                settings=settings,
                queue_depth_reader=lambda pid: int(queues.get(pid, 0)),
            )
            supervisor.initialize()
            # Essential / exempt stay configured; eligible cold pools start at 0.
            self.assertEqual(supervisor._pools["db_commit"].desired, 1)
            self.assertEqual(supervisor._pools["scheduler"].desired, 1)
            self.assertEqual(supervisor._pools["market_sim"].desired, 1)
            self.assertEqual(supervisor._pools["browser"].desired, 1)
            self.assertEqual(supervisor._pools["research"].desired, 0)
            self.assertEqual(supervisor._pools["coding"].desired, 0)
            warm = sum(1 for st in supervisor._pools.values() if st.desired > 0)
            self.assertLess(warm, 10)
            self.assertLess(warm, len(POOL_CATALOG) // 2)

            # Demand wakes research only.
            queues["research"] = 2
            supervisor._apply_scale_to_zero_targets()
            self.assertEqual(supervisor._pools["research"].desired, 1)
            self.assertEqual(supervisor._pools["coding"].desired, 0)

            # Idle past timeout returns to zero.
            supervisor._pools["research"].last_demand_at = 0.0
            queues["research"] = 0
            supervisor._apply_scale_to_zero_targets()
            self.assertEqual(supervisor._pools["research"].desired, 0)

    def test_supervisor_wires_host_profile_into_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = WorkerSettings(
                host_ram_mb=8192.0,
                vram_primary_mb=12288.0,
                vram_secondary_mb=4096.0,
                ram_headroom_mb=200.0,
                vram_headroom_mb=100.0,
                pool_counts={p: 0 for p in POOL_CATALOG},
            )
            supervisor = WorkerSupervisor(Path(tmp) / "s.db", settings=settings)
            self.assertEqual(supervisor.admission.host_ram_mb, 8192.0)
            self.assertEqual(supervisor.admission.vram_primary_mb, 12288.0)
            self.assertEqual(supervisor.admission.vram_secondary_mb, 4096.0)
            self.assertEqual(supervisor.admission.ram_headroom_mb, 200.0)
            self.assertEqual(supervisor.admission.vram_headroom_mb, 100.0)


if __name__ == "__main__":
    unittest.main()
