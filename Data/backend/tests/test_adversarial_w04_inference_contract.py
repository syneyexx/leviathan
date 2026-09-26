"""Adversarial W04 — model capability and inference contract gaps.

Covers:
1) tool-calling probe/record — never silently drop tools
2) structured / json_schema — repair or fail closed UNAVAILABLE
3) reasoning stream channel separation honesty (partial labeled)
4) context bounds — refuse or truncate with explicit signal
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from Data.backend.config import Settings
from Data.modules.model_runtime.dialect import FEATURE_SUPPORTED, adapt_transport
from Data.modules.model_runtime.inference_contract import (
    CONTEXT_TRUNCATED,
    STRUCTURED_RESPONSE_UNAVAILABLE,
    TOOL_CALLING_DROPPED,
    ContextOverflowPolicy,
    deterministic_json_repair,
    enforce_context_bounds,
    enforce_structured_response,
    probe_tool_calling_transport,
    record_tool_calling_response,
)
from Data.modules.model_runtime.openai_compatible import OpenAICompatibleLLM
from Data.modules.model_runtime.streaming import (
    StreamNormalizer,
    apply_reasoning_frames,
    apply_stream_frames,
)
from Data.modules.models.contracts import CapabilityState
from Data.modules.models.errors import CONTEXT_WINDOW_EXCEEDED, ModelControlError


class ToolCallingHonestyTests(unittest.TestCase):
    def test_tools_in_payload_when_requested(self) -> None:
        opts_result = adapt_transport(
            __import__(
                "Data.modules.model_runtime.dialect", fromlist=["InferenceTransportOptions"]
            ).InferenceTransportOptions(
                tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}]
            )
        )
        record = probe_tool_calling_transport(
            tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}],
            tool_choice=None,
            payload_fields=opts_result.payload_fields,
            feature_states=opts_result.feature_states,
        )
        self.assertTrue(record.requested)
        self.assertTrue(record.tools_in_payload)
        self.assertFalse(record.silently_dropped)
        self.assertEqual(record.feature_state, FEATURE_SUPPORTED)

    def test_supported_without_payload_is_silent_drop_error(self) -> None:
        with self.assertRaises(ModelControlError) as ctx:
            probe_tool_calling_transport(
                tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
                tool_choice="auto",
                payload_fields={},  # tools omitted
                feature_states={"tool_calling": CapabilityState.SUPPORTED.value},
            )
        self.assertEqual(ctx.exception.code, TOOL_CALLING_DROPPED)

    def test_roundtrip_records_supported(self) -> None:
        base = probe_tool_calling_transport(
            tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}],
            tool_choice=None,
            payload_fields={"tools": []},
            feature_states={"tool_calling": FEATURE_SUPPORTED},
        )
        updated = record_tool_calling_response(
            base,
            tool_calls=[{"id": "1", "type": "function", "function": {"name": "ping"}}],
        )
        self.assertTrue(updated.tool_calls_returned)
        self.assertEqual(updated.measured_state, CapabilityState.SUPPORTED.value)
        self.assertTrue(updated.public_dict()["truth"]["requested_tools_never_silently_dropped"])


class StructuredResponseContractTests(unittest.TestCase):
    def _schema(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "answer",
                "schema": {
                    "type": "object",
                    "required": ["ok", "value"],
                    "properties": {
                        "ok": {"type": "boolean"},
                        "value": {"type": "number"},
                    },
                },
            },
        }

    def test_valid_schema_satisfied(self) -> None:
        result = enforce_structured_response('{"ok": true, "value": 3}', self._schema())
        self.assertTrue(result.schema_satisfied)
        self.assertEqual(result.status, "satisfied")
        self.assertEqual(result.parsed, {"ok": True, "value": 3})

    def test_fence_repair_then_satisfied(self) -> None:
        text = 'Here you go:\n```json\n{"ok": true, "value": 1}\n```'
        result = enforce_structured_response(text, self._schema())
        self.assertTrue(result.schema_satisfied)
        self.assertTrue(result.repaired)
        self.assertEqual(result.status, "repaired")

    def test_trailing_comma_repair(self) -> None:
        parsed, notes = deterministic_json_repair('{"ok": true, "value": 2,}')
        self.assertEqual(parsed, {"ok": True, "value": 2})
        self.assertTrue(any("trailing" in n for n in notes))

    def test_type_mismatch_fail_closed_unavailable(self) -> None:
        with self.assertRaises(ModelControlError) as ctx:
            enforce_structured_response('{"ok": true, "value": "nope"}', self._schema())
        self.assertEqual(ctx.exception.code, STRUCTURED_RESPONSE_UNAVAILABLE)
        details = ctx.exception.details
        self.assertFalse(details.get("schemaSatisfied"))
        self.assertEqual(details.get("status"), "UNAVAILABLE")

    def test_unparseable_fail_closed_unavailable(self) -> None:
        with self.assertRaises(ModelControlError) as ctx:
            enforce_structured_response("not json at all", self._schema())
        self.assertEqual(ctx.exception.code, STRUCTURED_RESPONSE_UNAVAILABLE)

    def test_non_fail_closed_does_not_claim_success(self) -> None:
        result = enforce_structured_response(
            '{"ok": true}',
            self._schema(),
            fail_closed=False,
        )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertFalse(result.schema_satisfied)
        # Parsed may exist but must not be treated as structured success.
        self.assertFalse(result.public_dict()["schemaSatisfied"])
        self.assertNotEqual(result.status, "satisfied")
        self.assertNotEqual(result.status, "repaired")


class ReasoningStreamChannelTests(unittest.TestCase):
    def test_reasoning_separated_from_content(self) -> None:
        n = StreamNormalizer()
        frames = []
        frames.extend(
            n.ingest_openai_chunk(
                {
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "think-1",
                                "content": "hello",
                            }
                        }
                    ]
                }
            )
        )
        frames.extend(
            n.ingest_openai_chunk(
                {"choices": [{"delta": {"reasoning_content": "think-2", "content": " world"}}]}
            )
        )
        frames.extend(
            n.ingest_openai_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        )
        self.assertEqual(apply_stream_frames(frames), "hello world")
        self.assertEqual(apply_reasoning_frames(frames), "think-1think-2")
        self.assertNotIn("think", apply_stream_frames(frames))
        honesty = n.channel_honesty.public_dict()
        self.assertEqual(honesty["reasoningSeparation"], "separated")
        self.assertGreaterEqual(honesty["reasoningFrames"], 2)
        self.assertGreaterEqual(honesty["contentFrames"], 2)

    def test_tool_deltas_not_silently_dropped(self) -> None:
        n = StreamNormalizer()
        frames = n.ingest_openai_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "ping", "arguments": "{}"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )
        tool_frames = [f for f in frames if f.kind == "tool_delta"]
        self.assertEqual(len(tool_frames), 1)
        self.assertEqual(tool_frames[0].tool_calls[0]["id"], "call_1")
        self.assertFalse(n.channel_honesty.tools_silently_dropped)

    def test_partial_separation_labeled_when_mixed_then_separated(self) -> None:
        n = StreamNormalizer()
        n.channel_honesty.note_reasoning_field(separated=False)
        n.channel_honesty.note_reasoning_field(separated=True)
        self.assertEqual(n.channel_honesty.reasoning_separation, "partial")
        self.assertTrue(n.channel_honesty.public_dict()["truth"]["partial_separation_is_labeled"])


class ContextBoundTests(unittest.TestCase):
    def test_refuse_over_limit(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 4000},
        ]
        with self.assertRaises(ModelControlError) as ctx:
            enforce_context_bounds(
                messages,
                context_window=256,
                max_output_tokens=64,
                policy=ContextOverflowPolicy.REFUSE,
            )
        self.assertEqual(ctx.exception.code, CONTEXT_WINDOW_EXCEEDED)
        self.assertTrue(ctx.exception.details.get("refused"))
        self.assertTrue(ctx.exception.details["truth"]["no_silent_context_overflow"])

    def test_truncate_with_explicit_signal(self) -> None:
        messages = [
            {"role": "system", "content": "identity"},
            {"role": "user", "content": "old " * 200},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": "newest question"},
        ]
        bounded, signal = enforce_context_bounds(
            messages,
            context_window=200,
            max_output_tokens=32,
            policy=ContextOverflowPolicy.TRUNCATE,
        )
        self.assertTrue(signal.truncated)
        self.assertEqual(signal.code, CONTEXT_TRUNCATED)
        self.assertEqual(signal.applied, "truncated")
        self.assertGreater(signal.dropped_message_count, 0)
        roles = [m["role"] for m in bounded]
        self.assertIn("system", roles)
        self.assertEqual(bounded[-1]["content"], "newest question")
        self.assertTrue(signal.public_dict()["truth"]["truncation_is_explicit"])

    def test_fit_passes_without_mutation(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        bounded, signal = enforce_context_bounds(
            messages, context_window=4096, policy="refuse"
        )
        self.assertEqual(bounded, messages)
        self.assertEqual(signal.applied, "fit")
        self.assertFalse(signal.truncated)


class CompleteMessagesContractIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_fail_closed_on_bad_json(self) -> None:
        settings = Settings.from_env()
        llm = OpenAICompatibleLLM(settings)

        class FakeResp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "choices": [
                        {
                            "message": {"content": "I refuse to emit JSON"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

        class FakeClient:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def post(self, url: str, headers: dict | None = None, json: dict | None = None):
                return FakeResp()

        with mock.patch(
            "Data.modules.model_runtime.openai_compatible.httpx.AsyncClient", FakeClient
        ):
            with self.assertRaises(ModelControlError) as ctx:
                await llm.complete_messages(
                    [{"role": "user", "content": "json please"}],
                    model_id="m",
                    endpoint="http://127.0.0.1:9/v1",
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "ok",
                            "schema": {
                                "type": "object",
                                "required": ["ok"],
                                "properties": {"ok": {"type": "boolean"}},
                            },
                        },
                    },
                )
        self.assertEqual(ctx.exception.code, STRUCTURED_RESPONSE_UNAVAILABLE)

    async def test_tools_recorded_and_not_dropped(self) -> None:
        settings = Settings.from_env()
        llm = OpenAICompatibleLLM(settings)
        captured: dict[str, Any] = {}

        class FakeResp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {"name": "ping", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                }

        class FakeClient:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def post(self, url: str, headers: dict | None = None, json: dict | None = None):
                captured["json"] = json
                return FakeResp()

        with mock.patch(
            "Data.modules.model_runtime.openai_compatible.httpx.AsyncClient", FakeClient
        ):
            result = await llm.complete_messages(
                [{"role": "user", "content": "ping"}],
                model_id="m",
                endpoint="http://127.0.0.1:9/v1",
                tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}],
            )
        self.assertIn("tools", captured["json"])
        self.assertTrue(result["tool_calling"]["toolsInPayload"])
        self.assertFalse(result["tool_calling"]["silentlyDropped"])
        self.assertEqual(result["tool_calling"]["measuredState"], "supported")
        self.assertEqual(result["context_bound"]["applied"], "unknown")

    async def test_context_refuse_before_provider(self) -> None:
        settings = Settings.from_env()
        llm = OpenAICompatibleLLM(settings)
        posted = {"called": False}

        class FakeClient:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def post(self, *a: Any, **k: Any):
                posted["called"] = True
                raise AssertionError("provider must not be called when context refused")

        with mock.patch(
            "Data.modules.model_runtime.openai_compatible.httpx.AsyncClient", FakeClient
        ):
            with self.assertRaises(ModelControlError) as ctx:
                await llm.complete_messages(
                    [{"role": "user", "content": "y" * 8000}],
                    model_id="m",
                    endpoint="http://127.0.0.1:9/v1",
                    context_window=128,
                    max_tokens=32,
                    on_context_overflow="refuse",
                )
        self.assertEqual(ctx.exception.code, CONTEXT_WINDOW_EXCEEDED)
        self.assertFalse(posted["called"])


if __name__ == "__main__":
    unittest.main()
