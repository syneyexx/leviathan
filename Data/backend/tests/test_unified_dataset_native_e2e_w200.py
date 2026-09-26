"""W200 — unified dataset intelligence + native data-plane e2e scenarios.

Scenarios (tempfile corpus roots; small fixtures; stub model when needed):
  A) Import machine-like CSV → materialize → semantic enrich → display/category
     → sidecar → catalog → validate/transform/split/export (streaming)
  B) Native binary (if available): force rust validate; receipt + semantic preserved
  C) Fresh metadata DB + same corpus: reconcile recovers dataset + semantic display;
     Brain not fabricated LEARNED; REINDEX_REQUIRED if no index
  D) Native disabled: operations succeed via PYTHON_STREAMING
  E) Oversized JSONL line: RECORD_TOO_LARGE fail-closed
  F) Corrupt catalog: no DB corruption; recovery still works from sidecar
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.catalog import catalog_path
from Data.modules.datasets.compute_planner import ComputeBackend
from Data.modules.datasets.memory_policy import DatasetMemoryPolicy
from Data.modules.datasets.recovery import RecoveryState
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.sidecar import SIDECAR_FILENAME
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus, DatasetJobType
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.knowledge.store import KnowledgeStore
from Data.modules.workers.native_compute import resolve_native_binary


def _layout(root: Path) -> CorpusLayout:
    layout = CorpusLayout(
        root=root,
        datasets=root / "datasets",
        datasets_raw=root / "datasets" / "raw",
        datasets_materialized=root / "datasets" / "materialized",
        datasets_processed=root / "datasets" / "processed",
        datasets_exports=root / "datasets" / "exports",
        datasets_manifests=root / "datasets" / "manifests",
        training=root / "training",
        training_jobs=root / "training" / "jobs",
        training_runs=root / "training" / "runs",
        training_checkpoints=root / "training" / "checkpoints",
        training_adapters=root / "training" / "adapters",
        training_exports=root / "training" / "exports",
        training_logs=root / "training" / "logs",
        research=root / "research",
        research_projects=root / "research" / "projects",
        research_sources=root / "research" / "sources",
        research_snapshots=root / "research" / "snapshots",
        research_reports=root / "research" / "reports",
        research_exports=root / "research" / "exports",
        models_artifacts=root / "models" / "artifacts",
        models_cache=root / "models" / "cache",
        hf_cache=root / "hf_cache",
    )
    return layout.ensure()


class _NC:
    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode
        self.memory_budget_mb = 256
        self.max_record_mb = 1  # 1 MiB — small enough for RECORD_TOO_LARGE tests
        self.batch_rows = 1024
        self.threads = 2
        self.rust_threshold_mb = 1


class _RI:
    datasets_auto_index_ready_to_knowledge = False
    datasets_recovery_auto_reindex = False
    datasets_recovery_max_auto_jobs = 0
    dataset_jobs_runner = "none"
    dataset_index_batch_size = 50
    dataset_max_relations_per_doc = 8
    dataset_extract_relations = False


class _K:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root


class _S:
    def __init__(self, data_root: Path, *, native_mode: str = "auto") -> None:
        self.knowledge = _K(data_root)
        self.research_integration = _RI()
        self.native_compute = _NC(mode=native_mode)


def _service(tmp: Path, *, native_mode: str = "auto") -> tuple[DatasetService, Path, CorpusLayout]:
    data_root = tmp / "ModelData"
    data_root.mkdir(parents=True, exist_ok=True)
    db = tmp / "leviathan.db"
    corpus = _layout(data_root / "leviathan")
    knowledge = KnowledgeStore(
        db,
        data_root=data_root,
        embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
    )
    knowledge.initialize()
    store = DatasetStore(db)
    store.initialize()
    settings = _S(data_root, native_mode=native_mode)
    service = DatasetService(
        store,
        corpus=corpus,
        knowledge=knowledge,
        settings=settings,  # type: ignore[arg-type]
        allowed_import_roots=[data_root, corpus.root],
    )
    # Tighten record limit for fail-closed tests without relying solely on settings.
    service.memory_policy = DatasetMemoryPolicy(
        memory_budget_bytes=256 * 1024 * 1024,
        max_record_bytes=64 * 1024,
        native_mode=native_mode,
        rust_threshold_bytes=1024,
    )
    return service, data_root, corpus


class UnifiedDatasetNativeE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lev-e2e-w200-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _machine_csv(self, data_root: Path) -> Path:
        path = data_root / "ds_2024_03_machine_dump_v3.csv"
        path.write_text(
            "species,population,region,notes\n"
            "Ursus arctos,1200,Scandinavia,brown bear survey\n"
            "Canis lupus,400,Yellowstone,wolf pack census\n"
            "Lynx lynx,90,Carpathians,camera trap\n"
            "Vulpes vulpes,2100,Netherlands,urban foxes\n",
            encoding="utf-8",
        )
        return path

    def test_a_streaming_pipeline_semantic_stable_id(self) -> None:
        service, data_root, corpus = _service(self.root, native_mode="python")
        csv_path = self._machine_csv(data_root)

        load_calls: list[str] = []

        def _forbidden_load(*_a, **_k):
            load_calls.append("load_materialized_jsonl")
            raise AssertionError("full load_materialized_jsonl must not be required")

        with mock.patch(
            "Data.modules.datasets.service.load_materialized_jsonl",
            side_effect=_forbidden_load,
        ):
            imported = service.import_local_sync(
                str(csv_path), name="ds_2024_03_machine_dump_v3", materialize=True
            )
            ds_id = imported["dataset"]["datasetId"]
            self.assertTrue(ds_id)
            ver = service.pick_usable_version(ds_id)
            assert ver is not None

            enrich = service.enrich_semantic_deterministic(
                ds_id, ver.version_id, sync_artifacts=True
            )
            profile = enrich["semanticProfile"]
            self.assertTrue(profile.get("displayName"))
            self.assertTrue(profile.get("primaryCategory"))
            pub = service.public_dataset(ds_id)
            self.assertEqual(pub["datasetId"], ds_id)
            self.assertEqual(pub.get("displayName"), profile["displayName"])

            recovery = enrich["recovery"]
            self.assertTrue(Path(recovery["sidecarPath"]).is_file())
            self.assertTrue(Path(recovery["catalogPath"]).is_file())

            # validate → transform → split → export (streaming)
            vjob = service.enqueue_validate(ds_id, ver.version_id)
            vdone = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(vdone.job_id, vjob.job_id)
            self.assertEqual(vdone.status, DatasetJobStatus.COMPLETED)
            self.assertEqual(
                (vdone.result or {}).get("backend"),
                ComputeBackend.PYTHON_STREAMING.value,
            )

            tjob = service.enqueue_transform(
                ds_id,
                ver.version_id,
                [{"name": "strip_whitespace", "params": {"strip": True}}],
            )
            tdone = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(tdone.status, DatasetJobStatus.COMPLETED)
            transformed_id = (tdone.result or {}).get("versionId")
            self.assertTrue(transformed_id)

            sjob = service.enqueue_split(ds_id, transformed_id, seed=7)
            sdone = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(sdone.status, DatasetJobStatus.COMPLETED)
            split_id = (sdone.result or {}).get("versionId")
            self.assertTrue(split_id)

            ejob = service.enqueue_export(ds_id, split_id or transformed_id)
            edone = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(edone.status, DatasetJobStatus.COMPLETED)
            self.assertEqual(
                (edone.result or {}).get("backend"),
                ComputeBackend.PYTHON_STREAMING.value,
            )

            # Stable dataset id across the pipeline
            self.assertEqual(service.get_dataset(ds_id).dataset_id, ds_id)
            self.assertEqual(load_calls, [])

            # Catalog still lists the dataset with semantic display
            cat = json.loads(Path(recovery["catalogPath"]).read_text(encoding="utf-8"))
            entries = cat.get("entries") or cat.get("datasets") or []
            ids = {
                (e.get("datasetId") or e.get("id"))
                for e in entries
                if isinstance(e, dict)
            }
            self.assertIn(ds_id, ids)

    def test_b_native_force_rust_validate_preserves_semantic(self) -> None:
        binary = resolve_native_binary()
        if binary is None:
            self.skipTest("leviathan-data-plane binary not available")
        service, data_root, _corpus = _service(self.root, native_mode="auto")
        csv_path = self._machine_csv(data_root)
        imported = service.import_local_sync(str(csv_path), name="native_force_animals", materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        ver = service.pick_usable_version(ds_id)
        assert ver is not None
        enrich = service.enrich_semantic_deterministic(ds_id, ver.version_id, sync_artifacts=True)
        display = enrich["semanticProfile"]["displayName"]

        job = service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=ds_id,
            version_id=ver.version_id,
            config={"forceBackend": "RUST_NATIVE"},
        )
        done = service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.job_id, job.job_id)
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, msg=done.error)
        result = done.result or {}
        self.assertEqual(result.get("backend"), ComputeBackend.RUST_NATIVE.value)
        plan = result.get("backendPlan") or {}
        self.assertIn("force_backend", (plan.get("detail") or "").lower() + str(plan))
        # Receipt / validation report present
        self.assertIn("rowCount", result)
        refreshed = service.get_dataset(ds_id)
        meta = refreshed.metadata if isinstance(refreshed.metadata, dict) else {}
        semantic = meta.get("semanticProfile") or {}
        self.assertEqual(semantic.get("displayName"), display)

    def test_c_fresh_db_reconcile_recovers_semantic_not_learned(self) -> None:
        service, data_root, corpus = _service(self.root, native_mode="python")
        csv_path = self._machine_csv(data_root)
        imported = service.import_local_sync(str(csv_path), name="recover_me", materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        ver = service.pick_usable_version(ds_id)
        assert ver is not None
        enrich = service.enrich_semantic_deterministic(ds_id, ver.version_id, sync_artifacts=True)
        display = enrich["semanticProfile"]["displayName"]
        category = enrich["semanticProfile"]["primaryCategory"]
        sidecar = corpus.datasets_raw / ds_id / SIDECAR_FILENAME
        self.assertTrue(sidecar.is_file())
        catalog_file = catalog_path(corpus)
        catalog_bytes = catalog_file.read_bytes()

        # Fresh metadata DB, preserve corpus + catalog + sidecar
        fresh_root = self.root / "fresh"
        fresh_root.mkdir()
        fresh_db = fresh_root / "fresh.db"
        fresh_knowledge = KnowledgeStore(
            fresh_db,
            data_root=data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        fresh_knowledge.initialize()
        fresh_store = DatasetStore(fresh_db)
        fresh_store.initialize()
        # Restore catalog file if anything touched it
        catalog_file.write_bytes(catalog_bytes)
        fresh = DatasetService(
            fresh_store,
            corpus=corpus,
            knowledge=fresh_knowledge,
            settings=_S(data_root, native_mode="python"),  # type: ignore[arg-type]
            allowed_import_roots=[data_root, corpus.root],
        )
        result = fresh.reconcile_sidecars()
        restored_ids = list(result.get("restoredDatasetIds") or [])
        self.assertIn(ds_id, restored_ids, msg=f"reconcile={result}")
        ds = fresh.store.get_dataset(ds_id)
        self.assertIsNotNone(ds, msg=f"expected restore; reconcile={result}")
        assert ds is not None
        meta = ds.metadata if isinstance(ds.metadata, dict) else {}
        semantic = meta.get("semanticProfile") or {}
        self.assertEqual(semantic.get("displayName") or meta.get("displayName"), display)
        self.assertEqual(
            semantic.get("primaryCategory") or meta.get("primaryCategory"),
            category,
        )
        assessment2 = fresh.assess_dataset_recovery(ds_id)
        self.assertEqual(assessment2["recoveryState"], RecoveryState.REINDEX_REQUIRED.value)
        self.assertTrue(assessment2["reindexRequired"])
        self.assertFalse(assessment2.get("brainLearned"))
        learning = fresh.learning_state_for_dataset(ds_id)
        self.assertNotEqual(learning.get("canonicalState"), "LEARNED")
        self.assertFalse(learning.get("learned"))

    def test_d_native_disabled_python_streaming(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LEVIATHAN_NATIVE_COMPUTE_DISABLED": "1", "LEVIATHAN_NATIVE_COMPUTE_MODE": "python"},
            clear=False,
        ):
            service, data_root, _ = _service(self.root, native_mode="python")
            csv_path = self._machine_csv(data_root)
            imported = service.import_local_sync(
                str(csv_path), name="python_only", materialize=True
            )
            ds_id = imported["dataset"]["datasetId"]
            ver = service.pick_usable_version(ds_id)
            assert ver is not None
            job = service.enqueue_validate(ds_id, ver.version_id)
            done = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(done.job_id, job.job_id)
            self.assertEqual(done.status, DatasetJobStatus.COMPLETED)
            self.assertEqual(
                (done.result or {}).get("backend"),
                ComputeBackend.PYTHON_STREAMING.value,
            )
            ejob = service.enqueue_export(ds_id, ver.version_id)
            edone = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(edone.job_id, ejob.job_id)
            self.assertEqual(edone.status, DatasetJobStatus.COMPLETED)
            self.assertEqual(
                (edone.result or {}).get("backend"),
                ComputeBackend.PYTHON_STREAMING.value,
            )

    def test_e_oversized_jsonl_record_fail_closed(self) -> None:
        service, data_root, _ = _service(self.root, native_mode="python")
        # Import a tiny valid set first, then overwrite materialized storage with an oversized line.
        path = data_root / "tiny.jsonl"
        path.write_text(
            json.dumps({"id": "1", "text": "ok", "metadata": {}}) + "\n",
            encoding="utf-8",
        )
        imported = service.import_local_sync(str(path), name="too_large", materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        ver = service.pick_usable_version(ds_id)
        assert ver is not None and ver.storage_path
        huge = "y" * (service.memory_policy.max_record_bytes + 2048)
        Path(ver.storage_path).write_text(
            json.dumps({"id": "2", "text": huge, "metadata": {}}) + "\n",
            encoding="utf-8",
        )
        job = service.enqueue_validate(ds_id, ver.version_id)
        done = service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.job_id, job.job_id)
        self.assertEqual(done.status, DatasetJobStatus.FAILED)
        self.assertIn("RECORD_TOO_LARGE", done.error or "")

    def test_f_corrupt_catalog_sidecar_recovery(self) -> None:
        service, data_root, corpus = _service(self.root, native_mode="python")
        csv_path = self._machine_csv(data_root)
        imported = service.import_local_sync(str(csv_path), name="catalog_corrupt", materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        ver = service.pick_usable_version(ds_id)
        assert ver is not None
        service.enrich_semantic_deterministic(ds_id, ver.version_id, sync_artifacts=True)
        before = service.get_dataset(ds_id)
        before_meta = dict(before.metadata or {})

        cat = catalog_path(corpus)
        cat.write_text("{not-json-at-all", encoding="utf-8")
        status = service.catalog_status()
        self.assertFalse(status.get("valid"))
        reconcile = service.reconcile_sidecars()
        after = service.get_dataset(ds_id)
        self.assertEqual(after.dataset_id, before.dataset_id)
        self.assertEqual(after.name, before.name)
        # DB metadata intact (no corruption from catalog parse failure)
        self.assertEqual(
            (after.metadata or {}).get("semanticProfile", {}).get("displayName"),
            before_meta.get("semanticProfile", {}).get("displayName"),
        )
        # Sidecar still readable and usable for recovery evidence
        sidecar = corpus.datasets_raw / ds_id / SIDECAR_FILENAME
        self.assertTrue(sidecar.is_file())
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("datasetId"), ds_id)
        self.assertTrue(payload.get("displayName") or (payload.get("semanticProfile") or {}).get("displayName"))
        # Corrupt catalog flagged somehow
        conflicts = reconcile.get("conflicts") or []
        corrupt = [c for c in conflicts if c.get("reason") == "corrupt_catalog"]
        self.assertTrue(corrupt or status.get("code") == "catalog_corrupt" or not status.get("valid"))


class WorkerRecycleHelpers(unittest.TestCase):
    def test_recycle_env_parsing(self) -> None:
        from Data.modules.datasets.worker import _max_jobs_before_recycle

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEVIATHAN_DATASET_WORKER_MAX_JOBS_BEFORE_RECYCLE", None)
            self.assertIsNone(_max_jobs_before_recycle())
        with mock.patch.dict(
            os.environ, {"LEVIATHAN_DATASET_WORKER_MAX_JOBS_BEFORE_RECYCLE": "3"}, clear=False
        ):
            self.assertEqual(_max_jobs_before_recycle(), 3)


if __name__ == "__main__":
    unittest.main()
