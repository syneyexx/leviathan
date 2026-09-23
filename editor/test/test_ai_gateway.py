"""Protocol, task, action, and OmniRoute gateway unit tests."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.actions import validate_actions
from ai.gateway import OmniRouteEditorGateway, reset_gateway_for_tests
from ai.protocol import validate_context, make_result, CONTEXT_PROTOCOL
from ai.providers.mock import MockProvider, make_placeholder_png
from ai.providers.registry import ProviderRegistry
from ai.tasks import get_task, resolve_task_id, list_tasks
from ai.temp_assets import TempAssetStore


def test_validate_context_ok():
    raw = {
        "protocol": CONTEXT_PROTOCOL,
        "version": 1,
        "request": {"id": "abc123", "task": "generate_image", "instruction": "ocean hero"},
        "selection": {"keys": ["node:1"], "primary": "node:1", "count": 1},
        "output": {"width": 1280, "height": 720, "variants": 2, "placement": "cover"},
        "style": {"source": "page_and_selection"},
        "policy": {"previewOnly": True},
    }
    ctx, err = validate_context(raw)
    assert err is None
    assert ctx["request"]["task"] == "generate_image"
    assert ctx["output"]["variants"] == 2
    assert ctx["policy"]["requireExplicitAccept"] is True


def test_validate_context_rejects_bad_version():
    ctx, err = validate_context({"version": 99, "request": {"task": "generate_image", "instruction": "x"}})
    assert ctx is None and "version" in err


def test_validate_context_rejects_unknown_task_later():
    # Protocol allows any string task; gateway resolves
    ctx, err = validate_context({"request": {"task": "nope", "instruction": "x"}})
    assert err is None
    assert resolve_task_id(ctx["request"]["task"]) is None


def test_validate_context_rejects_huge_variants():
    ctx, err = validate_context(
        {"request": {"task": "generate_image", "instruction": "x"}, "output": {"variants": 99}}
    )
    assert ctx is None and "variants" in err


def test_validate_context_rejects_bad_placement():
    ctx, err = validate_context(
        {"request": {"task": "generate_image", "instruction": "x"}, "output": {"placement": "explode"}}
    )
    assert ctx is None


def test_tasks_exist():
    assert get_task("generate_image").capability == "image.generate"
    assert resolve_task_id("replace") == "replace_image"
    assert len(list_tasks()) >= 10


def test_actions_allowlist():
    ok, err = validate_actions(
        [{"type": "update_style_properties", "target": "node:1", "changes": {"padding": "12px"}}]
    )
    assert err is None and ok[0]["changes"]["padding"] == "12px"

    bad, err = validate_actions([{"type": "eval_script", "target": "node:1"}])
    assert bad is None and err

    bad2, err2 = validate_actions(
        [{"type": "update_style_properties", "target": "node:1", "changes": {"background": "url(javascript:alert(1))"}}]
    )
    assert bad2 is None and "unsafe" in err2


def test_mock_png_magic():
    raw = make_placeholder_png(64, 36, "seed")
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")


def test_mock_provider_variants():
    p = MockProvider(latency_ms=0)
    from ai.providers.base import ProviderRequest

    res = p.execute(
        ProviderRequest(
            request_id="r1",
            task="generate_image",
            capability="image.generate",
            instruction="leviathan ocean",
            context={},
            width=128,
            height=72,
            variants=2,
        )
    )
    assert res.ok and len(res.variants) == 2
    assert res.variants[0]["isMock"] is True


def test_registry_no_provider_without_mock():
    with mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "", "LEVIATHAN_EDITOR_AI_IMAGE_ENDPOINT": ""}, clear=False):
        # Clear image keys
        env = {k: v for k, v in os.environ.items() if not k.startswith("LEVIATHAN_EDITOR_AI")}
        env["LEVIATHAN_EDITOR_AI_MOCK"] = "0"
        with mock.patch.dict(os.environ, env, clear=True):
            reg = ProviderRegistry()
            report = reg.capability_report()
            assert report["capabilities"]["image.generate"]["available"] is False


def test_registry_mock_enables_image():
    with mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "1"}, clear=False):
        reg = ProviderRegistry()
        report = reg.capability_report()
        assert report["mockEnabled"] is True
        assert report["capabilities"]["image.generate"]["available"] is True
        assert report["capabilities"]["image.edit"]["available"] is False


def test_gateway_generate_no_doc_mutation():
    reset_gateway_for_tests()
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "1"}, clear=False):
            gw = OmniRouteEditorGateway(Path(tmp) / "ai-temp")
            status, body = gw.handle(
                {
                    "instruction": "kosmische data oceaan in deze stijl",
                    "task": "generate_image",
                    "context": {
                        "request": {
                            "id": "req1",
                            "task": "generate_image",
                            "instruction": "kosmische data oceaan in deze stijl",
                        },
                        "selection": {"primary": "node:hero", "keys": ["node:hero"], "count": 1},
                        "output": {"width": 320, "height": 180, "variants": 1},
                        "style": {"source": "page_and_selection", "tokens": {"--accent": "#5B9FD4"}},
                        "targetFingerprint": {"nodeKey": "node:hero"},
                    },
                }
            )
            assert status == 200, body
            assert body["status"] == "success"
            assert body["diagnostics"]["documentMutated"] is False
            assert body["provider"]["isMock"] is True
            variant = body["result"]["variants"][0]
            assert variant["tempId"]
            assert variant["url"].startswith("/api/editor-ai/preview/")
            got = gw.get_preview_bytes(variant["tempId"])
            assert got and got[0].startswith(b"\x89PNG")


def test_gateway_invalid_task():
    reset_gateway_for_tests()
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "1"}, clear=False):
            gw = OmniRouteEditorGateway(Path(tmp))
            status, body = gw.handle({"instruction": "x", "task": "hack_the_planet"})
            assert status == 400
            assert body["error"]["code"] == "invalid_task"


def test_gateway_no_provider():
    reset_gateway_for_tests()
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "0", "LEVIATHAN_EDITOR_AI_IMAGE_ENDPOINT": ""}, clear=False):
            # Ensure image provider off
            os.environ.pop("LEVIATHAN_EDITOR_AI_IMAGE_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            gw = OmniRouteEditorGateway(Path(tmp))
            status, body = gw.handle(
                {
                    "instruction": "make image",
                    "task": "generate_image",
                }
            )
            assert status == 501
            assert body["error"]["code"] == "no-provider"


def test_temp_asset_cleanup():
    with tempfile.TemporaryDirectory() as tmp:
        store = TempAssetStore(Path(tmp), ttl_seconds=3600)
        raw = make_placeholder_png(32, 32, "a")
        rec = store.put(raw, meta={"requestId": "r99"})
        assert store.get(rec["id"])
        assert store.cleanup_request("r99") >= 1
        assert store.get(rec["id"]) is None


def test_cancel_marks_abandoned():
    reset_gateway_for_tests()
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "1", "LEVIATHAN_EDITOR_AI_MOCK_LATENCY_MS": "500"}, clear=False):
            gw = OmniRouteEditorGateway(Path(tmp))
            results = {}

            def run():
                status, body = gw.handle({"instruction": "slow", "task": "generate_image", "requestId": "cancel-me"})
                results["status"] = status
                results["body"] = body

            t = threading.Thread(target=run)
            t.start()
            import time

            time.sleep(0.05)
            out = gw.cancel("cancel-me")
            assert out["ok"] is True
            assert out["providerCancelSupported"] is False
            t.join(timeout=2)


def test_make_result_shape():
    r = make_result(request_id="x", status="success", result={"kind": "asset_preview", "variants": []})
    assert r["protocol"] == "leviathan.editor-result"
    assert r["version"] == 1


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, exc)
    if failed:
        raise SystemExit(1)
    print(f"ai unit ok ({len(tests)})")
