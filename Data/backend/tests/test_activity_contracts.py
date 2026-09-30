"""Wave 1 — ActivityEvent / DecisionReceipt contract tests."""

from __future__ import annotations

import unittest

from Data.modules.run import (
    ACTIVITY_SCHEMA_VERSION,
    ActivityCategory,
    ActivityEmitter,
    ActivityEvent,
    ActivityLifecycle,
    ActivityPhase,
    ActivityProjector,
    ActorType,
    ConfigTriple,
    DecisionReceipt,
    EventType,
    ProgressKind,
    ProgressMeasurement,
    VisibilityClass,
    activity_from_cognition_operational_event,
    activity_from_team_event,
    decision_receipt_from_packet,
    legacy_steps_to_plan_events,
)


class ActivityContractTests(unittest.TestCase):
    def test_public_dict_schema_and_truth_flags(self) -> None:
        event = ActivityEvent(
            event_id="e1",
            operation_id="op1",
            sequence=1,
            category=ActivityCategory.REQUEST,
            phase=ActivityPhase.REQUEST_UNDERSTOOD,
            lifecycle=ActivityLifecycle.COMPLETED,
            title="Request interpreted",
            summary="The request has been classified.",
            actor_type=ActorType.LEVIATHAN,
            progress=ProgressMeasurement.indeterminate(basis="classification"),
        )
        pub = event.public_dict()
        assert pub is not None
        self.assertEqual(pub["schemaVersion"], ACTIVITY_SCHEMA_VERSION)
        self.assertEqual(pub["lifecycle"], "completed")
        self.assertTrue(pub["truth"]["operational_telemetry_not_cot"])
        self.assertTrue(pub["truth"]["progress_not_fabricated"])
        self.assertEqual(pub["progress"]["kind"], "indeterminate")

    def test_internal_visibility_hidden_from_user(self) -> None:
        event = ActivityEvent(
            event_id="e2",
            operation_id="op1",
            sequence=2,
            category=ActivityCategory.SYSTEM,
            phase=ActivityPhase.UNKNOWN,
            lifecycle=ActivityLifecycle.RUNNING,
            title="Internal",
            visibility=VisibilityClass.INTERNAL,
        )
        self.assertIsNone(event.public_dict(for_user=True))
        self.assertIsNotNone(event.public_dict(for_user=False))

    def test_developer_visibility_requires_flag(self) -> None:
        event = ActivityEvent(
            event_id="e3",
            operation_id="op1",
            sequence=3,
            category=ActivityCategory.SYSTEM,
            phase=ActivityPhase.UNKNOWN,
            lifecycle=ActivityLifecycle.RUNNING,
            title="Dev only",
            visibility=VisibilityClass.DEVELOPER,
        )
        self.assertIsNone(event.public_dict(for_user=True))
        self.assertIsNotNone(event.public_dict(for_user=True, include_developer=True))

    def test_unknown_schema_version_degrades(self) -> None:
        event = ActivityEvent.from_dict(
            {
                "eventId": "future",
                "operationId": "op1",
                "sequence": 1,
                "category": "REQUEST",
                "phase": "request_received",
                "lifecycle": "completed",
                "title": "Future",
                "schemaVersion": 999,
            }
        )
        self.assertEqual(event.schema_version, 999)
        self.assertIn("_unsupported_schema_version", event.payload)

    def test_unknown_category_phase_degrade(self) -> None:
        event = ActivityEvent.from_dict(
            {
                "eventId": "x",
                "operationId": "op",
                "sequence": 1,
                "category": "NOT_A_REAL_CATEGORY",
                "phase": "not_a_real_phase",
                "lifecycle": "running",
                "title": "x",
            }
        )
        self.assertEqual(event.category, ActivityCategory.SYSTEM)
        self.assertEqual(event.phase, ActivityPhase.UNKNOWN)

    def test_malformed_progress_stays_unknown(self) -> None:
        progress = ProgressMeasurement.from_dict({"kind": "nonsense", "value": "nope"})
        assert progress is not None
        self.assertEqual(progress.kind, ProgressKind.UNKNOWN)

    def test_measured_progress_rejects_zero_denominator(self) -> None:
        progress = ProgressMeasurement.measured(numerator=1, denominator=0)
        self.assertEqual(progress.kind, ProgressKind.UNKNOWN)

    def test_secret_redaction_in_payload(self) -> None:
        event = ActivityEvent(
            event_id="e4",
            operation_id="op1",
            sequence=4,
            category=ActivityCategory.TOOL,
            phase=ActivityPhase.TOOL_INVOCATION,
            lifecycle=ActivityLifecycle.COMPLETED,
            title="Tool",
            payload={"api_key": "sk-secret-value", "ok": True},
        )
        pub = event.public_dict()
        assert pub is not None
        self.assertEqual(pub["payload"]["api_key"], "[REDACTED]")
        self.assertTrue(pub["payload"]["ok"])

    def test_legacy_steps_are_planned_not_completed(self) -> None:
        events = legacy_steps_to_plan_events(
            ["understand_request", "generate_answer"],
            operation_id="op1",
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].title, "Request interpreted")
        self.assertEqual(events[0].lifecycle, ActivityLifecycle.QUEUED)
        self.assertTrue(events[0].payload.get("planned"))
        self.assertEqual(events[1].title, "Answer synthesis")

    def test_event_type_activity_exists(self) -> None:
        self.assertEqual(EventType.ACTIVITY.value, "activity")


class ActivityProjectorTests(unittest.TestCase):
    def test_dedupe_and_out_of_order(self) -> None:
        projector = ActivityProjector()
        first = ActivityEvent(
            event_id="same",
            operation_id="op",
            sequence=1,
            category=ActivityCategory.KNOWLEDGE,
            phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
            lifecycle=ActivityLifecycle.RUNNING,
            title="Knowledge retrieval",
        )
        later = ActivityEvent(
            event_id="same",
            operation_id="op",
            sequence=2,
            category=ActivityCategory.KNOWLEDGE,
            phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
            lifecycle=ActivityLifecycle.COMPLETED,
            title="Knowledge retrieved",
            result_count=17,
        )
        out_of_order = ActivityEvent(
            event_id="child",
            operation_id="op",
            parent_event_id="same",
            sequence=1,
            category=ActivityCategory.KNOWLEDGE,
            phase=ActivityPhase.SOURCE_VALIDATION,
            lifecycle=ActivityLifecycle.COMPLETED,
            title="Sources identified",
            result_count=17,
        )
        projector.ingest(later)
        projector.ingest(first)
        projector.ingest(out_of_order)
        projector.ingest(later)  # duplicate
        projection = projector.project()
        self.assertEqual(len(projection.events), 2)
        root = projection.nodes[0]
        self.assertEqual(root.event.lifecycle, ActivityLifecycle.COMPLETED)
        self.assertEqual(root.event.result_count, 17)
        self.assertEqual(len(root.children), 1)

    def test_disconnected_marks_stale_not_completed(self) -> None:
        projector = ActivityProjector()
        projector.ingest(
            ActivityEvent(
                event_id="r",
                operation_id="op",
                sequence=1,
                category=ActivityCategory.MODEL,
                phase=ActivityPhase.MODEL_INVOCATION,
                lifecycle=ActivityLifecycle.RUNNING,
                title="Model",
            )
        )
        projector.mark_disconnected()
        projection = projector.project()
        self.assertTrue(projection.disconnected)
        self.assertTrue(projection.stale)
        self.assertEqual(projection.events[0].lifecycle, ActivityLifecycle.RUNNING)
        self.assertTrue(projection.public_dict()["truth"]["stale_not_completed"])

    def test_parent_missing_still_projects_orphan(self) -> None:
        projector = ActivityProjector()
        projector.ingest(
            ActivityEvent(
                event_id="orphan",
                operation_id="op",
                parent_event_id="missing-parent",
                sequence=5,
                category=ActivityCategory.TOOL,
                phase=ActivityPhase.TOOL_INVOCATION,
                lifecycle=ActivityLifecycle.COMPLETED,
                title="Tool",
            )
        )
        projection = projector.project()
        # Orphan with missing parent is not in root tree, but remains in flat events.
        self.assertEqual(len(projection.events), 1)
        self.assertEqual(len(projection.nodes), 0)


class ActivityEmitterTests(unittest.TestCase):
    def test_stable_id_updates_lifecycle(self) -> None:
        emitter = ActivityEmitter(operation_id="op", persist=False, emit_to_hub=False)
        a = emitter.emit(
            category=ActivityCategory.RETRIEVAL,
            phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
            lifecycle=ActivityLifecycle.RUNNING,
            title="Knowledge retrieval",
            stable_id="knowledge",
        )
        b = emitter.emit(
            category=ActivityCategory.RETRIEVAL,
            phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
            lifecycle=ActivityLifecycle.COMPLETED,
            title="Knowledge retrieved",
            stable_id="knowledge",
            result_count=3,
        )
        self.assertEqual(a.event_id, b.event_id)
        self.assertEqual(len(emitter.events), 1)
        self.assertEqual(emitter.events[0].lifecycle, ActivityLifecycle.COMPLETED)
        self.assertEqual(emitter.events[0].result_count, 3)

    def test_config_triple_requested_effective(self) -> None:
        emitter = ActivityEmitter(operation_id="op", persist=False, emit_to_hub=False)
        event = emitter.emit(
            category=ActivityCategory.MODEL,
            phase=ActivityPhase.MODEL_INVOCATION,
            lifecycle=ActivityLifecycle.RUNNING,
            title="Model invocation",
            config=ConfigTriple(
                requested={"model": "X"},
                effective={"model": "Y", "fallback": True},
                measured={"model": "Y"},
            ),
        )
        pub = event.public_dict()
        assert pub is not None
        self.assertEqual(pub["config"]["requested"]["model"], "X")
        self.assertEqual(pub["config"]["effective"]["model"], "Y")
        self.assertTrue(pub["config"]["effective"]["fallback"])


class AdapterTests(unittest.TestCase):
    def test_cognition_operational_adapter(self) -> None:
        event = activity_from_cognition_operational_event(
            "tool.completed",
            {"capability_id": "knowledge.search", "result_count": 4},
            operation_id="op",
            sequence=7,
        )
        assert event is not None
        self.assertEqual(event.lifecycle, ActivityLifecycle.COMPLETED)
        self.assertEqual(event.capability_ref, "knowledge.search")
        self.assertEqual(event.result_count, 4)

    def test_unknown_cognition_event_ignored(self) -> None:
        self.assertIsNone(
            activity_from_cognition_operational_event(
                "meta_decision",
                {"secret_plan": "nope"},
                operation_id="op",
            )
        )

    def test_team_event_adapter(self) -> None:
        event = activity_from_team_event(
            {
                "event_id": "t1",
                "seq": 2,
                "kind": "agent_assigned",
                "summary": "Research Agent assigned",
                "payload": {"agent_id": "research"},
            },
            operation_id="op",
        )
        assert event is not None
        self.assertEqual(event.actor_type, ActorType.AGENT)
        self.assertEqual(event.agent_ref, "research")
        self.assertEqual(event.lifecycle, ActivityLifecycle.RUNNING)


class DecisionReceiptTests(unittest.TestCase):
    def test_packet_projection_does_not_invent_pass(self) -> None:
        receipt = decision_receipt_from_packet(
            {
                "packetId": "d1",
                "actor": "risk-agent",
                "status": "OBSERVED",
                "payload": {
                    "strategyId": "MOM_V12",
                    "checks": [
                        {"name": "walk_forward", "status": "PASS"},
                        {"name": "paper_deploy", "status": "PENDING"},
                        {"name": "unknown_check"},
                    ],
                },
                "refs": [{"kind": "payload", "digest": "abc"}],
            }
        )
        self.assertIsInstance(receipt, DecisionReceipt)
        statuses = {c.name: c.status for c in receipt.checks}
        self.assertEqual(statuses["walk_forward"], "PASS")
        self.assertEqual(statuses["paper_deploy"], "PENDING")
        self.assertEqual(statuses["unknown_check"], "UNMEASURED")
        pub = receipt.public_dict()
        self.assertTrue(pub["truth"]["projection_not_authority"])
        self.assertTrue(pub["truth"]["pass_requires_real_check"])


if __name__ == "__main__":
    unittest.main()
