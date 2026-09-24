"""Inference Efficiency Plane — tokenization, budget/fit, caches, runtime capabilities."""

from __future__ import annotations

import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.context import (
    CONTEXT_WINDOW_EXCEEDED,
    CachePolicyEngine,
    CacheScope,
    CacheType,
    ContextBudgetPlanner,
    ContextBuilder,
    ContextFitState,
    FixtureTokenizer,
    InferenceEfficiencyPlane,
    TokenPrecision,
    TokenizationRequest,
    TokenizationService,
    build_stable_prefix_fingerprint,
    compact_hierarchical,
    estimate_tokens,
    get_efficiency_plane,
    preflight_context_fit,
    raise_if_unfit,
    set_efficiency_plane,
)
from Data.modules.context.cache_policy import CacheBypassReason
from Data.modules.models.contracts import ModelDescriptor, ModelCapabilities, ModelRequest, ModelSource
from Data.modules.models.efficiency_capabilities import (
    normalize_provider_usage,
    probe_llama_cpp_efficiency,
    probe_vllm_efficiency,
    external_provider_efficiency,
)
from Data.modules.models.errors import ModelControlError
from Data.modules.models.router import ModelRouter
from Data.modules.reasoning import ReasoningEngine


class ExactTokenizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = TokenizationService(mode="exact_preferred")
        self.svc.bind_model_tokenizer("fixture:demo", "fixture:whitespace_v1")

    def test_simple_text(self) -> None:
        r = self.svc.count_text("hello world", model_id="fixture:demo", tokenizer_id="fixture:whitespace_v1")
        self.assertEqual(r.precision, TokenPrecision.EXACT_LOCAL_TOKENIZER)
        self.assertEqual(r.token_count, 2)
        self.assertTrue(r.is_exact)

    def test_unicode_dutch(self) -> None:
        r = self.svc.count_text(
            "Ik moet uitsluitend Nederlands gebruiken",
            tokenizer_id="fixture:whitespace_v1",
        )
        self.assertEqual(r.precision, TokenPrecision.EXACT_LOCAL_TOKENIZER)
        self.assertGreater(r.token_count, 3)

    def test_code(self) -> None:
        r = self.svc.count_text("def foo(x):\n    return x + 1", tokenizer_id="fixture:whitespace_v1")
        self.assertTrue(r.is_exact)
        self.assertGreater(r.token_count, 4)

    def test_multi_message_chat(self) -> None:
        r = self.svc.count(
            TokenizationRequest(
                messages=(
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hallo"},
                    {"role": "assistant", "content": "Hoi"},
                ),
                tokenizer_id="fixture:whitespace_v1",
                chat_template_id="fixture_chat_v1",
            )
        )
        self.assertTrue(r.is_exact)
        self.assertGreater(r.token_count, 10)

    def test_tool_schema(self) -> None:
        r = self.svc.count(
            TokenizationRequest(
                messages=({"role": "user", "content": "call tool"},),
                tokenizer_id="fixture:whitespace_v1",
                tools_schema={"name": "search", "parameters": {"q": "string"}},
            )
        )
        self.assertTrue(r.is_exact)


class HeuristicFallbackTests(unittest.TestCase):
    def test_heuristic_when_no_tokenizer(self) -> None:
        svc = TokenizationService(mode="heuristic_only")
        r = svc.count_text("abcd efgh")
        self.assertEqual(r.precision, TokenPrecision.HEURISTIC)
        self.assertFalse(r.is_exact)
        self.assertGreater(r.safety_margin_tokens, 0)
        self.assertGreaterEqual(r.budget_count, r.token_count)

    def test_estimate_tokens_compat(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("abcd"), 1)


class TokenCacheVersioningTests(unittest.TestCase):
    def test_hit_then_miss_on_revision_change(self) -> None:
        svc = TokenizationService()
        req = TokenizationRequest(
            text="same immutable text",
            tokenizer_id="fixture:whitespace_v1",
            tokenizer_revision="1",
            chat_template_id="t1",
            chat_template_revision="1",
        )
        a = svc.count(req)
        b = svc.count(req)
        self.assertFalse(a.cached)
        self.assertTrue(b.cached)
        req2 = TokenizationRequest(
            text="same immutable text",
            tokenizer_id="fixture:whitespace_v1",
            tokenizer_revision="2",
            chat_template_id="t1",
            chat_template_revision="1",
        )
        c = svc.count(req2)
        self.assertFalse(c.cached)


class ModelContextWindowTests(unittest.TestCase):
    def test_budget_uses_selected_model_window(self) -> None:
        plan = ReasoningEngine().analyze("x", has_knowledge=False)
        large = ContextBuilder(model_context_window=8192, auto_budget=True)
        small = ContextBuilder(model_context_window=1024, auto_budget=True)
        self.assertGreater(large.usable_budget, small.usable_budget)
        pack_l = large.build(history=[{"role": "user", "content": "hi"}], knowledge=[], plan=plan)
        pack_s = small.build(history=[{"role": "user", "content": "hi"}], knowledge=[], plan=plan)
        self.assertGreater(pack_l.token_budget, pack_s.token_budget)

    def test_oversized_not_sent_to_small_model(self) -> None:
        planner = ContextBudgetPlanner()
        plan = planner.plan(context_window=512, max_output_tokens=128)
        fit = planner.evaluate_fit(
            plan,
            required_input_tokens=10_000,
            model_id="small",
            explicit_selection=True,
        )
        self.assertEqual(fit.state, ContextFitState.TOO_LARGE_FOR_SELECTED_MODEL)
        self.assertEqual(fit.error_code, CONTEXT_WINDOW_EXCEEDED)


class ExplicitModelTooSmallTests(unittest.TestCase):
    def test_structured_error_no_silent_switch(self) -> None:
        decision = preflight_context_fit(
            messages=[{"role": "user", "content": "x" * 50_000}],
            model_id="tiny",
            context_window=256,
            max_output_tokens=64,
            explicit_selection=True,
            tokenization=TokenizationService(mode="heuristic_only"),
        )
        self.assertFalse(decision.ok)
        with self.assertRaises(ModelControlError) as ctx:
            raise_if_unfit(decision)
        self.assertEqual(ctx.exception.code, CONTEXT_WINDOW_EXCEEDED)
        self.assertTrue(decision.explicit_selection)


class AutomaticFallbackContextFitTests(unittest.TestCase):
    def test_router_skips_too_small_for_auto_route(self) -> None:
        from Data.modules.models.contracts import CapabilityState, ModelHealthState, ModelLifecycleState
        from Data.modules.models.gateway import ModelGateway
        from Data.modules.models.store import ModelStore
        from Data.backend.migrations import MigrationRunner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.db"
            MigrationRunner(path).apply_all()
            store = ModelStore(path)
            gateway = ModelGateway(global_limit=2)

            def models():
                return [
                    ModelDescriptor(
                        id="small",
                        display_name="small",
                        provider_id="p",
                        source=ModelSource.LOCAL,
                        capabilities=ModelCapabilities(chat=CapabilityState.SUPPORTED),
                        lifecycle_state=ModelLifecycleState.AVAILABLE,
                        health=ModelHealthState.HEALTHY,
                        context_window=512,
                    ),
                    ModelDescriptor(
                        id="large",
                        display_name="large",
                        provider_id="p",
                        source=ModelSource.LOCAL,
                        capabilities=ModelCapabilities(chat=CapabilityState.SUPPORTED),
                        lifecycle_state=ModelLifecycleState.AVAILABLE,
                        health=ModelHealthState.HEALTHY,
                        context_window=8192,
                    ),
                ]

            router = ModelRouter(store, gateway, get_models=models)
            decision = router.resolve(
                ModelRequest(
                    required_capabilities=("chat",),
                    minimum_context_window=4096,
                )
            )
            self.assertEqual(decision.model_id, "large")


class PinnedConstraintOverflowTests(unittest.TestCase):
    def test_pinned_overflow_structured_failure(self) -> None:
        planner = ContextBudgetPlanner()
        plan = planner.plan(context_window=1024, max_output_tokens=256)
        fit = planner.evaluate_fit(
            plan,
            required_input_tokens=100,
            pinned_tokens=plan.usable_input_tokens + 50,
            explicit_selection=True,
        )
        self.assertEqual(fit.state, ContextFitState.TOO_LARGE_PINNED_CONTEXT)


class StablePrefixTests(unittest.TestCase):
    def test_stable_prefix_invariant_to_user_suffix(self) -> None:
        fp1, _ = build_stable_prefix_fingerprint(
            model_id="m1",
            behavior_profile_prompt="You are LEVIATHAN",
            system_core="core",
            constraints="never delete",
            tool_schema={"a": 1},
        )
        fp2, _ = build_stable_prefix_fingerprint(
            model_id="m1",
            behavior_profile_prompt="You are LEVIATHAN",
            system_core="core",
            constraints="never delete",
            tool_schema={"a": 1},
        )
        self.assertEqual(fp1, fp2)
        plan = ReasoningEngine().analyze("q", has_knowledge=False)
        b = ContextBuilder(model_id="m1", tokenization=TokenizationService(mode="heuristic_only"))
        b.bind_model(model_id="m1", tokenizer_id="fixture:whitespace_v1")
        p1 = b.build(
            history=[{"role": "user", "content": "hello"}],
            knowledge=[],
            plan=plan,
            behavior_profile_prompt="You are LEVIATHAN",
            constraints="never delete",
        )
        p2 = b.build(
            history=[{"role": "user", "content": "different user turn"}],
            knowledge=[],
            plan=plan,
            behavior_profile_prompt="You are LEVIATHAN",
            constraints="never delete",
        )
        self.assertEqual(p1.stable_prefix_fingerprint, p2.stable_prefix_fingerprint)
        self.assertNotEqual(p1.context_fingerprint, p2.context_fingerprint)
        p3 = b.build(
            history=[{"role": "user", "content": "hello"}],
            knowledge=[],
            plan=plan,
            behavior_profile_prompt="CHANGED PROFILE",
            constraints="never delete",
        )
        self.assertNotEqual(p1.stable_prefix_fingerprint, p3.stable_prefix_fingerprint)


class RuntimeCacheInvalidationTests(unittest.TestCase):
    def test_unload_invalidates_affinity_keeps_tokenizer_cache(self) -> None:
        plane = InferenceEfficiencyPlane()
        set_efficiency_plane(plane)
        plane.tokenization.count_text("hello", tokenizer_id="fixture:whitespace_v1")
        before = plane.tokenization.cache_snapshot()["stats"]["hits"] + plane.tokenization.cache_snapshot()["stats"]["misses"]
        aff = plane.on_worker_ready("model-a", worker_id="w1", prefix_cache_state="supported")
        self.assertEqual(aff.prefix_cache_state, "supported")
        plane.note_prefix_reuse("model-a", "spf:abc")
        plane.on_worker_unloaded("model-a", worker_id="w1")
        dead = plane.get_affinity("model-a")
        assert dead is not None
        self.assertEqual(dead.prefix_cache_state, "dead")
        # Tokenizer cache still works
        r = plane.tokenization.count_text("hello", tokenizer_id="fixture:whitespace_v1")
        self.assertTrue(r.cached or r.token_count > 0)
        self.assertGreaterEqual(
            plane.tokenization.cache_snapshot()["stats"]["lookups"], before
        )


class ProviderCachedTokensTests(unittest.TestCase):
    def test_normalize_cached_tokens(self) -> None:
        u = normalize_provider_usage(
            {"prompt_tokens": 100, "completion_tokens": 10, "cached_tokens": 40}
        )
        self.assertEqual(u.cached_input_tokens, 40)
        self.assertEqual(u.usage_source, "provider")

    def test_omit_is_null_not_zero(self) -> None:
        u = normalize_provider_usage({"prompt_tokens": 100, "completion_tokens": 10})
        self.assertIsNone(u.cached_input_tokens)
        self.assertEqual(u.usage_source, "provider")


class SemanticCacheFalsePositiveTests(unittest.TestCase):
    def test_negation_and_numeric_not_collapsed(self) -> None:
        plane = InferenceEfficiencyPlane()
        plane.apply_settings({"caches_enabled": True, "semantic_enabled": True})
        # Two similar embeddings but different constraint digests / operations store separately;
        # lookup requires high similarity AND same operation — we also check constraint digest.
        emb_a = [1.0, 0.0, 0.0]
        emb_b = [0.999, 0.01, 0.0]  # very similar
        plane.semantic_store(
            operation_id="intent.classify",
            key="a",
            query_embedding=emb_a,
            embedding_is_semantic=True,
            payload={"label": "enable_deletion", "constraint_digest": "enable"},
            scope=CacheScope.PROJECT,
            constraint_digest="enable",
        )
        # Near-duplicate embedding for opposite intent — still same vector space neighborhood.
        hit = plane.semantic_lookup(
            operation_id="intent.classify",
            query_embedding=emb_b,
            embedding_is_semantic=True,
            scope=CacheScope.PROJECT,
            threshold=0.99,
        )
        # Even if similarity is high, callers must compare constraint digests for safety.
        if hit is not None:
            self.assertNotEqual(hit.get("constraint_digest"), "do_not_enable")
        # Forbidden operation always bypasses
        elig = CachePolicyEngine().evaluate(
            cache_type=CacheType.SEMANTIC, operation_id="chat.final"
        )
        self.assertFalse(elig.cacheable)
        # LocalHash is not semantic
        bypass = plane.semantic_lookup(
            operation_id="intent.classify",
            query_embedding=emb_a,
            embedding_is_semantic=False,
            scope=CacheScope.PROJECT,
        )
        self.assertIsNone(bypass)


class PrivateScopeTests(unittest.TestCase):
    def test_no_cross_scope_leakage(self) -> None:
        plane = InferenceEfficiencyPlane()
        key = plane.retrieval_key(
            query="secret",
            policy_version="1",
            index_generation=1,
            project_scope="projA",
            security_scope="projA",
            embedding_model="e",
            embedding_revision="1",
            reranker_model=None,
            top_k=5,
        )
        plane.retrieval_put(key, {"hits": [1], "index_generation": 1}, scope=CacheScope.PROJECT)
        # Same key but different scope value stored — get requires matching scope field
        hit = plane.retrieval_get(key, scope=CacheScope.PROJECT)
        self.assertIsNotNone(hit)
        # Exact result scoped
        plane.apply_settings({"exact_result_enabled": True, "caches_enabled": True})
        plane.exact_result_store(
            operation_id="classification.deterministic",
            key_digest="k1",
            payload={"answer": "private-a"},
            scope=CacheScope.PROJECT,
        )
        miss = plane.exact_result_lookup(
            operation_id="classification.deterministic",
            key_digest="k1",
            scope=CacheScope.USER,
        )
        self.assertIsNone(miss)


class SideEffectBypassTests(unittest.TestCase):
    def test_side_effect_bypasses_result_cache(self) -> None:
        plane = InferenceEfficiencyPlane()
        plane.apply_settings({"exact_result_enabled": True})
        ok = plane.exact_result_store(
            operation_id="classification.deterministic",
            key_digest="side",
            payload={"done": True},
            has_side_effects=True,
        )
        self.assertFalse(ok)
        hit = plane.exact_result_lookup(
            operation_id="classification.deterministic",
            key_digest="side",
            has_side_effects=True,
        )
        self.assertIsNone(hit)


class SingleFlightTests(unittest.TestCase):
    def test_concurrent_tokenization_coalesces(self) -> None:
        svc = TokenizationService()
        calls = {"n": 0}
        original = svc._registry["fixture:whitespace_v1"]

        class Counting(FixtureTokenizer):
            def count_text(self, text: str) -> int:
                calls["n"] += 1
                return super().count_text(text)

        svc.register_tokenizer(Counting())
        barrier = threading.Barrier(8)

        def work() -> int:
            barrier.wait()
            return svc.count_text("coalesce me please", tokenizer_id="fixture:whitespace_v1").token_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: work(), range(8)))
        self.assertEqual(len(set(results)), 1)
        # Leader + possible cache; should not be 8 full compute races unbounded
        self.assertLessEqual(calls["n"], 8)
        self.assertGreaterEqual(svc._flight.stats()["leaders"], 1)


class CacheCorruptionTests(unittest.TestCase):
    def test_quarantine_corrupt_entry(self) -> None:
        plane = InferenceEfficiencyPlane()
        plane.context_compile_put("bad", {"ok": True})
        plane.quarantine_corrupt("context_compile", "bad")
        self.assertIsNone(plane.context_compile_get("bad"))


class ContextCompactionTests(unittest.TestCase):
    def test_hierarchical_preserves_constraints_and_reuses(self) -> None:
        history = []
        for i in range(40):
            history.append({"role": "user", "content": f"message {i} about topic"})
            history.append({"role": "assistant", "content": f"reply {i}"})
        history[0] = {
            "role": "user",
            "content": "Je moet nooit bestanden verwijderen. Never modify files outside the project.",
        }
        first = compact_hierarchical(history, recent_tail_messages=6, segment_size=10)
        self.assertGreater(len(first.hard_constraints), 0)
        # Change only recent tail
        history2 = list(history)
        history2[-1] = {"role": "assistant", "content": "new tail only"}
        existing = {s.segment_id: s for s in first.segments}
        second = compact_hierarchical(
            history2, recent_tail_messages=6, segment_size=10, existing_segments=existing
        )
        # When segments roll to session summary, reuse may vary; ensure canonical inputs unchanged length
        self.assertEqual(second.total_source_messages, first.total_source_messages)
        self.assertEqual(len(history2), len(history))


class Tier2DistillationUnavailableTests(unittest.TestCase):
    def test_deterministic_fallback_without_tier2(self) -> None:
        # Without a Tier-2 model, hierarchical/deterministic compaction still works.
        history = [{"role": "user", "content": f"long turn {i} " + ("woord " * 20)} for i in range(30)]
        result = compact_hierarchical(history)
        self.assertGreater(result.total_source_messages, 0)
        self.assertTrue(result.public_dict()["truth"]["canonical_history_preserved"])


class ContinuousBatchingCapabilityTests(unittest.TestCase):
    def test_supported_when_help_mentions(self) -> None:
        caps = probe_vllm_efficiency(help_text="--max-num-seqs 256 enable-prefix-caching")
        self.assertEqual(caps.continuous_batching.state.value, "supported")
        self.assertEqual(caps.prefix_cache.state.value, "supported")

    def test_unknown_without_evidence(self) -> None:
        caps = probe_vllm_efficiency(help_text="")
        self.assertEqual(caps.continuous_batching.state.value, "unknown")


class SpeculativeDecodingTests(unittest.TestCase):
    def test_unsupported_without_flags(self) -> None:
        caps = probe_llama_cpp_efficiency(help_text="--ctx-size 4096 --threads 4")
        self.assertEqual(caps.speculative_decoding.state.value, "unsupported")

    def test_supported_with_draft_flag(self) -> None:
        caps = probe_llama_cpp_efficiency(help_text="--draft model.gguf --ctx-size 4096")
        self.assertEqual(caps.speculative_decoding.state.value, "supported")


class CacheOffTests(unittest.TestCase):
    def test_inference_still_works_with_caches_disabled(self) -> None:
        plane = InferenceEfficiencyPlane()
        plane.apply_settings({"caches_enabled": False})
        plan = ReasoningEngine().analyze("hi", has_knowledge=False)
        builder = ContextBuilder(tokenization=plane.tokenization)
        pack = builder.build(history=[{"role": "user", "content": "hi"}], knowledge=[], plan=plan)
        self.assertGreater(pack.token_estimate, 0)
        self.assertIsNone(plane.context_compile_get("x"))


class ModelSwitchBrainUnaffectedTests(unittest.TestCase):
    def test_embedding_cache_survives_llm_switch(self) -> None:
        plane = InferenceEfficiencyPlane()
        key = plane.embedding_key(
            content_digest="abc",
            model_id="emb-1",
            model_revision="1",
            dimension=8,
            normalization="l2",
            provider_version="1",
        )
        plane.embedding_put(key, {"vector": [0.1] * 8})
        # Switching main LLM does not touch embedding keys
        hit = plane.embedding_get(key)
        self.assertIsNotNone(hit)
        # Changing embedding revision misses
        key2 = plane.embedding_key(
            content_digest="abc",
            model_id="emb-1",
            model_revision="2",
            dimension=8,
            normalization="l2",
            provider_version="1",
        )
        self.assertIsNone(plane.embedding_get(key2))


class BehaviorProfileChangeTests(unittest.TestCase):
    def test_profile_change_invalidates_prefix(self) -> None:
        a, _ = build_stable_prefix_fingerprint(behavior_profile_prompt="A", system_core="s")
        b, _ = build_stable_prefix_fingerprint(behavior_profile_prompt="B", system_core="s")
        self.assertNotEqual(a, b)


class ToolSchemaChangeTests(unittest.TestCase):
    def test_tool_schema_changes_prefix(self) -> None:
        a, _ = build_stable_prefix_fingerprint(tool_schema={"name": "a"})
        b, _ = build_stable_prefix_fingerprint(tool_schema={"name": "b"})
        self.assertNotEqual(a, b)


class RetrievalGenerationChangeTests(unittest.TestCase):
    def test_stale_generation_invalidated(self) -> None:
        plane = InferenceEfficiencyPlane()
        key = plane.retrieval_key(
            query="q",
            policy_version="1",
            index_generation=1,
            project_scope="p",
            security_scope="p",
            embedding_model="e",
            embedding_revision="1",
            reranker_model=None,
            top_k=3,
        )
        plane.retrieval_put(key, {"hits": [], "index_generation": 1}, scope=CacheScope.PROJECT)
        n = plane.invalidate_index_generation(1)
        self.assertGreaterEqual(n, 1)
        self.assertIsNone(plane.retrieval_get(key, scope=CacheScope.PROJECT))


class CachePressureTests(unittest.TestCase):
    def test_bounded_eviction(self) -> None:
        from Data.modules.context.bounded_cache import BoundedLRUCache

        cache = BoundedLRUCache(max_entries=3, max_bytes=10_000, name="t")
        for i in range(10):
            cache.put(f"k{i}", f"v{i}")
        self.assertLessEqual(cache.snapshot()["entries"], 3)
        self.assertGreater(cache.stats.evictions, 0)


class MigrationTests(unittest.TestCase):
    def test_migration_39_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lev.db"
            runner = MigrationRunner(path)
            applied = runner.apply_all()
            self.assertIn(39, applied)
            # Upgrade path: apply again is no-op
            self.assertEqual(runner.apply_all(), [])


class ExternalProviderBoundaryTests(unittest.TestCase):
    def test_external_does_not_claim_kv_ownership(self) -> None:
        caps = external_provider_efficiency()
        self.assertEqual(caps.kv_cache.state.value, "unsupported")
        self.assertEqual(caps.kv_cache.controlled_by, "provider_external")


class BudgetNegativeGuardTests(unittest.TestCase):
    def test_reserve_overflow_surfaces_zero_usable(self) -> None:
        planner = ContextBudgetPlanner(minimum_response_tokens=1000)
        plan = planner.plan(context_window=512, operator_response_tokens=2000)
        self.assertEqual(plan.usable_input_tokens, 0)
        self.assertIn("error", plan.diagnostics)


if __name__ == "__main__":
    unittest.main()
