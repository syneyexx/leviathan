"""Regression tests for chat / LLM / retrieval pipeline bugs fixed 2026-09-10."""

from __future__ import annotations

import asyncio
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class KnowledgeWriteBackIncludesAssistantTests(unittest.TestCase):
    def test_verified_index_path_indexes_current_exchange_only(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("index_conversation_exchange", source)
        verified_block = source.split("if knowledge_write.action == \"allow\":", 1)[1].split(
            "else:", 1
        )[0]
        self.assertIn("index_conversation_exchange", verified_block)
        self.assertIn("verified_write_back=True", verified_block)
        # Must not promote the whole transcript's assistants under verified write-back.
        self.assertNotIn("include_assistant=True", verified_block)
        self.assertNotIn("transcript_with_answer", verified_block)


class ResolveModelFallbackTests(unittest.TestCase):
    def test_preferred_unloaded_falls_back_to_loaded_model(self) -> None:
        import main as hades_main

        async def _run() -> None:
            with mock.patch.object(
                hades_main,
                "discover_models",
                new=mock.AsyncMock(return_value=([{"id": "local-loaded"}], None)),
            ), mock.patch.object(
                hades_main.database,
                "profile_for",
                return_value={"model_id": "local-loaded", "temperature": 0.4},
            ), mock.patch.object(
                hades_main.database,
                "active_profile",
                return_value={"model_id": "local-loaded"},
            ), mock.patch.object(
                hades_main,
                "runtime_values",
                return_value={
                    "lm_studio_base_url": "http://127.0.0.1:1234/v1",
                    "allow_cloud_model_fallback": False,
                    "model_fallback_order": ["local-loaded"],
                    "role_model_overrides": {},
                },
            ):
                model_id, profile = await hades_main.resolve_model("missing-from-lm-studio")
            self.assertEqual(model_id, "local-loaded")
            selection = profile.get("_model_selection") or {}
            self.assertIn(selection.get("reason"), {"fallback", "default", "fallback_after_explicit_unavailable"})

        asyncio.run(_run())

    def test_resolve_model_no_longer_skips_discovery_for_preferred(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.resolve_model)
        self.assertNotIn("skips discovery when given", source)
        self.assertIn("discover_models", source)
        # Early return of preferred without checking model_ids must be gone.
        self.assertNotIn("if preferred and not role:\n        profile = database.profile_for(preferred)", source)


class ConversationStateWiringTests(unittest.TestCase):
    def test_resolve_reasoning_profile_accepts_conversation_state(self) -> None:
        from reasoning.profiles import resolve_reasoning_profile

        chosen, spec, meta = resolve_reasoning_profile(
            "Waarom faalt dit?",
            "adaptive",
            conversation_state={"last_assistant": "deploy failed", "recent_failures": ["timeout"]},
        )
        self.assertTrue(spec.interpretation.get("follow_up"))
        self.assertEqual(spec.kind, "debug")
        self.assertIn(chosen, {"fast", "standard", "high", "maximum"})
        self.assertEqual(meta["request"]["kind"], "debug")

    def test_send_message_passes_conversation_state(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("conversation_state=prior_state", source)
        self.assertIn("prior_failures=prior_failures", source)

    def test_working_state_stores_last_assistant_and_failures(self) -> None:
        from reasoning.conversation_state import build_conversation_working_state

        failed = build_conversation_working_state(
            previous=None,
            user_text="Deploy naar staging",
            assistant_text="Deploy failed: timeout",
            request_spec={"goal": "deploy"},
            route={"target": "tool_loop"},
            executed={"status": "failed"},
        )
        self.assertIn("timeout", failed["last_assistant"])
        self.assertTrue(failed["recent_failures"])

        recovered = build_conversation_working_state(
            previous=failed,
            user_text="Probeer opnieuw",
            assistant_text="Deploy gelukt",
            request_spec={"goal": "deploy"},
            route={"target": "tool_loop"},
            executed={"status": "completed"},
        )
        self.assertEqual(recovered["recent_failures"], [])
        self.assertIn("gelukt", recovered["last_assistant"])


class ToolLoopAndResearchHonestyTests(unittest.TestCase):
    def test_tool_loop_called_requires_tool_log(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("executed.tool_loop_called = bool(tool_log)", source)
        self.assertNotIn(
            "bool(tool_log) or (tool_rounds is None or tool_rounds > 0)",
            source,
        )

    def test_research_route_web_refresh_is_local_first_and_policy_gated(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        # Local retrieval precedes optional web refresh.
        retrieval_pos = source.find("retrieved_items, retrieval = retrieval_context_items(")
        refresh_pos = source.find("web_refresh = await maybe_refresh_web_knowledge(")
        self.assertGreater(retrieval_pos, 0)
        self.assertGreater(refresh_pos, retrieval_pos)
        self.assertIn("allow_web=True", source)
        self.assertIn("request_disallow_web", source)
        self.assertIn("research_via_web_refresh_and_chat", source)
        self.assertIn("research_route_without_web_refresh", source)


class ChatPayloadTemperatureBiasTests(unittest.TestCase):
    def test_high_profile_applies_negative_temperature_bias(self) -> None:
        import main as hades_main

        with mock.patch.object(
            hades_main,
            "runtime_values",
            return_value={"system_prompt": ""},
        ):
            payload = hades_main.chat_payload(
                "m1",
                {"temperature": 0.7, "top_p": 0.95, "max_tokens": 2048, "system_prompt": ""},
                [{"role": "user", "content": "hi"}],
                "high",
            )
        self.assertAlmostEqual(payload["temperature"], 0.65, places=3)


class StreamPathTests(unittest.TestCase):
    def test_dead_false_stream_gate_removed(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.run_model_with_optional_tool)
        self.assertNotIn("and False", source)
        # Wave 1: stream tool rounds via chat_stream_events assembler (not tools-gated).
        self.assertIn("use_stream = bool(run_id)", source)
        self.assertNotIn('and not payload.get("tools")', source)


class WorkspaceRetrievalPreviewTests(unittest.TestCase):
    def test_retrieval_uses_knowledge_chunk_preview_for_workspace(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.retrieval_context_items)
        self.assertIn("list_knowledge_chunks", source)
        self.assertIn("preview", source)


class KnowledgeIndexUnitTests(unittest.TestCase):
    def test_index_conversation_includes_eligible_assistant_only(self) -> None:
        from database import Database
        from platform_db import PlatformDatabase
        from platform_services_core import KnowledgeService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = Database(root / "core.db")
            core.initialize()
            platform = PlatformDatabase(root / "platform.db")
            platform.initialize()
            knowledge = KnowledgeService(platform, root / "knowledge")
            conv = core.create_conversation(title="t")
            core.add_message(conv["id"], "user", "Wat is de status?")
            # Without eligibility, historical assistants must not be promoted.
            skipped = knowledge.index_conversation(
                conv["id"],
                [
                    *core.list_messages(conv["id"]),
                    {"role": "assistant", "id": "old-a", "content": "Oude ongeverifyerde claim."},
                    {
                        "role": "assistant",
                        "id": "new-a",
                        "content": "Alles is geverifieerd groen.",
                        "_force_include_assistant": True,
                    },
                ],
                include_assistant=True,
                verified_write_back=True,
                eligible_assistant_ids={"new-a"},
            )
            self.assertIn("new-a", skipped.get("included_assistant_ids") or [])
            self.assertNotIn("old-a", skipped.get("included_assistant_ids") or [])
            hits = platform.search_knowledge("geverifieerd groen", limit=5)
            self.assertTrue(hits, "verified assistant prose must be searchable after write-back")
            bad_hits = platform.search_knowledge("ongeverifyerde claim", limit=5)
            self.assertFalse(bad_hits, "old unchecked assistant must not be promoted")

    def test_index_conversation_exchange_verified_path(self) -> None:
        from database import Database
        from platform_db import PlatformDatabase
        from platform_services_core import KnowledgeService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = Database(root / "core.db")
            core.initialize()
            platform = PlatformDatabase(root / "platform.db")
            platform.initialize()
            knowledge = KnowledgeService(platform, root / "knowledge")
            conv = core.create_conversation(title="ex")
            result = knowledge.index_conversation_exchange(
                conv["id"],
                "Vraag",
                "Antwoord met feiten.",
                verified_write_back=True,
                user_message_id="u1",
                assistant_message_id="a1",
                branch_id="b1",
            )
            self.assertTrue(result.get("indexed") or (result.get("persistence") or {}).get("inserted_count", 0) >= 0)
            self.assertEqual(result.get("included_assistant_ids"), ["a1"])


if __name__ == "__main__":
    unittest.main()
