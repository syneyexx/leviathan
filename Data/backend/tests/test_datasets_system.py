"""Datasets subsystem integration tests — real pipeline, no fixtures of fake rows."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from Data.modules.common.corpus import CorpusLayout
from Data.modules.common.paths import PathEscapeError, safe_join
from Data.modules.common.secrets import redact_secrets
from Data.modules.datasets.formats import detect_format
from Data.modules.datasets.huggingface import HfDownloadCheckpoint, download_hf_file
from Data.modules.datasets.importers import reject_traversal_components, resolve_import_path
from Data.modules.datasets.jobs import DatasetJobRunner
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetJobStatus,
    DatasetJobType,
    DatasetStatus,
    DetectedFormat,
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


class FormatDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_detect_jsonl(self) -> None:
        path = self.root / "rows.jsonl"
        path.write_text(
            '{"id":"1","text":"alpha"}\n{"id":"2","text":"beta"}\n',
            encoding="utf-8",
        )
        det = detect_format(path)
        self.assertEqual(det.format, DetectedFormat.JSONL)
        self.assertGreaterEqual(det.confidence, 0.7)

    def test_detect_csv(self) -> None:
        path = self.root / "rows.csv"
        path.write_text("id,text\n1,hello\n2,world\n", encoding="utf-8")
        det = detect_format(path)
        self.assertEqual(det.format, DetectedFormat.CSV)

    def test_detect_tsv(self) -> None:
        path = self.root / "rows.tsv"
        path.write_text("id\ttext\n1\thello\n", encoding="utf-8")
        det = detect_format(path)
        self.assertEqual(det.format, DetectedFormat.TSV)

    def test_detect_md(self) -> None:
        path = self.root / "notes.md"
        path.write_text("# Title\n\n- item one\n- item two\n", encoding="utf-8")
        det = detect_format(path)
        self.assertEqual(det.format, DetectedFormat.MD)


class PathTraversalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "safe.txt").write_text("ok", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reject_parent_segments(self) -> None:
        with self.assertRaises(Exception):
            reject_traversal_components("../etc/passwd")

    def test_safe_join_blocks_escape(self) -> None:
        with self.assertRaises(PathEscapeError):
            safe_join(self.root, "..", "etc", "passwd")

    def test_resolve_import_blocks_outside_root(self) -> None:
        outside = Path(tempfile.mkdtemp()) / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            with self.assertRaises(Exception):
                resolve_import_path(str(outside), allowed_roots=[self.root])
        finally:
            outside.unlink(missing_ok=True)
            outside.parent.rmdir()


class PipelineTests(unittest.TestCase):
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
        self.service.datasets_auto_index_ready_to_knowledge = False

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_jsonl(self, name: str, rows: list[dict]) -> Path:
        path = self.import_root / name
        path.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )
        return path

    def test_full_pipeline_import_dedupe_split_export_index(self) -> None:
        path = self._write_jsonl(
            "sample.jsonl",
            [
                {"id": "a", "text": "Leviathan uses SQLite knowledge retrieval."},
                {"id": "b", "text": "Leviathan uses SQLite knowledge retrieval."},  # exact dup
                {"id": "c", "text": "Dataset materialization writes canonical JSONL."},
                {"id": "d", "text": "Transforms keep lineage for every step."},
            ],
        )
        job = self.service.enqueue_import_local(path=str(path), name="sample", materialize=True)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.job_id, job.job_id)
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED)
        ds = self.service.get_dataset(done.dataset_id or "")
        self.assertEqual(ds.status, DatasetStatus.READY)
        self.assertEqual(ds.row_count, 4)
        self.assertTrue(ds.content_hash)
        self.assertTrue(Path(ds.raw_path or "").is_file())

        versions = self.service.list_versions(ds.dataset_id)
        mat = next(v for v in versions if v.kind == VersionKind.MATERIALIZED)
        self.assertEqual(mat.row_count, 4)
        self.assertTrue(mat.validation.get("valid"))

        # Dedupe
        djob = self.service.enqueue_dedupe(ds.dataset_id, mat.version_id)
        ddone = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(ddone.status, DatasetJobStatus.COMPLETED)
        deduped_id = ddone.result["versionId"]
        deduped = self.service.get_version(deduped_id)
        self.assertEqual(deduped.row_count, 3)

        # Transform
        tjob = self.service.enqueue_transform(
            ds.dataset_id,
            deduped_id,
            [{"name": "strip_whitespace", "params": {"strip": True}}],
        )
        tdone = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(tdone.status, DatasetJobStatus.COMPLETED)
        xform_id = tdone.result["versionId"]
        xform = self.service.get_version(xform_id)
        self.assertTrue(xform.transform_lineage)
        self.assertEqual(xform.transform_lineage[-1]["name"], "strip_whitespace")

        # Split (deterministic)
        s1 = self.service.enqueue_split(ds.dataset_id, xform_id, seed=7)
        self.service.process_jobs(max_jobs=1)
        split_a = self.service.get_version(self.service.get_job(s1.job_id).result["versionId"])
        s2 = self.service.enqueue_split(ds.dataset_id, xform_id, seed=7)
        self.service.process_jobs(max_jobs=1)
        split_b = self.service.get_version(self.service.get_job(s2.job_id).result["versionId"])
        self.assertEqual(split_a.content_hash, split_b.content_hash)
        self.assertEqual(split_a.split.get("seed"), 7)

        # Token stats (estimate labeled when no tiktoken)
        self.service.enqueue_tokenize_stats(ds.dataset_id, split_a.version_id)
        stats_job = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(stats_job.status, DatasetJobStatus.COMPLETED)
        self.assertIn("totalTokens", stats_job.result)
        self.assertIn("method", stats_job.result)

        # Export
        self.service.enqueue_export(ds.dataset_id, split_a.version_id)
        export_job = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(export_job.status, DatasetJobStatus.COMPLETED)
        self.assertTrue(Path(export_job.result["path"]).is_file())

        # Index into knowledge
        self.service.enqueue_index(ds.dataset_id, split_a.version_id)
        index_job = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(index_job.status, DatasetJobStatus.COMPLETED)
        self.assertGreater(index_job.result["chunkCount"], 0)
        self.assertGreater(index_job.result["documentCount"], 0)


class Hf429ResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resumes_after_429(self) -> None:
        payload = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        dest = self.root / "file.txt"
        sleeps: list[float] = []
        state = {"calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            # Second call: honor Range if present
            range_header = request.headers.get("range") or request.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                start = int(range_header.split("=", 1)[1].split("-", 1)[0] or "0")
                body = payload[start:]
                return httpx.Response(
                    206,
                    content=body,
                    headers={
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {start}-{len(payload)-1}/{len(payload)}",
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
                request=request,
            )

        transport = httpx.MockTransport(handler)
        # First attempt gets 429; we also pre-seed a partial to exercise resume path
        partial = dest.with_suffix(dest.suffix + ".partial")
        partial.write_bytes(payload[:10])
        cp = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="file.txt",
            bytes_downloaded=10,
        )
        result = download_hf_file(
            repository_id="org/ds",
            filename="file.txt",
            dest_path=dest,
            checkpoint=cp,
            sleep_fn=lambda s: sleeps.append(s),
            transport=transport,
        )
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), payload)
        self.assertEqual(result.byte_size, len(payload))
        self.assertGreaterEqual(cp.rate_limit_events, 1)
        self.assertTrue(sleeps)  # backoff invoked
        self.assertGreaterEqual(state["calls"], 2)


class CancelInterruptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "db.sqlite"
        self.corpus = _layout(self.root / "corpus")
        self.import_root = self.root / "imports"
        self.import_root.mkdir()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=KnowledgeStore(self.db, data_root=self.root / "k"),
            allowed_import_roots=[self.import_root],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cancel_queued_job(self) -> None:
        path = self.import_root / "a.jsonl"
        path.write_text('{"id":"1","text":"x"}\n', encoding="utf-8")
        job = self.service.enqueue_import_local(path=str(path), name="a")
        cancelled = self.service.cancel_job(job.job_id)
        self.assertEqual(cancelled.status, DatasetJobStatus.CANCELLED)
        processed = self.service.process_jobs(max_jobs=5)
        self.assertEqual(processed, [])

    def test_interrupt_reconcile_dead_pid(self) -> None:
        job = self.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            status=DatasetJobStatus.QUEUED,
        )
        # Force into RUNNING with a dead PID
        self.store.update_job(
            job.job_id,
            status=DatasetJobStatus.RUNNING,
            worker_pid=999999,
            started_at="2020-01-01T00:00:00+00:00",
        )
        with mock.patch(
            "Data.modules.datasets.jobs.pid_is_alive",
            return_value=False,
        ):
            updated = self.service.reconcile()
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0].status, DatasetJobStatus.INTERRUPTED)


class SecretRedactionTests(unittest.TestCase):
    def test_redact_api_key_and_hf_token(self) -> None:
        text = "api_key=sk-abcdefghijklmnopqrstuvwxyz password=hunter2 hf_abcdefghijklmnopqrstuvwxyz"
        redacted = redact_secrets(text)
        self.assertNotIn("hunter2", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_job_public_dict_redacts_token_config(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            store = DatasetStore(root / "db.sqlite")
            store.initialize()
            service = DatasetService(
                store,
                corpus=_layout(root / "corpus"),
                allowed_import_roots=[root],
            )
            job = store.create_job(
                job_type=DatasetJobType.IMPORT_HF,
                config={"repositoryId": "org/ds", "token": "hf_SECRETOKEN1234567890", "filename": "a.jsonl"},
            )
            public = service.public_job(job)
            self.assertEqual(public["config"].get("token"), "[REDACTED]")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
