"""Wave 8 — Industrial data + training factory exit gates (U261–U300 foundations).

Exit gate: raw governed data → immutable mixture → training → artifact → registry
is reproducible after process/worker failure (fixture backends only).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.common.corpus import build_corpus_layout
from Data.modules.datasets import DatasetService, DatasetStore
from Data.modules.datasets.contamination import scan_contamination
from Data.modules.datasets.mixtures import MixtureComponent, build_mixture_manifest
from Data.modules.datasets.packing_sim import simulate_packing
from Data.modules.datasets.shards import ShardIngestCheckpoint, build_shard_plan, ingest_shards
from Data.modules.datasets.types import CanonicalRecord, DatasetJobStatus
from Data.modules.knowledge import KnowledgeStore
from Data.modules.models.store import ModelStore
from Data.modules.training import TrainingService, TrainingStore, verify_artifact_integrity
from Data.modules.training.model_registration import sync_completed_artifacts_to_models


class MixtureAndContaminationUnitTests(unittest.TestCase):
    def test_mixture_hash_stable_and_sealed(self) -> None:
        comps = [
            MixtureComponent(version_id="v1", content_hash="aaa", weight=2.0, domain="code"),
            MixtureComponent(version_id="v2", content_hash="bbb", weight=1.0, domain="chat"),
        ]
        a = build_mixture_manifest(name="mix", components=comps)
        b = build_mixture_manifest(name="mix", components=list(reversed(comps)))
        # Different order → different normalized component order in hash body
        # (weights normalized; order preserved as provided)
        self.assertTrue(a.sealed)
        self.assertEqual(sum(c.weight for c in a.components), 1.0)
        self.assertTrue(a.public_dict()["truth"]["trainable_manifest_not_mutable_folder"])
        # Same order → same hash
        c = build_mixture_manifest(name="mix", components=comps)
        self.assertEqual(a.content_hash, c.content_hash)
        self.assertNotEqual(a.content_hash, b.content_hash)

    def test_contamination_exact_and_fuzzy(self) -> None:
        sealed = [{"case_id": "e1", "prompt": "the quick brown fox jumps over the lazy dog"}]
        clean = [CanonicalRecord(id="r1", text="unrelated astronomy notes")]
        dirty = [
            CanonicalRecord(id="r2", text="the quick brown fox jumps over the lazy dog"),
        ]
        ok = scan_contamination(clean, sealed)
        self.assertTrue(ok.passed)
        bad = scan_contamination(dirty, sealed)
        self.assertFalse(bad.passed)
        self.assertEqual(bad.hits[0].kind, "exact")

    def test_packing_simulation(self) -> None:
        records = [CanonicalRecord(id=f"r{i}", text="word " * 40) for i in range(5)]
        sim = simulate_packing(records, max_seq_length=64)
        self.assertGreaterEqual(sim.packed_sequences, 1)
        self.assertTrue(0.0 <= sim.packing_efficiency <= 1.0)


class ShardResumeTests(unittest.TestCase):
    def test_interrupt_and_resume_verified_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(3):
                p = root / f"src_{i}.txt"
                p.write_text(f"shard-body-{i}", encoding="utf-8")
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            ckpt, outs = ingest_shards(plan, interrupt_after=1)
            self.assertEqual(ckpt.status, "interrupted")
            self.assertEqual(len(outs), 1)
            self.assertEqual(ckpt.next_index, 1)
            ckpt2, outs2 = ingest_shards(plan, checkpoint=ckpt)
            self.assertEqual(ckpt2.status, "completed")
            self.assertEqual(len(outs2), 3)
            # Content-addressed files exist and are stable
            for entry in outs2:
                self.assertTrue(Path(entry["path"]).exists())
                self.assertEqual(len(entry["content_hash"]), 64)


class Wave8ExitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        from Data.backend.config import Settings

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_env = {
            "LEVIATHAN_DATABASE_PATH": os.environ.get("LEVIATHAN_DATABASE_PATH"),
            "LEVIATHAN_CORPUS_ROOT": os.environ.get("LEVIATHAN_CORPUS_ROOT"),
            "LEVIATHAN_NETWORK_ALLOW_OUTBOUND": os.environ.get("LEVIATHAN_NETWORK_ALLOW_OUTBOUND"),
        }
        os.environ["LEVIATHAN_DATABASE_PATH"] = str(self.root / "wave8.db")
        os.environ["LEVIATHAN_CORPUS_ROOT"] = str(self.root / "corpus")
        os.environ["LEVIATHAN_NETWORK_ALLOW_OUTBOUND"] = "false"
        self.settings = Settings.from_env()
        MigrationRunner(self.settings.database_path).apply_all()
        self.corpus = build_corpus_layout(self.settings).ensure()
        self.store = DatasetStore(self.settings.database_path)
        self.store.initialize()
        self.knowledge = KnowledgeStore(
            self.settings.database_path,
            data_root=self.root / "corp",
        )
        self.knowledge.initialize()
        (self.root / "corp").mkdir(parents=True, exist_ok=True)
        self.datasets = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=self.settings,
            allowed_import_roots=[self.root, self.corpus.root],
        )
        self.training_store = TrainingStore(self.settings.database_path)
        self.training = TrainingService(
            self.settings,
            store=self.training_store,
            corpus=self.corpus,
        )
        self.models = ModelStore(self.settings.database_path)

    def tearDown(self) -> None:
        import os

        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_governed_data_to_registry_after_failure(self) -> None:
        # 1) Raw governed sources → shard ingest with intentional interrupt/resume
        ds = self.datasets.create_dataset(name="wave8-raw", description="exit gate")
        sources = []
        for i in range(2):
            p = self.root / f"raw_{i}.jsonl"
            p.write_text(
                '{"id":"a%d","text":"governed example %d about devices"}\n' % (i, i),
                encoding="utf-8",
            )
            sources.append(str(p))
        job1 = self.datasets.enqueue_shard_ingest(ds.dataset_id, sources=sources, interrupt_after=1)
        done1 = self.datasets.process_jobs(max_jobs=1)[0]
        self.assertEqual(done1.status, DatasetJobStatus.INTERRUPTED)
        self.assertGreaterEqual(done1.checkpoint.get("next_index", 0), 1)

        self.datasets.enqueue_shard_ingest(
            ds.dataset_id,
            sources=sources,
            resume_from_job_id=job1.job_id,
        )
        done2 = self.datasets.process_jobs(max_jobs=1)[0]
        self.assertEqual(done2.status, DatasetJobStatus.COMPLETED)
        self.assertEqual(done2.result.get("checkpoint", {}).get("status"), "completed")

        # 2) Import + materialize for a version with content hash
        import_job = self.datasets.enqueue_import_local(
            path=sources[0],
            name="wave8-canon",
            dataset_id=ds.dataset_id,
            materialize=True,
        )
        processed = self.datasets.process_jobs(max_jobs=5)
        self.assertTrue(
            any(j.job_id == import_job.job_id and j.status == DatasetJobStatus.COMPLETED for j in processed)
        )
        versions = self.datasets.list_versions(ds.dataset_id)
        self.assertTrue(versions)
        version = next(v for v in versions if v.content_hash)
        self.assertTrue(version.content_hash)

        # 3) Immutable mixture
        mixture = self.datasets.create_mixture(
            name="wave8-mix",
            components=[{"version_id": version.version_id, "weight": 1.0, "domain": "devices"}],
        )
        self.assertTrue(mixture["sealed"])
        frozen_hash = mixture["content_hash"]
        again = self.datasets.get_mixture(mixture["mixture_id"])
        self.assertEqual(again["content_hash"], frozen_hash)

        # 4) Contamination scan against sealed-like eval prompt
        self.datasets.enqueue_contamination_scan(
            ds.dataset_id,
            version.version_id,
            sealed_cases=[{"case_id": "seal1", "prompt": "totally unique sealed benchmark string xyzzy"}],
        )
        scan_done = self.datasets.process_jobs(max_jobs=1)[0]
        self.assertEqual(scan_done.status, DatasetJobStatus.COMPLETED)
        self.assertTrue(scan_done.result.get("passed"))

        # 5) Packing simulation + annotation queue
        packing = self.datasets.packing_simulation(version.version_id, max_seq_length=128)
        self.assertIn("packing_efficiency", packing)
        ann = self.datasets.enqueue_annotation(
            dataset_id=ds.dataset_id,
            record_id="a0",
            version_id=version.version_id,
        )
        self.assertEqual(ann["status"], "pending")

        # 6) Fixture training bound to mixture → artifact → integrity → registry
        job = self.training.create_job(
            {
                "name": "wave8-fixture",
                "method": "fixture",
                "base_model_ref": "fixture-base",
                "dataset_version_id": version.version_id,
                "mixture_id": mixture["mixture_id"],
                "mixture_content_hash": frozen_hash,
                "fixture_steps": 3,
                "fixture_sleep_ms": 5,
            },
            auto_start=True,
        )
        finished = self.training.wait_until_terminal(job.job_id, timeout=30.0)
        self.assertEqual(finished.status.value, "completed")
        self.assertTrue(finished.artifact_id)
        artifact = self.training_store.get_artifact(finished.artifact_id)
        assert artifact is not None
        report = verify_artifact_integrity(artifact, job=finished)
        self.assertTrue(report.passed, report.public_dict())

        synced = sync_completed_artifacts_to_models(
            model_store=self.models,
            training_store=self.training_store,
        )
        passed = [s for s in synced if s.get("integrity") == "passed"]
        self.assertEqual(len(passed), 1)
        model = self.models.get_model(passed[0]["modelId"])
        self.assertIsNotNone(model)
        import json as _json

        meta = model.get("metadata") or _json.loads(model.get("metadata_json") or "{}")
        self.assertEqual(meta.get("mixtureContentHash"), frozen_hash)


if __name__ == "__main__":
    unittest.main()
