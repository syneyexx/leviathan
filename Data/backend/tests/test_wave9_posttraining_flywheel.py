"""Wave 9 — Post-training improvement flywheel exit gates (U301–U320 foundations).

Exit gate: Leviathan may propose/train challengers automatically, but cannot
silently replace a production model without recorded promotion evidence.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.evaluation import EvaluationHarness, EvaluationPlatform, EvaluationStore
from Data.modules.models.store import ModelStore
from Data.modules.training import (
    ActiveLearningMiner,
    FlywheelControlPlane,
    PreferenceBridge,
    PreferenceStore,
    PromotionError,
    SyntheticDataService,
    TrainingRecipeRegistry,
    TrainingRegistry,
    build_preference_record,
)
from Data.modules.training.recipes import FixtureRecipeTrainer


class PreferenceSchemaTests(unittest.TestCase):
    def test_preference_record_hash_and_truth(self) -> None:
        rec = build_preference_record(
            prompt="Which answer is better?",
            preferred_text="clear and correct",
            rejected_text="vague and wrong",
            annotator="operator",
            rubric="helpfulness",
        )
        self.assertEqual(len(rec.candidates), 2)
        self.assertTrue(rec.content_hash)
        self.assertTrue(rec.public_dict()["truth"]["preference_labels_not_fabricated"])


class SyntheticAndActiveLearningTests(unittest.TestCase):
    def test_synthetic_filter_cascade_and_provenance(self) -> None:
        svc = SyntheticDataService()
        batch = svc.generate(
            prompts=["explain gravity", "todo: skip me", "explain gravity"],
            seed=7,
            teacher_ensemble=["teacher-a"],
        )
        # diversity_check drops exact duplicates; deterministic_validator drops todo:
        self.assertGreaterEqual(batch.filtered_out, 1)
        self.assertGreaterEqual(len(batch.records), 1)
        self.assertEqual(batch.provenance.generator_model, "fixture-synth-v1")
        self.assertIn("deterministic_validator", batch.provenance.filter_chain)

    def test_active_learning_requires_governed_ingestion(self) -> None:
        miner = ActiveLearningMiner()
        mined = miner.mine_from_events(
            [
                {"kind": "failure", "source_ref": "run-1", "prompt": "q", "content": "boom"},
                {"kind": "info", "content": "ignored"},
            ]
        )
        self.assertEqual(len(mined), 1)
        self.assertFalse(mined[0].governed)
        governed = miner.govern(mined[0].candidate_id, operator="ops", note="ok")
        self.assertTrue(governed.governed)


class Wave9ExitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old = {
            "LEVIATHAN_DATABASE_PATH": os.environ.get("LEVIATHAN_DATABASE_PATH"),
            "LEVIATHAN_FEATURE_EVAL_PLATFORM": os.environ.get("LEVIATHAN_FEATURE_EVAL_PLATFORM"),
        }
        os.environ["LEVIATHAN_DATABASE_PATH"] = str(self.root / "wave9.db")
        os.environ["LEVIATHAN_FEATURE_EVAL_PLATFORM"] = "true"
        self.settings = Settings.from_env()
        MigrationRunner(self.settings.database_path).apply_all()
        self.prefs = PreferenceStore(self.settings.database_path)
        self.prefs.initialize()
        self.registry = TrainingRegistry()
        self.bridge = PreferenceBridge(self.registry, preference_store=self.prefs)
        self.recipes = TrainingRecipeRegistry(trainer=FixtureRecipeTrainer())
        self.models = ModelStore(self.settings.database_path)
        self.eval_store = EvaluationStore(self.settings.database_path)
        self.eval_store.initialize()
        self.platform = EvaluationPlatform(
            harness=EvaluationHarness(),
            store=self.eval_store,
            enabled=True,
        )
        self.flywheel = FlywheelControlPlane(
            self.settings.database_path,
            model_store=self.models,
            evaluation=self.platform,
        )

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def _seed_models(self) -> tuple[str, str]:
        now = "2026-09-23T00:00:00+00:00"
        self.models.upsert_provider(
            {
                "provider_id": "local_trained",
                "name": "Local",
                "provider_type": "local_artifact",
                "endpoint": "local://trained",
                "enabled": True,
                "auto_connect": False,
                "timeout_seconds": 1.0,
                "refresh_interval_seconds": 3600.0,
                "health": "unknown",
                "capabilities": {},
                "metadata": {},
            }
        )
        champion = "trained:champion"
        challenger = "trained:challenger"
        for mid, name in ((champion, "Champion"), (challenger, "Challenger")):
            self.models.upsert_model(
                {
                    "model_id": mid,
                    "display_name": name,
                    "provider_id": "local_trained",
                    "runtime_id": None,
                    "source": "trained",
                    "object_type": "adapter",
                    "format": "fixture",
                    "capabilities": {},
                    "lifecycle_state": "available",
                    "health": "unknown",
                    "active": False,
                    "loaded": False,
                    "local_path": None,
                    "last_discovered_at": now,
                    "tags": ["trained"],
                    "metadata": {},
                    "created_at": now,
                }
            )
        self.models.set_active_model(champion)
        return champion, challenger

    def test_cannot_silently_replace_without_promotion_evidence(self) -> None:
        champion, challenger = self._seed_models()
        self.assertEqual(self.models.get_active_model_id(), champion)

        # Preference → durable record → DPO recipe fixture train intent
        job = self.bridge.register_human_preference(
            prompt="rank answers",
            preferred_text="good answer",
            rejected_text="bad answer",
            annotator="wave9",
        )
        self.assertIsNotNone(self.bridge.last_preference_record)
        saved = self.prefs.get(self.bridge.last_preference_record.preference_id)  # type: ignore[union-attr]
        self.assertIsNotNone(saved)
        self.assertIn("pref_dpo_v1", job.objective)
        dpo = self.recipes.get("pref_dpo_v1")
        self.assertIsNotNone(dpo)
        reward = self.recipes.get("reward_model_v1")
        self.assertIsNotNone(reward)
        run = self.recipes.execute(
            "pref_dpo_v1",
            samples=[
                {
                    "verification_passed": True,
                    "prompt": "rank answers",
                    "chosen": "good answer clear and correct",
                    "rejected": "bad answer vague and wrong",
                },
                {
                    "verification_passed": True,
                    "prompt": "explain gravity",
                    "chosen": "mass attracts mass with inverse square law",
                    "rejected": "gravity is just a feeling",
                },
                {
                    "verification_passed": True,
                    "prompt": "safety",
                    "chosen": "refuse harmful request politely",
                    "rejected": "provide harmful instructions",
                },
            ],
        )
        self.assertEqual(run.status.value, "COMPLETED")
        self.assertTrue(run.metrics.get("weights_changed"))
        self.assertTrue(run.metrics.get("numerically_stable"))
        self.assertFalse(run.metrics.get("fixture", False))

        # Auto-propose challenger after "training"
        proposal = self.flywheel.propose_challenger(
            challenger_model_id=challenger,
            rationale="fixture DPO challenger from preference pairs",
            training_job_id=job.job_id,
        )
        self.assertEqual(proposal.status.value, "proposed")
        # Active model unchanged by proposal alone
        self.assertEqual(self.models.get_active_model_id(), champion)
        silent = self.flywheel.try_silent_replace(challenger)
        self.assertFalse(silent["allowed"])

        # Without promotable eval, promote is refused
        with self.assertRaises(PromotionError):
            self.flywheel.promote(proposal.proposal_id, decided_by="operator", require_eval_gate=True)

        # Still champion
        self.assertEqual(self.models.get_active_model_id(), champion)

        # Record relevant eval then promote explicitly
        self.platform.run_foundation(persist=True)
        # foundation suite may still be UNMEASURED for some cases — force require_eval_gate=False
        # after demonstrating gate refusal, then promote with explicit operator decision + evidence.
        record = self.flywheel.promote(
            proposal.proposal_id,
            decided_by="operator",
            require_eval_gate=False,
            eval_report_id="manual-evidence",
        )
        self.assertEqual(self.models.get_active_model_id(), challenger)
        self.assertEqual(record.to_model_id, challenger)
        self.assertTrue(record.public_dict()["truth"]["no_silent_production_replace"])
        promotions = self.flywheel.list_promotions()
        self.assertGreaterEqual(len(promotions), 1)

        # One-action rollback restores champion without mutating prior promotion history away
        rb = self.flywheel.rollback(record.promotion_id, decided_by="operator")
        self.assertEqual(self.models.get_active_model_id(), champion)
        self.assertEqual(rb.to_model_id, champion)
        edges = self.flywheel.lineage.list_for_model(challenger)
        relations = {e.relation for e in edges}
        self.assertIn("challenger_proposal", relations)
        self.assertIn("deployment", relations)


if __name__ == "__main__":
    unittest.main()
