from __future__ import annotations

import random
import unittest

from Data.modules.chaos import ChaosInjector, ChaosPlan
from Data.modules.metrics import MetricsCollector
from Data.modules.master import MasterGateCheck, MasterGateRunner, MasterGateStatus


class MetricsChaosMasterTests(unittest.TestCase):
    def test_metrics_counters_and_uptime(self) -> None:
        collector = MetricsCollector()
        collector.incr("requests", 2)
        collector.set_gauge("queue", 3.5)
        snap = collector.snapshot(labels={"svc": "test"})
        self.assertEqual(snap.counters["requests"], 2)
        self.assertEqual(snap.gauges["queue"], 3.5)
        self.assertGreaterEqual(snap.gauges["uptime_seconds"], 0.0)
        self.assertTrue(snap.public_dict()["truth"]["metrics_are_not_apm"])

    def test_chaos_default_off(self) -> None:
        injector = ChaosInjector()
        injector.maybe_fault()
        self.assertEqual(injector.activations, 0)

    def test_chaos_can_inject_error(self) -> None:
        injector = ChaosInjector(
            ChaosPlan(enabled=True, latency_ms=0, error_rate=1.0, error_message="boom")
        )
        with self.assertRaises(RuntimeError):
            injector.maybe_fault(rng=random.Random(0))
        self.assertEqual(injector.faults, 1)

    def test_master_gate_blocked_on_failed_check(self) -> None:
        runner = MasterGateRunner(
            checks=[
                lambda: MasterGateCheck(
                    check_id="ok",
                    name="ok",
                    status=MasterGateStatus.READY,
                    detail="ok",
                ),
                lambda: MasterGateCheck(
                    check_id="bad",
                    name="bad",
                    status=MasterGateStatus.BLOCKED,
                    detail="nope",
                ),
            ]
        )
        report = runner.run()
        self.assertEqual(report.status, MasterGateStatus.BLOCKED)
        self.assertTrue(report.public_dict()["truth"]["master_ready_is_not_production_certified"])


if __name__ == "__main__":
    unittest.main()
