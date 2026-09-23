"""Wave 10 production-ops control plane — coordinates existing owners (EXTEND).

Does not replace JobRuntime, ObservabilityHub, ArtifactStore, or SecretsBroker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from Data.modules.artifacts.storage import FixtureObjectStore, LocalFsObjectStore, ObjectStore
from Data.modules.chaos.injector import ChaosInjector
from Data.modules.chaos.scenarios import ChaosScenarioRunner
from Data.modules.execution import ExecutionGateway
from Data.modules.isolation.sandbox_fixture import FixtureSandboxBackend
from Data.modules.jobs.fleet import WorkerFleetRegistry, WorkerKind
from Data.modules.jobs.gpu_scheduler import FixtureGpuScheduler
from Data.modules.jobs.recovery import LeaseRecoveryPlane, RecoveryAction
from Data.modules.jobs.store import JobStore
from Data.modules.observability.otel import FixtureOtelExporter
from Data.modules.observability.slo import SloRegistry, default_production_slos
from Data.modules.ops.deployment import DeploymentProfile, DeploymentProfileId, get_profile
from Data.modules.security.secrets_broker import SecretsBroker


@dataclass
class ProductionOpsPlane:
    """Fixture-backed production operations surface for Wave 10."""

    profile: DeploymentProfile
    fleet: WorkerFleetRegistry
    gpu: FixtureGpuScheduler
    object_store: ObjectStore
    sandbox: FixtureSandboxBackend
    otel: FixtureOtelExporter
    slos: SloRegistry
    chaos_runner: ChaosScenarioRunner
    recovery: LeaseRecoveryPlane | None = None
    secrets: SecretsBroker | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile(
        cls,
        profile_id: str | DeploymentProfileId,
        *,
        store: JobStore | None = None,
        gateway: ExecutionGateway | None = None,
        secrets: SecretsBroker | None = None,
        chaos: ChaosInjector | None = None,
        artifacts_root: Path | None = None,
    ) -> "ProductionOpsPlane":
        profile = get_profile(profile_id)
        fleet = WorkerFleetRegistry()
        # Seed local + fixture remote workers for ci_fixture / cluster profiles.
        fleet.register(
            worker_id="local-main",
            kind=WorkerKind.LOCAL,
            supported_job_kinds=(),
            labels={"role": "local"},
        )
        if profile.worker_transport == "fixture_remote":
            fleet.register(
                worker_id="fixture-remote-1",
                kind=WorkerKind.FIXTURE_REMOTE,
                supported_job_kinds=(),
                project_affinity=(),
                gpu_device_ids=("gpu0",) if profile.gpu_scheduler else (),
                labels={"role": "fixture_remote", "slot": "1"},
            )
            fleet.register(
                worker_id="fixture-remote-2",
                kind=WorkerKind.FIXTURE_REMOTE,
                supported_job_kinds=(),
                project_affinity=(),
                gpu_device_ids=("gpu0",) if profile.gpu_scheduler else (),
                labels={"role": "fixture_remote", "slot": "2"},
            )

        if profile.object_store == "fixture":
            object_store: ObjectStore = FixtureObjectStore()
        else:
            root = Path(artifacts_root or Path("data/object_store"))
            object_store = LocalFsObjectStore(root)

        otel = FixtureOtelExporter()
        slos = SloRegistry()
        for definition in default_production_slos():
            slos.register(definition)

        injector = chaos or ChaosInjector()
        chaos_runner = ChaosScenarioRunner(injector)
        gpu = FixtureGpuScheduler() if profile.gpu_scheduler else FixtureGpuScheduler(devices=[])
        sandbox = FixtureSandboxBackend()

        recovery = None
        if store is not None and gateway is not None:
            recovery = LeaseRecoveryPlane(
                store,
                gateway,
                fleet=fleet,
                secrets=secrets,
            )

        plane = cls(
            profile=profile,
            fleet=fleet,
            gpu=gpu,
            object_store=object_store,
            sandbox=sandbox,
            otel=otel,
            slos=slos,
            chaos_runner=chaos_runner,
            recovery=recovery,
            secrets=secrets,
        )

        def _expire_hook() -> None:
            plane.expire_all_running_leases()

        def _kill_hook() -> None:
            for worker in list(plane.fleet.list_workers()):
                if worker.kind == WorkerKind.FIXTURE_REMOTE and worker.labels.get("slot") == "1":
                    plane.fleet.mark_dead(worker.worker_id)

        chaos_runner.register_hook("expire_lease", _expire_hook)
        chaos_runner.register_hook("mark_worker_dead", _kill_hook)
        return plane

    def expire_all_running_leases(self, *, ttl_seconds: float = -1.0) -> int:
        """Force-expire running leases for chaos/recovery tests."""
        if self.recovery is None:
            return 0
        store = self.recovery.store
        now = datetime.now(timezone.utc)
        # list running with owners
        expired = 0
        for job in store.list(limit=200):
            if job.lease_owner and job.state.value == "RUNNING":
                # Rewrite expiry into the past via acquire with negative/zero ttl workaround:
                past = (now + timedelta(seconds=-5)).isoformat(timespec="seconds")
                with store.connect() as conn:
                    store._ensure_schema(conn)
                    conn.execute(
                        """
                        UPDATE jobs
                        SET lease_expires_at = ?, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (past, now.isoformat(timespec="seconds"), job.job_id),
                    )
                expired += 1
        return expired

    def run_recovery(self, *, project_id: str | None = None, limit: int = 20) -> list[RecoveryAction]:
        if self.recovery is None:
            return []
        span = self.otel.start_span(
            "ops.lease_recovery",
            attributes={"project_id": project_id or "", "profile": self.profile.profile_id.value},
        )
        actions = self.recovery.reclaim_expired(project_id=project_id, limit=limit)
        for action in actions:
            self.slos.record(
                "job_recovery",
                success=action.status in {"recovered", "awaiting_worker"} or action.duplicate_effect_prevented,
                labels={"job_id": action.job_id},
            )
            self.otel.add_event(
                span.span_id,
                "reclaim",
                attributes={
                    "job_id": action.job_id,
                    "status": action.status,
                    "duplicate_effect_prevented": action.duplicate_effect_prevented,
                },
            )
        self.otel.end_span(span.span_id, status="OK")
        return actions

    def public_dict(self) -> dict[str, Any]:
        store_public = getattr(self.object_store, "public_dict", None)
        return {
            "profile": self.profile.public_dict(),
            "fleet": self.fleet.public_dict(),
            "gpu": self.gpu.public_dict(),
            "object_store": store_public() if callable(store_public) else {"backend": self.profile.object_store},
            "sandbox": self.sandbox.public_dict(),
            "otel": self.otel.public_dict(),
            "slos": self.slos.public_dict(),
            "chaos": self.chaos_runner.public_dict(),
            "recovery": self.recovery.public_dict() if self.recovery else None,
            "truth": {
                "extends_existing_owners": True,
                "not_second_job_runtime": True,
                "fixture_backends_not_production_claims": True,
            },
        }
