"""Regression: Chat Run lifecycle must never attempt RETRIEVING → COMPLETED.

Deep Recall (and all other successful retrieval strategies) must converge on:
RETRIEVAL_STARTED → strategy work → RETRIEVAL_COMPLETED → EXECUTING → COMPLETED
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from Data.modules.knowledge.deep_recall import DeepRecallResult
from Data.modules.knowledge.economy import EconomyDecision
from Data.modules.models.errors import ModelControlError
from Data.modules.reasoning.engine import ReasoningPlan
from Data.modules.run import EventType, RunState, validate_transition
from Data.modules.run.states import InvalidRunTransition


def _plan(
    *,
    use_knowledge: bool,
    use_deep_recall: bool = False,
    intent: str = "knowledge",
    complexity: str = "medium",
) -> ReasoningPlan:
    steps = ["understand_request"]
    if use_deep_recall:
        steps.append("deep_recall_hydrate")
    elif use_knowledge:
        steps.append("retrieve_relevant_knowledge")
    steps.append("generate_answer")
    return ReasoningPlan(
        intent=intent,
        complexity=complexity,
        use_knowledge=use_knowledge,
        steps=tuple(steps),
        use_deep_recall=use_deep_recall,
        use_atlas=use_knowledge and not use_deep_recall,
    )


def _economy(*, allow_deep_recall: bool) -> EconomyDecision:
    return EconomyDecision(
        allow_deep_recall=allow_deep_recall,
        max_depth=2,
        max_relation_count=12,
        deep_recall_budget=800,
        explanation_burden="normal",
        reason="test_fixture",
    )


def _deep_recall_ok() -> DeepRecallResult:
    return DeepRecallResult(
        atlas_matches=({"atlas_id": "a1", "title": "Atlas hit"},),
        hydrated_evidence_refs=("chunk-1",),
        exact_details=(
            {
                "document_id": "doc-1",
                "title": "Evidence",
                "content": "Exact detail from deep recall.",
                "chunk_id": "chunk-1",
                "content_hash": "hash-1",
                "ref": "chunk-1",
            },
        ),
        unresolved_gaps=(),
        contradictions_found=(),
        confidence=0.9,
        context_cost=40,
        retrieval_steps=("hot_query", "atlas_search", "hydrate"),
        stopped_reason="completed",
        available=True,
    )


class ChatRunLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from Data.backend import main as backend_main

        cls.m = backend_main
        # Lifespan applies migrations + store initialize (required for /api/chat).
        cls._client_cm = TestClient(backend_main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.m = self.__class__.m
        self._patches: list[mock._patch] = []
        self._enter(
            mock.patch.object(self.m.knowledge, "list_documents", return_value=[{"id": "k1"}])
        )
        self._enter(
            mock.patch.object(
                self.m.model_plane,
                "resolve_for_chat",
                side_effect=ModelControlError(
                    "ROUTER_EXHAUSTED",
                    "no models",
                    http_status=503,
                ),
            )
        )
        self._enter(mock.patch.object(self.m.model_plane.gateway, "record_fallback"))
        self._enter(
            mock.patch.object(
                self.m.llm,
                "chat",
                new=mock.AsyncMock(return_value=("deterministic answer", "test-model")),
            )
        )

        async def _stream(**kwargs):
            yield ("deterministic ", "test-model")
            yield ("stream answer", "test-model")

        self._enter(mock.patch.object(self.m.llm, "chat_stream", new=_stream))
        # Default: cognition off so Chat retrieval path is exercised alone.
        self._set_features(cognition_enabled=False, cognition_shadow=True, chat_streaming=False)
        self._enter(mock.patch.object(self.m.neuro_advisor, "assess", return_value=self._neuro_off()))
        self._enter(mock.patch.object(self.m.memory_store, "search", return_value=[]))
        self._enter(
            mock.patch.object(
                self.m.staged_retriever,
                "search",
                return_value=SimpleNamespace(
                    hits=[
                        SimpleNamespace(
                            as_context_document=lambda: {
                                "id": "staged-1",
                                "title": "Staged",
                                "content": "staged hit",
                                "source": "staged",
                                "chunk_id": "sc1",
                            }
                        )
                    ],
                    negative_reasons=[],
                    coverage=1.0,
                    early_exit=False,
                ),
            )
        )

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _enter(self, patcher: mock._patch):
        self._patches.append(patcher)
        return patcher.start()

    def _set_features(self, **kwargs) -> None:
        original = self.m.settings.features
        updated = dataclasses.replace(original, **kwargs)
        object.__setattr__(self.m.settings, "features", updated)

        def _restore() -> None:
            object.__setattr__(self.m.settings, "features", original)

        self.addCleanup(_restore)

    @staticmethod
    def _neuro_off():
        from Data.modules.neuro.types import NeuroAssessment

        return NeuroAssessment(enabled=False, signals=(), notes=("test",))

    def _force_plan(self, plan: ReasoningPlan, economy: EconomyDecision) -> None:
        self._enter(mock.patch.object(self.m.reasoner, "analyze", return_value=plan))
        self._enter(mock.patch.object(self.m.economy_governor, "decide", return_value=economy))

    def _run_events(self, run_id: str):
        return self.m.runs.list_events(run_id)

    def _transition_pairs(self, run_id: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for event in self._run_events(run_id):
            if event.event_type in {
                EventType.STATE_CHANGED,
                EventType.RUN_COMPLETED,
                EventType.RUN_FAILED,
                EventType.RUN_CANCELLED,
            }:
                fr = (event.payload or {}).get("from")
                to = (event.payload or {}).get("to")
                if fr and to:
                    pairs.append((str(fr), str(to)))
        return pairs

    def _final_state(self, run_id: str) -> str:
        run = self.m.runs.get_run(run_id)
        assert run is not None
        return run.state.value

    def _event_types(self, run_id: str) -> list[EventType]:
        return [e.event_type for e in self._run_events(run_id)]

    def test_retrieving_to_completed_remains_illegal(self) -> None:
        with self.assertRaises(InvalidRunTransition):
            validate_transition(RunState.RETRIEVING, RunState.COMPLETED)

    def test_deep_recall_reaches_executing_before_completed(self) -> None:
        plan = _plan(use_knowledge=True, use_deep_recall=True)
        economy = _economy(allow_deep_recall=True)
        self._force_plan(plan, economy)
        recall = self._enter(
            mock.patch.object(
                self.m.deep_recall_service,
                "recall",
                return_value=_deep_recall_ok(),
            )
        )

        response = self.client.post("/api/chat", json={"message": "Cite the exact evidence path"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["run_state"], RunState.COMPLETED.value)
        self.assertNotIn("Illegal Run transition", response.text)

        run_id = body["run_id"]
        self.assertEqual(self._final_state(run_id), RunState.COMPLETED.value)
        pairs = self._transition_pairs(run_id)
        self.assertIn((RunState.PLANNING.value, RunState.RETRIEVING.value), pairs)
        self.assertIn((RunState.RETRIEVING.value, RunState.EXECUTING.value), pairs)
        self.assertIn((RunState.EXECUTING.value, RunState.COMPLETED.value), pairs)
        self.assertNotIn((RunState.RETRIEVING.value, RunState.COMPLETED.value), pairs)

        types = self._event_types(run_id)
        self.assertEqual(types.count(EventType.RETRIEVAL_STARTED), 1)
        self.assertEqual(types.count(EventType.RETRIEVAL_COMPLETED), 1)
        started_at = next(
            e.created_at
            for e in self._run_events(run_id)
            if e.event_type == EventType.RETRIEVAL_STARTED
        )
        completed_at = next(
            e.created_at
            for e in self._run_events(run_id)
            if e.event_type == EventType.RETRIEVAL_COMPLETED
        )
        self.assertLessEqual(started_at, completed_at)
        completed_payload = next(
            e.payload
            for e in self._run_events(run_id)
            if e.event_type == EventType.RETRIEVAL_COMPLETED
        )
        self.assertEqual(completed_payload.get("count"), 1)
        self.assertEqual(completed_payload.get("atlas_count"), 1)
        self.assertTrue(completed_payload.get("deep_recall"))
        self.assertEqual(completed_payload.get("source"), "deep_recall")
        recall.assert_called_once()

    def test_normal_retrieval_lifecycle(self) -> None:
        plan = _plan(use_knowledge=True, use_deep_recall=False)
        economy = _economy(allow_deep_recall=False)
        self._force_plan(plan, economy)
        recall = self._enter(mock.patch.object(self.m.deep_recall_service, "recall"))

        response = self.client.post(
            "/api/chat",
            json={"message": "What does the leviathan knowledge base say about retrieval?"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["run_state"], RunState.COMPLETED.value)
        run_id = body["run_id"]
        pairs = self._transition_pairs(run_id)
        self.assertIn((RunState.PLANNING.value, RunState.RETRIEVING.value), pairs)
        self.assertIn((RunState.RETRIEVING.value, RunState.EXECUTING.value), pairs)
        self.assertIn((RunState.EXECUTING.value, RunState.COMPLETED.value), pairs)
        self.assertNotIn((RunState.RETRIEVING.value, RunState.COMPLETED.value), pairs)
        types = self._event_types(run_id)
        self.assertEqual(types.count(EventType.RETRIEVAL_STARTED), 1)
        self.assertEqual(types.count(EventType.RETRIEVAL_COMPLETED), 1)
        completed_payload = next(
            e.payload
            for e in self._run_events(run_id)
            if e.event_type == EventType.RETRIEVAL_COMPLETED
        )
        self.assertFalse(completed_payload.get("deep_recall"))
        recall.assert_not_called()

    def test_no_retrieval_skips_retrieving(self) -> None:
        plan = _plan(
            use_knowledge=False,
            use_deep_recall=False,
            intent="conversation",
            complexity="low",
        )
        economy = _economy(allow_deep_recall=False)
        self._force_plan(plan, economy)
        self._enter(mock.patch.object(self.m.knowledge, "list_documents", return_value=[]))

        response = self.client.post("/api/chat", json={"message": "hi"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["run_state"], RunState.COMPLETED.value)
        run_id = body["run_id"]
        self.assertEqual(self._final_state(run_id), RunState.COMPLETED.value)
        pairs = self._transition_pairs(run_id)
        self.assertNotIn(RunState.RETRIEVING.value, {fr for fr, _ in pairs} | {to for _, to in pairs})
        self.assertIn((RunState.PLANNING.value, RunState.EXECUTING.value), pairs)
        self.assertIn((RunState.EXECUTING.value, RunState.COMPLETED.value), pairs)
        types = self._event_types(run_id)
        self.assertEqual(types.count(EventType.RETRIEVAL_STARTED), 0)
        self.assertEqual(types.count(EventType.RETRIEVAL_COMPLETED), 0)

    def test_cognition_early_own_skips_duplicate_retrieval_and_model(self) -> None:
        plan = _plan(use_knowledge=True, use_deep_recall=True)
        economy = _economy(allow_deep_recall=True)
        self._force_plan(plan, economy)
        self._set_features(cognition_enabled=True, cognition_shadow=False, chat_streaming=False)
        self._enter(
            mock.patch.object(
                self.m.cognition_runtime,
                "submit",
                return_value={
                    "shadow": False,
                    "response": "Cognition authoritative answer",
                    "response_ownership": "cognition",
                    "status": "ACTIVE",
                    "usage": {"retrieval_rounds": 2},
                    "observations": [{"id": "o1"}],
                },
            )
        )
        recall = self._enter(mock.patch.object(self.m.deep_recall_service, "recall"))
        staged = self.m.staged_retriever.search
        llm_chat = self.m.llm.chat

        response = self.client.post("/api/chat", json={"message": "Cite exact leviathan knowledge"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["run_state"], RunState.COMPLETED.value)
        assistant = body["assistant_message"]
        content = assistant["content"] if isinstance(assistant, dict) else str(assistant)
        self.assertIn("Cognition authoritative answer", content)
        self.assertTrue((body.get("truth") or {}).get("no_duplicate_authoritative_model_call"))
        self.assertEqual((body.get("truth") or {}).get("response_owned_by"), "cognition")

        run_id = body["run_id"]
        pairs = self._transition_pairs(run_id)
        self.assertNotIn(RunState.RETRIEVING.value, {fr for fr, _ in pairs} | {to for _, to in pairs})
        self.assertIn((RunState.PLANNING.value, RunState.EXECUTING.value), pairs)
        self.assertIn((RunState.EXECUTING.value, RunState.COMPLETED.value), pairs)
        recall.assert_not_called()
        llm_chat.assert_not_called()
        staged.assert_not_called()

    def test_streaming_retrieval_reaches_executing_before_done(self) -> None:
        plan = _plan(use_knowledge=True, use_deep_recall=True)
        economy = _economy(allow_deep_recall=True)
        self._force_plan(plan, economy)
        self._enter(
            mock.patch.object(
                self.m.deep_recall_service,
                "recall",
                return_value=_deep_recall_ok(),
            )
        )
        self._set_features(cognition_enabled=False, cognition_shadow=True, chat_streaming=True)

        with self.client.stream(
            "POST",
            "/api/chat",
            json={"message": "Cite exact deep recall evidence", "stream": True},
            headers={"Accept": "text/event-stream"},
        ) as response:
            self.assertEqual(response.status_code, 200)
            raw = "".join(response.iter_text())

        self.assertIn("event: done", raw)
        done_line = next(
            line for line in raw.splitlines() if line.startswith("data: ") and '"run_state"' in line
        )
        done_payload = json.loads(done_line[len("data: ") :])
        self.assertEqual(done_payload["run_state"], RunState.COMPLETED.value)
        run_id = done_payload["run_id"]
        pairs = self._transition_pairs(run_id)
        self.assertIn((RunState.RETRIEVING.value, RunState.EXECUTING.value), pairs)
        self.assertIn((RunState.EXECUTING.value, RunState.COMPLETED.value), pairs)
        self.assertNotIn((RunState.RETRIEVING.value, RunState.COMPLETED.value), pairs)
        types = self._event_types(run_id)
        self.assertEqual(types.count(EventType.RETRIEVAL_STARTED), 1)
        self.assertEqual(types.count(EventType.RETRIEVAL_COMPLETED), 1)

    def test_deep_recall_failure_marks_failed_not_completed(self) -> None:
        plan = _plan(use_knowledge=True, use_deep_recall=True)
        economy = _economy(allow_deep_recall=True)
        self._force_plan(plan, economy)
        self._enter(
            mock.patch.object(
                self.m.deep_recall_service,
                "recall",
                side_effect=RuntimeError("deep recall exploded"),
            )
        )

        response = self.client.post("/api/chat", json={"message": "Cite the exact evidence now"})
        self.assertEqual(response.status_code, 500, response.text)
        self.assertIn("Retrieval failed", response.text)
        self.m.llm.chat.assert_not_called()
        self.assertNotIn("Illegal Run transition", response.text)
        self.assertNotIn("RETRIEVING → COMPLETED", response.text)

        with self.m.runs.connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, state, error FROM runs
                WHERE error LIKE ?
                ORDER BY created_at DESC LIMIT 1
                """,
                ("%deep recall exploded%",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["state"], RunState.FAILED.value)
        pairs = self._transition_pairs(row["run_id"])
        self.assertIn((RunState.RETRIEVING.value, RunState.FAILED.value), pairs)
        self.assertNotIn((RunState.RETRIEVING.value, RunState.EXECUTING.value), pairs)
        self.assertNotIn((RunState.EXECUTING.value, RunState.COMPLETED.value), pairs)
        self.assertNotIn(RunState.COMPLETED.value, {to for _, to in pairs})


if __name__ == "__main__":
    unittest.main()
