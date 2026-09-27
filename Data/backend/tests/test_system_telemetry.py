"""System telemetry — honest CPU/RAM/disk/network/GPU sampling (no fabricated values)."""

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from Data.modules.observability.system_telemetry import (
    NetIoCounters,
    SystemTelemetrySampler,
    collect_system_sample,
    network_rate_from_delta,
    parse_nvidia_smi_csv,
    probe_disk_capacity,
    probe_nvidia_smi,
)


class FakePsutil:
    def __init__(
        self,
        *,
        cpu: float = 18.4,
        total: int = 8_000_000_000,
        available: int = 4_000_000_000,
        percent: float = 50.0,
        bytes_sent: int = 1_000_000,
        bytes_recv: int = 2_000_000,
        net_raises: bool = False,
    ):
        self._cpu = cpu
        self._total = total
        self._available = available
        self._percent = percent
        self._bytes_sent = bytes_sent
        self._bytes_recv = bytes_recv
        self._net_raises = net_raises

    def cpu_percent(self, interval=None):  # noqa: ANN001
        return self._cpu

    def virtual_memory(self):
        used = self._total - self._available
        return SimpleNamespace(total=self._total, available=self._available, used=used, percent=self._percent)

    def net_io_counters(self):
        if self._net_raises:
            raise RuntimeError("net boom")
        return SimpleNamespace(bytes_sent=self._bytes_sent, bytes_recv=self._bytes_recv)


class SystemTelemetryUnitTests(unittest.TestCase):
    def test_cpu_ram_sample_shape_and_bounds(self) -> None:
        sample, _net = collect_system_sample(
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
        self.assertIn("disk", payload)
        self.assertIn("network", payload)
        self.assertEqual(payload["disk"]["metric"], "capacity_utilization")
        self.assertTrue(payload["truth"]["measured"])
        self.assertFalse(payload["truth"]["synthetic"])
        self.assertIsNone(payload["dashboard"]["gpuPct"])
        self.assertIsNone(payload["dashboard"]["vramPct"])
        self.assertEqual(payload["dashboard"]["cpuPct"], 18.4)
        self.assertEqual(payload["dashboard"]["ramPct"], 50.0)

    def test_unavailable_gpu_is_not_zero(self) -> None:
        sample, _net = collect_system_sample(
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
        sample, _net = collect_system_sample(
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
        with tempfile.TemporaryDirectory() as tmp:
            sampler = SystemTelemetrySampler(
                interval_s=10.0,
                gpu_interval_s=10.0,
                data_root=tmp,
            )
            sampler.start()
            try:
                latest = sampler.latest()
                self.assertIsNotNone(latest)
                assert latest is not None
                self.assertFalse(latest.synthetic)
                public = sampler.latest_public()
                self.assertIn("dashboard", public)
                self.assertIn("disk", public)
                self.assertIn("network", public)
                self.assertEqual(public["disk"]["metric"], "capacity_utilization")
                self.assertFalse(public["truth"]["synthetic"])
            finally:
                sampler.stop(timeout=1.0)
            # Second start after stop should work (no duplicate leak).
            sampler.start()
            sampler.stop(timeout=1.0)

    def test_missing_psutil_reports_unavailable(self) -> None:
        class Boom:
            def cpu_percent(self, interval=None):  # noqa: ANN001
                raise RuntimeError("boom")

            def virtual_memory(self):
                raise RuntimeError("boom")

            def net_io_counters(self):
                raise RuntimeError("boom")

        sample, net = collect_system_sample(psutil_module=Boom(), include_gpu=False)
        self.assertFalse(sample.cpu_available)
        self.assertFalse(sample.memory_available)
        self.assertIsNone(sample.cpu_utilization_pct)
        self.assertIsNone(sample.memory_utilization_pct)
        self.assertFalse(sample.network_available)
        self.assertIsNone(sample.network_bytes_per_sec)
        self.assertIsNone(net)

    def test_disk_metric_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def fake_usage(_path):  # noqa: ANN001
                return SimpleNamespace(total=1_000_000_000, used=250_000_000, free=750_000_000)

            fields, notes = probe_disk_capacity(tmp, disk_usage_fn=fake_usage)
            self.assertTrue(fields["available"])
            self.assertEqual(fields["total_bytes"], 1_000_000_000)
            self.assertEqual(fields["used_bytes"], 250_000_000)
            self.assertAlmostEqual(fields["utilization_pct"], 25.0, places=1)
            self.assertEqual(notes, [])

            sample, _net = collect_system_sample(
                psutil_module=FakePsutil(),
                include_gpu=False,
                data_root=tmp,
                disk_usage_fn=fake_usage,
            )
            payload = sample.public_dict()
            self.assertTrue(payload["disk"]["available"])
            self.assertEqual(payload["disk"]["utilizationPct"], 25.0)
            self.assertEqual(payload["disk"]["metric"], "capacity_utilization")
            self.assertEqual(payload["dashboard"]["diskPct"], 25.0)
            # Label is capacity utilization — not an I/O rate field.
            self.assertNotIn("ioOpsPerSec", payload["disk"])
            self.assertNotIn("bytesPerSec", payload["disk"])

    def test_network_first_sample_unmeasured(self) -> None:
        sample, net = collect_system_sample(
            psutil_module=FakePsutil(bytes_sent=1000, bytes_recv=2000),
            include_gpu=False,
            prev_net_io=None,
        )
        self.assertIsNotNone(net)
        self.assertTrue(sample.network_available)
        self.assertIsNone(sample.network_bytes_per_sec)
        self.assertIsNone(sample.public_dict()["network"]["bytesPerSec"])

    def test_network_delta_measured(self) -> None:
        prev = NetIoCounters(bytes_sent=1_000, bytes_recv=2_000, at_ms=1_000.0)
        psutil = FakePsutil(bytes_sent=1_000 + 5_000, bytes_recv=2_000 + 3_000)
        # Force current timestamp via patching network probe timing: call rate helper directly
        # after collect with injected prev; collect uses time.time()*1000 for current.
        sample, current = collect_system_sample(
            psutil_module=psutil,
            include_gpu=False,
            prev_net_io=prev,
        )
        self.assertIsNotNone(current)
        assert current is not None
        # Rate should be measured (positive) given ~now vs at_ms=1000.
        self.assertIsNotNone(sample.network_bytes_per_sec)
        assert sample.network_bytes_per_sec is not None
        self.assertGreater(sample.network_bytes_per_sec, 0.0)
        total, sent, recv = network_rate_from_delta(
            prev,
            NetIoCounters(bytes_sent=6_000, bytes_recv=5_000, at_ms=2_000.0),
        )
        # 1 second delta: 5000+3000 = 8000 B/s
        self.assertAlmostEqual(total or -1, 8_000.0, places=1)
        self.assertAlmostEqual(sent or -1, 5_000.0, places=1)
        self.assertAlmostEqual(recv or -1, 3_000.0, places=1)

    def test_network_counter_reset(self) -> None:
        prev = NetIoCounters(bytes_sent=10_000, bytes_recv=20_000, at_ms=1_000.0)
        current = NetIoCounters(bytes_sent=100, bytes_recv=50, at_ms=2_000.0)
        total, sent, recv = network_rate_from_delta(prev, current)
        self.assertIsNone(total)
        self.assertIsNone(sent)
        self.assertIsNone(recv)
        sample, new_counters = collect_system_sample(
            psutil_module=FakePsutil(bytes_sent=100, bytes_recv=50),
            include_gpu=False,
            prev_net_io=prev,
        )
        self.assertIsNone(sample.network_bytes_per_sec)
        self.assertIsNotNone(new_counters)
        # After reset, subsequent idle/delta from new baseline can measure.
        later = NetIoCounters(bytes_sent=100, bytes_recv=50, at_ms=(new_counters.at_ms if new_counters else 0) + 1000)
        total2, _, _ = network_rate_from_delta(new_counters, later)
        self.assertEqual(total2, 0.0)

    def test_idle_network_can_be_zero(self) -> None:
        prev = NetIoCounters(bytes_sent=5_000, bytes_recv=5_000, at_ms=1_000.0)
        current = NetIoCounters(bytes_sent=5_000, bytes_recv=5_000, at_ms=2_000.0)
        total, sent, recv = network_rate_from_delta(prev, current)
        self.assertEqual(total, 0.0)
        self.assertEqual(sent, 0.0)
        self.assertEqual(recv, 0.0)
        sample, _ = collect_system_sample(
            psutil_module=FakePsutil(bytes_sent=5_000, bytes_recv=5_000),
            include_gpu=False,
            prev_net_io=NetIoCounters(
                bytes_sent=5_000,
                bytes_recv=5_000,
                at_ms=time.time() * 1000 - 1000,
            ),
        )
        self.assertTrue(sample.network_available)
        self.assertIsNotNone(sample.network_bytes_per_sec)
        self.assertAlmostEqual(sample.network_bytes_per_sec or -1, 0.0, places=1)

    def test_metric_failure_does_not_fabricate_zero(self) -> None:
        def boom_usage(_path):  # noqa: ANN001
            raise OSError("disk gone")

        fields, notes = probe_disk_capacity("/tmp", disk_usage_fn=boom_usage)
        self.assertFalse(fields["available"])
        self.assertIsNone(fields["utilization_pct"])
        self.assertIsNone(fields["total_bytes"])
        self.assertNotEqual(fields["utilization_pct"], 0)
        self.assertTrue(any("failed" in n for n in notes))

        sample, net = collect_system_sample(
            psutil_module=FakePsutil(net_raises=True),
            include_gpu=False,
            data_root="/tmp",
            disk_usage_fn=boom_usage,
        )
        self.assertFalse(sample.disk_available)
        self.assertIsNone(sample.disk_utilization_pct)
        self.assertFalse(sample.network_available)
        self.assertIsNone(sample.network_bytes_per_sec)
        self.assertIsNone(net)
        payload = sample.public_dict()
        self.assertIsNone(payload["disk"]["utilizationPct"])
        self.assertIsNone(payload["network"]["bytesPerSec"])
        self.assertIsNone(payload["dashboard"]["diskPct"])

    def test_latest_public_empty_shape_includes_disk_network(self) -> None:
        sampler = SystemTelemetrySampler(interval_s=10.0, gpu_interval_s=10.0)
        empty = sampler.latest_public()
        self.assertIn("disk", empty)
        self.assertIn("network", empty)
        self.assertEqual(empty["disk"]["metric"], "capacity_utilization")
        self.assertIsNone(empty["disk"]["utilizationPct"])
        self.assertIsNone(empty["network"]["bytesPerSec"])
        self.assertIn("diskPct", empty["dashboard"])


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


class OperatorSnapshotMetricTests(unittest.TestCase):
    def test_count_completed_since_and_cache(self) -> None:
        from Data.modules.jobs.store import JobStore
        from Data.modules.jobs.states import JobState
        from Data.backend.routes.observability import (
            _JOBS_24H_CACHE,
            _count_jobs_completed_24h,
            _tasks_per_min,
        )
        from Data.modules.metrics import TimeSeriesStore

        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite")
            store.initialize()
            job = store.create(capability_id="test.op", requested_by="unit")
            store.transition(job.job_id, JobState.QUEUED)
            store.transition(job.job_id, JobState.RUNNING)
            store.transition(job.job_id, JobState.COMPLETED, result={"ok": True})
            # Reset cache for isolation
            _JOBS_24H_CACHE["value"] = None
            _JOBS_24H_CACHE["expires_at"] = 0.0
            _JOBS_24H_CACHE["path"] = None
            n = _count_jobs_completed_24h(store)
            self.assertEqual(n, 1)
            # Cached path should not re-query (poison count method)
            store.count_completed_since = lambda _since: 999  # type: ignore[method-assign]
            n2 = _count_jobs_completed_24h(store)
            self.assertEqual(n2, 1)

            ts = TimeSeriesStore(max_points_per_series=100)
            runtime = SimpleNamespace(telemetry={"completed": 10})
            # First observation — no rate yet
            self.assertIsNone(_tasks_per_min(job_runtime=runtime, timeseries=ts))
            # Inject an older point ~60s ago with lower completed count
            now_ms = time.time() * 1000
            with ts._lock:  # noqa: SLF001
                from Data.modules.metrics.timeseries import MetricSample

                ts._series["jobs.completed"].append(
                    MetricSample(ts_ms=now_ms - 60_000, value=4.0)
                )
            rate = _tasks_per_min(job_runtime=runtime, timeseries=ts)
            self.assertIsNotNone(rate)
            # 6 jobs over ~60s → ~6/min
            assert rate is not None
            self.assertGreater(rate, 4.0)
            self.assertLess(rate, 8.0)


if __name__ == "__main__":
    unittest.main()
