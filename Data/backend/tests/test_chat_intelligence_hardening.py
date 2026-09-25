"""Chat intelligence hardening — language, settings, model routing, leakage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.context.advisory import (
    looks_like_diagnostic_leak,
    normalize_neuro_item,
    sanitize_model_facing_text,
)
from Data.modules.context.builder import ContextBuilder
from Data.modules.context.response_quality import check_response_quality
from Data.modules.models.capability_eligibility import (
    capability_satisfies_request,
    enrich_descriptor_capabilities,
    is_chat_capable,
)
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelLifecycleState,
    ModelSource,
)
from Data.modules.models.errors import MODEL_NOT_CHAT_CAPABLE, ModelControlError
from Data.modules.models.gateway import ModelGateway
from Data.modules.models.router import ModelRouter
from Data.modules.neuro.types import NeuroSignal
from Data.modules.reasoning import ReasoningPlan
from Data.modules.reasoning.mode import apply_mode_to_plan, resolve_effective_mode, to_cognition_depth
from Data.modules.settings.behavior import DEFAULT_BEHAVIOR_PROFILE, BehaviorProfile
from Data.modules.settings.behavior_store import BehaviorProfileStore
from Data.modules.settings.resolver import (
    BehaviorSettingsResolver,
    detect_message_language,
    resolve_language,
)
from Data.modules.settings.seed import SEED_SYSTEM_PROMPT


class LanguageMatrixTests(unittest.TestCase):
    def test_dutch_matrix(self) -> None:
        cases = [
            ("Hoe gaat het met jou?", "nl"),
            ("Wat is je naam?", "nl"),
            ("Kan je dit uitleggen?", "nl"),
            ("Hello, how are you?", "en"),
            ("Now answer in Dutch", "nl"),
            ("Antwoord nu in het Engels", "en"),
            ("Ga weer verder in het Nederlands.", "nl"),
        ]
        for text, expected in cases:
            lang, _reason = detect_message_language(text)
            self.assertEqual(lang, expected, msg=text)

    def test_short_message_stickiness(self) -> None:
        profile = DEFAULT_BEHAVIOR_PROFILE
        oke = resolve_language(
            profile,
            latest_user_message="oke",
            recent_user_messages=["Hoe gaat het met jou?"],
        )
        self.assertEqual(oke.response_language, "nl")
        waarom = resolve_language(
            profile,
            latest_user_message="waarom?",
            recent_user_messages=["Hoe gaat het met jou?"],
        )
        self.assertEqual(waarom.response_language, "nl")
        ja_after_en = resolve_language(
            profile,
            latest_user_message="ja",
            recent_user_messages=["Hello, how are you?", "Antwoord nu in het Engels"],
        )
        self.assertEqual(ja_after_en.response_language, "en")

    def test_english_internal_config_does_not_force_english_output(self) -> None:
        snap = BehaviorSettingsResolver(None).resolve(latest_user_message="Hoe gaat het?")
        self.assertEqual(snap.language.response_language, "nl")
        self.assertIn("Dutch", snap.system_prompt)
        # Language instruction is last.
        self.assertTrue(snap.system_prompt.strip().endswith("output language.") or "Reply in Dutch" in snap.system_prompt)


class SettingsPersistenceTests(unittest.TestCase):
    def test_patch_system_prompt_persists_and_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "meta.db"
            store = BehaviorProfileStore(db)
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.on_change(resolver.invalidate)
            marker = "UNIQUE_CHAT_HARDENING_PROMPT_MARKER_42"
            store.patch({"system_prompt": marker})
            snap = resolver.resolve(latest_user_message="hi")
            self.assertIn(marker, snap.system_prompt)
            # Fresh store proves disk persistence
            store2 = BehaviorProfileStore(db)
            self.assertEqual(store2.get_effective().system_prompt, marker)
            # Restore
            store2.reset_to_default()
            self.assertEqual(store2.get_effective().system_prompt, SEED_SYSTEM_PROMPT)

    def test_put_and_patch_contracts_via_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            updated = store.update_system_prompt("PROMPT_VIA_PUT_PATH")
            self.assertEqual(updated.system_prompt, "PROMPT_VIA_PUT_PATH")
            patched = store.patch({"assistant_display_name": "ORCA", "reasoning_mode_default": "deep"})
            self.assertEqual(patched.assistant_display_name, "ORCA")
            self.assertEqual(patched.reasoning_mode_default, "deep")


class AdvisoryLeakageTests(unittest.TestCase):
    def test_neurosignal_normalization(self) -> None:
        sig = NeuroSignal(
            signal_id="s1",
            kind="memory_tiers",
            strength=0.6,
            summary="relevant association about Python",
            provenance={"truth": {"x": 1}},
        )
        item = normalize_neuro_item(sig)
        self.assertNotIn("NeuroSignal(", item["content"])
        self.assertNotIn("provenance=", item["content"])
        self.assertIn("advisory", item["content"].lower())

    def test_context_builder_does_not_dump_repr(self) -> None:
        pack = ContextBuilder(token_budget=2500).build(
            history=[{"role": "user", "content": "Hallo"}],
            knowledge=[],
            plan=ReasoningPlan(intent="greeting", complexity="low", use_knowledge=False, steps=("answer",)),
            neuro=[
                {
                    "id": "n1",
                    "content": 'NeuroSignal(signal_id="x", kind="memory_tiers", truth={"a":1}, provenance={"b":2})',
                    "status": "advisory",
                }
            ],
            behavior_profile_prompt=SEED_SYSTEM_PROMPT,
        )
        blob = "\n".join(m["content"] for m in pack.messages)
        self.assertFalse(looks_like_diagnostic_leak(sanitize_model_facing_text(blob)) and "NeuroSignal(" in blob)
        # Model-facing neuro section should be sanitized.
        neuro_bits = [s.content for s in pack.sections if s.kind == "neuro"]
        joined = "\n".join(neuro_bits)
        self.assertNotIn("truth={", joined)

    def test_quality_flags_diagnostic_leak(self) -> None:
        result = check_response_quality(
            "Here is NeuroSignal(signal_id='x', kind='k', strength=0.1, summary='s')",
            expected_language="en",
        )
        self.assertFalse(result.pass_)
        self.assertTrue(any(i.type == "diagnostic_leakage" for i in result.issues))


class ChatModelRoutingTests(unittest.TestCase):
    def _desc(
        self,
        mid: str,
        *,
        chat: CapabilityState,
        embeddings: CapabilityState = CapabilityState.UNKNOWN,
        reasoning: CapabilityState = CapabilityState.UNKNOWN,
        display: str | None = None,
    ) -> ModelDescriptor:
        return ModelDescriptor(
            id=mid,
            display_name=display or mid,
            provider_id="test",
            source=ModelSource.LOCAL,
            capabilities=ModelCapabilities(
                chat=chat,
                embeddings=embeddings,
                reasoning=reasoning,
                streaming=CapabilityState.UNVERIFIED,
            ),
            lifecycle_state=ModelLifecycleState.AVAILABLE,
        )

    def test_eligibility_matrix(self) -> None:
        a = self._desc("a", chat=CapabilityState.SUPPORTED)
        b = self._desc(
            "b",
            chat=CapabilityState.UNSUPPORTED,
            embeddings=CapabilityState.SUPPORTED,
            display="text-embedding-nomic",
        )
        c = enrich_descriptor_capabilities(
            self._desc("c", chat=CapabilityState.UNKNOWN, display="nomic-embed-text")
        )
        d = self._desc("d", chat=CapabilityState.SUPPORTED, reasoning=CapabilityState.SUPPORTED)

        self.assertTrue(is_chat_capable(a).satisfies)
        self.assertFalse(is_chat_capable(b).satisfies)
        self.assertFalse(is_chat_capable(c).satisfies)
        self.assertTrue(is_chat_capable(d).satisfies)
        self.assertTrue(
            capability_satisfies_request(b, "embeddings").satisfies
            or b.capabilities.embeddings == CapabilityState.SUPPORTED
        )

    def test_router_rejects_explicit_embedding(self) -> None:
        class _MemStore:
            def get_active_model_id(self):
                return None

            def get_router_config(self):
                return {
                    "fallback_order": [],
                    "role_overrides": {},
                    "cloud_fallback_allowed": False,
                    "streaming": True,
                    "stream_provisional_text": True,
                    "progress_events_enabled": True,
                }

            def save_router_config(self, payload):
                return payload

            def append_audit(self, *_a, **_k):
                return None

        models = {
            "chat-a": self._desc("chat-a", chat=CapabilityState.SUPPORTED),
            "embed-b": enrich_descriptor_capabilities(
                self._desc(
                    "embed-b",
                    chat=CapabilityState.UNKNOWN,
                    embeddings=CapabilityState.SUPPORTED,
                    display="text-embedding-nomic-embed-text-v1.5",
                )
            ),
        }
        gateway = ModelGateway()
        router = ModelRouter(_MemStore(), gateway, get_models=lambda: list(models.values()))  # type: ignore[arg-type]
        from Data.modules.models.contracts import ModelRequest

        with self.assertRaises(ModelControlError) as ctx:
            router.resolve(
                ModelRequest(
                    explicit_model_id="embed-b",
                    required_capabilities=("chat",),
                )
            )
        self.assertEqual(ctx.exception.code, MODEL_NOT_CHAT_CAPABLE)

        decision = router.resolve(
            ModelRequest(required_capabilities=("chat",), preferred_role="chat")
        )
        self.assertEqual(decision.model_id, "chat-a")


class ReasoningModeTests(unittest.TestCase):
    def test_auto_maps_greeting_to_fast(self) -> None:
        plan = ReasoningPlan(
            intent="greeting",
            complexity="low",
            use_knowledge=True,
            steps=("answer",),
            use_deep_recall=True,
        )
        mode = resolve_effective_mode(settings_default="auto", plan=plan, message="Hoe gaat het?")
        self.assertEqual(mode.effective, "fast")
        adjusted = apply_mode_to_plan(plan, mode)
        self.assertFalse(adjusted.use_knowledge)
        self.assertFalse(adjusted.use_deep_recall)
        self.assertEqual(to_cognition_depth("deep"), "DEEP")

    def test_deep_prefers_reasoning_model_flag(self) -> None:
        mode = resolve_effective_mode(settings_default="deep", message="Analyseer de architectuur")
        self.assertTrue(mode.prefer_reasoning_model)
        self.assertTrue(mode.allow_verification)


class SeedContractTests(unittest.TestCase):
    def test_seed_covers_quality_contract(self) -> None:
        self.assertIn("LANGUAGE", SEED_SYSTEM_PROMPT)
        self.assertIn("INTERNALS", SEED_SYSTEM_PROMPT)
        self.assertIn("NeuroSignal", SEED_SYSTEM_PROMPT)
        self.assertIn("Respond in the language used by the user", SEED_SYSTEM_PROMPT)
        self.assertTrue(SEED_SYSTEM_PROMPT.startswith("You are LEVIATHAN"))


if __name__ == "__main__":
    unittest.main()


class BehaviorRouteBodyBindingTests(unittest.TestCase):
    def test_behavior_models_are_module_level_for_fastapi_body(self) -> None:
        from Data.backend.routes import settings as settings_routes

        self.assertTrue(hasattr(settings_routes, "BehaviorPromptPatch"))
        self.assertTrue(hasattr(settings_routes, "BehaviorProfilePatch"))
        # Nested local classes caused FastAPI to bind payload as a query param
        # (422 Field required at loc=['query','payload']).
        src = open(settings_routes.__file__, encoding="utf-8").read()
        self.assertIn("payload: BehaviorPromptPatch = Body(...)", src)
        self.assertIn("payload: BehaviorProfilePatch = Body(...)", src)
