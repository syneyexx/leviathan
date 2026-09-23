"""Deployment profiles selecting storage/worker backends (U371).

Profiles are capability matrices — not Kubernetes/Terraform dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DeploymentProfileId(str, Enum):
    LOCAL_DESKTOP = "local_desktop"
    GPU_WORKSTATION = "gpu_workstation"
    SINGLE_SERVER = "single_server"
    SMALL_CLUSTER = "small_cluster"
    MULTI_USER_CLUSTER = "multi_user_cluster"
    CI_FIXTURE = "ci_fixture"


@dataclass(frozen=True)
class DeploymentProfile:
    profile_id: DeploymentProfileId
    name: str
    object_store: str  # local_fs | fixture
    worker_transport: str  # local | fixture_remote
    sandbox: str  # report_only | fixture
    otel_exporter: str  # noop | fixture
    queue_backend: str  # sqlite_inline | fixture_partitioned
    postgres: bool = False
    gpu_scheduler: bool = False
    multi_project_isolation: bool = False
    notes: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id.value,
            "name": self.name,
            "object_store": self.object_store,
            "worker_transport": self.worker_transport,
            "sandbox": self.sandbox,
            "otel_exporter": self.otel_exporter,
            "queue_backend": self.queue_backend,
            "postgres": self.postgres,
            "gpu_scheduler": self.gpu_scheduler,
            "multi_project_isolation": self.multi_project_isolation,
            "notes": self.notes,
            "capability_matrix": {
                "object_store": self.object_store,
                "worker_transport": self.worker_transport,
                "sandbox": self.sandbox,
                "otel_exporter": self.otel_exporter,
                "queue_backend": self.queue_backend,
                "postgres": self.postgres,
                "gpu_scheduler": self.gpu_scheduler,
            },
            "truth": {
                "k8s_not_architectural_dependency": True,
                "profile_selects_backends_not_forks_domain_code": True,
            },
        }


PROFILES: dict[DeploymentProfileId, DeploymentProfile] = {
    DeploymentProfileId.LOCAL_DESKTOP: DeploymentProfile(
        profile_id=DeploymentProfileId.LOCAL_DESKTOP,
        name="Local desktop",
        object_store="local_fs",
        worker_transport="local",
        sandbox="report_only",
        otel_exporter="fixture",
        queue_backend="sqlite_inline",
        notes="Default single-user local mode",
    ),
    DeploymentProfileId.GPU_WORKSTATION: DeploymentProfile(
        profile_id=DeploymentProfileId.GPU_WORKSTATION,
        name="GPU workstation",
        object_store="local_fs",
        worker_transport="local",
        sandbox="fixture",
        otel_exporter="fixture",
        queue_backend="sqlite_inline",
        gpu_scheduler=True,
        notes="Single host with fixture GPU claims",
    ),
    DeploymentProfileId.SINGLE_SERVER: DeploymentProfile(
        profile_id=DeploymentProfileId.SINGLE_SERVER,
        name="Single server",
        object_store="local_fs",
        worker_transport="local",
        sandbox="fixture",
        otel_exporter="fixture",
        queue_backend="sqlite_inline",
        gpu_scheduler=True,
    ),
    DeploymentProfileId.SMALL_CLUSTER: DeploymentProfile(
        profile_id=DeploymentProfileId.SMALL_CLUSTER,
        name="Small cluster",
        object_store="fixture",
        worker_transport="fixture_remote",
        sandbox="fixture",
        otel_exporter="fixture",
        queue_backend="fixture_partitioned",
        gpu_scheduler=True,
        multi_project_isolation=True,
        notes="Fixture remote workers — production transport UNMEASURED",
    ),
    DeploymentProfileId.MULTI_USER_CLUSTER: DeploymentProfile(
        profile_id=DeploymentProfileId.MULTI_USER_CLUSTER,
        name="Multi-user cluster",
        object_store="fixture",
        worker_transport="fixture_remote",
        sandbox="fixture",
        otel_exporter="fixture",
        queue_backend="fixture_partitioned",
        postgres=False,  # optional adapter declared but off by default
        gpu_scheduler=True,
        multi_project_isolation=True,
        notes="Postgres/Redis adapters optional and UNMEASURED by default",
    ),
    DeploymentProfileId.CI_FIXTURE: DeploymentProfile(
        profile_id=DeploymentProfileId.CI_FIXTURE,
        name="CI fixture",
        object_store="fixture",
        worker_transport="fixture_remote",
        sandbox="fixture",
        otel_exporter="fixture",
        queue_backend="fixture_partitioned",
        gpu_scheduler=True,
        multi_project_isolation=True,
        notes="Exit-gate profile for Wave 10 recovery tests",
    ),
}


def get_profile(profile_id: str | DeploymentProfileId) -> DeploymentProfile:
    if isinstance(profile_id, str):
        profile_id = DeploymentProfileId(profile_id)
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise KeyError(f"Unknown deployment profile: {profile_id}")
    return profile


def list_profiles() -> list[DeploymentProfile]:
    return list(PROFILES.values())
