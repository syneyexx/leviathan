"""Capability + Neuro production-boundary regressions."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.neuro.adapters import build_residual_runtime


class ResearchCapabilityHonestyTests(unittest.TestCase):
    def test_retrieve_synthesize_marked_unsupported_standalone(self) -> None:
        catalog = build_default_catalog()
        for cap_id in ("research.retrieve", "research.synthesize"):
            cap = catalog.get(cap_id)
            self.assertIsNotNone(cap)
            meta = dict(getattr(cap, "metadata", None) or {})
            self.assertEqual(meta.get("public_availability"), "UNSUPPORTED")
            self.assertEqual(meta.get("canonical_capability"), "research.advance")
            self.assertFalse(meta.get("advertise_as_available", True))


class DeterministicToyProductionGateTests(unittest.TestCase):
    def test_deterministic_refused_outside_allow(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LEVIATHAN_NEURO_ALLOW_DETERMINISTIC_TOY": "0"},
            clear=False,
        ):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            with mock.patch.dict("sys.modules", {k: v for k, v in list(__import__("sys").modules.items()) if k != "pytest" and not k.startswith("_pytest") and not k.startswith("pytest")}):
                # Force allow=False explicitly — production path.
                runtime = build_residual_runtime(kind="deterministic", allow_deterministic_toy=False)
        self.assertFalse(runtime.supports_residuals())
        info = runtime.runtime_info()
        self.assertFalse(info.get("production_grade"))
        self.assertTrue(info.get("truth", {}).get("deterministic_toy_refused_in_production"))

    def test_deterministic_allowed_under_explicit_flag(self) -> None:
        runtime = build_residual_runtime(kind="deterministic", allow_deterministic_toy=True)
        self.assertTrue(runtime.supports_residuals())
        self.assertFalse(runtime.runtime_info().get("production_grade"))


class DatasetLearningStateReachabilityTests(unittest.TestCase):
    def test_stale_job_canonical_when_ready_and_stale(self) -> None:
        from Data.modules.datasets.learning_state import (
            DatasetLearningCanonicalState,
            compute_dataset_learning_state,
        )
        from Data.modules.datasets.types import (
            DatasetIndex,
            DatasetJob,
            DatasetJobStatus,
            DatasetJobType,
            DatasetRecord,
            DatasetStatus,
            IndexStatus,
        )

        ds = DatasetRecord(
            dataset_id="d1",
            name="d1",
            status=DatasetStatus.READY,
            source_type="local",
            created_at="t",
            updated_at="t",
        )
        idx = DatasetIndex(
            index_id="i1",
            dataset_id="d1",
            version_id="v1",
            status=IndexStatus.READY,
            created_at="t",
            updated_at="t",
        )
        job = DatasetJob(
            job_id="j1",
            dataset_id="d1",
            job_type=DatasetJobType.INDEX,
            status=DatasetJobStatus.QUEUED,
            created_at="t",
            updated_at="t",
        )
        state = compute_dataset_learning_state(
            dataset=ds,
            versions=[],
            indexes=[idx],
            jobs=[job],
        )
        self.assertEqual(state.canonical_state, DatasetLearningCanonicalState.STALE_JOB)
        self.assertTrue(state.learned)


if __name__ == "__main__":
    unittest.main()
