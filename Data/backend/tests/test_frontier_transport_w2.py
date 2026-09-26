"""W2 — Model Control Plane frontier transport dialect + probe honesty."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.model_runtime.dialect import (
    FEATURE_SUPPORTED,
    FEATURE_UNMEASURED,
    InferenceTransportOptions,
    TransportFeature,
    adapt_transport,
)
from Data.modules.model_runtime.openai_compatible import OpenAICompatibleLLM
from Data.modules.models.capability_probe import CapabilityProbeService
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
)
from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore


class DialectAdaptationTests(unittest.TestCase):
    def test_tools_and_schema_supported_on_openai_compatible(self) -> None:
        opts = InferenceTransportOptions(
            tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}],
            tool_choice="auto",
            parallel_tool_calls=True,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "ok", "schema": {"type": "object"}},
            },
            logprobs=True,
            top_logprobs=2,
            n=3,
        )
        result = adapt_transport(opts, dialect_id="openai_compatible")
        self.assertEqual(result.feature_states[TransportFeature.TOOL_CALLING.value], FEATURE_SUPPORTED)
        self.assertEqual(
            result.feature_states[TransportFeature.PARALLEL_TOOL_CALLS.value], FEATURE_SUPPORTED
        )
        self.assertEqual(
            result.feature_states[TransportFeature.JSON_SCHEMA_RESPONSE.value], FEATURE_SUPPORTED
        )
        self.assertEqual(result.feature_states[TransportFeature.LOGPROBS.value], FEATURE_SUPPORTED)
        self.assertEqual(
            result.feature_states[TransportFeature.MULTI_CANDIDATE.value], FEATURE_SUPPORTED
        )
        self.assertIn("tools", result.payload_fields)
        self.assertIn("response_format", result.payload_fields)
        self.assertEqual(result.payload_fields["n"], 3)

    def test_reasoning_effort_not_silently_dropped(self) -> None:
        opts = InferenceTransportOptions(reasoning_effort="high")
        with self.assertRaises(ModelControlError) as ctx:
            adapt_transport(opts, dialect_id="openai_compatible")
        self.assertEqual(ctx.exception.code, CAPABILITY_NOT_SUPPORTED)
        self.assertIn("reasoning_effort", ctx.exception.message)

    def test_reasoning_dialect_emits_effort(self) -> None:
        opts = InferenceTransportOptions(
            reasoning_effort="medium",
            reasoning_max_tokens=128,
            prompt_cache_key="ckpt-1",
        )
        result = adapt_transport(opts, dialect_id="openai_reasoning")
        self.assertEqual(
            result.feature_states[TransportFeature.REASONING_EFFORT.value], FEATURE_SUPPORTED
        )
        self.assertEqual(
            result.feature_states[TransportFeature.REASONING_TOKEN_BUDGET.value],
            FEATURE_SUPPORTED,
        )
        self.assertEqual(
            result.feature_states[TransportFeature.CACHE_HINTS.value], FEATURE_SUPPORTED
        )
        self.assertEqual(result.payload_fields["reasoning_effort"], "medium")
        self.assertEqual(result.payload_fields["reasoning"]["max_tokens"], 128)
        self.assertEqual(result.payload_fields["prompt_cache_key"], "ckpt-1")

    def test_cache_hints_unmeasured_not_silent(self) -> None:
        opts = InferenceTransportOptions(prompt_cache_key="x", reject_unsupported=False)
        result = adapt_transport(opts, dialect_id="openai_compatible")
        self.assertEqual(
            result.feature_states[TransportFeature.CACHE_HINTS.value], FEATURE_UNMEASURED
        )
        self.assertNotIn("prompt_cache_key", result.payload_fields)


class CompleteMessagesTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_messages_merges_tools_and_reports_transport(self) -> None:
        settings = Settings.from_env()
        llm = OpenAICompatibleLLM(settings)

        captured: dict[str, Any] = {}

        class FakeResp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "id": "cmpl-1",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "ping", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
                }

        class FakeClient:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def post(self, url: str, headers: dict | None = None, json: dict | None = None):
                captured["url"] = url
                captured["json"] = json
                return FakeResp()

        with mock.patch("Data.modules.model_runtime.openai_compatible.httpx.AsyncClient", FakeClient):
            result = await llm.complete_messages(
                [{"role": "user", "content": "call ping"}],
                model_id="test-model",
                endpoint="http://127.0.0.1:9/v1",
                tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}],
                response_format={"type": "json_object"},
            )

        self.assertIn("tools", captured["json"])
        self.assertIn("response_format", captured["json"])
        self.assertTrue(result.get("tool_calls"))
        self.assertEqual(
            result["transport"]["featureStates"]["tool_calling"], FEATURE_SUPPORTED
        )
        self.assertTrue(result["transport"]["truth"]["requested_capability_never_silently_dropped"])
        self.assertTrue(
            result["transport"]["truth"]["mcp_means_model_context_protocol_not_control_plane"]
        )


def _upsert_test_model(store: ModelStore, model_id: str, **cap_kwargs: Any) -> None:
    caps = ModelCapabilities(**cap_kwargs) if cap_kwargs else ModelCapabilities()
    store.upsert_model(
        {
            "model_id": model_id,
            "display_name": model_id,
            "provider_id": "p1",
            "source": "local",
            "capabilities": caps.public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
            "metadata": {},
        }
    )


class CapabilityProbeHonestyTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_calling_unmeasured_without_probe_hook(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "m.db"
        MigrationRunner(db).apply_all()
        store = ModelStore(db)
        registry = ModelRegistry(store)
        _upsert_test_model(
            store,
            "m1",
            chat=CapabilityState.SUPPORTED,
            tool_calling=CapabilityState.UNKNOWN,
        )

        class Adapter:
            provider_id = "p1"

            async def test_inference(self, model_id: str, **kwargs: Any) -> dict[str, Any]:
                return {"ok": True, "latencyMs": 1, "preview": "OK"}

        probes = CapabilityProbeService(store, registry, get_adapter=lambda _: Adapter())
        results = await probes.probe("m1", capabilities=["toolCalling", "chat"])
        by_name = {r.capability: r for r in results}
        self.assertEqual(by_name["chat"].verified, CapabilityState.SUPPORTED)
        self.assertEqual(by_name["toolCalling"].verified, CapabilityState.UNMEASURED)
        self.assertIn("not inferred from config", by_name["toolCalling"].detail or "")

    async def test_tool_calling_supported_when_roundtrip_measured(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "m.db"
        MigrationRunner(db).apply_all()
        store = ModelStore(db)
        registry = ModelRegistry(store)
        _upsert_test_model(store, "m2", tool_calling=CapabilityState.UNKNOWN)

        class Adapter:
            provider_id = "p1"

            async def test_tool_calling(self, model_id: str) -> dict[str, Any]:
                return {"tool_call_roundtrip": True}

        probes = CapabilityProbeService(store, registry, get_adapter=lambda _: Adapter())
        results = await probes.probe("m2", capabilities=["toolCalling"])
        self.assertEqual(results[0].verified, CapabilityState.SUPPORTED)

    async def test_structured_schema_valid_probe(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "m.db"
        MigrationRunner(db).apply_all()
        store = ModelStore(db)
        registry = ModelRegistry(store)
        _upsert_test_model(store, "m3")

        class Adapter:
            provider_id = "p1"

            async def test_structured_output(self, model_id: str, *, schema: dict) -> dict[str, Any]:
                return {"schema_valid": True, "ok": True, "json_parsed": True}

        probes = CapabilityProbeService(store, registry, get_adapter=lambda _: Adapter())
        results = await probes.probe("m3", capabilities=["jsonSchemaResponse"])
        self.assertEqual(results[0].verified, CapabilityState.SUPPORTED)


class ModelCapabilitiesFrontierFieldsTests(unittest.TestCase):
    def test_frontier_fields_roundtrip(self) -> None:
        caps = ModelCapabilities(
            tool_calling=CapabilityState.SUPPORTED,
            parallel_tool_calls=CapabilityState.UNMEASURED,
            json_schema_response=CapabilityState.SUPPORTED,
            reasoning_effort=CapabilityState.UNSUPPORTED,
            logprobs=CapabilityState.SUPPORTED,
            multi_candidate=CapabilityState.UNKNOWN,
        )
        raw = caps.public_dict()
        again = ModelCapabilities.from_dict(raw)
        self.assertEqual(again.tool_calling, CapabilityState.SUPPORTED)
        self.assertEqual(again.parallel_tool_calls, CapabilityState.UNMEASURED)
        self.assertEqual(again.json_schema_response, CapabilityState.SUPPORTED)
        self.assertEqual(again.reasoning_effort, CapabilityState.UNSUPPORTED)
        self.assertIn("parallelToolCalls", raw)
        self.assertIn("jsonSchemaResponse", raw)


if __name__ == "__main__":
    unittest.main()
