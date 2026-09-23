"""Wave 11 product unification control plane — one operating surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Data.modules.artifacts import ArtifactStore, EditableArtifactRuntime
from Data.modules.execution import ExecutionGateway
from Data.modules.memory import MemoryStore
from Data.modules.plugins import PluginRegistry
from Data.modules.projects.continuity import ContinuityPlane
from Data.modules.projects.store import ProjectStore
from Data.modules.schedules import ScheduleRunner, ScheduleStore
from Data.modules.sdk.fixture import FixtureSdk
from Data.modules.timeline.store import WorkTimeline


@dataclass
class ProductUnificationPlane:
    projects: ProjectStore
    timeline: WorkTimeline
    artifacts: EditableArtifactRuntime
    continuity: ContinuityPlane
    sdk: FixtureSdk
    schedules: ScheduleRunner | None = None

    @classmethod
    def create(
        cls,
        db_path: Path,
        *,
        artifact_store: ArtifactStore,
        memory: MemoryStore,
        gateway: ExecutionGateway,
        plugins: PluginRegistry | None = None,
        schedule_store: ScheduleStore | None = None,
        schedule_runner: ScheduleRunner | None = None,
    ) -> "ProductUnificationPlane":
        projects = ProjectStore(db_path)
        projects.initialize()
        timeline = WorkTimeline(db_path, projects=projects)
        timeline.initialize()
        continuity = ContinuityPlane(memory, projects)
        runtime = EditableArtifactRuntime(artifact_store)
        sdk = FixtureSdk(
            projects=projects,
            timeline=timeline,
            gateway=gateway,
            plugins=plugins,
        )
        return cls(
            projects=projects,
            timeline=timeline,
            artifacts=runtime,
            continuity=continuity,
            sdk=sdk,
            schedules=schedule_runner,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "projects": len(self.projects.list_projects()),
            "sdk": self.sdk.public_dict(),
            "truth": {
                "one_operating_platform": True,
                "not_menu_of_disconnected_modules": True,
                "domains_keep_own_storage": True,
            },
        }
