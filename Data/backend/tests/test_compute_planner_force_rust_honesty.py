"""Forced RUST must not claim native for non-allowlisted operations."""

from __future__ import annotations

import unittest

from Data.modules.datasets.compute_planner import ComputeBackend, ComputeBackendPlanner
from Data.modules.workers.native_compute import (
    SUPPORTED_OPERATIONS,
    NativeCapabilities,
    NativeStatus,
)


class ForcedRustHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.caps = NativeCapabilities(
            status=NativeStatus.AVAILABLE,
            protocol_version=1,
            operations=sorted(SUPPORTED_OPERATIONS),
            backend={"name": "rust_native", "version": "0.1.0", "protocolVersion": 1},
            features={"streaming": True},
            binary_path="/tmp/leviathan-data-plane",
            detail="ok",
        )
        self.planner = ComputeBackendPlanner(capabilities=self.caps)

    def test_force_rust_unsupported_stays_python(self) -> None:
        plan = self.planner.plan(
            "dataset.relations", input_bytes=50_000_000, force_backend="rust"
        )
        self.assertEqual(plan.backend, ComputeBackend.PYTHON_STREAMING)
        self.assertEqual(plan.fallback_reason, "forced_rust_unsupported_operation")

    def test_force_rust_allowlisted_selects_native(self) -> None:
        plan = self.planner.plan(
            "dataset.validate", input_bytes=50_000_000, force_backend="rust"
        )
        self.assertEqual(plan.backend, ComputeBackend.RUST_NATIVE)
        self.assertIsNone(plan.fallback_reason)

    def test_auto_relations_remain_python(self) -> None:
        plan = self.planner.plan("dataset.relations", input_bytes=50_000_000)
        self.assertEqual(plan.backend, ComputeBackend.PYTHON_STREAMING)
        self.assertEqual(plan.fallback_reason, "unsupported_native_operation")


if __name__ == "__main__":
    unittest.main()
