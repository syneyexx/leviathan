"""Chat responses expose structured activity events (not CoT)."""

from __future__ import annotations

import dataclasses
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelLifecycleState,
    ModelProfile,
    ModelSource,
    RouteDecision,
)
from Data.modules.reasoning.engine import ReasoningPlan


def _plan() -> ReasoningPlan:
    return ReasoningPlan(
        intent="factual_question",
        complexity="low",
        use_knowledge=False,
        steps=("understand_request", "generate_answer"),
        use_deep_recall=False,
        use_atlas=False,
    )


class ChatActivityResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from Data.backend import main as backend_main

        cls.m = backend_main
        cls._client_cm = TestClient(backend_main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.m = self.__class__.m
        self._patches: list[mock._patch] = []
        self._enter(mock.patch.object(self.m.knowledge, "list_documents", return_value=[]))
        self._enter(
            mock.patch.object(
                self.m.model_plane,
                "resolve_for_chat",
                return_value=self._fake_routed(),
            )
        )
        self._enter(
            mock.patch.object(
                self.m.model_plane.residency,
                "acquire_lease",
                new=mock.AsyncMock(return_value=SimpleNamespace(lease_id="lease-test")),
            )
        )
        self._enter(
            mock.patch.object(
                self.m.model_plane.residency,
                "release_lease",
                new=mock.AsyncMock(),
            )
        )
        self._enter(
            mock.patch.object(
                self.m.model_plane.residency,
                "snapshot",
                return_value=SimpleNamespace(endpoint=None),
            )
        )
        self._enter(mock.patch.object(self.m.model_plane.gateway, "acquire", return_value="call-test"))
        self._enter(mock.patch.object(self.m.model_plane.gateway, "release"))
        self._enter(mock.patch.object(self.m.model_plane.registry, "touch_used"))
        self._enter(mock.patch.object(self.m.reasoner, "analyze", return_value=_plan()))
        self._enter(
            mock.patch.object(
                self.m.llm,
                "chat",
                new=mock.AsyncMock(return_value=("Activity path answer.", "test-model")),
            )
        )
        self._set_features(cognition_enabled=False, cognition_shadow=True, chat_streaming=False)

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _enter(self, p: mock._patch):
        self._patches.append(p)
        return p.start()

    def _set_features(self, **kwargs) -> None:
        original = self.m.settings.features
        updated = dataclasses.replace(original, **kwargs)
        object.__setattr__(self.m.settings, "features", updated)

        def _restore() -> None:
            object.__setattr__(self.m.settings, "features", original)

        self.addCleanup(_restore)

    @staticmethod
    def _fake_routed() -> dict:
        model = ModelDescriptor(
            id="test-model",
            display_name="test-model",
            provider_id="test-provider",
            source=ModelSource.API,
            capabilities=ModelCapabilities(chat=CapabilityState.SUPPORTED),
            lifecycle_state=ModelLifecycleState.AVAILABLE,
            context_window=4096,
            endpoint="http://127.0.0.1:1234/v1",
            metadata={"provider_model_id": "test-model"},
        )
        decision = RouteDecision(model_id=model.id, reason="test_fixture")
        profile = ModelProfile(model_id=model.id, temperature=0.2, max_tokens=256)
        return {
            "decision": decision,
            "model": model,
            "profile": profile,
            "endpoint": model.endpoint,
            "api_key": "not-needed",
            "provider_model_id": "test-model",
            "provider_id": model.provider_id,
            "resolved": None,
        }

    def test_non_stream_chat_includes_activity_projection(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={"message": "hello there", "stream": False},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("activity", body)
        self.assertIn("activity_events", body)
        events = body.get("activity_events") or []
        self.assertGreaterEqual(len(events), 1)
        titles = {e.get("title") for e in events}
        self.assertTrue(
            {"Request received", "Request interpreted"} & titles,
            titles,
        )
        for event in events:
            self.assertNotIn("chain_of_thought", event)
            self.assertNotIn("hidden_reasoning", event)
            self.assertIn("lifecycle", event)
            self.assertIn("schemaVersion", event)
            self.assertTrue(event.get("truth", {}).get("operational_telemetry_not_cot"))


if __name__ == "__main__":
    unittest.main()
