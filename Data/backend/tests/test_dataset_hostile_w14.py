"""Wave 14 — Hostile failure-engineering tests for dataset data plane.

Covers filesystem, database/checkpoint, worker cancel/lease, HF network,
and data-corruption failure modes with mocks/sparse fixtures (bounded disk).
"""

from __future__ import annotations

import errno
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from Data.modules.common.corpus import CorpusLayout
from Data.modules.common.retry import RetryPolicy
from Data.modules.datasets.canonicalize import iter_canonical_from_path
from Data.modules.datasets.checkpoint import (
    build_checkpoint,
    can_resume,
    load_checkpoint,
    resolve_resume_skip,
    save_checkpoint,
)
from Data.modules.datasets.dedupe import exact_dedupe
from Data.modules.datasets.formats import detect_format
from Data.modules.datasets.huggingface import (
    HfDownloadCheckpoint,
    download_hf_file,
)
from Data.modules.datasets.indexing import index_records
from Data.modules.datasets.jobs import enqueue_kernel_for_domain_job, kernel_idempotency_key
from Data.modules.datasets.materialize import write_canonical_jsonl_stream
from Data.modules.datasets.publish import publish_atomic
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.shards import (
    ShardIngestCheckpoint,
    build_shard_plan,
    ingest_shards,
)
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    CanonicalRecord,
    DatasetError,
    DatasetJobStatus,
    DatasetJobType,
    DetectedFormat,
)
from Data.modules.datasets.validation import validate_records
from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.leases import make_lease_bound_checks
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider


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


def _settings(root: Path):
    class _RI:
        datasets_auto_index_ready_to_knowledge = False
        dataset_jobs_runner = "external"
        dataset_index_batch_size = 10
        dataset_max_relations_per_doc = 4
        dataset_extract_relations = False

    class _K:
        data_root = str(root / "knowledge")
        embedding_provider = "hash"
        hash_dimensions = 16
        embedding_model = "hash"

    class _S:
        knowledge = _K()
        research_integration = _RI()

    Path(_K.data_root).mkdir(parents=True, exist_ok=True)
    return _S()


def _rec(rid: str, text: str, *, split: str | None = None) -> CanonicalRecord:
    return CanonicalRecord(id=rid, text=text, split=split)


# ---------------------------------------------------------------------------
# Filesystem hostility
# ---------------------------------------------------------------------------


class FilesystemHostileW14Tests(unittest.TestCase):
    def test_source_disappears_mid_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(2):
                p = root / f"src_{i}.bin"
                p.write_bytes(b"payload-" + bytes([i]) * 64)
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            # Delete second source before it is processed.
            sources[1].unlink()
            with self.assertRaises(FileNotFoundError) as ctx:
                ingest_shards(plan, interrupt_after=None)
            self.assertIn("shard source missing", str(ctx.exception))

    def test_output_disappears_after_checkpoint_resume_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(3):
                p = root / f"s{i}.txt"
                p.write_text(f"body-{i}-hostile", encoding="utf-8")
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            ckpt, outs = ingest_shards(plan, interrupt_after=2)
            self.assertEqual(ckpt.status, "interrupted")
            self.assertEqual(len(outs), 2)
            Path(outs[0]["path"]).unlink()
            ckpt2, outs2 = ingest_shards(plan, checkpoint=ckpt)
            self.assertEqual(ckpt2.status, "completed")
            self.assertEqual(len(outs2), 3)
            for entry in outs2:
                self.assertTrue(Path(entry["path"]).is_file())

    def test_corrupt_partial_output_rewinds_and_recompletes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(2):
                p = root / f"s{i}.txt"
                p.write_text(f"shard-{i}-payload", encoding="utf-8")
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            ckpt, outs = ingest_shards(plan, interrupt_after=1)
            Path(outs[0]["path"]).write_bytes(b"CORRUPT-PARTIAL")
            ckpt2, outs2 = ingest_shards(plan, checkpoint=ckpt)
            self.assertEqual(ckpt2.status, "completed")
            from Data.modules.datasets.streaming_io import hash_file_streaming

            for entry in outs2:
                digest, size = hash_file_streaming(entry["path"])
                self.assertEqual(digest, entry["content_hash"])
                self.assertEqual(size, entry["bytes"])

    def test_rename_failure_on_publish_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared = root / ".out.prepared.tmp"
            prepared.write_bytes(b"prepared-bytes")
            dest = root / "out.bin"
            with mock.patch.object(Path, "replace", side_effect=OSError(errno.EACCES, "rename denied")):
                with self.assertRaises(OSError) as ctx:
                    publish_atomic(prepared, dest)
            self.assertEqual(ctx.exception.errno, errno.EACCES)
            self.assertFalse(dest.exists())
            # Prepared temp still present for retry (not silently deleted on rename fail).
            self.assertTrue(prepared.exists())

    def test_hf_partial_rename_failure_surfaces(self) -> None:
        payload = b"rename-fail-payload"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        real_replace = Path.replace

        def boom(self, target):  # noqa: ANN001
            if str(self).endswith(".partial"):
                raise OSError(errno.EBUSY, "Device or resource busy")
            return real_replace(self, target)

        with mock.patch.object(Path, "replace", boom):
            with self.assertRaises(OSError) as ctx:
                download_hf_file(
                    repository_id="org/ds",
                    filename="file.bin",
                    dest_path=dest,
                    expected_size=len(payload),
                    transport=httpx.MockTransport(handler),
                    sleep_fn=lambda _s: None,
                    policy=RetryPolicy(max_attempts=1, base_seconds=0.01, max_seconds=0.05),
                )
        self.assertEqual(ctx.exception.errno, errno.EBUSY)
        self.assertFalse(dest.exists())


# ---------------------------------------------------------------------------
# Database / checkpoint hostility
# ---------------------------------------------------------------------------


class DatabaseHostileW14Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "lev.db"
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.jobs = JobRuntime(
            self.job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        self.corpus = _layout(root / "corpus")
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=None,
            settings=_settings(root),  # type: ignore[arg-type]
            allowed_import_roots=[self.corpus.root],
            job_runtime=self.jobs,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_restart_between_domain_and_kernel_reconciles(self) -> None:
        """Simulate crash after domain QUEUED row exists but before kernel enqueue."""
        orphan = self.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={"w14": "restart"},
        )
        self.assertEqual(orphan.status, DatasetJobStatus.QUEUED)
        self.assertIsNone(
            self.job_store.get_by_idempotency_key(kernel_idempotency_key(orphan.job_id))
        )
        # "Restart" = new service process using same DB; reconcile relinks kernel.
        recovered = self.service.reconcile_orphan_queued_jobs()
        self.assertTrue(recovered)
        kernel = self.job_store.get_by_idempotency_key(
            kernel_idempotency_key(orphan.job_id)
        )
        self.assertIsNotNone(kernel)
        assert kernel is not None
        self.assertEqual(kernel.state, JobState.QUEUED)
        # Second reconcile is idempotent — no duplicate kernel.
        again = enqueue_kernel_for_domain_job(self.jobs, orphan, raise_on_error=True)
        assert again is not None
        self.assertEqual(again.job_id, kernel.job_id)

    def test_stale_streaming_checkpoint_refuses_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ckpt = build_checkpoint(
                input_hash="aaa",
                operation="materialize",
                options={"mode": "v1"},
                records_processed=10,
                phase="streaming",
            )
            save_checkpoint(root, ckpt)
            loaded = load_checkpoint(root)
            self.assertIsNotNone(loaded)
            # Different fingerprint / input → cannot resume (would duplicate/skip).
            self.assertFalse(
                can_resume(loaded, fingerprint="wrong-fp", input_hash="aaa")
            )
            skip, resumed = resolve_resume_skip(
                loaded, fingerprint="wrong-fp", input_hash="aaa"
            )
            self.assertEqual(skip, 0)
            self.assertFalse(resumed)
            # Matching fingerprint + different input hash also refuses.
            self.assertFalse(
                can_resume(
                    loaded,
                    fingerprint=ckpt.fingerprint,
                    input_hash="CHANGED",
                )
            )


# ---------------------------------------------------------------------------
# Workers: cancel + lease loss
# ---------------------------------------------------------------------------


class WorkerHostileW14Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.db = self.root / "leviathan.db"
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=16),
        )
        self.knowledge.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cancel_during_index(self) -> None:
        records = [_rec(str(i), f"index cancel signal {i} alpha") for i in range(20)]
        hits = {"n": 0}

        def cancel_cb() -> bool:
            hits["n"] += 1
            return hits["n"] >= 3

        with self.assertRaises(DatasetError) as ctx:
            index_records(
                self.knowledge,
                records,
                dataset_id="ds-w14-cancel",
                version_id="ver-1",
                cancel_cb=cancel_cb,
                extract_relations=False,
                write_batch_size=2,
            )
        self.assertEqual(ctx.exception.code, "cancelled")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_lease_loss_cancel_check_stops_work(self) -> None:
        """Existing JobRuntime lease harness: owner mismatch → cancel_check True."""
        job_store = JobStore(self.root / "jobs.db")
        job_store.initialize()
        runtime = JobRuntime(
            job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
        )
        job = runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        claimed = job_store.claim_next_queued(worker_id="worker-a", lease_ttl_seconds=30.0)
        self.assertIsNotNone(claimed)
        # Steal lease to simulate loss.
        from datetime import datetime, timedelta, timezone

        future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(
            timespec="seconds"
        )
        with job_store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
                ("worker-b", future, job.job_id),
            )
        cancel_check, _heartbeat = make_lease_bound_checks(
            {},
            job_store,
            job.job_id,
            worker_id="worker-a",
            ttl_seconds=30.0,
        )
        self.assertTrue(cancel_check())


# ---------------------------------------------------------------------------
# Network (HF) — extend W9 gaps (exhaustion paths)
# ---------------------------------------------------------------------------


class NetworkHostileW14Tests(unittest.TestCase):
    def test_429_exhausts_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                policy=RetryPolicy(max_attempts=3, base_seconds=0.01, max_seconds=0.05),
            )
        self.assertIn(
            ctx.exception.code,
            {"hf_rate_limited", "hf_download_failed", "hf_http_error"},
        )
        self.assertFalse(dest.exists())

    def test_500_exhausts_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                policy=RetryPolicy(max_attempts=3, base_seconds=0.01, max_seconds=0.05),
            )
        self.assertEqual(ctx.exception.code, "hf_server_error")
        self.assertEqual(ctx.exception.http_status, 502)
        self.assertFalse(dest.exists())

    def test_invalid_range_and_changed_etag_covered(self) -> None:
        """Regression glue: invalid Content-Range + ETag change remain fail-closed."""
        # Invalid Range
        payload = b"hello-world-payload"
        dest = Path(tempfile.mkdtemp()) / "file.bin"
        Path(str(dest) + ".partial").write_bytes(payload[:5])
        cp = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="file.bin",
            bytes_downloaded=5,
        )

        def bad_range(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                206,
                content=payload[5:],
                headers={
                    "Content-Length": str(len(payload) - 5),
                    "Content-Range": "bytes junk",
                },
                request=request,
            )

        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                checkpoint=cp,
                transport=httpx.MockTransport(bad_range),
                sleep_fn=lambda _s: None,
                policy=RetryPolicy(max_attempts=2, base_seconds=0.01, max_seconds=0.05),
            )
        self.assertEqual(ctx.exception.code, "hf_invalid_content_range")

        # Changed ETag → restart then complete
        full = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 20
        dest2 = Path(tempfile.mkdtemp()) / "etag.bin"
        Path(str(dest2) + ".partial").write_bytes(full[:40])
        cp2 = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="etag.bin",
            bytes_downloaded=40,
            etag='"old"',
        )
        state = {"n": 0}
        phases: list[str] = []

        def etag_handler(request: httpx.Request) -> httpx.Response:
            state["n"] += 1
            range_header = request.headers.get("range") or ""
            if state["n"] == 1 and range_header:
                start = int(range_header.split("=", 1)[1].split("-", 1)[0])
                body = full[start:]
                return httpx.Response(
                    206,
                    content=body,
                    headers={
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {start}-{len(full) - 1}/{len(full)}",
                        "ETag": '"new"',
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                content=full,
                headers={"Content-Length": str(len(full)), "ETag": '"new"'},
                request=request,
            )

        result = download_hf_file(
            repository_id="org/ds",
            filename="etag.bin",
            dest_path=dest2,
            checkpoint=cp2,
            expected_size=len(full),
            transport=httpx.MockTransport(etag_handler),
            sleep_fn=lambda _s: None,
            progress_cb=lambda info: phases.append(str(info.get("phase"))),
            policy=RetryPolicy(max_attempts=4, base_seconds=0.01, max_seconds=0.05),
        )
        self.assertEqual(dest2.read_bytes(), full)
        self.assertTrue(result.checkpoint.completed)
        self.assertIn("etag_mismatch", phases)


# ---------------------------------------------------------------------------
# Data hostility
# ---------------------------------------------------------------------------


class DataHostileW14Tests(unittest.TestCase):
    def test_duplicate_ids_still_fail_closed(self) -> None:
        # Covered primarily by W4; assert contract still holds under hostile framing.
        report = validate_records(
            [_rec("dup", "a"), _rec("dup", "b-different")]
        )
        self.assertFalse(report["valid"])
        self.assertGreaterEqual(report["duplicateIdConflictCount"], 1)

    def test_malformed_json_after_streamed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.jsonl"
            path.write_text(
                json.dumps({"id": "1", "text": "ok"})
                + "\n"
                + json.dumps({"id": "2", "text": "also-ok"})
                + "\n"
                + "{not-valid-json\n"
                + json.dumps({"id": "4", "text": "never-reached"})
                + "\n",
                encoding="utf-8",
            )
            collected: list[CanonicalRecord] = []
            with self.assertRaises(DatasetError) as ctx:
                for rec in iter_canonical_from_path(path, fmt=DetectedFormat.JSONL):
                    collected.append(rec)
            self.assertEqual(ctx.exception.code, "invalid_jsonl")
            # First two streamed successfully before fail-closed.
            self.assertEqual([r.id for r in collected], ["1", "2"])

    def test_invalid_utf8_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_utf8.jsonl"
            # Valid JSONL line then a line with invalid UTF-8 bytes (decoded via replace).
            good = json.dumps({"id": "1", "text": "ascii-ok"}, ensure_ascii=False).encode(
                "utf-8"
            )
            # Construct invalid UTF-8: start of multi-byte then truncate.
            bad_line = b'{"id":"2","text":"bad\xff\xfebytes"}\n'
            path.write_bytes(good + b"\n" + bad_line)
            det = detect_format(path)
            # Detection must not crash; replacement path is used.
            self.assertIn(det.format, {DetectedFormat.JSONL, DetectedFormat.UNKNOWN})
            records = list(iter_canonical_from_path(path, fmt=DetectedFormat.JSONL))
            self.assertGreaterEqual(len(records), 1)
            # Invalid bytes become U+FFFD replacement — visible, not silent drop of the row.
            joined = " ".join(r.text for r in records)
            self.assertTrue("\ufffd" in joined or any(r.id == "2" for r in records))

    def test_empty_dataset_materialize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "empty.jsonl"
            outcome = write_canonical_jsonl_stream([], dest)
            self.assertEqual(outcome["rowCount"], 0)
            self.assertEqual(outcome["validation"]["rowCount"], 0)
            self.assertTrue(outcome["validation"]["valid"])
            self.assertTrue(dest.exists())
            self.assertEqual(dest.read_text(encoding="utf-8"), "")
            # Empty source file detection is honest.
            empty_src = Path(tmp) / "empty_src.jsonl"
            empty_src.write_bytes(b"")
            det = detect_format(empty_src)
            self.assertEqual(det.details.get("reason"), "empty_file")

    def test_cross_split_duplicate_content(self) -> None:
        records = [
            _rec("train-1", "shared-leak-body", split="train"),
            _rec("test-1", "shared-leak-body", split="test"),
        ]
        kept, stats = exact_dedupe(records)
        self.assertEqual(len(kept), 1)
        self.assertEqual(stats["crossSplitDuplicateCount"], 1)
        self.assertTrue(kept[0].metadata.get("crossSplitDedupe"))
        self.assertTrue(kept[0].metadata["lineage"][0]["crossSplit"])


if __name__ == "__main__":
    unittest.main()
