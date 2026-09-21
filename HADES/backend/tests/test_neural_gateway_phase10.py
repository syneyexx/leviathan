"""Phase 10: ModelGateway runtime selection + Neural bridge."""

from __future__ import annotations

import asyncio
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RuntimeSelectionPolicyTests(unittest.TestCase):
    def test_off_is_standard(self) -> None:
        from reasoning.runtime_selection import (
            NeuralRequirement,
            RuntimeKind,
            RuntimeSelectionRequest,
            select_model_runtime,
        )

        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="off",
                neural_requirement=NeuralRequirement.OFF,
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertEqual(decision.neural_mode, "off")
        self.assertFalse(decision.shadow)
        self.assertIsNone(decision.fallback_reason)

    def test_read_preferred_falls_back_when_unavailable(self) -> None:
        from reasoning.runtime_selection import (
            NeuralRequirement,
            RuntimeKind,
            RuntimeSelectionRequest,
            select_model_runtime,
            should_fail_closed,
        )

        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="read",
                neural_requirement=NeuralRequirement.PREFERRED,
                allow_neural=True,
                neural_available=False,
                neural_ready=False,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertEqual(decision.fallback_reason, "neural_read_not_product_ready")
        self.assertFalse(should_fail_closed(decision))

    def test_read_required_fails_closed_when_unavailable(self) -> None:
        from reasoning.runtime_selection import (
            NeuralRequirement,
            RuntimeSelectionRequest,
            select_model_runtime,
            should_fail_closed,
        )

        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="read",
                neural_requirement=NeuralRequirement.REQUIRED,
                allow_neural=True,
                neural_available=False,
                neural_ready=False,
            )
        )
        self.assertTrue(should_fail_closed(decision))
        self.assertEqual(decision.fallback_reason, "neural_read_not_product_ready")

    def test_read_refuses_neural_primary_when_ready(self) -> None:
        from reasoning.runtime_selection import (
            NeuralRequirement,
            RuntimeKind,
            RuntimeSelectionRequest,
            select_model_runtime,
        )

        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="read",
                neural_requirement=NeuralRequirement.PREFERRED,
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
            )
        )
        # F-06: READ is research-only until real LM fusion exists.
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertEqual(decision.neural_mode, "off")
        self.assertEqual(decision.fallback_reason, "neural_read_not_product_ready")
        self.assertTrue(decision.detail.get("research_only"))

    def test_shadow_keeps_standard_primary(self) -> None:
        from reasoning.runtime_selection import (
            NeuralRequirement,
            RuntimeKind,
            RuntimeSelectionRequest,
            select_model_runtime,
        )

        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="shadow",
                neural_requirement=NeuralRequirement.PREFERRED,
                shadow_sample_rate=0.25,
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertTrue(decision.shadow)
        self.assertEqual(decision.neural_mode, "shadow")

    def test_learn_never_primary(self) -> None:
        from reasoning.runtime_selection import (
            NeuralRequirement,
            RuntimeKind,
            RuntimeSelectionRequest,
            select_model_runtime,
        )

        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="learn",
                neural_requirement=NeuralRequirement.PREFERRED,
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertEqual(decision.fallback_reason, "neural_learn_unsupported")


class ModelRuntimeBridgeTests(unittest.TestCase):
    def test_off_matches_plain_gateway_chat(self) -> None:
        from reasoning.model_gateway import ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime, standard_only_request

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "model": payload.get("model"),
            }

        async def run() -> None:
            plain = await gw.chat(standard, {"model": "m"}, model_id="m", endpoint="lm")
            bridged = await gateway_chat_with_runtime(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                selection=standard_only_request(),
                model_id="m",
                endpoint="lm",
            )
            self.assertEqual(plain["choices"], bridged["choices"])
            self.assertEqual(bridged["_hades_runtime"]["runtime"]["primary"], "standard")
            self.assertEqual(bridged["_hades_runtime"]["runtime"]["neural_mode"], "off")

        asyncio.run(run())

    def test_preferred_fallback_uses_standard(self) -> None:
        from reasoning.model_gateway import ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime
        from reasoning.runtime_selection import NeuralRequirement, RuntimeSelectionRequest

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "std"}}]}

        async def run() -> None:
            out = await gateway_chat_with_runtime(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                selection=RuntimeSelectionRequest(
                    neural_mode="read",
                    neural_requirement=NeuralRequirement.PREFERRED,
                    allow_neural=True,
                    neural_available=False,
                    neural_ready=False,
                ),
                neural_infer_fn=None,
                model_id="m",
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "std")
            self.assertEqual(
                out["_hades_runtime"]["runtime"]["fallback_reason"],
                "neural_read_not_product_ready",
            )
            self.assertEqual(gw.overview().get("fallback_reason"), "neural_read_not_product_ready")

        asyncio.run(run())

    def test_required_neural_unavailable_fails_truthfully(self) -> None:
        from reasoning.model_gateway import ModelCallFailed, ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime
        from reasoning.runtime_selection import NeuralRequirement, RuntimeSelectionRequest

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "std"}}]}

        async def run() -> None:
            with self.assertRaises(ModelCallFailed) as ctx:
                await gateway_chat_with_runtime(
                    {"model": "m"},
                    chat_fn=standard,
                    gateway=gw,
                    selection=RuntimeSelectionRequest(
                        neural_mode="read",
                        neural_requirement=NeuralRequirement.REQUIRED,
                        allow_neural=True,
                        neural_available=False,
                        neural_ready=False,
                    ),
                    model_id="m",
                )
            self.assertEqual(ctx.exception.code, "neural_read_not_product_ready")

        asyncio.run(run())

    def test_shadow_does_not_alter_user_visible_result(self) -> None:
        from reasoning.model_gateway import ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime
        from reasoning.runtime_selection import NeuralRequirement, RuntimeSelectionRequest

        gw = ModelGateway(global_limit=2, max_retries=0)
        shadow_calls = {"n": 0}

        async def standard(payload):
            return {"choices": [{"message": {"content": "primary-answer"}}]}

        def shadow_hook(payload):
            shadow_calls["n"] += 1
            return {
                "choices": [{"message": {"content": "SHOULD_NOT_LEAK"}}],
                "latency_ms": 1.5,
                "mode": "shadow",
                "bypassed": False,
                "fusion_events": [{"layer": 1}],
            }

        async def run() -> None:
            out = await gateway_chat_with_runtime(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                selection=RuntimeSelectionRequest(
                    neural_mode="shadow",
                    neural_requirement=NeuralRequirement.PREFERRED,
                    shadow_sample_rate=1.0,
                    allow_neural=True,
                    neural_available=True,
                    neural_ready=True,
                ),
                neural_infer_fn=shadow_hook,
                model_id="m",
                shadow_rng=random.Random(0),
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "primary-answer")
            self.assertEqual(shadow_calls["n"], 1)
            self.assertTrue(out["_hades_runtime"]["shadow"]["sampled"])
            self.assertTrue(out["_hades_runtime"]["shadow"]["ok"])
            self.assertNotIn("SHOULD_NOT_LEAK", str(out["choices"]))

        asyncio.run(run())

    def test_read_keeps_lm_provider_content(self) -> None:
        """F-06: READ must not replace LM output with neural diagnostic prose."""
        from reasoning.model_gateway import ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime
        from reasoning.runtime_selection import NeuralRequirement, RuntimeSelectionRequest

        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "std"}}]}

        def neural_hook(payload):
            return {"choices": [{"message": {"content": "neural-read"}}], "mode": "read"}

        async def run() -> None:
            out = await gateway_chat_with_runtime(
                {"model": "m"},
                chat_fn=standard,
                gateway=gw,
                selection=RuntimeSelectionRequest(
                    neural_mode="read",
                    neural_requirement=NeuralRequirement.PREFERRED,
                    allow_neural=True,
                    neural_available=True,
                    neural_ready=True,
                ),
                neural_infer_fn=neural_hook,
                model_id="m",
            )
            self.assertEqual(out["choices"][0]["message"]["content"], "std")
            self.assertEqual(out["_hades_runtime"]["runtime"]["primary"], "standard")
            self.assertEqual(
                out["_hades_runtime"]["runtime"]["fallback_reason"],
                "neural_read_not_product_ready",
            )

        asyncio.run(run())

    def test_cancellation_still_works(self) -> None:
        from reasoning.model_gateway import ModelCallCancelled, ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime, standard_only_request

        gw = ModelGateway(global_limit=1, max_retries=0, acquire_timeout_s=0.05)
        cancel = asyncio.Event()
        cancel.set()

        async def standard(payload):
            return {"choices": []}

        async def run() -> None:
            with self.assertRaises(ModelCallCancelled):
                await gateway_chat_with_runtime(
                    {"model": "m"},
                    chat_fn=standard,
                    gateway=gw,
                    selection=standard_only_request(),
                    model_id="m",
                    cancel_event=cancel,
                )

        asyncio.run(run())

    def test_main_wires_gateway_but_defaults_off(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        self.assertIn("dispatch_model_chat", text)
        self.assertIn("resolve_neural_mode", text)


class NeuralRuntimeHookIntegrationTests(unittest.TestCase):
    """Optional: toy NeuralRuntimeBoundary as neural_infer_fn."""

    def test_toy_neural_boundary_hook(self) -> None:
        from neural.deps import neural_available

        if not neural_available():
            self.skipTest("torch unavailable")
        from neural.contracts import NeuralInferRequest, NeuralMode, NeuralModelSpec
        from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig
        from reasoning.model_gateway import ModelGateway
        from reasoning.model_runtime_bridge import gateway_chat_with_runtime
        from reasoning.runtime_selection import NeuralRequirement, RuntimeSelectionRequest

        rt = NeuralRuntimeBoundary()
        rt.start(NeuralRuntimeStartConfig(model_spec=NeuralModelSpec(), mode=NeuralMode.OFF))
        gw = ModelGateway(global_limit=2, max_retries=0)

        async def standard(payload):
            return {"choices": [{"message": {"content": "std"}}]}

        def neural_hook(payload):
            result = rt.infer(
                NeuralInferRequest(
                    request_id="gw1",
                    input_ids=[[1, 2, 3, 4]],
                    mode=NeuralMode.READ,
                )
            )
            return {
                "choices": [{"message": {"content": f"logits_shape={len(result.logits)}"}}],
                "mode": result.mode.value,
                "bypassed": result.bypassed,
                "base_checksum": result.base_checksum,
                "latency_ms": result.latency_ms,
                "fusion_events": result.fusion_events,
            }

        async def run() -> None:
            out = await gateway_chat_with_runtime(
                {"model": "toy"},
                chat_fn=standard,
                gateway=gw,
                selection=RuntimeSelectionRequest(
                    neural_mode="read",
                    neural_requirement=NeuralRequirement.PREFERRED,
                    allow_neural=True,
                    neural_available=True,
                    neural_ready=True,
                ),
                neural_infer_fn=neural_hook,
                model_id="toy",
                endpoint="neural",
            )
            self.assertEqual(out["_hades_runtime"]["runtime"]["primary"], "neural")
            self.assertIn("logits_shape=", out["choices"][0]["message"]["content"])
            rt.prove_base_frozen()
            rt.stop()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
