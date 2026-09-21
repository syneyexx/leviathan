"""Optional OmniRoute coding backend — behavior, fallback, tokens, secrets, resume."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_jobs import CodingJobStore, reset_coding_job_store_for_tests
from coding_omniroute import (
    PLUGIN_ID,
    STATUS_COMPLETION_FAILED,
    STATUS_NO_ELIGIBLE_ROUTE,
    STATUS_PLUGIN_DISABLED,
    STATUS_PLUGIN_MISSING,
    STATUS_PLUGIN_NOT_READY,
    OmniRouteCodingChat,
    OmniRouteCodingProvider,
    clear_omniroute_inventory_cache,
    public_routing_snapshot,
    wrap_coding_chat_fn,
)


def _ready_plugin(**overrides):
    row = {
        "id": PLUGIN_ID,
        "enabled": True,
        "status": "ready",
        "trust": "verified",
        "health": "prepared",
        "failure_state": None,
        "permissions": ["subprocess", "network"],
        "capabilities": {"effects": ["subprocess", "network"]},
        "manifest": {"autonomous": True, "capabilities": {"effects": ["subprocess", "network"]}},
    }
    row.update(overrides)
    return row


def _inventory(n: int = 3, *, secret: str | None = None) -> dict:
    models = [{"id": f"model-{i}", "context_length": 8000 + i} for i in range(n)]
    payload = {
        "ok": True,
        "local": {"ok": True, "base_url": "http://127.0.0.1:1234/v1", "local": True, "models": models, "count": n},
        "extra": [],
    }
    if secret:
        payload["api_key"] = secret
    return payload


class _FakeInvoke:
    def __init__(self, inventory: dict):
        self.inventory = inventory
        self.calls: list[tuple[str, str]] = []

    def __call__(self, plugin_id, tool_name, input_data, **kwargs):
        self.calls.append((plugin_id, tool_name))
        return {"status": "completed", "stdout": json.dumps(self.inventory)}


class OmniRouteOffPathTests(unittest.TestCase):
    def test_wrap_returns_same_callable_when_off(self) -> None:
        sentinel = object()

        def fallback(payload):  # noqa: ANN001
            return sentinel

        wrapped = wrap_coding_chat_fn(fallback, use_omniroute=False, plugin_manager=None)
        self.assertIs(wrapped, fallback)
        self.assertIs(wrapped({"messages": []}), sentinel)


class AvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_omniroute_inventory_cache()

    def test_plugin_missing(self) -> None:
        provider = OmniRouteCodingProvider(plugin_lookup=lambda _pid: None)
        avail = provider.availability()
        self.assertFalse(avail.usable)
        self.assertEqual(avail.status_code, STATUS_PLUGIN_MISSING)
        self.assertEqual(avail.status_label, "OmniRoute plugin not installed")
        result = asyncio.run(provider.complete({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), STATUS_PLUGIN_MISSING)

    def test_plugin_disabled(self) -> None:
        provider = OmniRouteCodingProvider(plugin_lookup=lambda _pid: _ready_plugin(enabled=False))
        avail = provider.availability()
        self.assertFalse(avail.usable)
        self.assertEqual(avail.status_code, STATUS_PLUGIN_DISABLED)

    def test_plugin_not_ready(self) -> None:
        provider = OmniRouteCodingProvider(plugin_lookup=lambda _pid: _ready_plugin(status="needs_review"))
        avail = provider.availability()
        self.assertFalse(avail.usable)
        self.assertEqual(avail.status_code, STATUS_PLUGIN_NOT_READY)

    def test_plugin_unhealthy_failure_state(self) -> None:
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(failure_state="dependency_failed", status="needs_review", enabled=False)
        )
        self.assertEqual(provider.availability().status_code, STATUS_PLUGIN_DISABLED)

    def test_untrusted_plugin_is_not_invoked(self) -> None:
        invoke = _FakeInvoke(_inventory())
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(trust="untrusted"),
            plugin_tools=lambda _pid: [
                {"name": "chat", "enabled": True, "metadata": {"autonomous": True}, "capabilities": {"effects": ["network", "subprocess"]}}
            ],
            invoke=invoke,
        )
        avail = provider.availability()
        self.assertFalse(avail.usable)
        self.assertEqual(avail.status_code, STATUS_PLUGIN_NOT_READY)
        self.assertIn("trust=", avail.reason)
        result = asyncio.run(provider.complete({"messages": [{"role": "user", "content": "x"}]}))
        self.assertEqual(result.get("error"), STATUS_PLUGIN_NOT_READY)
        self.assertEqual(invoke.calls, [])

    def test_ready_plugin_without_registered_tools_is_not_usable(self) -> None:
        invoke = _FakeInvoke(_inventory())
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [],
            invoke=invoke,
        )
        avail = provider.availability()
        self.assertFalse(avail.usable)
        self.assertEqual(avail.reason, "omniroute_tools_not_registered")
        self.assertEqual(invoke.calls, [])


class RoutingAndFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_omniroute_inventory_cache()

    def _provider(self, inventory=None, complete_fn=None):
        inv = inventory if inventory is not None else _inventory(4)
        invoke = _FakeInvoke(inv)
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [{"name": "chat", "enabled": True, "metadata": {"autonomous": True}, "capabilities": {"effects": ["network", "subprocess"]}}],
            invoke=invoke,
            complete_fn=complete_fn or (lambda payload, selection: {"ok": True, "response": {"choices": [{"message": {"content": "ok"}}]}, "model": selection["model_id"]}),
            settings=lambda: {"allow_cloud_model_fallback": False, "lm_studio_api_key": "lm-studio"},
        )
        provider._invoke_spy = invoke  # type: ignore[attr-defined]
        return provider

    def test_successful_route_uses_omniroute_complete(self) -> None:
        seen = {}

        def complete_fn(payload, selection):  # noqa: ANN001
            seen["selection"] = selection
            seen["payload"] = payload
            return {"ok": True, "response": {"choices": [{"message": {"content": "from-omni"}}], "model": selection["model_id"]}, "model": selection["model_id"]}

        provider = self._provider(complete_fn=complete_fn)
        chat = OmniRouteCodingChat(lambda _p: {"choices": [{"message": {"content": "fallback"}}]}, provider, allow_fallback=True)
        import asyncio

        result = asyncio.run(chat.chat({"model": "local", "messages": [{"role": "user", "content": "fix add()"}]}))
        self.assertEqual(result["choices"][0]["message"]["content"], "from-omni")
        self.assertTrue(chat.last_snapshot["omniroute_used"])
        self.assertFalse(chat.last_snapshot["fallback_used"])
        self.assertEqual(seen["selection"]["base_url"], "http://127.0.0.1:1234/v1")
        self.assertEqual(provider.routing_llm_calls, 0)

    def test_fallback_when_completion_fails(self) -> None:
        provider = self._provider(complete_fn=lambda *_a: {"ok": False, "error": STATUS_COMPLETION_FAILED})
        chat = OmniRouteCodingChat(lambda _p: {"choices": [{"message": {"content": "std"}}]}, provider, allow_fallback=True)
        import asyncio

        result = asyncio.run(chat.chat({"messages": [{"role": "user", "content": "x"}]}))
        self.assertEqual(result["choices"][0]["message"]["content"], "std")
        self.assertTrue(chat.last_snapshot["fallback_used"])
        self.assertEqual(chat.last_snapshot["fallback_reason"], STATUS_COMPLETION_FAILED)
        self.assertFalse(chat.last_snapshot["omniroute_used"])

    def test_no_fallback_raises(self) -> None:
        provider = self._provider(complete_fn=lambda *_a: {"ok": False, "error": STATUS_COMPLETION_FAILED})
        chat = OmniRouteCodingChat(lambda _p: {"choices": [{"message": {"content": "std"}}]}, provider, allow_fallback=False)
        import asyncio

        with self.assertRaises(RuntimeError):
            asyncio.run(chat.chat({"messages": [{"role": "user", "content": "x"}]}))

    def test_missing_plugin_falls_back(self) -> None:
        provider = OmniRouteCodingProvider(plugin_lookup=lambda _pid: None)
        chat = OmniRouteCodingChat(lambda _p: "fallback-ok", provider, allow_fallback=True)
        import asyncio

        result = asyncio.run(chat.chat({"messages": [{"role": "user", "content": "x"}]}))
        self.assertEqual(result, "fallback-ok")
        self.assertEqual(chat.last_snapshot["fallback_reason"], STATUS_PLUGIN_MISSING)

    def test_disabled_plugin_is_not_invoked(self) -> None:
        invoke = _FakeInvoke(_inventory())
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(enabled=False),
            invoke=invoke,
        )
        result = asyncio.run(provider.complete({"messages": []}))
        self.assertEqual(result.get("error"), STATUS_PLUGIN_DISABLED)
        self.assertEqual(invoke.calls, [])

    def test_remote_excluded_when_cloud_blocked(self) -> None:
        inventory = {
            "ok": True,
            "local": {"ok": False, "base_url": "http://127.0.0.1:1234/v1", "local": True, "models": [], "count": 0},
            "extra": [
                {
                    "ok": True,
                    "base_url": "https://api.example.com/v1",
                    "local": False,
                    "models": [{"id": "cloud-1"}],
                    "count": 1,
                }
            ],
        }
        provider = self._provider(inventory=inventory)
        selection = provider.select_route(inventory=inventory, requirements={"allow_remote": False})
        self.assertFalse(selection.get("ok"))
        self.assertEqual(selection.get("error"), STATUS_NO_ELIGIBLE_ROUTE)


class TokenEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_omniroute_inventory_cache()

    def test_full_catalog_not_injected_into_prompt(self) -> None:
        inventory = _inventory(400)
        captured = {}

        def complete_fn(payload, selection):  # noqa: ANN001
            captured["messages"] = json.dumps(payload.get("messages"))
            captured["selection"] = selection
            return {"ok": True, "response": {"choices": [{"message": {"content": "ok"}}]}, "model": selection["model_id"]}

        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [{"name": "chat", "enabled": True, "metadata": {"autonomous": True}, "capabilities": {"effects": ["network"]}}],
            invoke=_FakeInvoke(inventory),
            complete_fn=complete_fn,
            settings=lambda: {"allow_cloud_model_fallback": False},
        )
        prompt = [{"role": "user", "content": "Implement add() with a test."}]
        baseline = json.dumps(prompt)
        result = asyncio.run(provider.complete({"messages": prompt, "model": "local"}))
        self.assertTrue(result.get("ok"))
        self.assertEqual(captured["messages"], baseline)
        for i in range(400):
            self.assertNotIn(f"model-{i}", captured["messages"])
        delta = provider.prompt_catalog_delta({"messages": prompt})
        self.assertFalse(delta["catalog_injected_into_prompt"])
        self.assertEqual(delta["prompt_chars"], len(baseline))
        self.assertEqual(provider.routing_llm_calls, 0)
        self.assertEqual(result["snapshot"]["catalog_injected_into_prompt"], False)
        self.assertEqual(result["snapshot"]["extra_routing_llm_calls"], 0)

    def test_omniroute_adds_almost_no_prompt_overhead(self) -> None:
        messages = [{"role": "user", "content": "GOAL: fix add\nFILE util.py\n```\ndef add(a,b):\n    return a-b\n```"}]
        baseline_chars = len(json.dumps(messages))
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [{"name": "chat", "enabled": True, "capabilities": {"effects": ["network"]}}],
            invoke=_FakeInvoke(_inventory(80)),
            complete_fn=lambda payload, selection: {
                "ok": True,
                "response": {"choices": [{"message": {"content": "x"}}]},
                "model": selection["model_id"],
            },
        )
        asyncio.run(provider.complete({"messages": messages}))
        delta = provider.prompt_catalog_delta({"messages": messages})
        self.assertEqual(delta["prompt_chars"], baseline_chars)
        self.assertEqual(delta["token_count_mode"], "serialized_prompt_chars")


class DiscoveryCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_omniroute_inventory_cache()

    def test_multiple_completions_reuse_inventory(self) -> None:
        invoke = _FakeInvoke(_inventory(5))
        calls = {"n": 0}

        def complete_fn(payload, selection):  # noqa: ANN001
            calls["n"] += 1
            return {"ok": True, "response": {"choices": [{"message": {"content": "ok"}}]}, "model": selection["model_id"]}

        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [{"name": "chat", "enabled": True, "capabilities": {"effects": ["network"]}}],
            invoke=invoke,
            complete_fn=complete_fn,
            generation=lambda: 1,
        )
        with patch("coding_omniroute._inventory_ttl_seconds", return_value=60.0):
            asyncio.run(provider.complete({"messages": [{"role": "user", "content": "a"}]}))
            asyncio.run(provider.complete({"messages": [{"role": "user", "content": "b"}]}))
        self.assertEqual(len(invoke.calls), 1)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(provider.discovery_calls, 1)

    def test_registry_generation_busts_inventory_cache(self) -> None:
        invoke = _FakeInvoke(_inventory(2))
        gen = {"n": 1}
        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [{"name": "chat", "enabled": True, "capabilities": {"effects": ["network"]}}],
            invoke=invoke,
            complete_fn=lambda payload, selection: {
                "ok": True,
                "response": {"choices": [{"message": {"content": "ok"}}]},
                "model": selection["model_id"],
            },
            generation=lambda: gen["n"],
        )
        with patch("coding_omniroute._inventory_ttl_seconds", return_value=60.0):
            asyncio.run(provider.complete({"messages": [{"role": "user", "content": "a"}]}))
            gen["n"] = 2
            asyncio.run(provider.complete({"messages": [{"role": "user", "content": "b"}]}))
        self.assertEqual(len(invoke.calls), 2)
        self.assertEqual(provider.discovery_calls, 2)


class SecretRedactionTests(unittest.TestCase):
    def test_snapshot_and_errors_redact_keys(self) -> None:
        secret = "sk-live-SUPER-SECRET-KEY"
        snap = public_routing_snapshot(
            {
                "omniroute_requested": True,
                "api_key": secret,
                "authorization": f"Bearer {secret}",
                "selected_model": "qwen",
            }
        )
        blob = json.dumps(snap)
        self.assertNotIn(secret, blob)
        self.assertNotIn("sk-live", blob)
        self.assertEqual(snap.get("selected_model"), "qwen")
        self.assertNotIn("api_key", snap)

    def test_reason_strings_cannot_carry_api_keys(self) -> None:
        secret = "sk-live-SHOULD-NOT-LEAK"
        snap = public_routing_snapshot(
            {
                "omniroute_requested": True,
                "reason": f"provider said {secret}",
                "status_label": f"Bearer {secret}",
            }
        )
        blob = json.dumps(snap)
        self.assertNotIn(secret, blob)
        self.assertNotIn("sk-live", blob)

    def test_job_state_redacts_secrets_on_routing_event(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)

        def runner(params):  # noqa: ANN001
            progress = params["progress"]
            progress(
                "MODEL_ROUTING",
                {
                    "omniroute_requested": True,
                    "omniroute_used": True,
                    "api_key": "sk-live-SHOULD-NOT-LEAK",
                    "selected_model": "local-qwen",
                },
            )
            return {"status": "verified", "id": "r1"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp), "use_omniroute": True})
        for _ in range(80):
            snap = store.get(job["id"])
            if snap["status"] == "verified":
                break
            import time

            time.sleep(0.02)
        snap = store.get(job["id"])
        blob = json.dumps(snap)
        self.assertNotIn("sk-live-SHOULD-NOT-LEAK", blob)
        self.assertEqual((snap.get("omniroute") or {}).get("selected_model"), "local-qwen")


class ResumeAndCancelTests(unittest.TestCase):
    def test_paused_job_retains_use_omniroute(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        job = store.start(
            runner=lambda params: {"status": "verified", "id": "r"},
            params={"goal": "g", "source_repo": str(tmp), "use_omniroute": True},
        )
        import time

        for _ in range(80):
            snap = store.get(job["id"])
            if snap["status"] in {"verified", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        snap = store.get(job["id"])
        self.assertTrue((snap.get("params") or {}).get("use_omniroute"))
        self.assertTrue((snap.get("omniroute") or {}).get("omniroute_requested"))

    def test_legacy_job_without_field_is_off(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = CodingJobStore(tmp)
        jid = "cjob_legacy"
        (tmp / jid).mkdir()
        payload = {
            "id": jid,
            "status": "paused",
            "params": {"goal": "g", "source_repo": str(tmp)},
            "cancel_requested": False,
            "checkpoint": {"phase": "paused"},
            "execution_payload": {"params": {"goal": "g", "source_repo": str(tmp)}},
        }
        (tmp / jid / "status.json").write_text(json.dumps(payload), encoding="utf-8")
        snap = store.get(jid)
        self.assertFalse(bool((snap.get("params") or {}).get("use_omniroute")))

    def test_cancelled_job_does_not_start_omniroute_completion(self) -> None:
        clear_omniroute_inventory_cache()
        started = {"n": 0}

        def complete_fn(payload, selection):  # noqa: ANN001
            started["n"] += 1
            return {"ok": True, "response": {}, "model": selection["model_id"]}

        provider = OmniRouteCodingProvider(
            plugin_lookup=lambda _pid: _ready_plugin(),
            plugin_tools=lambda _pid: [{"name": "chat", "enabled": True, "capabilities": {"effects": ["network"]}}],
            invoke=_FakeInvoke(_inventory()),
            complete_fn=complete_fn,
        )
        result = asyncio.run(provider.complete({"messages": [{"role": "user", "content": "x"}]}, cancel_check=lambda: True))
        self.assertEqual(result.get("error"), "cancelled")
        self.assertEqual(started["n"], 0)
        self.assertEqual(provider.completion_calls, 0)


class PluginBridgeTests(unittest.TestCase):
    def test_complete_fail_closed_and_redacts_key(self) -> None:
        import subprocess
        import sys

        complete = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "plugins" / "omniroute" / "hades_bridge.py"),
                "complete",
                "--prompt",
                "hi",
                "--model",
                "local-test-model",
                "--base-url",
                "http://127.0.0.1:1",
                "--api-key",
                "sk-live-not-for-logs",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertNotEqual(complete.returncode, 0)
        self.assertNotIn("sk-live-not-for-logs", complete.stdout)
        payload = json.loads(complete.stdout)
        self.assertFalse(payload.get("ok"))

    def test_chat_requires_payload(self) -> None:
        import subprocess
        import sys

        chat = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "plugins" / "omniroute" / "hades_bridge.py"),
                "chat",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertNotEqual(chat.returncode, 0)
        payload = json.loads(chat.stdout)
        self.assertEqual(payload.get("error"), "messages_required")


if __name__ == "__main__":
    unittest.main()
