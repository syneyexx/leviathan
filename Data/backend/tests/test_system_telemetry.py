"""System telemetry — honest CPU/RAM/GPU sampling (no fabricated values)."""

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from Data.modules.observability.system_telemetry import (
    SystemTelemetrySampler,
    collect_system_sample,
    parse_nvidia_smi_csv,
    probe_nvidia_smi,
)


class FakePsutil:
    def __init__(self, *, cpu: float = 18.4, total: int = 8_000_000_000, available: int = 4_000_000_000, percent: float = 50.0):
        self._cpu = cpu
        self._total = total
        self._available = available
        self._percent = percent

    def cpu_percent(self, interval=None):  # noqa: ANN001
        return self._cpu

    def virtual_memory(self):
        used = self._total - self._available
        return SimpleNamespace(total=self._total, available=self._available, used=used, percent=self._percent)


class SystemTelemetryUnitTests(unittest.TestCase):
    def test_cpu_ram_sample_shape_and_bounds(self) -> None:
        sample = collect_system_sample(
            psutil_module=FakePsutil(),
            include_gpu=False,
        )
        payload = sample.public_dict()
        self.assertTrue(payload["cpu"]["available"])
        self.assertEqual(payload["cpu"]["utilizationPct"], 18.4)
        self.assertTrue(payload["memory"]["available"])
        self.assertEqual(payload["memory"]["totalBytes"], 8_000_000_000)
        self.assertEqual(payload["memory"]["utilizationPct"], 50.0)
        self.assertFalse(payload["gpu"]["available"])
        self.assertEqual(payload["gpu"]["devices"], [])
        self.assertTrue(payload["truth"]["measured"])
        self.assertFalse(payload["truth"]["synthetic"])
        self.assertIsNone(payload["dashboard"]["gpuPct"])
        self.assertIsNone(payload["dashboard"]["vramPct"])
        self.assertEqual(payload["dashboard"]["cpuPct"], 18.4)
        self.assertEqual(payload["dashboard"]["ramPct"], 50.0)

    def test_unavailable_gpu_is_not_zero(self) -> None:
        sample = collect_system_sample(
            psutil_module=FakePsutil(),
            nvidia_probe=lambda: ([], ["nvidia-smi not found"]),
            include_gpu=True,
        )
        payload = sample.public_dict()
        self.assertFalse(payload["gpu"]["available"])
        self.assertIsNone(payload["dashboard"]["gpuPct"])
        self.assertIsNone(payload["dashboard"]["vramPct"])
        self.assertNotEqual(payload["dashboard"]["gpuPct"], 0)
        self.assertTrue(payload["truth"]["unavailableIsNotZero"])

    def test_parse_nvidia_smi_csv(self) -> None:
        rows = parse_nvidia_smi_csv(
            "0, NVIDIA RTX, 34, 8192, 4096, 4096, 535.86\n"
            "1, NVIDIA RTX 2, 12, 16384, 8192, 8192, 535.86\n"
            "bad,line\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].index, 0)
        self.assertEqual(rows[0].utilization_pct, 34.0)
        self.assertEqual(rows[0].vram_utilization_pct, 50.0)
        self.assertEqual(rows[1].utilization_pct, 12.0)

    def test_malformed_nvidia_smi_yields_empty(self) -> None:
        self.assertEqual(parse_nvidia_smi_csv("not,csv\n,,,,"), [])

    def test_probe_nvidia_smi_missing(self) -> None:
        devices, notes = probe_nvidia_smi(which=lambda _name: None)
        self.assertEqual(devices, [])
        self.assertTrue(any("not found" in n for n in notes))

    def test_probe_nvidia_smi_success(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout="0, Test GPU, 22, 1024, 512, 512, 1.0\n",
            stderr="",
        )
        devices, notes = probe_nvidia_smi(
            which=lambda _name: "/usr/bin/nvidia-smi",
            runner=lambda *a, **k: completed,
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].utilization_pct, 22.0)
        self.assertEqual(notes, [])

    def test_dashboard_multi_gpu_max_and_vram_ratio(self) -> None:
        sample = collect_system_sample(
            psutil_module=FakePsutil(cpu=10.0, percent=40.0),
            nvidia_probe=lambda: (
                parse_nvidia_smi_csv(
                    "0, A, 10, 1000, 500, 500, 1\n"
                    "1, B, 40, 3000, 1000, 2000, 1\n"
                ),
                [],
            ),
            include_gpu=True,
        )
        dash = sample.dashboard_gauges()
        self.assertEqual(dash["gpuPct"], 40.0)
        # used 500+2000 / total 1000+3000 = 62.5
        self.assertAlmostEqual(dash["vramPct"] or 0.0, 62.5, places=1)

    def test_sampler_start_stop_no_synthetic(self) -> None:
        sampler = SystemTelemetrySampler(interval_s=10.0, gpu_interval_s=10.0)
        sampler.start()
        try:
            latest = sampler.latest()
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertFalse(latest.synthetic)
            public = sampler.latest_public()
            self.assertIn("dashboard", public)
            self.assertFalse(public["truth"]["synthetic"])
        finally:
            sampler.stop(timeout=1.0)
        # Second start after stop should work (no duplicate leak).
        sampler.start()
        sampler.stop(timeout=1.0)

    def test_missing_psutil_reports_unavailable(self) -> None:
        sample = collect_system_sample(
            psutil_module=None,
            include_gpu=False,
        )
        # Without injection of missing import path: pass a broken module via custom.
        # Force ImportError path by monkeypatching via empty include and fake import isn't easy;
        # instead pass an object that raises.
        class Boom:
            def cpu_percent(self, interval=None):  # noqa: ANN001
                raise RuntimeError("boom")

            def virtual_memory(self):
                raise RuntimeError("boom")

        sample = collect_system_sample(psutil_module=Boom(), include_gpu=False)
        self.assertFalse(sample.cpu_available)
        self.assertFalse(sample.memory_available)
        self.assertIsNone(sample.cpu_utilization_pct)
        self.assertIsNone(sample.memory_utilization_pct)


class ConversationPinnedMigrationTests(unittest.TestCase):
    def test_migration_adds_pinned_and_crud(self) -> None:
        from Data.backend.database import Database
        from Data.backend.migrations import MigrationRunner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.sqlite"
            applied = MigrationRunner(path).apply_all()
            self.assertIn(21, applied)
            db = Database(path)
            db.initialize()
            created = db.create_conversation("Alpha")
            self.assertFalse(created["pinned"])
            updated = db.update_conversation(created["id"], pinned=True, title="Alpha Renamed")
            assert updated is not None
            self.assertTrue(updated["pinned"])
            self.assertEqual(updated["title"], "Alpha Renamed")
            listed = db.list_conversations()
            self.assertEqual(listed[0]["id"], created["id"])
            self.assertTrue(listed[0]["pinned"])
            self.assertTrue(db.delete_conversation(created["id"]))
            self.assertIsNone(db.get_conversation(created["id"]))


class CodingContractAliasTests(unittest.TestCase):
    def test_turn_request_accepts_snake_and_camel(self) -> None:
        from Data.backend.routes.coding import SessionCreate, TurnRequest

        camel = TurnRequest.model_validate({"approvalId": "a1", "capabilityId": "file.write"})
        self.assertEqual(camel.approvalId, "a1")
        self.assertEqual(camel.capabilityId, "file.write")
        snake = TurnRequest.model_validate({"approval_id": "a2", "capability_id": "file.patch"})
        self.assertEqual(snake.approvalId, "a2")
        self.assertEqual(snake.capabilityId, "file.patch")
        session = SessionCreate.model_validate(
            {"goal": "x", "workspace_root": "/tmp/ws", "model_id": "m1"}
        )
        self.assertEqual(session.workspaceRoot, "/tmp/ws")
        self.assertEqual(session.modelId, "m1")


if __name__ == "__main__":
    unittest.main()
