"""P0 tool engine + chat repetition + plugin zip upload regressions."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from claim_register import filter_circular_knowledge, is_active_conversation_knowledge
from database import Database
from reasoning.tool_engine import ToolEngineConfig, run_tool_engine
from reasoning.tool_protocol import (
    ResponseState,
    StreamingToolCallAssembler,
    classify_model_response,
    decode_provider_function_name,
    encode_provider_function_name,
    strip_raw_tool_protocol,
)
from reasoning.tool_registry import validate_against_schema


class ToolProtocolTests(unittest.TestCase):
    def test_provider_function_name_roundtrip(self) -> None:
        name = encode_provider_function_name("humanizer", "humanize")
        self.assertEqual(name, "humanizer__humanize")
        self.assertEqual(decode_provider_function_name(name), ("humanizer", "humanize"))

    def test_null_content_with_native_tool_calls_is_valid(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "humanizer__humanize",
                                    "arguments": '{"text":"Hallo"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        classified = classify_model_response(response)
        self.assertEqual(classified.state, ResponseState.TOOL_CALLS)
        self.assertEqual(classified.tool_calls[0].plugin_id, "humanizer")
        self.assertEqual(classified.tool_calls[0].arguments["text"], "Hallo")

    def test_empty_without_tools_is_fatal(self) -> None:
        response = {"choices": [{"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}]}
        classified = classify_model_response(response)
        self.assertEqual(classified.state, ResponseState.EMPTY_FATAL)

    def test_text_fallback_tool_call(self) -> None:
        content = json.dumps({"hades_tool_call": {"plugin_id": "echo", "tool_name": "echo", "input": {"args": ["x"]}}})
        classified = classify_model_response({"choices": [{"message": {"role": "assistant", "content": content}}]})
        self.assertEqual(classified.state, ResponseState.TOOL_CALLS)
        self.assertEqual(classified.mode, "text_fallback")

    def test_strip_raw_tool_protocol(self) -> None:
        raw = json.dumps({"hades_tool_call": {"plugin_id": "x", "tool_name": "y", "input": {}}})
        cleaned = strip_raw_tool_protocol(raw)
        self.assertNotIn("hades_tool_call", cleaned)

    def test_streaming_fragmented_arguments(self) -> None:
        asm = StreamingToolCallAssembler()
        asm.ingest_chunk(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "p__", "arguments": ""}}]}}]}
        )
        asm.ingest_chunk(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "t", "arguments": '{"q":'}}]}}]}
        )
        asm.ingest_chunk(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"hi"}'}}]}, "finish_reason": "tool_calls"}]}
        )
        classified = classify_model_response(asm.build_response())
        self.assertEqual(classified.state, ResponseState.TOOL_CALLS)
        self.assertEqual(classified.tool_calls[0].arguments, {"q": "hi"})

    def test_streaming_snapshot_arguments_are_not_concatenated(self) -> None:
        asm = StreamingToolCallAssembler()
        full = '{"text":"Hallo"}'
        for _ in range(3):
            asm.ingest_chunk(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "c1",
                                        "function": {"name": "humanizer__humanize", "arguments": full},
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        classified = classify_model_response(asm.build_response())
        self.assertEqual(classified.state, ResponseState.TOOL_CALLS)
        self.assertEqual(classified.tool_calls[0].plugin_id, "humanizer")
        self.assertEqual(classified.tool_calls[0].arguments, {"text": "Hallo"})
        self.assertIsNone(classified.tool_calls[0].parse_error)

    def test_schema_validation(self) -> None:
        schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }
        self.assertEqual(validate_against_schema({"text": "ok"}, schema), [])
        self.assertTrue(validate_against_schema({}, schema))
        self.assertTrue(validate_against_schema({"text": "ok", "extra": 1}, schema))


class ToolEngineLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_null_content_then_final(self) -> None:
        calls = {"n": 0}
        payloads: list[dict] = []

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            payloads.append(payload)
            if calls["n"] == 1:
                self.assertIn("tools", payload)
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "echo__echo",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            # Continuation must include role=tool
            roles = [m.get("role") for m in payload["messages"]]
            self.assertIn("tool", roles)
            return {"choices": [{"message": {"role": "assistant", "content": "Klaar na tool."}}]}

        def build_payload(messages, tools):
            body = {"model": "m", "messages": messages}
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"
            return body

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]

        def invoke(plugin_id, tool_name, arguments):
            return {
                "id": "tc1",
                "status": "completed",
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "output": "ok",
                "invocation_type": "autonomous",
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "gebruik echo"}],
            query="gebruik echo",
            tools=tools,
            chat=chat,
            build_payload=build_payload,
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3, max_model_calls=5),
        )
        self.assertEqual(result.content, "Klaar na tool.")
        self.assertEqual(len(result.tool_log), 1)
        self.assertEqual(result.tool_log[0]["status"], "completed")
        self.assertNotIn("hades_tool_call", result.content)

    async def test_four_tools_then_final(self) -> None:
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] <= 4:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"call_{calls['n']}",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {"choices": [{"message": {"role": "assistant", "content": "Vier tools klaar."}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]
        result = await run_tool_engine(
            messages=[{"role": "user", "content": "doe 4 tools"}],
            query="doe 4 tools",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t, "tool_choice": "auto"} if t else {})},
            invoke=lambda *a: {"id": "x", "status": "completed", "exit_code": 0, "output": "ok", "stdout": "ok", "stderr": "", "invocation_type": "autonomous"},
            config=ToolEngineConfig(max_rounds=8, max_model_calls=20),
        )
        self.assertEqual(result.content, "Vier tools klaar.")
        self.assertEqual(len(result.tool_log), 4)

    async def test_multiple_tool_calls_one_turn(self) -> None:
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {"id": "a", "type": "function", "function": {"name": "echo__echo", "arguments": "{}"}},
                                    {"id": "b", "type": "function", "function": {"name": "echo__echo", "arguments": "{}"}},
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            tool_msgs = [m for m in payload["messages"] if m.get("role") == "tool"]
            self.assertEqual({m.get("tool_call_id") for m in tool_msgs}, {"a", "b"})
            return {"choices": [{"message": {"role": "assistant", "content": "Beide tools."}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]
        result = await run_tool_engine(
            messages=[{"role": "user", "content": "twee"}],
            query="twee",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=lambda *a: {"id": "x", "status": "completed", "exit_code": 0, "output": "ok", "stdout": "", "stderr": "", "invocation_type": "autonomous"},
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(len(result.tool_log), 2)
        self.assertEqual(result.content, "Beide tools.")


class PluginZipImportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()
        self.client_patch = patch.object(main, "lm_client", return_value=None)
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def _make_package(self) -> Path:
        source = Path(self.temp_dir.name) / "zip-plugin"
        source.mkdir()
        (source / "echo.py").write_text("print('ok')\n", encoding="utf-8")
        (source / "hades-plugin.json").write_text(
            json.dumps(
                {
                    "format": 1,
                    "id": "zip-plugin",
                    "name": "Zip Plugin",
                    "version": "1.0.0",
                    "runtime_type": "python",
                    "permissions": ["subprocess"],
                    "tools": [
                        {
                            "name": "echo",
                            "description": "echo",
                            "command": ["{python}", "echo.py"],
                            "input_schema": {"type": "object", "properties": {}},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        converted = main.plugin_manager.import_local_folder(source, install_dependencies=False)
        return Path(converted["package_path"])

    def test_import_zip_works_when_network_blocked_and_deps_requested(self) -> None:
        self.client.put("/api/settings", json={"network_policy": "block", "file_write_policy": "ask"})
        pkg = self._make_package()
        with pkg.open("rb") as handle:
            response = self.client.post(
                "/api/plugins/import-zip",
                files={"file": (pkg.name, handle, "application/octet-stream")},
                data={
                    "install_dependencies": "true",
                    "approved_file_write": "true",
                    "approved_network": "true",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["plugin"]["id"], "zip-plugin")
        self.assertTrue(body.get("dependencies_skipped"))
        self.assertTrue(any("network" in w.lower() for w in body.get("warnings") or []))

    def test_import_zip_rejects_git_lfs_pointer(self) -> None:
        pointer = Path(self.temp_dir.name) / "fake.HadesPlugin"
        pointer.write_text(
            "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n",
            encoding="utf-8",
        )
        with pointer.open("rb") as handle:
            response = self.client.post(
                "/api/plugins/import-zip",
                files={"file": (pointer.name, handle, "application/octet-stream")},
                data={"install_dependencies": "false", "approved_file_write": "true", "approved_network": "false"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("LFS", response.json()["detail"])

    def test_import_zip_preserves_http_exception_status(self) -> None:
        self.client.put("/api/settings", json={"file_write_policy": "ask"})
        pkg = self._make_package()
        with pkg.open("rb") as handle:
            response = self.client.post(
                "/api/plugins/import-zip",
                files={"file": (pkg.name, handle, "application/octet-stream")},
                data={"install_dependencies": "false", "approved_file_write": "false", "approved_network": "false"},
            )
        self.assertEqual(response.status_code, 428)


class ChatRepetitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()
        self.captured: list[dict] = []

        class FakeLM:
            async def models(self_inner):
                return {"data": [{"id": "local-model"}]}

            async def chat(self_inner, payload):
                self.captured.append(payload)
                return {
                    "choices": [{"message": {"role": "assistant", "content": "ANTWOORD EENMAAL."}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
                }

        self.client_patch = patch.object(main, "lm_client", return_value=FakeLM())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_active_conversation_not_reinjected_via_knowledge(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "rep"}).json()
        first = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Zeg alleen: ANTWOORD EENMAAL."},
        )
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Ok, zeg nu KLAAR."},
        )
        self.assertEqual(second.status_code, 200)
        payload = self.captured[-1]
        blob = "\n".join(str(m.get("content") or "") for m in payload["messages"])
        # History may contain the phrase in prior user + assistant + compact working-state
        # (goal + last_assistant). It must NOT also reappear via indexed conversation knowledge.
        self.assertLessEqual(blob.count("ANTWOORD EENMAAL"), 4, blob)
        user_messages = [m for m in payload["messages"] if m.get("role") == "user"]
        self.assertEqual(sum(1 for m in user_messages if m.get("content") == "Ok, zeg nu KLAAR."), 1)

    def test_filter_active_conversation_knowledge(self) -> None:
        rows = [
            {"source_type": "conversation", "uri": "conversation:c1", "metadata": {"conversation_id": "c1"}, "content": "x"},
            {"source_type": "document", "uri": "file:doc.md", "content": "y"},
        ]
        independent, derived = filter_circular_knowledge(rows, active_conversation_id="c1")
        self.assertEqual(len(independent), 1)
        self.assertEqual(independent[0]["uri"], "file:doc.md")
        self.assertTrue(is_active_conversation_knowledge(rows[0], "c1"))


class ChatTelemetryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()

        class FakeLM:
            async def models(self_inner):
                return {"data": [{"id": "local-model"}]}

            async def chat(self_inner, payload):
                return {
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12},
                }

        self.client_patch = patch.object(main, "lm_client", return_value=FakeLM())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_send_message_returns_usage(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "usage"}).json()
        response = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Hallo"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        usage = body.get("usage")
        self.assertIsNotNone(usage)
        self.assertEqual(usage.get("total_tokens"), 12)
        self.assertEqual(usage.get("input_tokens"), 9)
        self.assertEqual(usage.get("output_tokens"), 3)

    def test_usage_telemetry_endpoint_tracks_peak_and_total(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "usage2"}).json()
        self.client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "Een"})
        self.client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "Twee"})
        snap = self.client.get("/api/chat/usage-telemetry", params={"conversation_id": conversation["id"]})
        self.assertEqual(snap.status_code, 200)
        body = snap.json()
        self.assertEqual(body["current"]["kind"], "exact")
        self.assertEqual(body["current"]["total_tokens"], 12)
        self.assertEqual(body["peak"]["total_tokens"], 12)
        self.assertGreaterEqual(body["totals"]["session_tokens"], 24)
        self.assertGreaterEqual(body["model_calls"], 2)


class ToolCapabilityCacheTests(unittest.TestCase):
    def test_fingerprint_and_invalidate_on_model_switch(self) -> None:
        from reasoning.tool_capability import ToolCapabilityCache

        cache = ToolCapabilityCache()
        cache.mark_native_success(endpoint="http://127.0.0.1:1234/v1", model_id="model-a")
        first = cache.get(endpoint="http://127.0.0.1:1234/v1", model_id="model-a")
        self.assertEqual(first.state, "native_verified")
        cache.invalidate(model_id="model-a")
        again = cache.get(endpoint="http://127.0.0.1:1234/v1", model_id="model-a")
        self.assertEqual(again.state, "unknown")

    def test_unsupported_prefers_text_fallback(self) -> None:
        from reasoning.tool_capability import ToolCapabilityCache

        cache = ToolCapabilityCache()
        cache.mark_unsupported(endpoint="http://x/v1", model_id="m", error="tools not supported")
        record = cache.get(endpoint="http://x/v1", model_id="m")
        self.assertEqual(record.state, "text_fallback")
        self.assertFalse(cache.prefer_native(record))


class ExtendedToolEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_eight_tools_then_final(self) -> None:
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] <= 8:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"call_{calls['n']}",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {"choices": [{"message": {"role": "assistant", "content": "Acht tools klaar."}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]
        result = await run_tool_engine(
            messages=[{"role": "user", "content": "doe 8 tools"}],
            query="doe 8 tools",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t, "tool_choice": "auto"} if t else {})},
            invoke=lambda *a: {
                "id": "x",
                "status": "completed",
                "exit_code": 0,
                "output": "ok",
                "stdout": "ok",
                "stderr": "",
                "invocation_type": "autonomous",
            },
            config=ToolEngineConfig(max_rounds=12, max_model_calls=20),
        )
        self.assertEqual(result.content, "Acht tools klaar.")
        self.assertEqual(len(result.tool_log), 8)

    async def test_unknown_native_function_rejected(self) -> None:
        async def chat(payload: dict) -> dict:
            if any(m.get("role") == "tool" for m in payload["messages"]):
                return {"choices": [{"message": {"role": "assistant", "content": "Onbekende tool geweigerd."}}]}
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "bad",
                                    "type": "function",
                                    "function": {"name": "nope__missing", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "x"}],
            query="x",
            tools=[
                {
                    "plugin_id": "echo",
                    "name": "echo",
                    "description": "echo",
                    "input_schema": {"type": "object", "properties": {}},
                    "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
                }
            ],
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=lambda *a: (_ for _ in ()).throw(AssertionError("must not invoke")),
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(result.tool_log[0]["status"], "rejected")
        self.assertIn("geweigerd", result.content.lower())

    async def test_malformed_args_not_executed(self) -> None:
        invoked = {"n": 0}

        async def chat(payload: dict) -> dict:
            if any(m.get("role") == "tool" for m in payload["messages"]):
                return {"choices": [{"message": {"role": "assistant", "content": "Schema fout hersteld."}}]}
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "echo__echo", "arguments": "{not-json"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        def invoke(*_a):
            invoked["n"] += 1
            return {"id": "x", "status": "completed", "exit_code": 0, "output": "ok", "stdout": "", "stderr": "", "invocation_type": "autonomous"}

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "x"}],
            query="x",
            tools=[
                {
                    "plugin_id": "echo",
                    "name": "echo",
                    "description": "echo",
                    "input_schema": {"type": "object", "properties": {}},
                    "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
                }
            ],
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(invoked["n"], 0)
        self.assertEqual(result.tool_log[0]["status"], "failed")
        self.assertIn("malformed", (result.tool_log[0].get("error") or "").lower())

    async def test_repairable_trailing_comma_args_are_executed(self) -> None:
        invoked = {"n": 0}

        async def chat(payload: dict) -> dict:
            if any(m.get("role") == "tool" for m in payload["messages"]):
                return {"choices": [{"message": {"role": "assistant", "content": "Tool gebruikt."}}]}
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "echo__echo", "arguments": '{"args":["x"],}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        def invoke(*_a):
            invoked["n"] += 1
            return {
                "id": "x",
                "status": "completed",
                "exit_code": 0,
                "output": "ok",
                "stdout": "",
                "stderr": "",
                "invocation_type": "autonomous",
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "x"}],
            query="x",
            tools=[
                {
                    "plugin_id": "echo",
                    "name": "echo",
                    "description": "echo",
                    "input_schema": {"type": "object", "properties": {}},
                    "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
                }
            ],
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(invoked["n"], 1)
        self.assertEqual(result.tool_log[0]["status"], "completed")

    async def test_tools_unsupported_falls_back_to_text(self) -> None:
        from reasoning.tool_capability import ToolsUnsupportedError

        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if payload.get("tools"):
                raise ToolsUnsupportedError("tools not supported")
            if calls["n"] == 2:
                content = json.dumps({"hades_tool_call": {"plugin_id": "echo", "tool_name": "echo", "input": {}}})
                return {"choices": [{"message": {"role": "assistant", "content": content}}]}
            return {"choices": [{"message": {"role": "assistant", "content": "Fallback gelukt."}}]}

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "tool"}],
            query="tool",
            tools=[
                {
                    "plugin_id": "echo",
                    "name": "echo",
                    "description": "echo",
                    "input_schema": {"type": "object", "properties": {}},
                    "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
                }
            ],
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t, "tool_choice": "auto"} if t else {})},
            invoke=lambda *a: {
                "id": "x",
                "status": "completed",
                "exit_code": 0,
                "output": "ok",
                "stdout": "ok",
                "stderr": "",
                "invocation_type": "autonomous",
            },
            config=ToolEngineConfig(max_rounds=4),
        )
        self.assertEqual(result.content, "Fallback gelukt.")
        self.assertEqual(result.tool_call_mode, "text_fallback")
        self.assertEqual(len(result.tool_log), 1)


class HumanizerPluginManagerE2ETests(unittest.TestCase):
    """Generic Humanizer E2E via PluginManager — no production special-case."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()
        self.client_patch = patch.object(main, "lm_client", return_value=None)
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_humanizer_search_skills_via_plugin_manager(self) -> None:
        from platform_services import PluginManager
        from reasoning.tool_registry import exact_tool_mentions

        src = Path(self.temp_dir.name) / "humanizer"
        # Minimal local Humanizer-shaped plugin (no git LFS dependency).
        src.mkdir()
        (src / "skill_bridge.py").write_text(
            "import json,sys\n"
            "if sys.argv[1]=='search':\n"
            " print(json.dumps({'query':'humanize','hits':[{'skill':'humanizer','score':1}]}))\n"
            "else:\n"
            " print(json.dumps({'ok':True}))\n",
            encoding="utf-8",
        )
        (src / "hades-plugin.json").write_text(
            json.dumps(
                {
                    "format": 1,
                    "id": "humanizer",
                    "name": "Humanizer",
                    "version": "0.1.0",
                    "runtime_type": "python",
                    "permissions": ["subprocess"],
                    "autonomous": True,
                    "labels": ["humanizer", "writing"],
                    "tools": [
                        {
                            "name": "search_skills",
                            "description": "Search Humanizer skills",
                            "command": ["{python}", "skill_bridge.py", "search", "--query", "{query}"],
                            "input_schema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {"query": {"type": "string"}},
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        plugin = main.plugin_manager.import_local_folder(src, install_dependencies=False)["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        main.platform_db.set_plugin_state(plugin["id"], enabled=True, trust="manual")

        mentions = exact_tool_mentions(
            "Gebruik Humanizer om dit antwoord natuurlijker te maken",
            main.platform_db.list_plugins(),
            main.platform_db.plugin_tools(),
        )
        self.assertTrue(any(item["plugin_id"] == "humanizer" for item in mentions))

        class NativeHumanizerLM:
            def __init__(self) -> None:
                self.calls = 0
                self.payloads: list[dict] = []
                self.saw_tools = False
                self.saw_tool_role = False

            async def models(self):
                return {"data": [{"id": "local-model"}]}

            async def chat(self, payload):
                self.calls += 1
                self.payloads.append(payload)
                if self.calls == 1:
                    self.saw_tools = "tools" in payload
                    names = [t["function"]["name"] for t in (payload.get("tools") or [])]
                    self.saw_tools = self.saw_tools and ("humanizer__search_skills" in names)
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "call_h1",
                                            "type": "function",
                                            "function": {
                                                "name": "humanizer__search_skills",
                                                "arguments": json.dumps({"query": "humanize"}),
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    }
                self.saw_tool_role = any(m.get("role") == "tool" for m in payload["messages"])
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Humanizer is gebruikt; hier is een natuurlijkere versie.",
                            }
                        }
                    ]
                }

        fake = NativeHumanizerLM()
        conversation = self.client.post("/api/conversations", json={"title": "humanizer"}).json()
        with patch.object(main, "lm_client", return_value=fake):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "Gebruik Humanizer om dit antwoord natuurlijker te maken: Hallo wereld."},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(fake.saw_tools, "native tools schema must include Humanizer")
        self.assertTrue(fake.saw_tool_role, "continuation must use role=tool")
        self.assertNotIn("hades_tool_call", body["assistant_message"]["content"])
        self.assertIn("natuurlijk", body["assistant_message"]["content"].lower())
        self.assertEqual(body["tools"][0]["status"], "completed")
        self.assertEqual(body["tools"][0]["plugin_id"], "humanizer")
        calls = main.platform_db.tool_calls("humanizer")
        self.assertTrue(calls)
        self.assertEqual(calls[0]["status"], "completed")
        self.assertEqual(calls[0]["tool_name"], "search_skills")

    def test_raw_text_tool_json_not_returned_to_user_when_budget_exhausted(self) -> None:
        plugin_id = "echo-raw"
        source = Path(self.temp_dir.name) / plugin_id
        source.mkdir()
        (source / "echo.py").write_text("print('ok')\n", encoding="utf-8")
        (source / "hades-plugin.json").write_text(
            json.dumps(
                {
                    "format": 1,
                    "id": plugin_id,
                    "name": "Echo Raw",
                    "version": "1.0.0",
                    "runtime_type": "python",
                    "permissions": ["subprocess"],
                    "autonomous": True,
                    "tools": [
                        {
                            "name": "echo",
                            "description": "echo",
                            "command": ["{python}", "echo.py"],
                            "input_schema": {"type": "object", "properties": {}},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        plugin = main.plugin_manager.import_local_folder(source, install_dependencies=False)["plugin"]
        main.platform_db.set_plugin_state(plugin["id"], enabled=True, trust="manual")
        self.client.put("/api/settings", json={"max_tool_rounds": 0, "plugin_autonomous_tools": True})

        class AlwaysToolLM:
            async def models(self):
                return {"data": [{"id": "local-model"}]}

            async def chat(self, payload):
                content = json.dumps({"hades_tool_call": {"plugin_id": plugin_id, "tool_name": "echo", "input": {}}})
                return {"choices": [{"message": {"role": "assistant", "content": content}}]}

        conversation = self.client.post("/api/conversations", json={"title": "raw"}).json()
        with patch.object(main, "lm_client", return_value=AlwaysToolLM()):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "roep echo aan"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        content = response.json()["assistant_message"]["content"]
        self.assertNotIn("hades_tool_call", content)


class ChatRegenerateContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()
        self.captured: list[dict] = []

        class FakeLM:
            async def models(self_inner):
                return {"data": [{"id": "local-model"}]}

            async def chat(self_inner, payload):
                self.captured.append(payload)
                return {
                    "choices": [{"message": {"role": "assistant", "content": "UNIEK-ANTWOORD"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                }

        self.client_patch = patch.object(main, "lm_client", return_value=FakeLM())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_regenerate_keeps_single_active_user_turn(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "regen"}).json()
        first = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Vraag eenmaal"},
        ).json()
        user_id = first["user_message"]["id"]
        assistant_id = first["assistant_message"]["id"]
        before = len(self.captured)
        # Mirror Chat UI: regenerate passes revise_message_id of the prior user turn.
        second = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={
                "content": "Vraag eenmaal",
                "regenerate_of": assistant_id,
                "revise_message_id": user_id,
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        payload = self.captured[-1]
        user_msgs = [m for m in payload["messages"] if m.get("role") == "user" and m.get("content") == "Vraag eenmaal"]
        self.assertEqual(len(user_msgs), 1, payload["messages"])
        self.assertGreater(len(self.captured), before)


class FiveStepHeterogeneousChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_five_distinct_tools_then_final(self) -> None:
        sequence = ["alpha__a", "beta__b", "gamma__c", "delta__d", "epsilon__e"]
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] <= 5:
                name = sequence[calls["n"] - 1]
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"c{calls['n']}",
                                        "type": "function",
                                        "function": {"name": name, "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {"choices": [{"message": {"role": "assistant", "content": "Keten van vijf afgerond."}}]}

        tools = []
        for plugin_id, tool_name in (
            ("alpha", "a"),
            ("beta", "b"),
            ("gamma", "c"),
            ("delta", "d"),
            ("epsilon", "e"),
        ):
            tools.append(
                {
                    "plugin_id": plugin_id,
                    "name": tool_name,
                    "description": plugin_id,
                    "input_schema": {"type": "object", "properties": {}},
                    "plugin": {"id": plugin_id, "name": plugin_id.title(), "category": "Test"},
                }
            )
        invoked: list[str] = []

        def invoke(plugin_id, tool_name, arguments):
            invoked.append(f"{plugin_id}__{tool_name}")
            return {
                "id": "x",
                "status": "completed",
                "exit_code": 0,
                "output": "ok",
                "stdout": "ok",
                "stderr": "",
                "invocation_type": "autonomous",
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "keten"}],
            query="keten",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=10, max_model_calls=20),
        )
        self.assertEqual(result.content, "Keten van vijf afgerond.")
        self.assertEqual(invoked, sequence)
        self.assertEqual(len(result.tool_log), 5)


class ToolFailureHonestyTests(unittest.IsolatedAsyncioTestCase):
    async def _run_status(self, status: str, *, error: str | None = None, exit_code: int | None = 1) -> list[dict]:
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            tool_msgs = [m for m in payload["messages"] if m.get("role") == "tool"]
            self.assertEqual(len(tool_msgs), 1)
            body = json.loads(tool_msgs[0]["content"])
            self.assertEqual(body.get("status"), status)
            return {"choices": [{"message": {"role": "assistant", "content": f"Observed {status}"}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]

        def invoke(*_a):
            return {
                "id": "x",
                "status": status,
                "error": error,
                "exit_code": exit_code,
                "output": "",
                "stdout": "",
                "stderr": error or "",
                "invocation_type": "autonomous",
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": status}],
            query=status,
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(result.content, f"Observed {status}")
        return result.tool_log

    async def test_plugin_failed_fed_back(self) -> None:
        log = await self._run_status("failed", error="boom", exit_code=1)
        self.assertEqual(log[0]["status"], "failed")

    async def test_plugin_timeout_fed_back(self) -> None:
        log = await self._run_status("timeout", error="timed out", exit_code=None)
        self.assertEqual(log[0]["status"], "timeout")

    async def test_plugin_cancelled_fed_back(self) -> None:
        log = await self._run_status("cancelled", error="cancelled", exit_code=None)
        self.assertEqual(log[0]["status"], "cancelled")

    async def test_blocked_permission_not_invoked(self) -> None:
        invoked = {"n": 0}
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            body = json.loads([m for m in payload["messages"] if m.get("role") == "tool"][0]["content"])
            self.assertEqual(body.get("status"), "blocked")
            return {"choices": [{"message": {"role": "assistant", "content": "Geblokkeerd."}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]

        def enforce(_plugin, _tool):
            raise PermissionError("network policy block")

        def invoke(*_a):
            invoked["n"] += 1
            return {"id": "x", "status": "completed", "exit_code": 0}

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "block"}],
            query="block",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            enforce_permissions=enforce,
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(invoked["n"], 0)
        self.assertEqual(result.tool_log[0]["status"], "blocked")
        self.assertEqual(result.content, "Geblokkeerd.")

    async def test_empty_recoverable_then_final(self) -> None:
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}]}
            return {"choices": [{"message": {"role": "assistant", "content": "Hersteld."}}]}

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "hi"}],
            query="hi",
            tools=[],
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m},
            invoke=lambda *_a: {},
            config=ToolEngineConfig(max_rounds=2, autonomous=False, max_empty_recoveries=1),
        )
        self.assertEqual(result.content, "Hersteld.")
        self.assertIn(ResponseState.EMPTY_RECOVERABLE.value, result.response_states)

    async def test_budget_exhausted_strips_tool_json(self) -> None:
        async def chat(_payload: dict) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "echo__echo", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]
        result = await run_tool_engine(
            messages=[{"role": "user", "content": "budget"}],
            query="budget",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=lambda *_a: {"id": "x", "status": "completed", "exit_code": 0},
            config=ToolEngineConfig(max_rounds=0, autonomous=True),
        )
        self.assertNotIn("hades_tool_call", result.content)
        self.assertNotIn("tool_calls", result.content)
        self.assertTrue(result.content)


class DiscoverAndMcpSpineTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_hydrates_tools_for_next_round(self) -> None:
        from reasoning.tools import DISCOVER_PLUGIN_ID, DISCOVER_TOOL_NAME
        from reasoning.tool_protocol import encode_provider_function_name

        calls = {"n": 0}
        discovered_tool = {
            "plugin_id": "remote",
            "name": "ping",
            "description": "ping",
            "input_schema": {"type": "object", "properties": {}},
            "plugin": {"id": "remote", "name": "Remote", "category": "Test"},
            "metadata": {},
        }
        discover_name = encode_provider_function_name(DISCOVER_PLUGIN_ID, DISCOVER_TOOL_NAME)

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "d1",
                                        "type": "function",
                                        "function": {
                                            "name": discover_name,
                                            "arguments": json.dumps({"query": "ping"}),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            if calls["n"] == 2:
                tools_payload = payload.get("tools") or []
                names = [((t.get("function") or {}).get("name")) for t in tools_payload]
                self.assertIn("remote__ping", names)
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "p1",
                                        "type": "function",
                                        "function": {"name": "remote__ping", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {"choices": [{"message": {"role": "assistant", "content": "Ontdekt en uitgevoerd."}}]}

        def discover(query: str, limit: int = 8, offset: int = 0, category: str | None = None) -> dict:
            return {
                "total": 1,
                "offset": 0,
                "next_offset": None,
                "tools": [{"plugin_id": "remote", "tool_name": "ping", "name": "ping"}],
            }

        invoked: list[str] = []

        def invoke(plugin_id, tool_name, arguments):
            invoked.append(f"{plugin_id}__{tool_name}")
            return {
                "id": "x",
                "status": "completed",
                "exit_code": 0,
                "output": "pong",
                "stdout": "pong",
                "stderr": "",
                "invocation_type": "autonomous",
            }

        tools = [
            {
                "plugin_id": "seed",
                "name": "noop",
                "description": "noop",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "seed", "name": "Seed", "category": "Test"},
            }
        ]
        result = await run_tool_engine(
            messages=[{"role": "user", "content": "discover ping"}],
            query="discover ping",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            discover=discover,
            hydrate_discovered=lambda page: [discovered_tool],
            config=ToolEngineConfig(max_rounds=5),
        )
        self.assertEqual(result.content, "Ontdekt en uitgevoerd.")
        self.assertEqual(invoked, ["remote__ping"])
        self.assertEqual(result.tool_log[0]["tool_name"], DISCOVER_TOOL_NAME)

    async def test_mcp_remote_tool_uses_same_plugin_manager_spine(self) -> None:
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "m1",
                                        "type": "function",
                                        "function": {
                                            "name": "mcp_demo__list_resources",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            tool_msgs = [m for m in payload["messages"] if m.get("role") == "tool"]
            self.assertEqual(len(tool_msgs), 1)
            self.assertEqual(tool_msgs[0].get("tool_call_id"), "m1")
            return {"choices": [{"message": {"role": "assistant", "content": "MCP klaar."}}]}

        tools = [
            {
                "plugin_id": "mcp_demo",
                "name": "list_resources",
                "description": "MCP list",
                "input_schema": {"type": "object", "properties": {}},
                "metadata": {"mcp_remote": True},
                "plugin": {"id": "mcp_demo", "name": "MCP Demo", "category": "MCP"},
            }
        ]
        invoked: list[tuple] = []

        def invoke(plugin_id, tool_name, arguments):
            invoked.append((plugin_id, tool_name, arguments))
            return {
                "id": "mcp-1",
                "status": "completed",
                "exit_code": 0,
                "output": "[]",
                "stdout": "[]",
                "stderr": "",
                "invocation_type": "autonomous",
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "mcp"}],
            query="mcp",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3),
        )
        self.assertEqual(result.content, "MCP klaar.")
        self.assertEqual(invoked, [("mcp_demo", "list_resources", {})])
        self.assertTrue(result.tool_log[0].get("mcp_remote"))


class ParallelToolCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_invokes_respect_order_and_limit(self) -> None:
        calls = {"n": 0}
        active = {"n": 0, "peak": 0}
        lock = asyncio.Lock()

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"c{i}",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": json.dumps({"i": i})},
                                    }
                                    for i in range(4)
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            tool_msgs = [m for m in payload["messages"] if m.get("role") == "tool"]
            self.assertEqual([m.get("tool_call_id") for m in tool_msgs], ["c0", "c1", "c2", "c3"])
            return {"choices": [{"message": {"role": "assistant", "content": "Parallel klaar."}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {"i": {"type": "integer"}}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]

        def invoke(plugin_id, tool_name, arguments):
            # Sync sleep via time — engine wraps in to_thread.
            import time

            # Track concurrency from thread via lock-free peak approx using active counter.
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
            time.sleep(0.05)
            active["n"] -= 1
            return {
                "id": f"r{arguments.get('i')}",
                "status": "completed",
                "exit_code": 0,
                "output": str(arguments.get("i")),
                "stdout": str(arguments.get("i")),
                "stderr": "",
                "invocation_type": "autonomous",
            }

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "parallel"}],
            query="parallel",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3, max_parallel_tool_calls=2),
        )
        self.assertEqual(result.content, "Parallel klaar.")
        self.assertEqual(len(result.tool_log), 4)
        self.assertLessEqual(active["peak"], 2)
        self.assertGreaterEqual(active["peak"], 2)

    async def test_serial_when_max_parallel_is_one(self) -> None:
        active = {"n": 0, "peak": 0}
        calls = {"n": 0}

        async def chat(payload: dict) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "a",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": "{}"},
                                    },
                                    {
                                        "id": "b",
                                        "type": "function",
                                        "function": {"name": "echo__echo", "arguments": "{}"},
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {"choices": [{"message": {"role": "assistant", "content": "Serial."}}]}

        tools = [
            {
                "plugin_id": "echo",
                "name": "echo",
                "description": "echo",
                "input_schema": {"type": "object", "properties": {}},
                "plugin": {"id": "echo", "name": "Echo", "category": "Test"},
            }
        ]

        def invoke(*_a):
            import time

            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
            time.sleep(0.03)
            active["n"] -= 1
            return {"id": "x", "status": "completed", "exit_code": 0, "output": "ok", "stdout": "", "stderr": "", "invocation_type": "autonomous"}

        result = await run_tool_engine(
            messages=[{"role": "user", "content": "serial"}],
            query="serial",
            tools=tools,
            chat=chat,
            build_payload=lambda m, t: {"model": "m", "messages": m, **({"tools": t} if t else {})},
            invoke=invoke,
            config=ToolEngineConfig(max_rounds=3, max_parallel_tool_calls=1),
        )
        self.assertEqual(result.content, "Serial.")
        self.assertEqual(active["peak"], 1)


class UsageEstimateAndStatusTests(unittest.TestCase):
    def test_estimate_from_response_and_status_transitions(self) -> None:
        from reasoning.usage_telemetry import UsageTelemetry, estimate_usage_from_response

        estimated = estimate_usage_from_response(
            {"choices": [{"message": {"role": "assistant", "content": "abcd" * 10}}]}
        )
        self.assertIsNotNone(estimated)
        self.assertTrue(estimated.get("estimated"))
        self.assertGreater(estimated["total_tokens"], 0)

        tel = UsageTelemetry()
        tel.set_status("queued", conversation_id="c1", model_id="m1")
        tel.record_usage(None, conversation_id="c1", model_id="m1", kind="unavailable")
        tel.record_usage(estimated, conversation_id="c1", model_id="m1", kind="estimate", status="generating")
        tel.set_status("error", conversation_id="c1", error="boom")
        snap = tel.snapshot("c1")
        self.assertEqual(snap.last_error, "boom")
        self.assertEqual(snap.status, "error")
        self.assertEqual(snap.current_kind, "estimate")
        tel.set_status("cancelled", conversation_id="c1")
        self.assertEqual(tel.snapshot("c1").status, "cancelled")

    def test_record_model_usage_labels_estimate(self) -> None:
        from reasoning.usage_telemetry import usage_telemetry

        before = usage_telemetry.snapshot("est-convo").model_calls
        main.record_model_usage(
            {"choices": [{"message": {"role": "assistant", "content": "hello world token estimate"}}]},
            agent_id="chat",
            model_id="local-model",
            conversation_id="est-convo",
        )
        snap = usage_telemetry.snapshot("est-convo")
        self.assertEqual(snap.current_kind, "estimate")
        self.assertGreater(snap.model_calls, before)


class PluginZipEmptyRejectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()
        self.client_patch = patch.object(main, "lm_client", return_value=None)
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_import_zip_rejects_empty_upload(self) -> None:
        self.client.put("/api/settings", json={"file_write_policy": "allow", "network_policy": "block"})
        response = self.client.post(
            "/api/plugins/import-zip",
            files={"file": ("empty.zip", b"", "application/zip")},
            data={"install_dependencies": "false", "approved_file_write": "true"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("leeg", response.json()["detail"].lower())


class StreamToolRoundProgressTests(unittest.IsolatedAsyncioTestCase):
    """Wave 1: tool rounds stream live SSE (content + tool_call progress)."""

    async def test_tool_call_delta_emits_tool_status_and_keeps_content_stream(self) -> None:
        from reasoning.events import RunEventBus

        bus = RunEventBus()
        encoded = encode_provider_function_name("echo", "echo")
        assembled = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": encoded, "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

        async def fake_events(_payload: dict):
            yield {"type": "content_delta", "delta": "Bezig "}
            yield {
                "type": "tool_call_delta",
                "delta": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": encoded, "arguments": ""},
                    }
                ],
            }
            yield {
                "type": "tool_call_delta",
                "delta": [{"index": 0, "function": {"arguments": "{}"}}],
            }
            yield {"type": "completed", "response": assembled}

        class FakeClient:
            async def chat_stream_events(self, payload: dict):
                async for item in fake_events(payload):
                    yield item

            async def chat_stream(self, payload: dict):
                if False:
                    yield ""

            async def chat(self, payload: dict):
                raise AssertionError("non-stream chat must not be used when stream assembles tools")

        class FakeSlot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakeGateway:
            def configure(self, **kwargs):
                return None

            def snapshot_config(self, **kwargs):
                return None

            def slot(self, *args, **kwargs):
                return FakeSlot()

            async def chat(self, fn, body, **kwargs):
                raise AssertionError("gateway non-stream fallback must not run for successful tool stream")

        with (
            patch.object(main, "lm_client", return_value=FakeClient()),
            patch.object(main, "model_gateway", FakeGateway()),
            patch.object(main, "run_event_bus", bus),
            patch.object(
                main,
                "runtime_values",
                return_value={
                    "streaming": True,
                    "stream_provisional_text": True,
                    "progress_events_enabled": True,
                    "lm_studio_base_url": "http://127.0.0.1:1234/v1",
                    "max_model_concurrency": 1,
                    "request_timeout_seconds": 30,
                },
            ),
            patch.object(main.model_router, "set_global_limit", return_value=None),
        ):
            response = await main._chat_with_optional_stream(
                model_id="local-model",
                profile={"temperature": 0.2, "top_p": 0.9, "max_tokens": 256},
                reasoning="standard",
                run_id="run_stream_tools",
                payload={
                    "model": "local-model",
                    "messages": [{"role": "user", "content": "echo please"}],
                    "tools": [{"type": "function", "function": {"name": encoded}}],
                },
            )

        self.assertEqual(
            ((response.get("choices") or [{}])[0].get("message") or {}).get("tool_calls")[0]["id"],
            "call_1",
        )
        history = bus.history("run_stream_tools")
        types = [event.type for event in history]
        self.assertIn("stream_delta", types)
        self.assertIn("tool_status", types)
        tool_events = [event for event in history if event.type == "tool_status"]
        self.assertEqual(len(tool_events), 1, "argument-only deltas must not spam tool_status")
        self.assertEqual(tool_events[0].payload.get("status"), "streaming")
        self.assertEqual(tool_events[0].payload.get("plugin_id"), "echo")
        self.assertEqual(tool_events[0].payload.get("tool_name"), "echo")
        self.assertTrue(tool_events[0].provisional)
        stream_text = "".join(
            str(event.payload.get("delta") or "") for event in history if event.type == "stream_delta"
        )
        self.assertEqual(stream_text, "Bezig ")

    def test_tool_rounds_use_stream_when_run_id_present(self) -> None:
        import inspect

        source = inspect.getsource(main.run_model_with_optional_tool)
        self.assertIn("use_stream = bool(run_id)", source)
        self.assertNotIn('and not payload.get("tools")', source)


if __name__ == "__main__":
    unittest.main()
