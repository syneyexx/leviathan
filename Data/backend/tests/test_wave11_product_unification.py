"""Wave 11 — Product unification exit gates (U381–U400 foundations).

Exit gate: Leviathan behaves like one AI operating platform, not a menu of
disconnected modules — one project timeline across chat/research/coding/browser/
artifacts with continuity, editable artifact lineage, schedules/events, and SDK.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.artifacts import ArtifactStore, EditableArtifactRuntime
from Data.modules.execution import (
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
)
from Data.modules.function_runtime.types import SideEffect
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.memory import MemoryStore
from Data.modules.plugins import PluginRegistry
from Data.modules.projects import ProductUnificationPlane
from Data.modules.schedules import ScheduleRunner, ScheduleStore, ScheduleTargetKind


class _EchoModule:
    def __init__(self) -> None:
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
        return {
            "status": "COMPLETED",
            "echo": arguments.get("text") or "ok",
            "project_id": arguments.get("project_id"),
            "call_index": self.calls,
        }


class Wave11ExitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old = {
            "LEVIATHAN_DATABASE_PATH": os.environ.get("LEVIATHAN_DATABASE_PATH"),
            "LEVIATHAN_FEATURE_PRODUCT_UNIFICATION": os.environ.get(
                "LEVIATHAN_FEATURE_PRODUCT_UNIFICATION"
            ),
        }
        os.environ["LEVIATHAN_DATABASE_PATH"] = str(self.root / "wave11.db")
        os.environ["LEVIATHAN_FEATURE_PRODUCT_UNIFICATION"] = "true"
        self.settings = Settings.from_env()
        MigrationRunner(self.settings.database_path).apply_all()

        self.executor = _EchoModule()
        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="wave11.echo",
                name="Echo",
                description="Fixture capability for product unification",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.MODULE,
                provider_ref="wave11.echo",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                output_schema={"type": "object"},
            )
        )
        self.gateway = ExecutionGateway(catalog=catalog, module_executor=self.executor)
        self.plugins = PluginRegistry(catalog)
        self.memory = MemoryStore(self.settings.database_path)
        self.memory.initialize()
        self.artifacts = ArtifactStore(self.settings.database_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.job_store = JobStore(self.settings.database_path)
        self.job_store.initialize()
        self.jobs = JobRuntime(self.job_store, self.gateway, ResourceManager(max_job_concurrency=2))
        self.schedule_store = ScheduleStore(self.settings.database_path)
        self.schedule_store.initialize()
        self.schedules = ScheduleRunner(self.schedule_store, jobs=self.jobs)
        self.plane = ProductUnificationPlane.create(
            self.settings.database_path,
            artifact_store=self.artifacts,
            memory=self.memory,
            gateway=self.gateway,
            plugins=self.plugins,
            schedule_runner=self.schedules,
        )

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_one_operating_platform_exit_gate(self) -> None:
        """Exit gate: one project unifies chat→coding→research→browser→artifact."""
        created = self.plane.sdk.create_project("P-wave11")
        project_id = created["project"]["project_id"]
        workspace_id = created["workspace"]["workspace_id"]
        other, _ = self.plane.projects.create_project("Other")
        other_id = other.project_id
        trace_id = "trace-wave11-platform"

        # Chat → coding → research → browser legs on one timeline / trace.
        for domain, name, entity in (
            ("chat", "message", "msg-1"),
            ("coding", "patch", "patch-1"),
            ("research", "claim", "claim-1"),
            ("browser", "navigate", "nav-1"),
        ):
            self.plane.timeline.append(
                project_id=project_id,
                workspace_id=workspace_id,
                domain=domain,
                name=name,
                entity_id=entity,
                run_id=f"run-{domain}",
                trace_id=trace_id,
                summary=f"{domain}:{name}",
            )

        # Capability invoke via SDK (Gateway) + timeline.
        invoke = self.plane.sdk.invoke_capability(
            "wave11.echo",
            {"text": "hello-platform", "project_id": project_id},
            project_id=project_id,
            run_id="run-capability",
            trace_id=trace_id,
            idempotency_key="wave11-echo-1",
        )
        self.assertEqual(invoke["status"], CapabilityStatus.COMPLETED.value)

        # Editable artifact lineage v1 → v2 (immutable prior hash).
        v1 = self.plane.artifacts.create(
            artifact_type="document",
            title="Platform note",
            sections=[{"id": "s1", "heading": "Intro", "body": "v1"}],
            project_id=project_id,
            run_id="run-artifact",
        )
        self.plane.timeline.append(
            project_id=project_id,
            domain="artifact",
            name="create",
            entity_id=v1.artifact_id,
            trace_id=trace_id,
            summary="Platform note",
        )
        v2 = self.plane.artifacts.edit(
            v1.artifact_id,
            sections=[{"id": "s1", "heading": "Intro", "body": "v2 edited"}],
            patch_note="clarify intro",
            run_id="run-artifact-edit",
        )
        self.plane.timeline.append(
            project_id=project_id,
            domain="artifact",
            name="edit",
            entity_id=v2.artifact_id,
            trace_id=trace_id,
            summary="clarify intro",
        )
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.parent_artifact_id, v1.artifact_id)
        self.assertNotEqual(v2.content_hash, v1.content_hash)
        lineage = self.plane.artifacts.lineage(v1.lineage_id)
        self.assertEqual(len(lineage), 2)

        # Interval schedule + event-triggered schedule under same project.
        interval = self.schedule_store.create(
            name="interval-echo",
            target_kind=ScheduleTargetKind.JOB,
            target_ref="wave11.echo",
            interval_seconds=1,
            start_after_seconds=0,
            target_payload={"arguments": {"text": "interval", "project_id": project_id}},
            metadata={"project_id": project_id},
        )
        event_sched = self.schedule_store.create(
            name="event-echo",
            target_kind=ScheduleTargetKind.EVENT,
            target_ref="artifact.edited",
            interval_seconds=1,
            start_after_seconds=0,
            target_payload={
                "enqueue_kind": "JOB",
                "enqueue_ref": "wave11.echo",
                "arguments": {"text": "from-event"},
            },
            metadata={"project_id": project_id, "event_name": "artifact.edited"},
        )
        tick_results = self.schedules.tick()
        self.assertTrue(any(r.get("ok") for r in tick_results))
        # Re-arm EVENT schedule (mark_ran advances next_run; force due again).
        with self.schedule_store.connect() as conn:
            conn.execute(
                "UPDATE schedules SET next_run_at = ? WHERE schedule_id = ?",
                ("1970-01-01T00:00:00+00:00", event_sched.schedule_id),
            )
        self.schedules.tick()
        event_fires = self.schedules.emit_event(
            "artifact.edited",
            payload={"note": "v2"},
            project_id=project_id,
        )
        self.assertTrue(any(r.get("ok") for r in event_fires))
        self.assertGreaterEqual(self.schedules.telemetry["event_matched"], 1)

        # Plugin + custom agent via SDK (discoverable ≠ second gateway).
        plugin = self.plane.sdk.register_plugin(
            name="wave11-plugin", capability_ids=["wave11.echo"]
        )
        self.assertEqual(plugin["status"], "ENABLED")
        agent = self.plane.sdk.register_custom_agent(
            name="Platform Helper",
            instructions="Stay on shared gateway",
            tools=["wave11.echo"],
            project_id=project_id,
        )
        self.assertTrue(agent["truth"]["custom_agent_uses_shared_cognition_gateway"])

        # Cross-session continuity: handoff + resume; other project does not leak.
        self.plane.continuity.remember_project_fact(
            project_id=project_id,
            content="keep constraint: never invent completion",
            workspace_id=workspace_id,
        )
        self.plane.continuity.remember_project_fact(
            project_id=other_id,
            content="foreign secret should not leak",
        )
        handoff = self.plane.continuity.handoff(
            project_id=project_id,
            from_session_id="chat-session-1",
            to_session_kind="coding",
            summary="continue coding from chat",
            workspace_id=workspace_id,
        )
        self.assertEqual(handoff.to_session_kind, "coding")
        resume = self.plane.continuity.resume_context(
            project_id=project_id, other_project_id=other_id
        )
        self.assertEqual(resume["cross_project_leak_count"], 0)
        self.assertGreaterEqual(len(resume["memories"]), 1)
        own_contents = " ".join(m["content"] for m in resume["memories"])
        self.assertIn("never invent completion", own_contents)
        self.assertNotIn("foreign secret", own_contents)

        # One timeline across domains — not five siloed lists.
        events = self.plane.timeline.list_for_project(project_id)
        domains = set(self.plane.timeline.domains_present(project_id))
        required = {"chat", "coding", "research", "browser", "artifact", "capability"}
        self.assertTrue(required.issubset(domains), f"missing domains: {required - domains}")
        self.assertGreaterEqual(len(events), 6)
        self.assertTrue(all(e.project_id == project_id for e in events))
        traced = [e for e in events if e.trace_id == trace_id]
        self.assertGreaterEqual(len(traced), 5)

        # Platform truth surface.
        status = self.plane.public_dict()
        self.assertTrue(status["truth"]["one_operating_platform"])
        self.assertTrue(status["truth"]["not_menu_of_disconnected_modules"])
        _ = interval  # created for interval path coverage


if __name__ == "__main__":
    unittest.main()
