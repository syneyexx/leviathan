"""Integration tests against a fake LM Studio native REST control server (stdlib)."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

import pytest

from Data.modules.models.contracts import LoadOptions
from Data.modules.models.errors import ModelControlError
from Data.modules.models.providers.lm_studio import LMStudioAdapter


class _FakeState:
    def __init__(self) -> None:
        self.loaded: dict[str, dict[str, Any]] = {}
        self.last_load_body: dict[str, Any] | None = None
        self.version = "0.4.25"


def _make_handler(state: _FakeState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _send(self, code: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/v1/models":
                models: list[dict[str, Any]] = []
                for key, meta in state.loaded.items():
                    models.append(
                        {
                            "id": key,
                            "model": key,
                            "instance_id": meta["instance_id"],
                            "loaded": True,
                            "state": "loaded",
                            "type": "llm",
                        }
                    )
                models.append(
                    {"id": "qwen/qwen2.5-14b-instruct", "type": "llm", "loaded": False}
                )
                self._send(200, {"models": models, "version": state.version})
                return
            if path == "/v1/models":
                self._send(200, {"data": [{"id": "qwen/qwen2.5-14b-instruct"}]})
                return
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            body = self._read_json()
            if path == "/api/v1/models/load":
                state.last_load_body = body
                model = body.get("model")
                if not model:
                    self._send(400, {"error": "model required"})
                    return
                if model == "missing/model":
                    self._send(404, {"error": "model not found"})
                    return
                if body.get("context_length") and int(body["context_length"]) > 200_000:
                    self._send(500, {"error": "failed to allocate buffer for kv cache"})
                    return
                instance_id = f"inst-{model}"
                applied = {
                    "context_length": body.get("context_length", 4096),
                    "eval_batch_size": body.get("eval_batch_size", 512),
                    "flash_attention": body.get("flash_attention", False),
                    "offload_kv_cache_to_gpu": body.get("offload_kv_cache_to_gpu", True),
                }
                if "num_experts" in body:
                    applied["num_experts"] = body["num_experts"]
                state.loaded[model] = {"instance_id": instance_id, "config": applied}
                resp: dict[str, Any] = {
                    "type": "llm",
                    "instance_id": instance_id,
                    "load_time_seconds": 1.23,
                    "status": "loaded",
                }
                if body.get("echo_load_config"):
                    resp["load_config"] = applied
                self._send(200, resp)
                return
            if path == "/api/v1/models/unload":
                instance_id = body.get("instance_id") or body.get("identifier")
                model = body.get("model")
                removed = None
                for key, meta in list(state.loaded.items()):
                    if (
                        meta["instance_id"] == instance_id
                        or key == model
                        or key == instance_id
                    ):
                        removed = state.loaded.pop(key)
                        break
                if removed is None and not instance_id:
                    self._send(404, {"error": "instance not found"})
                    return
                self._send(200, {"status": "unloaded", "instance_id": instance_id})
                return
            self._send(404, {"error": "not found"})

    return Handler


@pytest.fixture
def lm_studio_server():
    state = _FakeState()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        yield state, base
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_probe_native_rest_capabilities(lm_studio_server):
    _state, base = lm_studio_server

    async def _run() -> None:
        adapter = LMStudioAdapter(provider_id="lms", endpoint=base, timeout_seconds=5)
        caps = await adapter.probe_control_capabilities()
        assert caps.native_rest.value == "SUPPORTED"
        assert caps.load.value == "SUPPORTED"
        assert caps.flash_attention.value == "SUPPORTED"
        assert caps.custom_gpu_split.value == "UNSUPPORTED"

    asyncio.run(_run())


def test_load_echo_config_and_reconcile(lm_studio_server):
    state, base = lm_studio_server

    async def _run() -> None:
        adapter = LMStudioAdapter(provider_id="lms", endpoint=base, timeout_seconds=5)
        await adapter.probe_control_capabilities()
        result = await adapter.load(
            "qwen/qwen2.5-14b-instruct",
            LoadOptions(
                context_length=8192,
                batch_size=256,
                flash_attention=True,
                offload_kv_cache_to_gpu=True,
            ),
        )
        assert result["reconciled"] is True
        assert result["appliedConfig"]["context_length"] == 8192
        assert result["appliedConfig"]["flash_attention"] is True
        assert state.last_load_body["echo_load_config"] is True
        assert state.last_load_body["context_length"] == 8192
        assert state.last_load_body["eval_batch_size"] == 256
        receipt = adapter.last_load_receipt()
        assert receipt is not None
        assert receipt.instance_id.startswith("inst-")

    asyncio.run(_run())


def test_unload_reconciles(lm_studio_server):
    state, base = lm_studio_server

    async def _run() -> None:
        adapter = LMStudioAdapter(provider_id="lms", endpoint=base, timeout_seconds=5)
        await adapter.probe_control_capabilities()
        await adapter.load("qwen/qwen2.5-14b-instruct", LoadOptions(context_length=4096))
        assert "qwen/qwen2.5-14b-instruct" in state.loaded
        out = await adapter.unload("qwen/qwen2.5-14b-instruct")
        assert out["status"] == "unloaded"
        assert out["reconciled"] is True
        assert "qwen/qwen2.5-14b-instruct" not in state.loaded

    asyncio.run(_run())


def test_load_oom_classified(lm_studio_server):
    _state, base = lm_studio_server

    async def _run() -> None:
        adapter = LMStudioAdapter(provider_id="lms", endpoint=base, timeout_seconds=5)
        await adapter.probe_control_capabilities()
        with pytest.raises(ModelControlError) as ei:
            await adapter.load(
                "qwen/qwen2.5-14b-instruct",
                LoadOptions(context_length=250_000),
            )
        assert "OOM" in ei.value.code

    asyncio.run(_run())


def test_model_not_found(lm_studio_server):
    _state, base = lm_studio_server

    async def _run() -> None:
        adapter = LMStudioAdapter(provider_id="lms", endpoint=base, timeout_seconds=5)
        await adapter.probe_control_capabilities()
        with pytest.raises(ModelControlError) as ei:
            await adapter.load("missing/model", LoadOptions(context_length=1024))
        assert ei.value.code in {"MODEL_NOT_FOUND", "LOAD_FAILED"}

    asyncio.run(_run())
