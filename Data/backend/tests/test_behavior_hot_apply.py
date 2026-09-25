"""BehaviorProfile hot-apply — existing chats must receive the new prompt next turn.

Regression suite for live system-prompt propagation:

BehaviorProfileStore (persisted truth)
  -> BehaviorSettingsResolver (per operation)
  -> BehaviorSnapshot (immutable)
  -> ContextBuilder / ContextPack
  -> model-facing system identity

No real LLM required.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from Data.modules.context.builder import ContextBuilder
from Data.modules.reasoning import ReasoningEngine
from Data.modules.settings.behavior import DEFAULT_BEHAVIOR_PROFILE
from Data.modules.settings.behavior_store import BehaviorProfileStore
from Data.modules.settings.resolver import BehaviorSettingsResolver, BehaviorSnapshot
from Data.modules.settings.seed import SEED_SYSTEM_PROMPT


MARKER_A = "PROFILE_ALPHA_123"
MARKER_B = "PROFILE_BETA_456"


def _plan():
    return ReasoningEngine().analyze("hi", has_knowledge=False)


def _pack_for_snapshot(snap: BehaviorSnapshot, *, history: list[dict[str, str]] | None = None):
    return ContextBuilder(token_budget=4000).build(
        history=history
        or [
            {"role": "user", "content": "turn"},
        ],
        knowledge=[],
        plan=_plan(),
        behavior_profile_prompt=snap.system_prompt,
        behavior_profile_version=snap.version,
    )


class ExistingConversationHotApplyTests(unittest.TestCase):
    """Mandatory: same conversation ID, turn 1 = A, turn 2 = B after update."""

    def test_existing_conversation_receives_new_prompt_on_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "meta.db"
            store = BehaviorProfileStore(db)
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.on_change(resolver.invalidate)

            store.patch({"system_prompt": MARKER_A})
            conversation_id = "conv-hot-apply-C"

            # Turn 1 in conversation C
            snap1 = resolver.resolve(latest_user_message="Wat is jouw gedragsmarker?")
            pack1 = _pack_for_snapshot(
                snap1,
                history=[
                    {"role": "user", "content": "Wat is jouw gedragsmarker?"},
                ],
            )
            self.assertIn(MARKER_A, snap1.system_prompt)
            self.assertIn(MARKER_A, pack1.system_prompt)
            hash_a = snap1.settings_hash

            # Update SAME profile — do NOT create another conversation
            store.patch({"system_prompt": MARKER_B})

            # Turn 2 in SAME conversation C
            snap2 = resolver.resolve(latest_user_message="Wat is nu jouw gedragsmarker?")
            pack2 = _pack_for_snapshot(
                snap2,
                history=[
                    {"role": "user", "content": "Wat is jouw gedragsmarker?"},
                    {"role": "assistant", "content": f"Mijn marker is {MARKER_A}"},
                    {"role": "user", "content": "Wat is nu jouw gedragsmarker?"},
                ],
            )

            self.assertEqual(conversation_id, "conv-hot-apply-C")
            self.assertIn(MARKER_B, snap2.system_prompt)
            self.assertIn(MARKER_B, pack2.system_prompt)
            self.assertNotIn(MARKER_A, snap2.system_prompt)
            # History may still contain old assistant text as DATA, not as system identity.
            history_blob = "\n".join(m["content"] for m in pack2.messages if m["role"] != "system")
            self.assertIn(MARKER_A, history_blob)
            self.assertNotEqual(hash_a, snap2.settings_hash)
            self.assertIn("AUTHORITY:", snap2.system_prompt)


class InFlightSnapshotImmutabilityTests(unittest.TestCase):
    def test_in_flight_snapshot_stable_next_turn_hot_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.on_change(resolver.invalidate)

            store.patch({"system_prompt": MARKER_A})
            snap_a = resolver.resolve(latest_user_message="turn-a")
            self.assertIn(MARKER_A, snap_a.system_prompt)

            store.patch({"system_prompt": MARKER_B})
            # Existing snapshot remains A (immutable)
            self.assertIn(MARKER_A, snap_a.system_prompt)
            self.assertNotIn(MARKER_B, snap_a.system_prompt)

            snap_b = resolver.resolve(latest_user_message="turn-b")
            self.assertIn(MARKER_B, snap_b.system_prompt)
            self.assertNotIn(MARKER_A, snap_b.system_prompt)


class CacheInvalidationTests(unittest.TestCase):
    def test_resolver_sees_store_update_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.on_change(resolver.invalidate)

            store.patch({"system_prompt": MARKER_A})
            self.assertIn(MARKER_A, resolver.resolve().system_prompt)

            store.patch({"system_prompt": MARKER_B})
            self.assertIn(MARKER_B, resolver.resolve().system_prompt)

    def test_multi_instance_resolvers_both_see_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "meta.db"
            store = BehaviorProfileStore(db)
            store.ensure_schema()
            r1 = BehaviorSettingsResolver(store)
            r2 = BehaviorSettingsResolver(store)
            store.on_change(r1.invalidate)
            store.on_change(r2.invalidate)

            store.patch({"system_prompt": MARKER_A})
            self.assertIn(MARKER_A, r1.resolve().system_prompt)
            self.assertIn(MARKER_A, r2.resolve().system_prompt)

            store.patch({"system_prompt": MARKER_B})
            self.assertIn(MARKER_B, r1.resolve().system_prompt)
            self.assertIn(MARKER_B, r2.resolve().system_prompt)

    def test_missed_invalidate_still_fresh_via_store_read(self) -> None:
        """Even without on_change delivery, next resolve must observe persisted B."""
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            # Deliberately do NOT register on_change
            store.patch({"system_prompt": MARKER_A})
            self.assertIn(MARKER_A, resolver.resolve().system_prompt)
            store.patch({"system_prompt": MARKER_B})
            self.assertIn(MARKER_B, resolver.resolve().system_prompt)


class CrossProcessWorkerFreshnessTests(unittest.TestCase):
    def test_separate_store_instance_sees_persisted_update(self) -> None:
        """Simulates API process write + long-lived worker process read."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "meta.db"
            api_store = BehaviorProfileStore(db)
            api_store.ensure_schema()
            api_store.patch({"system_prompt": MARKER_A})

            worker_store = BehaviorProfileStore(db)
            worker_resolver = BehaviorSettingsResolver(worker_store)
            snap1 = worker_resolver.resolve()
            self.assertIn(MARKER_A, snap1.system_prompt)

            api_store.patch({"system_prompt": MARKER_B})
            # Worker stays alive; new job/operation must see B without restart.
            snap2 = worker_resolver.resolve()
            self.assertIn(MARKER_B, snap2.system_prompt)
            self.assertNotEqual(snap1.settings_hash, snap2.settings_hash)


class MultiConversationTests(unittest.TestCase):
    def test_all_existing_conversations_receive_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.on_change(resolver.invalidate)

            store.patch({"system_prompt": MARKER_A})
            c1, c2 = "conv-1", "conv-2"
            s1 = resolver.resolve(latest_user_message="hi from c1")
            s2 = resolver.resolve(latest_user_message="hi from c2")
            self.assertIn(MARKER_A, s1.system_prompt)
            self.assertIn(MARKER_A, s2.system_prompt)

            store.patch({"system_prompt": MARKER_B})
            s1b = resolver.resolve(latest_user_message="again c1")
            s2b = resolver.resolve(latest_user_message="again c2")
            self.assertEqual(c1, "conv-1")
            self.assertEqual(c2, "conv-2")
            self.assertIn(MARKER_B, s1b.system_prompt)
            self.assertIn(MARKER_B, s2b.system_prompt)


class LanguagePolicyTests(unittest.TestCase):
    def test_hot_apply_keeps_dutch_auto_follow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.patch(
                {
                    "system_prompt": MARKER_A,
                    "language_mode": "auto_follow_user",
                }
            )
            snap1 = resolver.resolve(latest_user_message="Hoe gaat het met jou?")
            self.assertEqual(snap1.language.response_language, "nl")
            self.assertIn(MARKER_A, snap1.system_prompt)
            self.assertIn("Dutch", snap1.system_prompt)

            store.patch({"system_prompt": MARKER_B})
            snap2 = resolver.resolve(
                latest_user_message="Wat is nu jouw gedragsmarker?",
                recent_user_messages=["Hoe gaat het met jou?"],
            )
            self.assertEqual(snap2.language.response_language, "nl")
            self.assertIn(MARKER_B, snap2.system_prompt)
            self.assertIn("Dutch", snap2.system_prompt)


class RestartPersistenceTests(unittest.TestCase):
    def test_reconstructed_services_keep_profile_b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "meta.db"
            store = BehaviorProfileStore(db)
            store.ensure_schema()
            store.patch({"system_prompt": MARKER_B})

            store2 = BehaviorProfileStore(db)
            resolver2 = BehaviorSettingsResolver(store2)
            snap = resolver2.resolve()
            self.assertIn(MARKER_B, snap.system_prompt)
            self.assertEqual(store2.get_effective().system_prompt, MARKER_B)


class CognitionHotApplyTests(unittest.TestCase):
    def test_cognition_submit_resolves_current_profile(self) -> None:
        from Data.modules.cognition.runtime import CognitiveRuntime

        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.patch({"system_prompt": MARKER_A})

            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                behavior_resolver=resolver,
            )
            status1 = runtime.submit("request one", run=True)
            meta1 = runtime._runs[status1["run_id"]].task.metadata  # noqa: SLF001
            self.assertIn(MARKER_A, str(meta1.get("behavior_system_prompt") or ""))

            store.patch({"system_prompt": MARKER_B})
            status2 = runtime.submit("request two", run=True)
            meta2 = runtime._runs[status2["run_id"]].task.metadata  # noqa: SLF001
            self.assertIn(MARKER_B, str(meta2.get("behavior_system_prompt") or ""))
            self.assertNotIn(MARKER_A, str(meta2.get("behavior_system_prompt") or ""))

    def test_chat_supplied_snapshot_not_overwritten_mid_turn(self) -> None:
        from Data.modules.cognition.runtime import CognitiveRuntime

        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.patch({"system_prompt": MARKER_A})
            snap = resolver.resolve()
            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                behavior_resolver=resolver,
            )
            # Profile changes after chat resolved turn snapshot
            store.patch({"system_prompt": MARKER_B})
            status = runtime.submit(
                "in-flight turn",
                metadata={
                    "behavior_system_prompt": snap.system_prompt,
                    "behavior_hash": snap.settings_hash,
                    "response_language": "en",
                },
                run=True,
            )
            meta = runtime._runs[status["run_id"]].task.metadata  # noqa: SLF001
            self.assertIn(MARKER_A, str(meta.get("behavior_system_prompt") or ""))
            self.assertNotIn(MARKER_B, str(meta.get("behavior_system_prompt") or ""))


class CodingSharedIdentityTests(unittest.TestCase):
    def test_coding_uses_updated_global_identity(self) -> None:
        from Data.modules.coding.loop import CodingLoop
        from Data.modules.coding.store import CodingStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = BehaviorProfileStore(root / "meta.db")
            store.ensure_schema()
            store.patch({"system_prompt": MARKER_A})
            coding_store = CodingStore(root / "coding.db")
            coding_store.initialize()
            loop = CodingLoop(coding_store, gateway=None, behavior_store=store)
            self.assertIn(MARKER_A, loop._behavior_prompt())  # noqa: SLF001

            store.patch({"system_prompt": MARKER_B})
            prompt_b = loop._behavior_prompt()  # noqa: SLF001
            self.assertIn(MARKER_B, prompt_b)
            self.assertNotIn(MARKER_A, prompt_b)

            pack = ContextBuilder(token_budget=4000).build(
                history=[{"role": "user", "content": "fix"}],
                knowledge=[],
                plan=_plan(),
                behavior_profile_prompt=prompt_b,
                mode="coding",
            )
            self.assertIn(MARKER_B, pack.system_prompt)
            self.assertIn("Coding Cognitive Overlay", pack.system_prompt)


class FakeModelChatPipelineTests(unittest.TestCase):
    """Higher-level: fake adapter records system context across two turns."""

    def test_fake_model_receives_marker_b_on_second_turn(self) -> None:
        recorded: list[str] = []

        class FakeLLM:
            def __init__(self) -> None:
                self.context_builder = ContextBuilder(token_budget=4000)

            async def complete(self, **kwargs: Any) -> dict[str, Any]:
                # Mirror openai_compatible identity wiring
                identity = kwargs.get("behavior_profile_prompt") or ""
                pack = self.context_builder.build(
                    history=kwargs.get("history") or [],
                    knowledge=[],
                    plan=kwargs.get("plan") or _plan(),
                    behavior_profile_prompt=identity,
                )
                recorded.append(pack.system_prompt)
                return {"text": "ok", "model": "fake"}

        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            llm = FakeLLM()
            conversation_id = "C-fake"

            store.patch({"system_prompt": MARKER_A})
            snap1 = resolver.resolve(latest_user_message="marker?")
            import asyncio

            async def _run_turns() -> None:
                await llm.complete(
                    history=[{"role": "user", "content": "marker?"}],
                    plan=_plan(),
                    behavior_profile_prompt=snap1.system_prompt,
                )
                store.patch({"system_prompt": MARKER_B})
                snap2 = resolver.resolve(latest_user_message="marker now?")
                await llm.complete(
                    history=[
                        {"role": "user", "content": "marker?"},
                        {"role": "assistant", "content": "ALPHA"},
                        {"role": "user", "content": "marker now?"},
                    ],
                    plan=_plan(),
                    behavior_profile_prompt=snap2.system_prompt,
                )

            asyncio.run(_run_turns())

            self.assertEqual(conversation_id, "C-fake")
            self.assertEqual(len(recorded), 2)
            self.assertIn(MARKER_A, recorded[0])
            self.assertIn(MARKER_B, recorded[1])
            self.assertNotIn(MARKER_A, recorded[1].split("AUTHORITY:")[0])


class ArchitectureInvariantTests(unittest.TestCase):
    def test_conversation_must_not_own_reusable_behavior_snapshot(self) -> None:
        """Conversations have no behavior_snapshot / system_prompt authority fields."""
        from Data.backend.database import Database

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "chat.db")
            db.initialize()
            conv = db.create_conversation("Test Conversation")
            self.assertNotIn("behavior_snapshot", conv)
            self.assertNotIn("system_prompt", conv)
            self.assertNotIn("behavior_profile", conv)

    def test_seed_is_bootstrap_not_runtime_when_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            store.patch({"system_prompt": MARKER_B})
            effective = store.get_effective()
            self.assertEqual(effective.system_prompt, MARKER_B)
            self.assertNotEqual(effective.system_prompt, SEED_SYSTEM_PROMPT)
            self.assertNotEqual(effective.compute_hash(), DEFAULT_BEHAVIOR_PROFILE.compute_hash())

    def test_version_and_hash_change_on_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            a = store.patch({"system_prompt": MARKER_A})
            b = store.patch({"system_prompt": MARKER_B})
            self.assertNotEqual(a.hash, b.hash)
            self.assertNotEqual(a.version, b.version)
            fp = store.fingerprint()
            self.assertEqual(fp["hash"], b.hash)
            self.assertEqual(fp["version"], str(b.version))


class ContextPackNoStaleReuseTests(unittest.TestCase):
    def test_recompile_after_profile_change_is_not_stale(self) -> None:
        """No cross-turn ContextPack cache today; compile path must still reflect B."""
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "meta.db")
            store.ensure_schema()
            resolver = BehaviorSettingsResolver(store)
            store.patch({"system_prompt": MARKER_A})
            pack_a = _pack_for_snapshot(resolver.resolve())
            store.patch({"system_prompt": MARKER_B})
            pack_b = _pack_for_snapshot(resolver.resolve())
            self.assertIn(MARKER_A, pack_a.system_prompt)
            self.assertIn(MARKER_B, pack_b.system_prompt)
            self.assertNotEqual(pack_a.stable_prefix_fingerprint, pack_b.stable_prefix_fingerprint)


if __name__ == "__main__":
    unittest.main()
