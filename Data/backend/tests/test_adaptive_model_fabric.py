"""Adaptive Model Fabric — per-device placement, reservations, launch strategy.

Deterministic injectable hardware fixtures. No real GPU required.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.model_runtime.launch_strategy import BackendLaunchStrategy
from Data.modules.model_runtime.managed_adapter import ManagedLocalServingAdapter
from Data.modules.models.contracts import (
    LoadOptions,
    ModelCapabilities,
    ModelDescriptor,
    ModelSource,
    MultiGpuCapability,
    PhysicalPlacement,
    PlacementReason,
    PinMode,
    ResourceProvenance,
    ShardingMode,
)
from Data.modules.models.placement import PlacementPlanner, usable_capacity_for_device
from Data.modules.models.resource_manager import ResourceManager
from Data.modules.workers.admission import AccountingMode, ResourceAdmission, ResourceClass


GB = 1024**3


def _descriptor(model_id: str, *, disk: int | None = None) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        display_name=model_id,
        provider_id="test",
        source=ModelSource.LOCAL,
        capabilities=ModelCapabilities(),
        disk_size_bytes=disk,
    )


def _asymmetric_telemetry() -> dict:
    """16 GB + 6 GB fixture — aggregate 22 GB must NOT imply contiguous fit."""
    return {
        "measured": True,
        "available": True,
        "ageMs": 0,
        "memory": {
            "available": True,
            "totalBytes": 8 * GB,
            "usedBytes": 2 * GB,
            "availableBytes": 6 * GB,
            "utilizationPct": 25.0,
        },
        "gpu": {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "name": "GPU-16GB",
                    "uuid": "GPU-AAAA",
                    "vramTotalBytes": 16 * GB,
                    "vramUsedBytes": 1 * GB,
                    "vramFreeBytes": 15 * GB,
                    "utilizationPct": 10.0,
                    "temperatureC": None,
                    "vendor": "nvidia",
                    "backend": "cuda",
                },
                {
                    "index": 1,
                    "name": "GPU-6GB",
                    "uuid": "GPU-BBBB",
                    "vramTotalBytes": 6 * GB,
                    "vramUsedBytes": 1 * GB,
                    "vramFreeBytes": 5 * GB,
                    "utilizationPct": 5.0,
                    "temperatureC": None,
                    "vendor": "nvidia",
                    "backend": "cuda",
                },
            ],
        },
        "notes": [],
        "truth": {"measured": True, "synthetic": False},
    }


class HardwareSnapshotTests(unittest.TestCase):
    def test_no_gpu_inventory(self) -> None:
        rm = ResourceManager(
            telemetry_provider=lambda: {
                "measured": True,
                "available": True,
                "memory": {"totalBytes": 16 * GB, "availableBytes": 12 * GB},
                "gpu": {"available": False, "devices": []},
            }
        )
        hw = rm.hardware_snapshot()
        self.assertEqual(hw.devices, ())
        self.assertIsNone(hw.aggregate_physical_vram_bytes)
        self.assertEqual(hw.host_memory.total_bytes, 16 * GB)

    def test_aggregate_vs_largest_single(self) -> None:
        rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)
        hw = rm.hardware_snapshot()
        self.assertEqual(len(hw.devices), 2)
        self.assertEqual(hw.aggregate_physical_vram_bytes, 22 * GB)
        self.assertEqual(hw.largest_single_device_total_bytes, 16 * GB)
        self.assertEqual(hw.largest_single_device_free_bytes, 15 * GB)
        # Stable IDs prefer UUID
        ids = {d.stable_device_id for d in hw.devices}
        self.assertIn("gpu-uuid-GPU-AAAA", ids)
        self.assertIn("gpu-uuid-GPU-BBBB", ids)
        public = hw.public_dict()
        self.assertTrue(public["truth"]["aggregateIsNotContiguous"])
        # Unknown temperature stays None — not 0
        self.assertIsNone(hw.devices[0].temperature_c)


class SingleDeviceFitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)

    def test_12gb_main_on_gpu0(self) -> None:
        model = _descriptor("main-12g", disk=12 * GB)
        plan = self.rm.plan_placement(model, vram_override=12 * GB)
        self.assertTrue(plan.feasible)
        self.assertEqual(len(plan.devices), 1)
        self.assertEqual(plan.devices[0].stable_device_id, "gpu-uuid-GPU-AAAA")

    def test_18gb_rejected_without_sharding(self) -> None:
        model = _descriptor("huge-18g", disk=18 * GB)
        plan = self.rm.plan_placement(
            model,
            vram_override=18 * GB,
            multi_gpu_capability=MultiGpuCapability.UNSUPPORTED,
        )
        self.assertFalse(plan.feasible)
        self.assertIn(PlacementReason.INSUFFICIENT_VRAM, plan.reasons)
        # Aggregate 22 must not make it fit
        self.assertEqual(plan.details.get("aggregatePhysicalVramBytes"), 22 * GB)
        self.assertLessEqual(plan.details.get("largestSingleDeviceTotalBytes"), 16 * GB)

    def test_estimate_uses_largest_single_not_aggregate(self) -> None:
        model = _descriptor("est", disk=18 * GB)
        est = self.rm.estimate(model)
        self.assertEqual(est.details.get("aggregatePhysicalVramBytes"), 22 * GB)
        self.assertEqual(est.details.get("largestSingleDeviceTotalBytes"), 16 * GB)
        self.assertTrue(est.details.get("aggregateIsNotContiguous"))
        self.assertEqual(est.details.get("vramAvailabilityScope"), "largest_single_device")


class SpecialistPackingTests(unittest.TestCase):
    def test_small_specialist_prefers_small_gpu(self) -> None:
        rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)
        # Simulate main model already occupying GPU A via reservation occupancy
        held = [
            {
                "device_stable_id": "gpu-uuid-GPU-AAAA",
                "reserved_vram_bytes": 12 * GB,
                "measured_vram_bytes": 12 * GB,
                "accounting": "LIVE_MEASURED",
                "resource_class": "MODEL_INFERENCE",
                "state": "HELD",
            }
        ]
        rm.set_reservation_reader(lambda: held)
        # Free on A after measured: telemetry still shows 15 free raw — capacity
        # reconciles reservation. Force free reduction via custom telemetry.
        def tele() -> dict:
            t = _asymmetric_telemetry()
            t["gpu"]["devices"][0]["vramFreeBytes"] = 3 * GB  # 16-13ish after main
            t["gpu"]["devices"][0]["vramUsedBytes"] = 13 * GB
            return t

        rm.set_telemetry_provider(tele)
        model = _descriptor("embed-2g", disk=2 * GB)
        plan = rm.plan_placement(
            model,
            vram_override=2 * GB,
            workload_class="EMBEDDING",
            latency_class="background",
        )
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.devices[0].stable_device_id, "gpu-uuid-GPU-BBBB")
        self.assertIn(PlacementReason.SPECIALIST_PACKING, plan.reasons)


class DevicePinTests(unittest.TestCase):
    def test_hard_pin_fails_when_too_small(self) -> None:
        rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)
        model = _descriptor("pinned", disk=10 * GB)
        opts = LoadOptions(pinned_device_ids=("gpu-uuid-GPU-BBBB",))
        plan = rm.plan_placement(model, load_options=opts, vram_override=10 * GB)
        self.assertFalse(plan.feasible)
        self.assertIn(PlacementReason.EXPLICIT_PIN, plan.reasons)

    def test_preference_may_fall_back(self) -> None:
        rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)
        model = _descriptor("pref", disk=10 * GB)
        opts = LoadOptions(preferred_device_ids=("gpu-uuid-GPU-BBBB",))
        plan = rm.plan_placement(model, load_options=opts, vram_override=10 * GB)
        # B cannot fit 10GB; preference fails over to A
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.devices[0].stable_device_id, "gpu-uuid-GPU-AAAA")


class MultiGpuCapabilityTests(unittest.TestCase):
    def test_sharding_unsupported(self) -> None:
        rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)
        model = _descriptor("shard-me", disk=18 * GB)
        opts = LoadOptions(allow_multi_gpu=True, sharding_mode=ShardingMode.TENSOR_SPLIT.value)
        plan = rm.plan_placement(
            model,
            load_options=opts,
            vram_override=18 * GB,
            multi_gpu_capability=MultiGpuCapability.UNSUPPORTED,
        )
        self.assertFalse(plan.feasible)
        self.assertIn(PlacementReason.SHARDING_UNSUPPORTED, plan.reasons)

    def test_verified_multi_gpu_plan(self) -> None:
        rm = ResourceManager(telemetry_provider=_asymmetric_telemetry)
        model = _descriptor("shard-ok", disk=18 * GB)
        opts = LoadOptions(allow_multi_gpu=True, sharding_mode=ShardingMode.TENSOR_SPLIT.value)
        plan = rm.plan_placement(
            model,
            load_options=opts,
            vram_override=18 * GB,
            multi_gpu_capability=MultiGpuCapability.SUPPORTED,
        )
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.placement_mode.value, "MULTI_DEVICE")
        self.assertEqual(len(plan.devices), 2)
        self.assertIsNotNone(plan.load_options)
        assert plan.load_options is not None
        self.assertIsNotNone(plan.load_options.tensor_split)


class LowRamTests(unittest.TestCase):
    def test_cpu_offload_blocked_under_critical_ram(self) -> None:
        def tele() -> dict:
            return {
                "measured": True,
                "available": True,
                "memory": {
                    "totalBytes": 8 * GB,
                    "availableBytes": 400 * 1024 * 1024,  # very low
                    "usedBytes": 7 * GB,
                },
                "gpu": {"available": False, "devices": []},
            }

        rm = ResourceManager(
            telemetry_provider=tele,
            min_ram_reserve_bytes=1 * GB,
        )
        model = _descriptor("offload", disk=10 * GB)
        opts = LoadOptions(allow_cpu_offload=True, gpu_offload_layers=0)
        plan = rm.plan_placement(model, load_options=opts, vram_override=0)
        self.assertFalse(plan.feasible)
        self.assertIn(PlacementReason.INSUFFICIENT_RAM, plan.reasons)


class ReservationAccountingTests(unittest.TestCase):
    def test_no_double_count_reservation_and_measured(self) -> None:
        device = MagicMock()
        device.free_vram_bytes = 6 * GB
        device.total_vram_bytes = 16 * GB
        device.used_vram_bytes = 10 * GB
        device.enabled_for_new_work = True
        device.health = MagicMock()
        from Data.modules.models.contracts import ComputeDevice, DeviceHealth

        d = ComputeDevice(
            stable_device_id="gpu-x",
            ordinal=0,
            total_vram_bytes=16 * GB,
            used_vram_bytes=10 * GB,
            free_vram_bytes=6 * GB,
            health=DeviceHealth.HEALTHY,
            enabled_for_new_work=True,
            provenance=ResourceProvenance.MEASURED,
        )
        # Pending 10GB reservation, measured 9.5GB — occupancy is max, not sum.
        cap = usable_capacity_for_device(
            d,
            headroom_bytes=0,
            reserved_bytes=10 * GB,
            measured_owned_bytes=int(9.5 * GB),
        )
        # free=6 already reflects measured ownership on device; pending_extra = max(0, 10-9.5)=0.5GB
        self.assertEqual(cap.usable_bytes, int(6 * GB - 0.5 * GB))

    def test_per_device_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            devices = [
                {"stableDeviceId": "gpu-A", "freeVramBytes": 14 * GB, "enabledForNewWork": True},
                {"stableDeviceId": "gpu-B", "freeVramBytes": 5 * GB, "enabledForNewWork": True},
            ]
            adm = ResourceAdmission(
                db,
                hardware_reader=lambda: {"devices": devices},
                telemetry_reader=lambda: {"ram_available_mb": 4096, "vram_available_mb": 8192},
            )
            adm.initialize()
            a = adm.try_reserve(
                job_id="train",
                worker_id="w1",
                resource_class=ResourceClass.GPU_EXCLUSIVE,
                device_stable_ids=["gpu-A"],
                reserved_vram_bytes=10 * GB,
                shared=False,
            )
            self.assertTrue(a.allowed)
            b = adm.try_reserve(
                job_id="embed",
                worker_id="w2",
                resource_class=ResourceClass.GPU_SHARED,
                device_stable_ids=["gpu-B"],
                reserved_vram_bytes=2 * GB,
                shared=True,
            )
            self.assertTrue(b.allowed, b.reason)

    def test_shared_amount_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            devices = [{"stableDeviceId": "gpu-B", "freeVramBytes": 5 * GB, "enabledForNewWork": True}]
            adm = ResourceAdmission(
                db,
                hardware_reader=lambda: {"devices": devices},
                telemetry_reader=lambda: {"ram_available_mb": 4096, "vram_available_mb": 5000},
            )
            adm.initialize()
            first = adm.try_reserve(
                job_id="j1",
                worker_id="w1",
                resource_class=ResourceClass.GPU_SHARED,
                device_stable_ids=["gpu-B"],
                reserved_vram_bytes=4 * GB,
            )
            self.assertTrue(first.allowed)
            second = adm.try_reserve(
                job_id="j2",
                worker_id="w2",
                resource_class=ResourceClass.GPU_SHARED,
                device_stable_ids=["gpu-B"],
                reserved_vram_bytes=4 * GB,
            )
            self.assertFalse(second.allowed)

    def test_mark_live_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            adm = ResourceAdmission(
                db,
                hardware_reader=lambda: {
                    "devices": [{"stableDeviceId": "gpu-A", "freeVramBytes": 14 * GB}]
                },
                telemetry_reader=lambda: {"ram_available_mb": 4096, "vram_available_mb": 14000},
            )
            adm.initialize()
            d = adm.try_reserve(
                job_id="m1",
                worker_id="res",
                resource_class=ResourceClass.MODEL_INFERENCE,
                device_stable_ids=["gpu-A"],
                reserved_vram_bytes=10 * GB,
                owner_type="model",
                model_id="m1",
            )
            self.assertTrue(d.allowed)
            adm.mark_live(d.reservation_id, measured_vram_bytes=int(9.5 * GB), accounting_mode=AccountingMode.LIVE_MEASURED)
            view = adm.reservation_view_for_planner()
            self.assertEqual(view[0]["accounting"], AccountingMode.LIVE_MEASURED.value)
            self.assertEqual(view[0]["measured_vram_bytes"], int(9.5 * GB))


class ConcurrentReservationTests(unittest.TestCase):
    def test_two_large_models_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            devices = [{"stableDeviceId": "gpu-A", "freeVramBytes": 14 * GB, "enabledForNewWork": True}]
            adm = ResourceAdmission(
                db,
                hardware_reader=lambda: {"devices": devices},
                telemetry_reader=lambda: {"ram_available_mb": 4096, "vram_available_mb": 14000},
            )
            adm.initialize()
            results: list[bool] = []

            def attempt(job: str) -> None:
                d = adm.try_reserve(
                    job_id=job,
                    worker_id=job,
                    resource_class=ResourceClass.MODEL_INFERENCE,
                    device_stable_ids=["gpu-A"],
                    reserved_vram_bytes=10 * GB,
                    owner_type="model",
                )
                results.append(d.allowed)

            t1 = threading.Thread(target=attempt, args=("A",))
            t2 = threading.Thread(target=attempt, args=("B",))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            self.assertEqual(sum(1 for r in results if r), 1)
            self.assertEqual(sum(1 for r in results if not r), 1)


class LaunchStrategyTests(unittest.TestCase):
    def test_load_options_reach_managed_adapter(self) -> None:
        adapter = ManagedLocalServingAdapter(
            provider_id="local",
            backend_kind="llama_cpp",
            mode="inproc",
            allow_inproc_fixture=True,
            multi_gpu_capability=MultiGpuCapability.UNKNOWN,
        )

        async def _run() -> dict:
            return await adapter.load(
                "m1",
                LoadOptions(context_length=4096, gpu_offload_layers=20, pinned_device_ids=("gpu-uuid-GPU-AAAA",)),
            )

        import asyncio

        result = asyncio.run(_run())
        self.assertTrue(result["truth"]["loadOptionsApplied"])
        self.assertEqual(result["launch"]["optionsApplied"]["contextLength"], 4096)
        self.assertEqual(result["launch"]["optionsApplied"]["gpuOffloadLayers"], 20)

    def test_unverified_tensor_split_rejected(self) -> None:
        strategy = BackendLaunchStrategy(
            backend_kind="llama_cpp",
            multi_gpu_capability=MultiGpuCapability.UNSUPPORTED,
            base_command=["llama-server", "-m", "x.gguf", "--port", "8080"],
        )
        from Data.modules.models.errors import ModelControlError

        with self.assertRaises(ModelControlError) as ctx:
            strategy.build(options=LoadOptions(tensor_split=(0.7, 0.3), allow_multi_gpu=True))
        self.assertEqual(ctx.exception.code, "MULTI_GPU_UNSUPPORTED")

    def test_cuda_visible_devices_from_ordinals(self) -> None:
        from Data.modules.models.contracts import DeploymentPlan, DeviceAssignment, PlacementMode

        strategy = BackendLaunchStrategy(
            backend_kind="llama_cpp",
            multi_gpu_capability=MultiGpuCapability.SUPPORTED,
            base_command=["llama-server", "-m", "x.gguf", "--port", "8080"],
        )
        plan = DeploymentPlan(
            plan_id="p1",
            model_id="m",
            devices=(
                DeviceAssignment(stable_device_id="gpu-uuid-GPU-BBBB", ordinal=1, process_visible_ordinal=0),
            ),
            placement_mode=PlacementMode.SINGLE_DEVICE,
            feasible=True,
            load_options=LoadOptions(main_gpu_ordinal=0, gpu_offload_layers=-1),
        )
        spec = strategy.build(plan=plan, options=plan.load_options)
        self.assertEqual(spec.env.get("CUDA_VISIBLE_DEVICES"), "1")
        self.assertEqual(spec.metadata["physicalToVisible"]["1"], 0)


class OrdinalSwapPinTests(unittest.TestCase):
    def test_stable_id_survives_ordinal_swap(self) -> None:
        def tele_before() -> dict:
            t = _asymmetric_telemetry()
            return t

        def tele_after() -> dict:
            t = _asymmetric_telemetry()
            # Swap ordinals; UUIDs stay
            t["gpu"]["devices"][0]["index"] = 1
            t["gpu"]["devices"][0]["uuid"] = "GPU-AAAA"
            t["gpu"]["devices"][1]["index"] = 0
            t["gpu"]["devices"][1]["uuid"] = "GPU-BBBB"
            return t

        rm = ResourceManager(telemetry_provider=tele_before)
        before = {d.stable_device_id: d.ordinal for d in rm.hardware_snapshot().devices}
        self.assertEqual(before["gpu-uuid-GPU-AAAA"], 0)
        rm.set_telemetry_provider(tele_after)
        after = {d.stable_device_id: d.ordinal for d in rm.hardware_snapshot(force_refresh=True).devices}
        self.assertEqual(after["gpu-uuid-GPU-AAAA"], 1)
        # Hard pin by stable ID still targets AAAA even after ordinal swap
        model = _descriptor("pin-stable", disk=4 * GB)
        opts = LoadOptions(pinned_device_ids=("gpu-uuid-GPU-AAAA",))
        plan = rm.plan_placement(model, load_options=opts, vram_override=4 * GB)
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.devices[0].stable_device_id, "gpu-uuid-GPU-AAAA")
        self.assertEqual(plan.devices[0].ordinal, 1)


class MigrationDeviceColumnsTests(unittest.TestCase):
    def test_migration_42_adds_device_columns(self) -> None:
        from Data.backend.migrations import MigrationRunner

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            runner = MigrationRunner(db)
            applied = runner.apply_all()
            self.assertIn(42, applied)
            import sqlite3

            conn = sqlite3.connect(db)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(resource_reservations)")}
            conn.close()
            self.assertIn("device_stable_id", cols)
            self.assertIn("reserved_vram_bytes", cols)
            self.assertIn("accounting_mode", cols)


if __name__ == "__main__":
    unittest.main()
