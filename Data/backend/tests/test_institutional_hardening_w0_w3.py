"""Wave 1–3 hardening tests: worker context, lessons, trading context fabric."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.market_sim.lesson_retrieval import retrieve_prior_lessons_for_generation
from Data.modules.market_sim.trading_context import (
    TradingContextFabric,
    TradingContextRequest,
)
from Data.modules.workers.context import (
    REQUIRES_BASE,
    REQUIRES_MAINTENANCE,
    WorkerContextError,
    ensure_handler_context,
    validate_worker_context,
)
from Data.modules.workers.pools import POOL_CATALOG


class WorkerContextContractTests(unittest.TestCase):
    def test_missing_settings_raises_typed_error(self) -> None:
        with self.assertRaises(WorkerContextError) as ctx:
            validate_worker_context({"job_store": object()}, requirements=REQUIRES_BASE)
        self.assertIn("settings", ctx.exception.missing)

    def test_maintenance_requirements_allow_reconcile_without_settings(self) -> None:
        ctx = {
            "job_store": object(),
            "admission": object(),
            "registry": object(),
        }
        out = ensure_handler_context(ctx, requirements=REQUIRES_MAINTENANCE)
        self.assertIs(out["job_store"], ctx["job_store"])

    def test_maintenance_stale_race_still_fenced_without_settings(self) -> None:
        """Regression: system.maintenance lease race must not KeyError on settings."""
        from datetime import datetime, timedelta, timezone

        from Data.modules.jobs.states import JobState
        from Data.modules.workers.entrypoints.maintenance import _handler

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "jobs.db"
        store = JobStore(db)
        store.initialize()
        job = store.create(capability_id="system.maintenance", arguments={})
        store.transition(job.job_id, JobState.QUEUED)
        claimed = store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
            capability_ids={"system.maintenance"},
        )
        assert claimed is not None
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")
        with store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
                ("worker-b", past, job.job_id),
            )
            conn.execute(
                "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
                ("worker-b", future, job.job_id),
            )
        store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"recovered": 99, "from": "b"},
            expected_lease_owner="worker-b",
        )
        ctx = {
            "job_store": store,
            "worker_id": "worker-a",
            "admission": mock.Mock(recover_expired=mock.Mock()),
            "registry": mock.Mock(reconcile_stale=mock.Mock()),
        }
        out = _handler(ctx, claimed)
        self.assertEqual(out.get("recovered"), 0)
        final = store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "b")

    def test_import_substring_does_not_trap_system_maintenance(self) -> None:
        from Data.modules.jobs.states import JobState
        from Data.modules.workers.entrypoints.maintenance import _handler

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "jobs.db"
        store = JobStore(db)
        store.initialize()
        job = store.create(capability_id="system.maintenance", arguments={})
        store.transition(job.job_id, JobState.QUEUED)
        claimed = store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
            capability_ids={"system.maintenance"},
        )
        assert claimed is not None
        ctx = {
            "job_store": store,
            "worker_id": "worker-a",
            "admission": mock.Mock(recover_expired=mock.Mock()),
            "registry": mock.Mock(reconcile_stale=mock.Mock()),
        }
        out = _handler(ctx, claimed)
        self.assertIn("recovered", out)
        self.assertNotIn("DB_IMPORT_FAILED", str(out.get("error") or ""))


class JobRuntimeInvariantTests(unittest.TestCase):
    def test_agents_pool_claims_agent_advance(self) -> None:
        agents = POOL_CATALOG["agents"]
        kinds = set(agents.job_kinds)
        self.assertTrue(
            any(k.startswith("agent.") for k in kinds) or "agent.advance" in kinds,
            msg=f"agents pool kinds={kinds}",
        )

    def test_fleet_without_job_runtime_fails_when_externalized(self) -> None:
        import os

        from Data.modules.agents import AgentFleetService, AgentFleetStore, AgentRuntime

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        self.addCleanup(
            lambda: (
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
                if prev is None
                else os.environ.__setitem__("LEVIATHAN_WORKERS_EXTERNALIZE_API", prev)
            )
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "fleet.db"
        gateway = ExecutionGateway(catalog=build_default_catalog())
        fleet = AgentFleetService(
            AgentFleetStore(db),
            AgentRuntime(gateway=gateway, agents_enabled=True),
            job_runtime=None,
        )
        fleet.initialize(seed_defaults=True)
        with self.assertRaises(RuntimeError) as ctx:
            fleet.enqueue_advance("mission-does-not-need-to-exist")
        self.assertIn("job_runtime not bound", str(ctx.exception))

    def test_production_fleet_with_job_runtime_can_enqueue(self) -> None:
        import os

        from Data.modules.agents import AgentFleetService, AgentFleetStore, AgentRuntime

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        self.addCleanup(
            lambda: (
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
                if prev is None
                else os.environ.__setitem__("LEVIATHAN_WORKERS_EXTERNALIZE_API", prev)
            )
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "fleet.db"
        store = JobStore(db)
        store.initialize()
        runtime = JobRuntime(
            store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        gateway = ExecutionGateway(catalog=build_default_catalog())
        fleet = AgentFleetService(
            AgentFleetStore(db),
            AgentRuntime(gateway=gateway, agents_enabled=True),
            job_runtime=runtime,
        )
        fleet.initialize(seed_defaults=True)
        self.assertIsNotNone(fleet.job_runtime)


class LessonRetrievalTests(unittest.TestCase):
    def test_prior_lessons_include_negative_first(self) -> None:
        class _Store:
            def get_agent_lab(self, lab_id):
                return {
                    "lessons": [
                        {
                            "lesson_id": "pos-1",
                            "claim": "momentum worked in trend",
                            "trust": "VALIDATED",
                            "applies_to": ["BTCUSD"],
                            "available_at": "2024-01-01T00:00:00+00:00",
                            "confidence": 0.8,
                        },
                        {
                            "lesson_id": "neg-1",
                            "claim": "transaction-cost failure on high-turnover",
                            "trust": "AGENT_PROPOSED",
                            "applies_to": ["BTCUSD"],
                            "available_at": "2024-01-02T00:00:00+00:00",
                            "confidence": 0.4,
                            "rejected": True,
                        },
                    ]
                }

            def list_strategy_memories(self, **kwargs):
                return [
                    {
                        "memory_id": "mem-rej",
                        "strategy_id": "lab:lab-1",
                        "outcome_summary": "walk-forward collapse under regime shift",
                        "rejected": True,
                        "available_at": "2024-01-03T00:00:00+00:00",
                        "created_at": "2024-01-03T00:00:00+00:00",
                        "metadata": {"epistemic_state": "REJECTED", "evidence_refs": ["e1"]},
                        "applicability": {"applies_to": ["BTCUSD"]},
                    }
                ]

        class _Run:
            lab_id = "lab-1"
            learning_run_id = "lr-1"
            metadata = {"symbols": ["BTCUSD"], "regime": "trend"}

        plane = mock.Mock(store=_Store())
        lessons = retrieve_prior_lessons_for_generation(
            plane,
            _Run(),
            perception={"symbols": ["BTCUSD"], "regime": "trend", "as_of": "2024-06-01T00:00:00+00:00"},
            as_of="2024-06-01T00:00:00+00:00",
        )
        self.assertGreaterEqual(len(lessons), 2)
        self.assertTrue(lessons[0].get("rejected") or lessons[0].get("failure_categories"))

    def test_future_lessons_excluded_by_pit(self) -> None:
        class _Store:
            def get_agent_lab(self, lab_id):
                return {
                    "lessons": [
                        {
                            "lesson_id": "future",
                            "claim": "future leak lesson",
                            "trust": "VALIDATED",
                            "applies_to": ["BTCUSD"],
                            "available_at": "2025-01-01T00:00:00+00:00",
                        }
                    ]
                }

            def list_strategy_memories(self, **kwargs):
                return []

        class _Run:
            lab_id = "lab-1"
            learning_run_id = "lr-1"
            metadata = {}

        plane = mock.Mock(store=_Store())
        lessons = retrieve_prior_lessons_for_generation(
            plane,
            _Run(),
            perception={"as_of": "2024-01-01T00:00:00+00:00"},
            as_of="2024-01-01T00:00:00+00:00",
        )
        self.assertEqual(lessons, [])


class TradingContextFabricTests(unittest.TestCase):
    def test_assemble_surfaces_rejected_and_blocks_future(self) -> None:
        def mem_lister(*, as_of_ts=None, limit=10, **_k):
            return [
                {
                    "memory_id": "ok",
                    "strategy_id": "s1",
                    "outcome_summary": "measured edge",
                    "rejected": False,
                    "available_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {"epistemic_state": "MEASURED"},
                },
                {
                    "memory_id": "bad",
                    "strategy_id": "s2",
                    "outcome_summary": "cost failure",
                    "rejected": True,
                    "available_at": "2024-01-02T00:00:00+00:00",
                    "metadata": {"epistemic_state": "REJECTED"},
                },
                {
                    "memory_id": "future",
                    "strategy_id": "s3",
                    "outcome_summary": "should not appear",
                    "rejected": False,
                    "available_at": "2025-01-01T00:00:00+00:00",
                    "metadata": {"epistemic_state": "MEASURED"},
                },
            ]

        fabric = TradingContextFabric(strategy_memory_lister=mem_lister)
        bundle = fabric.assemble(
            TradingContextRequest(
                role="critic",
                objective="review BTC edge",
                symbols=["BTCUSD"],
                decision_as_of="2024-06-01T00:00:00+00:00",
            )
        )
        ids = {r.ref_id for r in bundle.strategy_memory}
        self.assertIn("ok", ids)
        self.assertIn("bad", ids)
        self.assertNotIn("future", ids)
        self.assertTrue(any(r.rejected for r in bundle.rejected_strategies))
        pub = bundle.public_dict()
        self.assertTrue(pub["truth"]["contextIsNotExecutionAuthority"])
        self.assertTrue(pub["truth"]["noSecondBrain"])


if __name__ == "__main__":
    unittest.main()
