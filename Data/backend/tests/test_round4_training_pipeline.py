"""Round 4 — Real training pipeline exit gates."""

from __future__ import annotations

import unittest

from Data.modules.datasets.quality import (
    quality_balance_report,
    semantic_dedupe,
    train_eval_separation,
)
from Data.modules.datasets.types import CanonicalRecord
from Data.modules.training import (
    DpoMicroTrainer,
    DpoPair,
    DpoRecipeTrainer,
    FixtureRecipeTrainer,
    SyntheticDataService,
    TrainingRecipeRegistry,
    probe_training_capabilities,
)
from Data.modules.training.config import TrainingConfig
from Data.modules.training.sft_data import (
    apply_chat_template,
    build_assistant_masked_example,
    examples_from_raw_texts,
    pack_examples,
    revision_provenance,
    split_examples,
)


class SftDataTests(unittest.TestCase):
    def test_assistant_masking_and_chat_template(self) -> None:
        messages = [
            {"role": "user", "content": "Wat is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        ex = build_assistant_masked_example(messages)
        self.assertTrue(ex.labels_mask)
        self.assertGreater(sum(ex.labels_mask), 0)
        self.assertIn("4", ex.text)
        # Prompt tokens (user side) should be mostly masked off.
        prompt_end = ex.role_spans["prompt"][1]
        self.assertTrue(all(v == 0 for v in ex.labels_mask[:prompt_end]))

    def test_split_is_deterministic_and_held_out(self) -> None:
        examples = examples_from_raw_texts([f"example number {i} content here" for i in range(20)])
        a = split_examples(examples, seed=7, val_ratio=0.2, test_ratio=0.2)
        b = split_examples(examples, seed=7, val_ratio=0.2, test_ratio=0.2)
        self.assertEqual([e.text for e in a.train], [e.text for e in b.train])
        self.assertGreater(len(a.validation), 0)
        train_set = {e.text for e in a.train}
        self.assertTrue(all(e.text not in train_set for e in a.validation))
        self.assertTrue(a.public_dict()["truth"]["training_loss_is_not_evaluation"])

    def test_packing_and_revision_provenance(self) -> None:
        examples = examples_from_raw_texts(["alpha " * 10, "beta " * 10, "gamma " * 10])
        packed = pack_examples(examples, max_chars=80)
        self.assertLessEqual(len(packed), len(examples))
        prov = revision_provenance(
            base_model_ref="org/model",
            base_model_revision="abc123",
            tokenizer_revision="abc123",
            chat_template=None,
            seed=42,
            assistant_loss_masking=True,
            packing=True,
        )
        self.assertEqual(prov["base_model_revision"], "abc123")
        self.assertFalse(prov["truth"]["unpinned_revision_is_not_reproducible"])
        self.assertIn("<|user|>", apply_chat_template([{"role": "user", "content": "hi"}]))

    def test_config_carries_sft_fields(self) -> None:
        cfg = TrainingConfig(
            name="sft",
            method="lora",
            base_model_ref="org/model",
            base_model_revision="rev1",
            tokenizer_revision="rev1",
            assistant_loss_masking=True,
            packing=True,
            val_split_ratio=0.15,
        )
        self.assertEqual(cfg.base_model_revision, "rev1")
        self.assertTrue(cfg.assistant_loss_masking)
        blob = cfg.public_dict()
        self.assertEqual(blob["base_model_revision"], "rev1")


class DpoObjectiveTests(unittest.TestCase):
    def test_weights_change_stable_held_out(self) -> None:
        pairs = [
            DpoPair("q1", "correct detailed answer one", "wrong nonsense one"),
            DpoPair("q2", "correct detailed answer two", "wrong nonsense two"),
            DpoPair("q3", "correct detailed answer three", "wrong nonsense three"),
            DpoPair("q4", "correct detailed answer four", "wrong nonsense four"),
        ]
        result = DpoMicroTrainer().train(pairs, steps=50, lr=0.8, beta=0.5, seed=3)
        self.assertTrue(result.weights_changed)
        self.assertTrue(result.numerically_stable)
        self.assertLess(result.train_loss_end, result.train_loss_start)
        self.assertTrue(result.public_dict()["truth"]["micro_dpo_is_not_hf_production_dpo"])
        # Held-out should not worsen dramatically; prefer improvement.
        self.assertTrue(result.held_out_improved or result.held_out_loss_end <= result.held_out_loss_start + 0.05)

    def test_recipe_trainer_requires_pairs_and_runs_dpo(self) -> None:
        registry = TrainingRecipeRegistry(trainer=FixtureRecipeTrainer())
        failed = registry.execute(
            "pref_dpo_v1",
            samples=[{"verification_passed": True}],
        )
        self.assertEqual(failed.status.value, "FAILED")

        ok = registry.execute(
            "pref_dpo_v1",
            samples=[
                {"verification_passed": True, "prompt": "a", "chosen": "good a", "rejected": "bad a"},
                {"verification_passed": True, "prompt": "b", "chosen": "good b", "rejected": "bad b"},
                {"verification_passed": True, "prompt": "c", "chosen": "good c", "rejected": "bad c"},
            ],
        )
        self.assertEqual(ok.status.value, "COMPLETED")
        self.assertTrue(ok.metrics["weights_changed"])
        self.assertFalse(ok.metrics.get("fixture", False))

    def test_capabilities_honest_about_hf_dpo(self) -> None:
        caps = probe_training_capabilities()
        self.assertTrue(caps.can_run_dpo)
        joined = " ".join(caps.notes).lower()
        self.assertIn("micro", joined)
        self.assertIn("not claimed", joined)


class SyntheticAndQualityTests(unittest.TestCase):
    def test_teacher_inference_and_provenance(self) -> None:
        def teacher(prompt: str, cfg: dict) -> str:
            return f"teacher-answer:{prompt}:{cfg.get('seed')}"

        batch = SyntheticDataService().generate(
            prompts=["gravity", "gravity", "reconnect fouten"],
            teacher_infer=teacher,
            generator_model="teacher-x",
            generator_revision="r1",
            prompt_template_revision="pt1",
            sampling_config={"temperature": 0.2, "top_p": 0.9},
            seed=9,
        )
        self.assertEqual(batch.provenance.mode, "teacher_inference")
        self.assertEqual(batch.provenance.generator_revision, "r1")
        self.assertEqual(batch.provenance.prompt_template_revision, "pt1")
        self.assertIn("temperature", batch.provenance.sampling_config)
        self.assertTrue(batch.provenance.generation_run_id)
        # semantic dedupe should drop duplicate gravity prompt content
        self.assertGreaterEqual(batch.filtered_out, 1)
        self.assertTrue(any("teacher-answer" in r.text for r in batch.records))

    def test_fixture_preserved_for_tests(self) -> None:
        batch = SyntheticDataService().generate(prompts=["hello world example"], seed=1)
        self.assertEqual(batch.provenance.mode, "fixture")
        self.assertTrue(batch.provenance.public_dict()["truth"]["fixture_is_not_teacher_inference"])

    def test_semantic_dedupe_and_train_eval_separation(self) -> None:
        records = [
            CanonicalRecord(id="1", text="The reconnect bug drops sessions after timeout."),
            CanonicalRecord(id="2", text="The reconnect bug drops sessions after timeout!"),
            CanonicalRecord(id="3", text="Pasta carbonara with eggs and cheese."),
        ]
        kept, stats = semantic_dedupe(records, jaccard_threshold=0.85)
        self.assertEqual(stats["removedCount"], 1)
        self.assertEqual(len(kept), 2)

        train = [CanonicalRecord(id="t1", text="hidden eval question about gravity laws")]
        ev = [CanonicalRecord(id="e1", text="hidden eval question about gravity laws")]
        sep = train_eval_separation(train, ev)
        self.assertFalse(sep["passed"])
        self.assertTrue(sep["truth"]["never_optimize_on_hidden_eval"])

        bal = quality_balance_report(
            [
                CanonicalRecord(id="a", text="de reconnect fout in het systeem", metadata={"domain": "ops", "language": "nl", "license": "MIT"}),
                CanonicalRecord(id="b", text="cooking pasta recipe", metadata={"domain": "food", "language": "en"}),
            ]
        )
        self.assertIn("nl", bal["language_balance"])
        self.assertEqual(bal["licensing_metadata_present"], 1)


class RecipeHonestyTests(unittest.TestCase):
    def test_reward_and_proc_not_claimed_operational(self) -> None:
        registry = TrainingRecipeRegistry()
        reward = registry.get("reward_model_v1")
        proc = registry.get("proc_supervision_v1")
        assert reward is not None and proc is not None
        self.assertFalse(reward.metadata.get("operational", True))
        self.assertFalse(proc.metadata.get("operational", True))
        dpo = registry.get("pref_dpo_v1")
        assert dpo is not None
        self.assertEqual(dpo.metadata.get("operational_objective"), "dpo_micro")
        self.assertFalse(dpo.metadata.get("hf_production_dpo"))


if __name__ == "__main__":
    unittest.main()
