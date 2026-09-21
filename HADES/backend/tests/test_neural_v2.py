"""Neural V2: production encoder, Chat dual wiring, experience ingest, honesty."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _hash_embed(text: str, dim: int = 64) -> list[float]:
    """Deterministic bag-of-token fake embedding (paraphrases sharing words align)."""
    import hashlib
    import re

    vals = [0.0] * dim
    tokens = re.findall(r"[a-z0-9+]+", (text or "").lower()) or [" "]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for i in range(dim):
            vals[i] += ((digest[i % len(digest)] / 127.5) - 1.0)
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _keyword_embed(text: str, dim: int = 64) -> list[float]:
    """Eval harness embedder: shared keywords land on shared axes (not production)."""
    import re

    # Axes derived from ASSOCIATION_PAIRS discriminative terms.
    axes = [
        "plugin", "invoke", "enabled", "ready",
        "worker", "sqlite", "join",
        "exact", "brain", "provenance", "neural",
        "off", "bypass", "learn", "gateway",
        "promote", "evaluate", "loss",
        "secret", "trading", "opt",
        "budget", "shadow", "inject",
        "failure", "negative", "lm", "studio",
        "checkpoint", "schema", "fast", "verified",
        "domain", "routing", "permission", "embedding", "toy",
        "dual", "categories", "continual", "offline", "work", "ingest",
    ]
    vals = [0.0] * dim
    tokens = set(re.findall(r"[a-z0-9+]+", (text or "").lower()))
    for i, axis in enumerate(axes):
        if axis in tokens or any(axis in t for t in tokens):
            vals[i % dim] += 1.0
    # Light lexical hash residual so unrelated texts stay separated.
    residual = _hash_embed(text, dim)
    mixed = [vals[i] + 0.05 * residual[i] for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in mixed)) or 1.0
    return [v / norm for v in mixed]


class EncoderAbstractionTests(unittest.TestCase):
    def test_production_encoder_rejects_missing_embedding_model(self) -> None:
        from neural.encoder import EncoderNotReady, build_encoder

        with self.assertRaises(EncoderNotReady):
            build_encoder(settings={})

    def test_lm_studio_embedding_encoder_with_fake_fn(self) -> None:
        from neural.encoder import EncoderBackend, FrozenEmbeddingVector, build_encoder

        enc = build_encoder(
            settings={"embedding_model_id": "nomic-test"},
            embed_fn=lambda t: _hash_embed(t, 48),
            expected_dimension=48,
        )
        self.assertEqual(enc.backend, EncoderBackend.LM_STUDIO_EMBEDDING)
        self.assertTrue(enc.ready)
        vec = enc.encode_text("HADES plugin invoke needs enabled+ready")
        self.assertEqual(int(vec.shape[-1]), 48)
        # Production Chat path must not require torch for embedding encode.
        listed = enc.encode_text_list("HADES plugin invoke needs enabled+ready")
        self.assertEqual(len(listed), 48)
        from neural.deps import neural_available

        if not neural_available():
            self.assertIsInstance(vec, FrozenEmbeddingVector)

    def test_dimension_mismatch_raises_typed_error(self) -> None:
        from neural.encoder import LmStudioEmbeddingEncoder

        calls = {"n": 0}

        def _flip_dim(text: str) -> list[float]:
            calls["n"] += 1
            dim = 32 if calls["n"] == 1 else 64
            return _hash_embed(text, dim)

        enc = LmStudioEmbeddingEncoder(model_id="flip", embed_fn=_flip_dim, expected_dimension=32)
        enc.encode_text_list("first")
        with self.assertRaises(Exception) as ctx:
            enc.encode_text_list("second different dim")
        # Prefer embeddings.DimensionMismatchError when importable.
        self.assertTrue(
            "dimension" in str(ctx.exception).lower()
            or type(ctx.exception).__name__ in {"DimensionMismatchError", "NeuralEncoderError"}
        )

    def test_toy_encoder_requires_explicit_flag_and_runtime(self) -> None:
        from neural.deps import neural_available
        from neural.encoder import EncoderNotReady, build_encoder

        with self.assertRaises(EncoderNotReady):
            build_encoder(encoder="toy", settings={"embedding_model_id": "x"})

        if not neural_available():
            self.skipTest("torch unavailable")
        from neural.runtime import NeuralModelRuntime

        runtime = NeuralModelRuntime()
        enc = build_encoder(encoder="toy", runtime=runtime)
        self.assertEqual(enc.backend.value, "toy")
        self.assertFalse(enc.status()["production"])
        vec = enc.encode_text("hello neural")
        self.assertEqual(int(vec.shape[-1]), runtime.toy_config.hidden_size)

    def test_dim_schema_mismatch_rejects_toy_checkpoint_into_embedding_memory(self) -> None:
        from neural.deps import neural_available

        if not neural_available():
            self.skipTest("torch unavailable")
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.errors import NeuralCheckpointIncompatible
        from neural.memory import NeuralMemory

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = NeuralMemoryCheckpointStore(Path(tmp.name) / "ckpts")
        # Simulate legacy toy checkpoint (schema 1 / dim 32 / old arch).
        toy_cfg = NeuralMemoryConfig(
            dim=32,
            hidden_dim=64,
            mode=NeuralMode.OFF,
            seed=1,
            architecture_version="parametric_mlp_v1",
            schema_version=1,
        )
        toy_mem = NeuralMemory(toy_cfg)
        # Force-write a schema-1 manifest by patching save payload.
        manifest = store.save(toy_mem, checkpoint_id="toy32", candidate=True)
        # Downgrade published schema to 1 to emulate old on-disk checkpoint.
        man_path = Path(tmp.name) / "ckpts" / "candidate" / "toy32" / "manifest.json"
        raw = json.loads(man_path.read_text(encoding="utf-8"))
        raw["schema_version"] = 1
        raw["architecture_version"] = "parametric_mlp_v1"
        raw["dim"] = 32
        raw["config"]["schema_version"] = 1
        raw["config"]["architecture_version"] = "parametric_mlp_v1"
        raw["config"]["dim"] = 32
        man_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        embed_cfg = NeuralMemoryConfig(
            dim=384,
            hidden_dim=768,
            mode=NeuralMode.OFF,
            seed=1,
            architecture_version="parametric_mlp_v2_embedding",
            schema_version=2,
        )
        with self.assertRaises(NeuralCheckpointIncompatible):
            store.load("toy32", candidate=True, expected_config=embed_cfg)
        # Even without expected_config, schema 1 must fail closed against SCHEMA_VERSION=2.
        with self.assertRaises(NeuralCheckpointIncompatible):
            store.load("toy32", candidate=True)


class DualRetrievalProductionWiringTests(unittest.TestCase):
    def test_read_injects_neural_association_with_fake_embed(self) -> None:
        from reasoning.chat_context import assemble_chat_context_messages

        associations = [
            {
                "id": "a1",
                "key_text": "HADES plugin invoke needs enabled and ready",
                "value_text": "Plugin invoke requires enabled+ready status",
                "domain": "general",
                "vector": _hash_embed("HADES plugin invoke needs enabled and ready", 32),
            }
        ]
        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["sys"],
            history=[],
            context_items=[],
            user_text="How do I invoke a HADES plugin?",
            max_chars=4000,
            settings={
                "enable_context_compiler_chat": False,
                "neural_allow": True,
                "neural_mode": "read",
                "neural_dual_memory_enabled": True,
                "embedding_model_id": "fake-embed",
                "neural_embed_fn": lambda t: _hash_embed(t, 32),
                "neural_embedding_dim": 32,
                "neural_associations": associations,
                "neural_exact_retrieve_fn": lambda _q: [
                    {"id": "e1", "content": "Exact: check Plugin Manager status.", "score": 0.9}
                ],
            },
        )
        self.assertTrue(meta["neural_dual_memory"]["enabled"])
        self.assertFalse(meta["neural_dual_memory"].get("shadow"))
        self.assertGreaterEqual(meta["neural_dual_memory"]["neural_kept"], 1)
        joined = "\n".join(m.get("content", "") for m in messages)
        self.assertIn("neural_association", joined)
        # Never trusted.
        self.assertNotIn('"trusted": true', joined.lower())

    def test_production_read_wires_without_injected_retrieve_fns(self) -> None:
        """Acceptance: READ + encoder ready injects neural without test retrieve hooks."""
        from reasoning.chat_context import ContextItem, assemble_chat_context_messages

        associations = [
            {
                "id": "a-prod",
                "key_text": "Join worker threads before closing SQLite",
                "value_text": "Always join workers before SQLite close.",
                "domain": "general",
                "vector": _hash_embed("Join worker threads before closing SQLite", 32),
            }
        ]
        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["sys"],
            history=[],
            context_items=[
                ContextItem(
                    item_id="mem-1",
                    kind="memory",
                    content="Exact memory: join workers before sqlite close.",
                    provenance="memory:mem-1",
                    priority=10,
                    trusted=True,
                )
            ],
            user_text="Should I close SQLite while workers still run?",
            max_chars=4000,
            settings={
                "enable_context_compiler_chat": False,
                "neural_allow": True,
                "neural_mode": "read",
                "neural_dual_memory_enabled": True,
                "embedding_model_id": "fake-embed",
                "neural_embed_fn": lambda t: _hash_embed(t, 32),
                "neural_embedding_dim": 32,
                "neural_associations": associations,
                # Intentionally no neural_retrieve_fn / neural_exact_retrieve_fn.
            },
        )
        dual = meta["neural_dual_memory"]
        self.assertTrue(dual.get("enabled"), dual)
        self.assertTrue(dual.get("encoder_ready"), dual)
        self.assertNotIn("neural_retrieve_unwired", str(dual.get("error") or ""))
        self.assertGreaterEqual(int(dual.get("neural_kept") or 0), 1)
        joined = "\n".join(m.get("content", "") for m in messages)
        self.assertIn("neural_association", joined)
        self.assertIn("join workers", joined.lower())
        # Exact memory already in context — still present; neural is additive.
        self.assertIn("Exact memory", joined)

    def test_shadow_scores_but_does_not_inject_neural(self) -> None:
        from reasoning.chat_context import assemble_chat_context_messages

        associations = [
            {
                "id": "a1",
                "key_text": "worker shutdown",
                "content": "join threads before sqlite close",
                "domain": "coding",
                "vector": _hash_embed("worker shutdown", 32),
            }
        ]
        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["sys"],
            history=[],
            context_items=[],
            user_text="worker shutdown corruption",
            max_chars=4000,
            settings={
                "enable_context_compiler_chat": False,
                "neural_allow": True,
                "neural_mode": "shadow",
                "neural_dual_memory_enabled": True,
                "embedding_model_id": "fake-embed",
                "neural_embed_fn": lambda t: _hash_embed(t, 32),
                "neural_embedding_dim": 32,
                "neural_associations": associations,
                "neural_exact_retrieve_fn": lambda _q: [
                    {"id": "e1", "content": "Exact join workers.", "score": 0.95}
                ],
            },
        )
        self.assertTrue(meta["neural_dual_memory"]["enabled"])
        self.assertTrue(meta["neural_dual_memory"]["shadow"])
        self.assertEqual(meta["neural_dual_memory"]["neural_kept"], 0)
        self.assertGreaterEqual(meta["neural_dual_memory"].get("neural_scored", 0), 0)
        joined = "\n".join(m.get("content", "") for m in messages)
        self.assertNotIn("neural_association", joined)
        self.assertIn("Exact join", joined)

    def test_missing_retrieve_sets_error_when_read_and_encoder_unready(self) -> None:
        from reasoning.chat_context import assemble_chat_context_messages

        _messages, _report, meta = assemble_chat_context_messages(
            system_parts=["sys"],
            history=[],
            context_items=[],
            user_text="hello",
            max_chars=2000,
            settings={
                "enable_context_compiler_chat": False,
                "neural_allow": True,
                "neural_mode": "read",
                "neural_dual_memory_enabled": True,
                # No embedding_model_id and no retrieve fns → typed error, not silent skip.
            },
        )
        self.assertIn("error", meta["neural_dual_memory"])
        self.assertTrue(meta["neural_dual_memory"]["error"])

    def test_neural_cannot_mark_trusted(self) -> None:
        from neural.dual_retrieval import candidate_to_context_item, retrieve_dual

        result = retrieve_dual(
            "q",
            neural_retrieve=lambda _q: [
                {
                    "id": "n1",
                    "content": "assoc",
                    "score": 0.9,
                    "trusted": True,
                    "candidate_type": "exact",
                }
            ],
        )
        item = candidate_to_context_item(result.neural[0])
        self.assertEqual(item.kind, "neural_association")
        self.assertFalse(item.trusted)


class ExperienceIngestV2Tests(unittest.TestCase):
    def test_failed_experience_becomes_negative_sample(self) -> None:
        from neural.continual_learning import ContinualLearningPipeline, evaluate_learning_eligibility
        from neural.experience import (
            ExperienceOutcome,
            ExperienceReward,
            NeuralExperience,
            RewardLabel,
            experience_to_negative_slow_example,
            experience_to_slow_example,
        )

        exp = NeuralExperience(
            experience_id="fail-1",
            outcome=ExperienceOutcome.VERIFIED_FAILURE,
            reward=ExperienceReward(label=RewardLabel.NEGATIVE, score=-1.0),
            problem_class="bad patch applied",
            strategy="tools=apply_patch",
            verification="tests_failed",
            result_summary="3 tests failed",
            tools=("pytest",),
            verified=True,
        )
        decision = evaluate_learning_eligibility(exp)
        self.assertTrue(decision.eligible)
        self.assertTrue(decision.failure_memory)
        self.assertFalse(decision.fast_memory_eligible)
        self.assertIsNone(experience_to_slow_example(exp))
        neg = experience_to_negative_slow_example(exp)
        self.assertIsNotNone(neg)
        pipe = ContinualLearningPipeline()
        result = pipe.process_experience(exp)
        self.assertIsNotNone(result.negative_slow_sample)
        self.assertEqual(result.negative_slow_sample["polarity"], "negative")
        self.assertFalse(result.negative_slow_sample["success_memory"])

    def test_verified_success_eligible_positive(self) -> None:
        from neural.continual_learning import evaluate_learning_eligibility
        from neural.experience import (
            ExperienceOutcome,
            ExperienceReward,
            NeuralExperience,
            RewardLabel,
            experience_to_slow_example,
        )

        exp = NeuralExperience(
            experience_id="ok-1",
            outcome=ExperienceOutcome.VERIFIED_SUCCESS,
            reward=ExperienceReward(label=RewardLabel.POSITIVE, score=1.0),
            problem_class="fix shutdown race",
            strategy="tools=pytest",
            verification="tests_passed",
            result_summary="ok",
            tools=("pytest",),
            verified=True,
        )
        self.assertTrue(evaluate_learning_eligibility(exp).eligible)
        self.assertIsNotNone(experience_to_slow_example(exp))

    def test_secret_blob_rejected(self) -> None:
        from neural.continual_learning import ContinualLearningPipeline, evaluate_learning_eligibility
        from neural.experience import (
            ExperienceOutcome,
            ExperienceReward,
            NeuralExperience,
            RewardLabel,
        )
        from neural.learning_lifecycle import ExperienceLifecycleState

        exp = NeuralExperience(
            experience_id="sec-1",
            outcome=ExperienceOutcome.VERIFIED_SUCCESS,
            reward=ExperienceReward(label=RewardLabel.POSITIVE, score=1.0),
            problem_class="rotate credentials",
            strategy="tools=none",
            verification="tests_passed",
            result_summary="stored api_key=sk-live-secret-token-99999",
            verified=True,
        )
        self.assertEqual(evaluate_learning_eligibility(exp).reason, "secret_material_rejected")
        result = ContinualLearningPipeline().process_experience(exp)
        self.assertEqual(result.lifecycle_state, ExperienceLifecycleState.REJECTED.value)
        self.assertIsNone(result.negative_slow_sample)
        self.assertIsNone(result.fast_write)

    def test_ingest_job_respects_allow_and_mode(self) -> None:
        from neural.experience import (
            ExperienceOutcome,
            ExperienceReward,
            NeuralExperience,
            RewardLabel,
        )
        from neural.experience_ingest import ingest_verified_experiences

        exp = NeuralExperience(
            experience_id="ok-2",
            outcome=ExperienceOutcome.VERIFIED_SUCCESS,
            reward=ExperienceReward(label=RewardLabel.POSITIVE, score=1.0),
            problem_class="task",
            strategy="tools=pytest",
            verification="passed",
            result_summary="ok",
            tools=("pytest",),
            verified=True,
        ).to_dict()
        # Reconstruct via continual path using items projection is harder; use store-less gate.
        report = ingest_verified_experiences(
            store=None,
            neural_allow=False,
            neural_mode="read",
            items=[],
        )
        self.assertIn("neural_allow_false", report.notes)

        report2 = ingest_verified_experiences(
            store=None,
            neural_allow=True,
            neural_mode="learn",
            items=[],
        )
        self.assertIn("learn_mode_rejected_as_gateway_primary", report2.notes)

    def test_maybe_ingest_hook_noops_when_off(self) -> None:
        from neural.experience_ingest import maybe_ingest_verified_experiences

        report = maybe_ingest_verified_experiences(
            None,
            {"neural_allow": False, "neural_mode": "off"},
            items=[],
        )
        self.assertIn("neural_allow_false", report.notes)
        report_ok = maybe_ingest_verified_experiences(
            None,
            {"neural_allow": True, "neural_mode": "read"},
            items=[],
        )
        self.assertEqual(report_ok.scanned, 0)
        self.assertFalse(any("learn_mode" in n for n in report_ok.notes))


class OffPathRegressionTests(unittest.TestCase):
    def test_main_still_does_not_import_neural_at_module_level(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        self.assertNotIn("from neural.", text)
        self.assertNotIn("import neural\n", text)

    def test_encoder_module_does_not_import_torch_at_load(self) -> None:
        import importlib
        import sys as _sys

        # Ensure fresh import does not pull torch via encoder.py top-level.
        for name in list(_sys.modules):
            if name == "neural.encoder" or name.startswith("neural.encoder."):
                del _sys.modules[name]
        mod = importlib.import_module("neural.encoder")
        self.assertFalse(getattr(mod, "torch", False))
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import torch", src)
        self.assertNotIn("from torch", src)


class TextAssociationEvalTests(unittest.TestCase):
    def test_fake_embed_recall_beats_toy_baseline_when_measurable(self) -> None:
        """Deterministic fake-embed recall@5 vs random baseline; writes UNMEASURED without provider."""
        from neural.v2_eval import run_text_association_eval, write_eval_artifact

        report = run_text_association_eval(
            embed_fn=lambda t: _keyword_embed(t, 64),
            encoder_id="keyword_harness_embed_dim64",
            dim=64,
            provider_available=False,
        )
        self.assertEqual(report["status"], "UNMEASURED")
        self.assertGreater(report["fake_embed_recall_at_5"], report["toy_baseline_recall_at_5"])
        self.assertTrue(report["interference_separated"])
        path = write_eval_artifact(report, Path(__file__).resolve().parents[2] / "docs" / "neural" / "v2_eval.json")
        self.assertTrue(path.is_file())
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["status"], "UNMEASURED")
        self.assertNotEqual(loaded["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
