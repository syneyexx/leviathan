"""Wave 10 — Production operations and scale exit gates (U341–U380 foundations).

Exit gate: failure of a worker/provider/node produces bounded, observable recovery
without cross-project data leakage or duplicate effects.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.artifacts.storage import FixtureObjectStore
from Data.modules.chaos import ChaosInjector
from Data.modules.execution import (
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
)
from Data.modules.function_runtime.types import SideEffect
from Data.modules.isolation.sandbox_fixture import FixtureSandboxBackend, SandboxLimits
from Data.modules.jobs import JobState, JobStore
from Data.modules.jobs.fleet import WorkerKind
from Data.modules.observability.otel import FixtureOtelExporter
from Data.modules.observability.slo import SloRegistry, default_production_slos
from Data.modules.ops import ProductionOpsPlane, get_profile, list_profiles
from Data.modules.security import SecretsBroker


class _ProjectArtifactExecutor:
    """MODULE executor that writes bytes into a project-scoped object store."""

    def __init__(self, store: FixtureObjectStore) -> None:
        self.store = store
        self.calls = 0

    def execute_module_capability(
        self,
        capability_id: str,
        provider_ref: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        project_id = str(arguments.get("project_id") or "default")
        payload = str(arguments.get("payload") or "x").encode("utf-8")
        key = str(arguments.get("key") or "artifact.bin")
        ref = self.store.put(payload, key=key, project_id=project_id)
        return {
            "status": "COMPLETED",
            "object_id": ref.object_id,
            "content_hash": ref.content_hash,
            "project_id": project_id,
            "call_index": self.calls,
        }


class DeploymentProfileTests(unittest.TestCase):
    def test_profiles_expose_capability_matrices(self) -> None:
        profiles = list_profiles()
        self.assertGreaterEqual(len(profiles), 5)
        ci = get_profile("ci_fixture")
        self.assertEqual(ci.object_store, "fixture")
        self.assertEqual(ci.worker_transport, "fixture_remote")
        self.assertTrue(ci.multi_project_isolation)
        self.assertTrue(ci.public_dict()["truth"]["k8s_not_architectural_dependency"])


class OtelAndSloTests(unittest.TestCase):
    def test_fixture_otel_and_slo_evaluation(self) -> None:
        otel = FixtureOtelExporter()
        span = otel.start_span("api.request", attributes={"route": "/health"})
        otel.add_event(span.span_id, "db.query")
        otel.end_span(span.span_id, status="OK")
        export = otel.export_otlp_shaped()
        self.assertIn("resourceSpans", export)
        self.assertTrue(export["truth"]["fixture_otlp_shape_not_network_export"])

        slos = SloRegistry()
        for definition in default_production_slos():
            slos.register(definition)
        for _ in range(10):
            slos.record("gateway_success", success=True, latency_ms=12.0)
        slos.record("gateway_success", success=False, latency_ms=90.0)
        evaluation = slos.evaluate("gateway_success")
        self.assertGreaterEqual(evaluation.success_ratio, 0.9)
        self.assertTrue(evaluation.public_dict()["sample_count"] >= 11)


class SandboxIsolationTests(unittest.TestCase):
    def test_fixture_sandbox_denies_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ws"
            sandbox = FixtureSandboxBackend()
            session = sandbox.open_session(
                project_id="P1",
                workspace_root=root,
                limits=SandboxLimits(writable_roots=(str(root.resolve()),)),
            )
            ok = sandbox.check_path(session, root / "ok.txt", write=True)
            self.assertTrue(ok.ok)
            denied = sandbox.check_path(session, Path(tmp) / "outside.txt", write=True)
            self.assertFalse(denied.ok)
            self.assertEqual(denied.denied_reason, "path_outside_workspace")


class Wave10ExitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old = {
            "LEVIATHAN_DATABASE_PATH": os.environ.get("LEVIATHAN_DATABASE_PATH"),
            "LEVIATHAN_FEATURE_PRODUCTION_OPS": os.environ.get("LEVIATHAN_FEATURE_PRODUCTION_OPS"),
            "LEVIATHAN_DEPLOYMENT_PROFILE": os.environ.get("LEVIATHAN_DEPLOYMENT_PROFILE"),
        }
        os.environ["LEVIATHAN_DATABASE_PATH"] = str(self.root / "wave10.db")
        os.environ["LEVIATHAN_FEATURE_PRODUCTION_OPS"] = "true"
        os.environ["LEVIATHAN_DEPLOYMENT_PROFILE"] = "ci_fixture"
        self.settings = Settings.from_env()
        MigrationRunner(self.settings.database_path).apply_all()

        self.object_store = FixtureObjectStore()
        self.executor = _ProjectArtifactExecutor(self.object_store)
        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="ops.project_artifact.write",
                name="Write project artifact",
                description="Fixture side-effect write into project-scoped object store",
                side_effects=(SideEffect.READ,),  # auto-allowed for test dispatch
                provider_kind=CapabilityProviderKind.MODULE,
                provider_ref="ops.project_artifact",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "payload": {"type": "string"},
                        "key": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                output_schema={"type": "object"},
            )
        )
        self.gateway = ExecutionGateway(catalog=catalog, module_executor=self.executor)
        self.job_store = JobStore(self.settings.database_path)
        self.job_store.initialize()
        self.secrets = SecretsBroker(
            self.settings.database_path,
            overrides={"env:P1_TOKEN": "super-secret-p1-token"},
        )
        self.secrets.initialize()
        self.ops = ProductionOpsPlane.from_profile(
            "ci_fixture",
            store=self.job_store,
            gateway=self.gateway,
            secrets=self.secrets,
            chaos=ChaosInjector(),
            artifacts_root=self.root / "objects",
        )
        # Prefer fixture remotes; mark local as dead so reclaim uses remote-2.
        self.ops.fleet.mark_dead("local-main")

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_worker_failure_bounded_recovery_no_leak_no_dup(self) -> None:
        """Exit gate: expire lease → reclaim → no duplicate effect / no cross-project leak."""
        project_p1 = "P1"
        project_p2 = "P2"

        # Seed object in P1 via first successful capability execution (caches idempotency).
        idem = "effect-key-wave10-1"
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="ops.project_artifact.write",
                arguments={"project_id": project_p1, "payload": "alpha", "key": "a.bin"},
                request_id="req-1",
                idempotency_key=idem,
                trace_id="trace-wave10",
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)
        object_id = first.output["object_id"]
        first_effects = len(self.gateway.effect_ledger)
        self.assertEqual(first_effects, 1)
        self.assertEqual(self.executor.calls, 1)

        # P2 cannot read P1 object.
        with self.assertRaises(PermissionError):
            self.object_store.get(object_id, project_id=project_p2)
        self.assertEqual(len(self.object_store.list_for_project(project_p2)), 0)
        self.assertEqual(len(self.object_store.list_for_project(project_p1)), 1)

        # Secrets lease for worker-1; sandbox session for P1.
        lease = self.secrets.issue(
            "env:P1_TOKEN",
            scope="project:P1",
            issued_to="fixture-remote-1",
            metadata={"project_id": project_p1},
        )
        plaintext = self.secrets.resolve_lease(lease.lease_id, issued_to="fixture-remote-1")
        self.assertEqual(plaintext, "super-secret-p1-token")

        workspace = self.root / "sandbox" / project_p1
        session = self.ops.sandbox.open_session(project_id=project_p1, workspace_root=workspace)
        self.assertTrue(
            self.ops.sandbox.check_path(session, workspace / "ok.txt", write=True).ok
        )

        # Create RUNNING job owned by fixture-remote-1 with same idempotency key.
        job = self.job_store.create(
            capability_id="ops.project_artifact.write",
            arguments={"project_id": project_p1, "payload": "alpha", "key": "a.bin"},
            requested_by="wave10-test",
            trace_id="trace-wave10",
            idempotency_key=idem,
            metadata={"project_id": project_p1},
        )
        job = self.job_store.transition(job.job_id, JobState.QUEUED)
        job = self.job_store.transition(job.job_id, JobState.RUNNING)
        self.job_store.acquire_lease(job.job_id, worker_id="fixture-remote-1", ttl_seconds=30.0)

        # Chaos: kill worker-1 + expire lease.
        self.ops.chaos_runner.apply("kill_worker", run_hooks=True)
        # Ensure expiry even if hook ordering differs.
        past = (datetime.now(timezone.utc) + timedelta(seconds=-10)).isoformat(timespec="seconds")
        with self.job_store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
                (past, job.job_id),
            )

        actions = self.ops.run_recovery(project_id=project_p1, limit=10)
        self.assertGreaterEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action.job_id, job.job_id)
        self.assertEqual(action.previous_worker_id, "fixture-remote-1")
        self.assertEqual(action.new_worker_id, "fixture-remote-2")
        self.assertTrue(action.duplicate_effect_prevented)
        self.assertGreaterEqual(action.secrets_revoked, 1)

        # No second effect ledger row / no second module dispatch.
        self.assertEqual(len(self.gateway.effect_ledger), 1)
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(
            int(self.gateway.telemetry.get("idempotent_replays", 0)),
            1,
        )

        # Revoked secret cannot resolve.
        with self.assertRaises(PermissionError):
            self.secrets.resolve_lease(lease.lease_id, issued_to="fixture-remote-1")

        # Still no cross-project leakage.
        self.assertEqual(len(self.object_store.list_for_project(project_p2)), 0)
        with self.assertRaises(PermissionError):
            self.object_store.get(object_id, project_id=project_p2)

        # Observable: OTel span + SLO sample recorded.
        spans = self.ops.otel.list_spans()
        self.assertTrue(any(s.name == "ops.lease_recovery" for s in spans))
        recovery_slo = self.ops.slos.evaluate("job_recovery")
        self.assertGreaterEqual(recovery_slo.sample_count, 1)

        refreshed = self.job_store.get(job.job_id)
        assert refreshed is not None
        self.assertEqual(refreshed.state, JobState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
