"""Wave 0 architecture guardrails — ownership, contracts, conformance (U001–U020)."""

from __future__ import annotations

import ast
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.approvals import (
    DEFAULT_AUTHORITY_PROFILE,
    ApprovalMode,
    AuthorityProfile,
)
from Data.modules.common import (
    CANONICAL_OWNERSHIP,
    FORBIDDEN_PRIVATE_DB_FILENAMES,
    SINGLETON_CLASS_OWNERS,
    CorrelationIds,
    ownership_public_dict,
)
from Data.modules.execution import (
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityProviderKind,
    ManifestAvailability,
    build_default_catalog,
    build_frontier_manifest,
)
from Data.modules.function_runtime.types import SideEffect
from Data.modules.jobs import (
    WORKER_PROTOCOL_VERSION,
    JobRuntime,
    JobState,
    JobStore,
    ResourceBudgetEnvelope,
    ResourceManager,
    WorkerProtocolInfo,
)
from Data.modules.run import (
    EVENT_ENVELOPE_SCHEMA_VERSION,
    EventEnvelope,
    EventType,
    RunState,
    RunStore,
)
from Data.modules.settings import DEFAULT_BEHAVIOR_PROFILE, BehaviorProfile

MODULES_ROOT = Path(__file__).resolve().parents[2] / "modules"


class OwnershipMatrixTests(unittest.TestCase):
    def test_ownership_matrix_is_complete_and_modules_exist(self) -> None:
        self.assertGreaterEqual(len(CANONICAL_OWNERSHIP), 20)
        for rule in CANONICAL_OWNERSHIP:
            if rule.owner_module == "backend":
                continue
            path = MODULES_ROOT / rule.owner_module
            self.assertTrue(path.is_dir(), f"Missing owner module: {rule.owner_module}")

    def test_ownership_public_dict_truth_flags(self) -> None:
        payload = ownership_public_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["truth"]["one_owner_per_concern"])
        self.assertTrue(payload["truth"]["extend_over_new"])


class SingletonClassOwnerConformanceTests(unittest.TestCase):
    """Exit gate: a second CapabilityCatalog / ExecutionGateway / etc. fails CI."""

    def test_singleton_classes_have_one_owner_module(self) -> None:
        violations: list[str] = []
        for py_path in MODULES_ROOT.rglob("*.py"):
            rel = py_path.relative_to(MODULES_ROOT)
            owner = rel.parts[0]
            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                expected = SINGLETON_CLASS_OWNERS.get(node.name)
                if expected is None:
                    continue
                if owner != expected:
                    violations.append(f"{rel}: class {node.name} must live in {expected}/")
        self.assertEqual(violations, [], msg="\n".join(violations))

    def test_forbidden_private_db_filenames_not_hardcoded(self) -> None:
        hits: list[str] = []
        for py_path in MODULES_ROOT.rglob("*.py"):
            # Ownership module documents the ban list itself.
            if py_path.name == "ownership.py":
                continue
            text = py_path.read_text(encoding="utf-8")
            for name in FORBIDDEN_PRIVATE_DB_FILENAMES:
                if f'"{name}"' in text or f"'{name}'" in text:
                    hits.append(f"{py_path.relative_to(MODULES_ROOT)}: {name}")
        self.assertEqual(hits, [], msg="Forbidden private DB filenames:\n" + "\n".join(hits))


class BehaviorVsAuthoritySeparationTests(unittest.TestCase):
    def test_profiles_are_distinct_types(self) -> None:
        behavior = DEFAULT_BEHAVIOR_PROFILE
        authority = DEFAULT_AUTHORITY_PROFILE
        self.assertIsInstance(behavior, BehaviorProfile)
        self.assertIsInstance(authority, AuthorityProfile)
        self.assertNotEqual(type(behavior), type(authority))
        self.assertTrue(behavior.public_dict()["truth"]["behavior_is_not_authority"])
        self.assertTrue(authority.public_dict()["truth"]["authority_is_not_behavior"])
        self.assertTrue(behavior.public_dict()["truth"]["system_prompt_is_not_capability_grant"])
        self.assertIn(ApprovalMode.STANDARD, ApprovalMode)

    def test_behavior_hash_is_stable(self) -> None:
        profile = BehaviorProfile(
            id="t",
            version="1",
            system_prompt="hello",
        ).with_hash()
        again = BehaviorProfile(
            id="t",
            version="1",
            system_prompt="hello",
        ).compute_hash()
        self.assertEqual(profile.hash, again)


class EventEnvelopeTests(unittest.TestCase):
    def test_envelope_roundtrip_and_version_guard(self) -> None:
        env = EventEnvelope.create(
            "state_changed",
            run_id="r1",
            trace_id="tr_1",
            payload={"from": "CREATED", "to": "PLANNING"},
        )
        self.assertEqual(env.schema_version, EVENT_ENVELOPE_SCHEMA_VERSION)
        restored = EventEnvelope.from_dict(env.public_dict())
        self.assertEqual(restored.event_id, env.event_id)
        with self.assertRaises(ValueError):
            EventEnvelope.from_dict({**env.public_dict(), "schema_version": 999})


class CorrelationAndRunKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "wave0.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_gets_trace_and_transition_metadata(self) -> None:
        ids = CorrelationIds.create(conversation_id="c1")
        run = self.store.create_run(
            user_request="wave0",
            conversation_id="c1",
            trace_id=ids.trace_id,
        )
        self.assertTrue(run.trace_id)
        self.assertEqual(run.attempt_number, 1)
        updated = self.store.transition(
            run.run_id,
            RunState.PLANNING,
            transition_reason="operator_start",
        )
        self.assertEqual(updated.transition_reason, "operator_start")
        failed = self.store.transition(
            run.run_id,
            RunState.FAILED,
            error="boom",
            transition_reason="probe_failure",
        )
        self.assertTrue(failed.retryable)
        events = self.store.list_events(run.run_id)
        self.assertTrue(any(e.trace_id == run.trace_id for e in events))
        envelope = events[-1].to_envelope()
        self.assertEqual(envelope.schema_version, EVENT_ENVELOPE_SCHEMA_VERSION)
        self.assertIn(EventType.RUN_FAILED, [e.event_type for e in events])


class JobLeaseIdempotencyBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "jobs.db"
        self.store = JobStore(self.db_path)
        self.store.initialize()
        self.catalog = build_default_catalog()
        from Data.modules.execution import ExecutionGateway

        self.gateway = ExecutionGateway(catalog=self.catalog)
        self.runtime = JobRuntime(
            store=self.store,
            gateway=self.gateway,
            resources=ResourceManager(max_job_concurrency=2),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_idempotent_enqueue_converges(self) -> None:
        # Pick any registered capability
        caps = self.catalog.list()
        self.assertTrue(caps)
        cap_id = caps[0].id
        first = self.runtime.enqueue(
            capability_id=cap_id,
            arguments={},
            idempotency_key="idem-1",
            trace_id="tr_jobs",
            budget=ResourceBudgetEnvelope(tool_calls=3).public_dict(),
        )
        second = self.runtime.enqueue(
            capability_id=cap_id,
            arguments={},
            idempotency_key="idem-1",
        )
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(first.trace_id, "tr_jobs")
        self.assertEqual(self.runtime.telemetry.get("idempotent_hits"), 1)

    def test_lease_acquire_heartbeat_and_expiry(self) -> None:
        job = self.store.create(capability_id="noop", arguments={})
        lease = self.store.acquire_lease(job.job_id, worker_id="w1", ttl_seconds=1.0)
        self.assertEqual(lease.worker_id, "w1")
        self.store.heartbeat_lease(job.job_id, worker_id="w1", ttl_seconds=1.0)
        with self.assertRaises(ValueError):
            self.store.acquire_lease(job.job_id, worker_id="w2", ttl_seconds=1.0)
        # Force expiry window in the past
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, lease_expires_at = ? WHERE job_id = ?",
                (JobState.RUNNING.value, past, job.job_id),
            )
        expired = self.store.list_expired_leases()
        self.assertEqual(len(expired), 1)
        # Takeover after expiry
        takeover = self.store.acquire_lease(job.job_id, worker_id="w2", ttl_seconds=30.0)
        self.assertEqual(takeover.worker_id, "w2")

    def test_protocol_negotiation_rejects_mismatch(self) -> None:
        local = WorkerProtocolInfo(protocol_version=WORKER_PROTOCOL_VERSION)
        peer = WorkerProtocolInfo(protocol_version=WORKER_PROTOCOL_VERSION + 1)
        with self.assertRaises(ValueError) as ctx:
            local.negotiate(peer)
        self.assertIn("WORKER_VERSION_MISMATCH", str(ctx.exception))

    def test_budget_exhaustion(self) -> None:
        budget = ResourceBudgetEnvelope(tool_calls=2)
        budget.consume("tool_calls", 2)
        self.assertEqual(budget.exhausted(), ["tool_calls"])


class FrontierManifestTests(unittest.TestCase):
    def test_manifest_from_catalog(self) -> None:
        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="demo.read",
                name="Demo",
                description="demo",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.BUILTIN,
                provider_ref="demo",
                input_schema={},
                output_schema={},
            )
        )
        catalog.register(
            CapabilityDefinition(
                id="demo.mcp",
                name="MCP demo",
                description="mcp",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.MCP,
                provider_ref="mcp://x",
                input_schema={},
                output_schema={},
                available=True,
            )
        )
        manifest = build_frontier_manifest(catalog)
        by_id = {e.capability_id: e for e in manifest.entries}
        self.assertEqual(by_id["demo.read"].availability, ManifestAvailability.READY)
        self.assertEqual(by_id["demo.mcp"].availability, ManifestAvailability.UNMEASURED)
        payload = manifest.public_dict()
        self.assertTrue(payload["truth"]["manifest_is_not_authorization"])
        self.assertTrue(payload["truth"]["ui_must_not_duplicate_capability_truth"])
        self.assertIn("UNMEASURED", payload["counts"])


class DurableKernelMigrationTests(unittest.TestCase):
    def test_migration_creates_profile_tables(self) -> None:
        from Data.backend.migrations import MigrationRunner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.db"
            MigrationRunner(path).apply_all()
            import sqlite3

            with sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertIn("behavior_profiles", tables)
                self.assertIn("authority_profiles", tables)
                cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
                self.assertIn("idempotency_key", cols)
                self.assertIn("lease_owner", cols)


if __name__ == "__main__":
    unittest.main()
