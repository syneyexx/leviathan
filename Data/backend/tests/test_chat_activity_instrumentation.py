"""Chat activity instrumentation helpers."""

from __future__ import annotations

import unittest

from Data.modules.run.activity import ActivityLifecycle
from Data.modules.run.chat_activity import (
    activity_snapshot,
    create_chat_activity_emitter,
    emit_cancellation,
    emit_knowledge_retrieval_completed,
    emit_knowledge_retrieval_started,
    emit_model_invocation,
    emit_operation_terminal,
    emit_plan_created,
    emit_request_received,
    emit_request_understood,
    ingest_cognition_operational_events,
)


class ChatActivityHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.emitter = create_chat_activity_emitter(run_id="run-1", trace_id="trace-1")
        self.emitter.persist = False
        self.emitter.emit_to_hub = False

    def test_lifecycle_path_produces_user_visible_projection(self) -> None:
        emit_request_received(self.emitter)
        emit_request_understood(
            self.emitter,
            intent="factual_question",
            complexity="low",
            retrieval_reason="eligible:factual_question",
        )
        emit_plan_created(
            self.emitter,
            steps=["understand_request", "retrieve_relevant_knowledge", "generate_answer"],
            reasoning_mode={"requested": "auto", "effective": "standard", "source": "auto"},
        )
        emit_knowledge_retrieval_started(self.emitter)
        emit_knowledge_retrieval_completed(self.emitter, knowledge_count=3, source="hybrid")
        emit_model_invocation(
            self.emitter,
            lifecycle=ActivityLifecycle.RUNNING,
            requested_model="req-model",
            effective_model="eff-model",
            fallback=True,
        )
        emit_model_invocation(
            self.emitter,
            lifecycle=ActivityLifecycle.COMPLETED,
            requested_model="req-model",
            effective_model="eff-model",
            fallback=True,
        )
        emit_operation_terminal(self.emitter, lifecycle=ActivityLifecycle.COMPLETED)
        snap = activity_snapshot(self.emitter)
        events = snap["events"]
        self.assertGreaterEqual(len(events), 5)
        titles = {e["title"] for e in events}
        self.assertIn("Request interpreted", titles)
        self.assertIn("Knowledge retrieved", titles)
        knowledge = next(e for e in events if e["title"] == "Knowledge retrieved")
        self.assertEqual(knowledge["resultCount"], 3)
        self.assertEqual(knowledge["lifecycle"], "completed")
        model = next(e for e in events if e["eventId"].endswith(":model") or "Model" in e["title"])
        self.assertEqual(model["config"]["requested"]["model"], "req-model")
        self.assertEqual(model["config"]["effective"]["model"], "eff-model")
        self.assertTrue(model["config"]["effective"]["fallback"])

    def test_cancellation_stages_are_truthful(self) -> None:
        emit_cancellation(self.emitter, stage="requested", reason="client_disconnect")
        emit_cancellation(self.emitter, stage="propagating", reason="client_disconnect")
        emit_cancellation(self.emitter, stage="cancelled", reason="client_disconnect")
        events = self.emitter.public_events()
        cancel = next(e for e in events if e["eventId"].endswith(":cancellation"))
        self.assertEqual(cancel["lifecycle"], "cancelled")
        self.assertEqual(cancel["payload"]["stage"], "cancelled")

    def test_cognition_ops_ingested_without_private_events(self) -> None:
        published = ingest_cognition_operational_events(
            self.emitter,
            [
                {
                    "event_type": "tool.completed",
                    "payload": {"capability_id": "knowledge.search", "result_count": 2},
                },
                {"event_type": "meta_decision", "payload": {"private": True}},
            ],
        )
        self.assertEqual(len(published), 1)
        self.assertIn("knowledge.search", published[0]["title"])


if __name__ == "__main__":
    unittest.main()
