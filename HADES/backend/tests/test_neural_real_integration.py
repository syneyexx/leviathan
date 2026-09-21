"""Phase 10/11 real HADES integration: dispatch + dual memory in chat path."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class NeuralSettingsDefaultsTests(unittest.TestCase):
    def test_defaults_are_off(self) -> None:
        from reasoning.neural_settings import (
            build_runtime_selection,
            dual_memory_enabled,
            neural_allow,
            resolve_neural_mode,
            resolve_shadow_sample_rate,
        )

        self.assertEqual(resolve_neural_mode({}), "off")
        self.assertFalse(neural_allow({}))
        self.assertFalse(dual_memory_enabled({}))
        self.assertEqual(resolve_shadow_sample_rate({}), 0.0)
        sel = build_runtime_selection({})
        self.assertEqual(sel.neural_mode, "off")
        self.assertFalse(sel.allow_neural)

    def test_probe_reports_no_streaming_no_learn(self) -> None:
        from reasoning.neural_settings import neural_runtime_probe

        probe = neural_runtime_probe()
        self.assertIn("neural_available", probe)
        self.assertFalse(probe.get("supports_streaming"))
        self.assertFalse(probe.get("supports_learn"))


class DispatchModelChatTests(unittest.TestCase):
    def test_off_uses_standard_only(self) -> None:
        from reasoning.model_chat_dispatch import dispatch_model_chat
        from reasoning.model_gateway import ModelGateway

        gw = ModelGateway(global_limit=2, max_retries=0)
        calls = {"n": 0}

        async def standard(payload):
            calls["n"] += 1
            return {"choices": [{"message": {"content": "std-answer"}}]}

        async def run() -> None:
            out = await dispatch_model_chat(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                settings={"neural_mode": "off", "neural_allow": False},
                model_id="m",
                endpoint="lm",
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "std-answer")
            self.assertNotIn("_hades_runtime", out)
            self.assertEqual(calls["n"], 1)

        asyncio.run(run())

    def test_read_preferred_falls_back_when_hook_missing(self) -> None:
        from reasoning.model_chat_dispatch import dispatch_model_chat
        from reasoning.model_gateway import ModelGateway

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "fallback-std"}}]}

        async def run() -> None:
            out = await dispatch_model_chat(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                settings={
                    "neural_allow": True,
                    "neural_mode": "read",
                    "neural_requirement": "preferred",
                },
                model_id="m",
                neural_infer_fn=None,
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "fallback-std")
            self.assertEqual(
                out["_hades_runtime"]["runtime"]["fallback_reason"],
                "neural_read_not_product_ready",
            )

        asyncio.run(run())

    def test_read_required_fails_when_unavailable(self) -> None:
        from reasoning.model_chat_dispatch import dispatch_model_chat
        from reasoning.model_gateway import ModelCallFailed, ModelGateway

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "std"}}]}

        async def run() -> None:
            with self.assertRaises(ModelCallFailed) as ctx:
                await dispatch_model_chat(
                    {"model": "m"},
                    chat_fn=standard,
                    gateway=gw,
                    settings={
                        "neural_allow": True,
                        "neural_mode": "read",
                        "neural_requirement": "required",
                    },
                    model_id="m",
                    neural_infer_fn=None,
                )
            self.assertEqual(ctx.exception.code, "neural_read_not_product_ready")

        asyncio.run(run())

    def test_read_keeps_lm_content_when_ready(self) -> None:
        from reasoning.model_chat_dispatch import dispatch_model_chat
        from reasoning.model_gateway import ModelGateway

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "std"}}]}

        def neural_hook(payload):
            return {"choices": [{"message": {"content": "neural-read"}}], "mode": "read"}

        async def run() -> None:
            out = await dispatch_model_chat(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                settings={
                    "neural_allow": True,
                    "neural_mode": "read",
                    "neural_requirement": "preferred",
                },
                model_id="m",
                neural_infer_fn=neural_hook,
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "std")
            self.assertEqual(out["_hades_runtime"]["runtime"]["primary"], "standard")
            self.assertEqual(
                out["_hades_runtime"]["runtime"]["fallback_reason"],
                "neural_read_not_product_ready",
            )

        asyncio.run(run())

    def test_cancellation_propagates(self) -> None:
        from reasoning.model_chat_dispatch import dispatch_model_chat
        from reasoning.model_gateway import ModelCallCancelled, ModelGateway

        gw = ModelGateway(global_limit=1, max_retries=0, acquire_timeout_s=0.05)
        cancel = asyncio.Event()
        cancel.set()

        async def standard(payload):
            return {"choices": []}

        async def run() -> None:
            with self.assertRaises(ModelCallCancelled):
                await dispatch_model_chat(
                    {"model": "m"},
                    chat_fn=standard,
                    gateway=gw,
                    settings={"neural_mode": "off"},
                    model_id="m",
                    cancel_event=cancel,
                )

        asyncio.run(run())


class DualMemoryChatContextTests(unittest.TestCase):
    def test_dual_memory_default_off_does_not_inject(self) -> None:
        from reasoning.chat_context import assemble_chat_context_messages
        from reasoning.contracts import ContextItem

        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["sys"],
            history=[],
            context_items=[
                ContextItem(item_id="c1", kind="knowledge", content="base fact", provenance="k", priority=10)
            ],
            user_text="hello",
            max_chars=2000,
            settings={"enable_context_compiler_chat": False},
        )
        self.assertFalse(meta["neural_dual_memory"]["enabled"])
        self.assertEqual(meta["neural_dual_memory"]["neural_kept"], 0)
        joined = "\n".join(m.get("content", "") for m in messages)
        self.assertNotIn("neural_association", joined)

    def test_dual_memory_injects_distinct_kinds_when_enabled(self) -> None:
        from reasoning.chat_context import assemble_chat_context_messages

        def exact_fn(_q):
            return [{"id": "e1", "content": "Exact: acquire A then B.", "score": 0.9, "source_ref": "file:x.py"}]

        def neural_fn(_q):
            return [
                {
                    "id": "n1",
                    "content": "Association: lock ordering pattern.",
                    "score": 0.7,
                    "checkpoint_id": "ck",
                }
            ]

        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["sys"],
            history=[],
            context_items=[],
            user_text="deadlock",
            max_chars=4000,
            settings={
                "enable_context_compiler_chat": False,
                "neural_allow": True,
                "neural_mode": "read",
                "neural_dual_memory_enabled": True,
                "neural_exact_retrieve_fn": exact_fn,
                "neural_retrieve_fn": neural_fn,
            },
        )
        self.assertTrue(meta["neural_dual_memory"]["enabled"])
        self.assertGreaterEqual(meta["neural_dual_memory"]["exact_kept"], 1)
        self.assertGreaterEqual(meta["neural_dual_memory"]["neural_kept"], 1)
        joined = "\n".join(m.get("content", "") for m in messages)
        self.assertIn("Exact:", joined)
        self.assertIn("neural_association", joined)


class DefaultSettingsNeuralKeysTests(unittest.TestCase):
    def test_default_settings_include_neural_off_keys(self) -> None:
        from database import DEFAULT_SETTINGS

        self.assertIn("neural_mode", DEFAULT_SETTINGS)
        self.assertEqual(DEFAULT_SETTINGS["neural_mode"], "off")
        self.assertFalse(DEFAULT_SETTINGS["neural_allow"])
        self.assertFalse(DEFAULT_SETTINGS["neural_dual_memory_enabled"])
        self.assertEqual(DEFAULT_SETTINGS["neural_shadow_sample_rate"], 0.0)


class MainWiringSmokeTests(unittest.TestCase):
    def test_main_uses_dispatch_and_keeps_off_bypass(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        self.assertIn("dispatch_model_chat", text)
        self.assertIn("resolve_neural_mode", text)


if __name__ == "__main__":
    unittest.main()
