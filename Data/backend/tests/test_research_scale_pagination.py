"""Scale / pagination regressions for Research maintenance sweeps."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.research import ResearchService, ResearchStatus, UnconfiguredWebProvider
from Data.modules.research.store import ResearchStore


def _runtime(db: Path) -> JobRuntime:
    store = JobStore(db)
    store.initialize()
    return JobRuntime(
        store,
        ExecutionGateway(catalog=build_default_catalog()),
        ResourceManager(4),
        lease_ttl_seconds=2.0,
    )


class ResearchEnqueuePaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "scale.db"
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.job_runtime = _runtime(self.db)
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            job_runtime=self.job_runtime,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enqueue_queued_projects_covers_beyond_first_100(self) -> None:
        """R-010: more than 100 QUEUED projects must all get advance jobs."""
        ids: list[str] = []
        for i in range(120):
            p = self.service.create_project(
                topic=f"scale topic {i}",
                depth="quick",
                execution_mode="custom",
            )
            # Force QUEUED without going through enqueue_run (which would already enqueue).
            p.status = ResearchStatus.QUEUED
            p.phase = p.phase
            self.store.save_project(p)
            ids.append(p.project_id)

        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            job_ids = self.service.enqueue_queued_projects()
        self.assertGreaterEqual(len(job_ids), 120)
        advance = [
            j
            for j in self.job_runtime.store.list(limit=500)
            if j.capability_id == "research.advance"
        ]
        # JobStore.list is capped; count via entity ids we created.
        linked = 0
        for pid in ids:
            for j in advance:
                if getattr(j, "domain_entity_id", None) == pid:
                    linked += 1
                    break
        # At least first-page + second-page coverage — all 120 should be enqueued
        # via pagination even if list(limit=500) truncates display.
        self.assertEqual(len(job_ids), 120)


if __name__ == "__main__":
    unittest.main()
