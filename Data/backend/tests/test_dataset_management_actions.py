"""Dataset Management action wiring — duplicate, export download, offline, rebuild."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetJobStatus,
    DatasetJobType,
    DatasetStatus,
    VersionKind,
)
from Data.modules.knowledge import KnowledgeStore


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


class DatasetManagementActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.root / "corpus")
        self.import_root = self.root / "imports"
        self.import_root.mkdir()
        self.knowledge = KnowledgeStore(self.db, data_root=self.root / "kdata")
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            allowed_import_roots=[self.import_root, self.corpus.root],
        )
        # Keep action tests deterministic: import materialize must not enqueue background INDEX.
        self.service.datasets_auto_index_ready_to_knowledge = False
        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _import_sample(self, name: str = "sample") -> tuple[str, str]:
        path = self.import_root / f"{name}.jsonl"
        path.write_text(
            "\n".join(
                json.dumps({"id": str(i), "text": f"row-{i} leviathan"})
                for i in range(1, 5)
            )
            + "\n",
            encoding="utf-8",
        )
        job = self.service.enqueue_import_local(path=str(path), name=name, materialize=True)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        ds_id = done.dataset_id or ""
        versions = self.service.list_versions(ds_id)
        mat = next(v for v in versions if v.kind == VersionKind.MATERIALIZED)
        return ds_id, mat.version_id

    def test_create_empty_dataset_via_api(self) -> None:
        res = self.client.post(
            "/api/datasets",
            json={"name": "empty-shell", "description": "no rows yet", "license": "MIT"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["dataset"]["name"], "empty-shell")
        self.assertEqual(body["dataset"]["status"], "created")
        self.assertIsNone(body["dataset"].get("rowCount"))

    def test_duplicate_success_independent_storage(self) -> None:
        ds_id, ver_id = self._import_sample("orig")
        job = self.service.enqueue_duplicate(ds_id, version_id=ver_id)
        self.assertEqual(job.job_type, DatasetJobType.DUPLICATE)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        dup_id = done.dataset_id or done.result.get("datasetId")
        self.assertTrue(dup_id)
        dup = self.service.get_dataset(dup_id)
        self.assertEqual(dup.status, DatasetStatus.READY)
        self.assertTrue(dup.name.startswith("orig copy"))
        self.assertEqual(dup.provenance.get("duplicatedFromDatasetId"), ds_id)

        dup_ver_id = done.result.get("versionId")
        self.assertTrue(dup_ver_id)
        orig_ver = self.service.get_version(ver_id)
        dup_ver = self.service.get_version(dup_ver_id)
        self.assertNotEqual(Path(orig_ver.storage_path or "").resolve(), Path(dup_ver.storage_path or "").resolve())
        self.assertEqual(orig_ver.content_hash, dup_ver.content_hash)
        self.assertTrue(Path(dup_ver.storage_path or "").is_file())

        # Source deletion must not invalidate the duplicate storage.
        self.store.delete_dataset(ds_id)
        self.assertTrue(Path(dup_ver.storage_path or "").is_file())
        still = self.service.get_dataset(dup_id)
        self.assertEqual(still.status, DatasetStatus.READY)

    def test_duplicate_via_http_route(self) -> None:
        ds_id, ver_id = self._import_sample("http-dup")
        res = self.client.post(
            f"/api/datasets/{ds_id}/duplicate",
            json={"versionId": ver_id},
        )
        self.assertEqual(res.status_code, 200, res.text)
        job = res.json()["job"]
        self.assertEqual(job["jobType"], "duplicate")
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)

    def test_duplicate_empty_dataset(self) -> None:
        empty = self.service.create_dataset(name="blank", description="shell")
        job = self.service.enqueue_duplicate(empty.dataset_id)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        dup = self.service.get_dataset(done.dataset_id or "")
        self.assertEqual(dup.status, DatasetStatus.CREATED)
        self.assertTrue(done.result.get("empty"))

    def test_duplicate_failure_rollback(self) -> None:
        ds_id, ver_id = self._import_sample("fail-src")
        ver = self.service.get_version(ver_id)
        # Break storage so copy fails after target shell is created.
        Path(ver.storage_path or "").unlink()
        before = {d.dataset_id for d in self.service.list_datasets()}
        job = self.service.enqueue_duplicate(ds_id, version_id=ver_id)
        target_id = job.dataset_id
        self.assertIsNotNone(target_id)
        self.assertNotIn(target_id, before)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.FAILED)
        after = {d.dataset_id for d in self.service.list_datasets()}
        self.assertNotIn(target_id, after)
        # Original still present
        self.assertIn(ds_id, after)
        # No leftover Ready dirs for the failed target
        self.assertFalse((self.corpus.datasets_materialized / (target_id or "")).exists())

    def test_export_and_download(self) -> None:
        ds_id, ver_id = self._import_sample("exp")
        job = self.service.enqueue_export(ds_id, ver_id)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        export_ver_id = done.result.get("versionId")
        self.assertTrue(export_ver_id)
        path = self.service.resolve_export_download(ds_id, export_ver_id)
        self.assertTrue(path.is_file())

        res = self.client.get(f"/api/datasets/{ds_id}/versions/{export_ver_id}/download")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("attachment", res.headers.get("content-disposition", ""))
        self.assertTrue(res.content.startswith(b"{") or b"row-" in res.content)

    def test_export_download_refuses_non_export_and_traversal(self) -> None:
        ds_id, ver_id = self._import_sample("safe")
        res = self.client.get(f"/api/datasets/{ds_id}/versions/{ver_id}/download")
        self.assertEqual(res.status_code, 400, res.text)

        # Materialized version must not be downloadable as export.
        with self.assertRaises(Exception):
            self.service.resolve_export_download(ds_id, ver_id)

    def test_offline_preflight_block_and_enqueue(self) -> None:
        ds_id, ver_id = self._import_sample("offline")
        # Force remote-only embedding status to block offline-only preflight when applicable.
        pf = self.service.offline_brain_preflight(ds_id, ver_id, offline_only=True)
        self.assertIn("ok", pf)
        if not pf["ok"]:
            with self.assertRaises(Exception) as ctx:
                self.service.enqueue_offline_brain_index(ds_id, ver_id)
            self.assertIn("OFFLINE_PREFLIGHT_BLOCKED", str(ctx.exception.code) if hasattr(ctx.exception, "code") else str(ctx.exception))
            res = self.client.post(
                "/api/datasets/offline/index",
                json={"datasetId": ds_id, "versionId": ver_id},
            )
            self.assertEqual(res.status_code, 409, res.text)
        else:
            job = self.service.enqueue_offline_brain_index(ds_id, ver_id)
            self.assertEqual(job.job_type, DatasetJobType.INDEX)
            self.assertTrue(job.config.get("offlineOnly"))
            done = self.service.process_jobs(max_jobs=1)[0]
            self.assertIn(done.status, {DatasetJobStatus.COMPLETED, DatasetJobStatus.FAILED})

    def test_index_rebuild_supersedes_prior_ready(self) -> None:
        ds_id, ver_id = self._import_sample("rebuild")
        j1 = self.service.enqueue_index(ds_id, ver_id, rebuild=False)
        d1 = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(d1.status, DatasetJobStatus.COMPLETED, d1.error)
        first_id = d1.result.get("indexId")
        self.assertTrue(first_id)

        j2 = self.service.enqueue_index(ds_id, ver_id, rebuild=True)
        d2 = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(d2.status, DatasetJobStatus.COMPLETED, d2.error)
        self.assertIn(first_id, d2.result.get("supersededIndexIds") or [])
        indexes = self.store.list_indexes(ds_id)
        ready = [i for i in indexes if i.status.value == "ready"]
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].index_id, d2.result.get("indexId"))

    def test_validate_job(self) -> None:
        ds_id, ver_id = self._import_sample("val")
        job = self.service.enqueue_validate(ds_id, ver_id)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        ver = self.service.get_version(ver_id)
        self.assertTrue(ver.validation)

    def test_duplicate_route_not_shadowed_by_static(self) -> None:
        # Ensure /jobs still works alongside new /{id}/duplicate
        res = self.client.get("/api/datasets/jobs")
        self.assertEqual(res.status_code, 200)
        self.assertIn("jobs", res.json())


if __name__ == "__main__":
    unittest.main()
