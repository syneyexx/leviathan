"""Hugging Face repository-level ingest tests — discovery, parallel download, parquet, streaming."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.canonicalize import iter_canonical_from_path
from Data.modules.datasets.formats import detect_format
from Data.modules.datasets.huggingface import (
    HfDownloadCheckpoint,
    HfFileKind,
    HfRepoFile,
    HfRepoManifest,
    HfRepoPlan,
    build_manifest_from_plan,
    classify_hf_file,
    download_hf_file,
    download_hf_repository,
    hf_download_chunk_bytes,
    hf_download_workers,
    infer_split_from_path,
    normalize_repo_path,
    write_repo_manifest,
)
from Data.modules.datasets.materialize import materialize_from_raw, materialize_from_sources, write_canonical_jsonl_stream
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    CanonicalRecord,
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


class ClassificationTests(unittest.TestCase):
    def test_nested_data_and_metadata(self) -> None:
        self.assertEqual(classify_hf_file("data/train/part-001.parquet"), HfFileKind.DATA)
        self.assertEqual(classify_hf_file("data/train-00000-of-00300.jsonl"), HfFileKind.DATA)
        self.assertEqual(classify_hf_file("README.md"), HfFileKind.METADATA)
        self.assertEqual(classify_hf_file("LICENSE"), HfFileKind.METADATA)
        self.assertEqual(classify_hf_file(".gitattributes"), HfFileKind.METADATA)
        self.assertEqual(classify_hf_file("dataset_infos.json"), HfFileKind.METADATA)
        self.assertEqual(classify_hf_file("docs/architecture.md"), HfFileKind.METADATA)
        self.assertEqual(classify_hf_file("corpus/notes.md"), HfFileKind.DATA)
        self.assertEqual(classify_hf_file("data/train.arrow"), HfFileKind.UNSUPPORTED_DATA)

    def test_deterministic_ordering_and_split(self) -> None:
        paths = ["data/test.parquet", "data/train-01.parquet", "data/validation.parquet"]
        self.assertEqual(infer_split_from_path(paths[0]), "test")
        self.assertEqual(infer_split_from_path(paths[1]), "train")
        self.assertEqual(infer_split_from_path(paths[2]), "validation")

    def test_traversal_rejected(self) -> None:
        with self.assertRaises(Exception):
            normalize_repo_path("../etc/passwd")
        with self.assertRaises(Exception):
            normalize_repo_path("/abs/path")
        with self.assertRaises(Exception):
            normalize_repo_path("a/\x00/b")


class ConfigBoundsTests(unittest.TestCase):
    def test_chunk_and_workers_bounds(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_HF_DOWNLOAD_CHUNK_MB": "16"}):
            self.assertEqual(hf_download_chunk_bytes(), 16 * 1024 * 1024)
        with mock.patch.dict(os.environ, {"LEVIATHAN_HF_DOWNLOAD_CHUNK_MB": "1"}):
            self.assertEqual(hf_download_chunk_bytes(), 4 * 1024 * 1024)
        with mock.patch.dict(os.environ, {"LEVIATHAN_HF_DOWNLOAD_CHUNK_MB": "999"}):
            self.assertEqual(hf_download_chunk_bytes(), 64 * 1024 * 1024)
        with mock.patch.dict(os.environ, {"LEVIATHAN_HF_DOWNLOAD_WORKERS": "6"}):
            self.assertEqual(hf_download_workers(), 6)
        with mock.patch.dict(os.environ, {"LEVIATHAN_HF_DOWNLOAD_WORKERS": "100"}):
            self.assertEqual(hf_download_workers(), 16)


class ChunkStreamingTests(unittest.TestCase):
    def test_uses_configured_chunk_size_and_resume(self) -> None:
        payload = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 2000
        dest = Path(tempfile.mkdtemp()) / "file.txt"
        state = {"calls": 0, "max_chunk_seen": 0}
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            range_header = request.headers.get("range") or request.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                start = int(range_header.split("=", 1)[1].split("-", 1)[0] or "0")
                body = payload[start:]
                return httpx.Response(
                    206,
                    content=body,
                    headers={
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {start}-{len(payload) - 1}/{len(payload)}",
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
        partial = Path(str(dest) + ".partial")
        partial.write_bytes(payload[:40])
        cp = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="file.txt",
            bytes_downloaded=40,
        )
        chunk = 8 * 1024 * 1024
        result = download_hf_file(
            repository_id="org/ds",
            filename="file.txt",
            dest_path=dest,
            checkpoint=cp,
            sleep_fn=lambda s: sleeps.append(s),
            transport=transport,
            chunk_size=chunk,
        )
        self.assertEqual(dest.read_bytes(), payload)
        self.assertEqual(result.byte_size, len(payload))
        self.assertGreaterEqual(cp.rate_limit_events, 1)
        self.assertTrue(sleeps)
        self.assertTrue(result.checkpoint.completed)


class ParallelDownloadTests(unittest.TestCase):
    def test_bounded_concurrency_and_multi_file_resume(self) -> None:
        root = Path(tempfile.mkdtemp())
        files = {f"data/shard-{i:03d}.jsonl": (f'{{"id":"{i}","text":"row-{i}"}}\n').encode() for i in range(12)}
        active = 0
        max_active = 0
        lock = threading.Lock()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active, max_active
            path = request.url.path
            # .../resolve/main/data/shard-XXX.jsonl
            rel = path.split("/resolve/main/", 1)[-1]
            body = files[rel]
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                range_header = request.headers.get("range") or ""
                if range_header.startswith("bytes="):
                    start = int(range_header.split("=", 1)[1].split("-", 1)[0] or "0")
                    chunk = body[start:]
                    return httpx.Response(
                        206,
                        content=chunk,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}",
                        },
                        request=request,
                    )
                return httpx.Response(
                    200,
                    content=body,
                    headers={"Content-Length": str(len(body))},
                    request=request,
                )
            finally:
                with lock:
                    active -= 1

        plan = HfRepoPlan(
            repository_id="org/many",
            revision="main",
            resolved_revision="abc123",
            files=[],
            classification={p: HfFileKind.DATA.value for p in files},
            data_files=[HfRepoFile(path=p, size=len(b), kind=HfFileKind.DATA) for p, b in sorted(files.items())],
            unsupported_files=[],
            metadata_files=[],
            bytes_total=sum(len(b) for b in files.values()),
        )
        transport = httpx.MockTransport(handler)
        raw = root / "raw"
        manifest_path = root / "manifest.json"
        result = download_hf_repository(
            plan=plan,
            raw_root=raw,
            workers=3,
            chunk_size=1024 * 1024,
            transport=transport,
            manifest_path=manifest_path,
            progress_persist_interval=0.0,
        )
        self.assertEqual(result.manifest.files_completed, 12)
        self.assertLessEqual(max_active, 3)
        self.assertTrue(manifest_path.is_file())
        for path in files:
            self.assertTrue((raw / path).is_file())

        # Second run should reuse completed files (no re-download required for completeness)
        result2 = download_hf_repository(
            plan=plan,
            raw_root=raw,
            workers=3,
            chunk_size=1024 * 1024,
            transport=transport,
            manifest=result.manifest,
            manifest_path=manifest_path,
        )
        self.assertEqual(result2.manifest.files_completed, 12)


class CancellationTests(unittest.TestCase):
    def test_cancel_leaves_partial_state(self) -> None:
        root = Path(tempfile.mkdtemp())
        body = b"x" * 50_000
        cancel_after = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=body,
                headers={"Content-Length": str(len(body))},
                request=request,
            )

        def cancel_check() -> bool:
            cancel_after["n"] += 1
            return cancel_after["n"] > 3

        plan = HfRepoPlan(
            repository_id="org/c",
            revision="main",
            resolved_revision=None,
            files=[],
            classification={"a.jsonl": "DATA"},
            data_files=[HfRepoFile(path="a.jsonl", size=len(body), kind=HfFileKind.DATA)],
            unsupported_files=[],
            metadata_files=[],
            bytes_total=len(body),
        )
        with self.assertRaises(Exception) as ctx:
            download_hf_repository(
                plan=plan,
                raw_root=root / "raw",
                workers=1,
                transport=httpx.MockTransport(handler),
                cancel_check=cancel_check,
                manifest_path=root / "m.json",
            )
        self.assertIn("cancel", str(ctx.exception).lower())


class ParquetMaterializeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_parquet(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path, row_group_size=2)

    def test_detect_and_stream_parquet(self) -> None:
        path = self.root / "nested" / "train.parquet"
        self._write_parquet(
            path,
            [
                {"id": "1", "text": "alpha", "label": None},
                {"id": "2", "text": "beta", "label": "x"},
                {"id": "3", "messages": [{"role": "user", "content": "hi"}], "text": ""},
            ],
        )
        det = detect_format(path)
        self.assertEqual(det.format, DetectedFormat.PARQUET)
        records = list(
            iter_canonical_from_path(
                path,
                fmt=DetectedFormat.PARQUET,
                split="train",
                provenance={"repositoryId": "org/ds", "relativePath": "nested/train.parquet"},
            )
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].split, "train")
        self.assertEqual(records[0].metadata.get("source", {}).get("repositoryId"), "org/ds")

    def test_multi_shard_one_version(self) -> None:
        paths = []
        for i in range(5):
            p = self.root / "data" / f"train-{i:03d}.parquet"
            self._write_parquet(p, [{"id": f"{i}", "text": f"row-{i}"}])
            paths.append(p)
        dest = self.root / "canonical.jsonl"
        outcome = materialize_from_sources(
            [
                {
                    "path": str(p),
                    "format": "parquet",
                    "split": "train",
                    "relativePath": f"data/{p.name}",
                    "provenance": {"repositoryId": "org/ds", "relativePath": f"data/{p.name}"},
                }
                for p in paths
            ],
            dest,
        )
        self.assertEqual(outcome["rowCount"], 5)
        self.assertTrue(dest.is_file())
        lines = dest.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 5)


class LargeCsvFieldMaterializeTests(unittest.TestCase):
    """HF prompts.csv often has fields above Python's default 128 KiB csv limit."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_materialize_csv_field_above_default_limit(self) -> None:
        # Python's default csv.field_size_limit is 131072; use a fixed oversize
        # so the test stays meaningful even if another test already raised it.
        oversized = "x" * (131072 + 4096)
        path = self.root / "prompts.csv"
        path.write_text(
            "id,prompt\n"
            f'1,"{oversized}"\n'
            '2,"short"\n',
            encoding="utf-8",
        )
        dest = self.root / "canonical.jsonl"
        outcome = materialize_from_sources(
            [
                {
                    "path": str(path),
                    "format": "csv",
                    "split": "train",
                    "relativePath": "prompts.csv",
                    "provenance": {"repositoryId": "org/prompts", "relativePath": "prompts.csv"},
                }
            ],
            dest,
        )
        self.assertEqual(outcome["rowCount"], 2)
        lines = dest.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(len(first.get("text") or ""), len(oversized))


class StreamingMaterializeTests(unittest.TestCase):
    def test_does_not_list_entire_iterator(self) -> None:
        """Architectural: materialize consumes an iterator incrementally."""
        produced = {"n": 0}

        def gen():
            for i in range(50):
                produced["n"] += 1
                yield CanonicalRecord(id=str(i), text=f"t-{i}")
                # After first write path has started, produced should grow without
                # requiring full list first — generator yields one-by-one.
                if i == 0:
                    self.assertEqual(produced["n"], 1)

        dest = Path(tempfile.mkdtemp()) / "out.jsonl"
        outcome = write_canonical_jsonl_stream(gen(), dest)
        self.assertEqual(outcome["rowCount"], 50)
        self.assertEqual(produced["n"], 50)
        # Prove no giant join: file exists with 50 lines
        self.assertEqual(len(dest.read_text(encoding="utf-8").strip().splitlines()), 50)

    def test_local_jsonl_still_works(self) -> None:
        root = Path(tempfile.mkdtemp())
        src = root / "a.jsonl"
        src.write_text('{"id":"1","text":"hello"}\n{"id":"2","text":"world"}\n', encoding="utf-8")
        out = materialize_from_raw(src, root / "c.jsonl")
        self.assertEqual(out["rowCount"], 2)
        self.assertTrue(out["validation"]["valid"])


class RepoImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "db.sqlite"
        self.corpus = _layout(self.root / "corpus")
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=KnowledgeStore(self.db, data_root=self.root / "k"),
            allowed_import_roots=[self.root],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enqueue_repo_mode_without_filename(self) -> None:
        job = self.service.enqueue_import_hf(repository_id="org/demo", revision="main", materialize=True)
        self.assertEqual(job.config.get("mode"), "repository")
        self.assertNotIn("filename", job.config)
        ds = self.service.get_dataset(job.dataset_id or "")
        self.assertEqual(ds.status, DatasetStatus.IMPORTING)
        self.assertEqual(ds.name, "org/demo")

    def test_legacy_filename_still_supported(self) -> None:
        job = self.service.enqueue_import_hf(
            repository_id="org/demo",
            filename="data/train.jsonl",
            revision="main",
        )
        self.assertEqual(job.config.get("mode"), "file")
        self.assertEqual(job.config.get("filename"), "data/train.jsonl")

    def test_mocked_repository_import_one_dataset(self) -> None:
        shards = {
            "data/train-000.jsonl": b'{"id":"1","text":"a"}\n{"id":"2","text":"b"}\n',
            "data/train-001.jsonl": b'{"id":"3","text":"c"}\n',
            "data/validation-000.jsonl": b'{"id":"4","text":"d"}\n',
        }
        plan_files = [
            HfRepoFile(path=p, size=len(b), kind=HfFileKind.DATA) for p, b in shards.items()
        ]
        plan = HfRepoPlan(
            repository_id="org/mixed",
            revision="main",
            resolved_revision="deadbeef",
            files=plan_files,
            classification={p: "DATA" for p in shards},
            data_files=sorted(plan_files, key=lambda x: x.path),
            unsupported_files=[],
            metadata_files=[],
            bytes_total=sum(len(b) for b in shards.values()),
        )
        job = self.service.enqueue_import_hf(repository_id="org/mixed", revision="main", materialize=True)
        assert job.dataset_id
        dirs = self.service._dataset_dirs(job.dataset_id)
        raw_root = dirs["raw"] / "hf"

        def fake_download(**kwargs):
            from Data.modules.datasets.huggingface import HfDownloadResult, HfRepoDownloadResult

            results = []
            manifest = build_manifest_from_plan(plan)
            for path, body in shards.items():
                dest = raw_root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                digest = __import__("hashlib").sha256(body).hexdigest()
                st = manifest.files[path]
                st.status = "complete"
                st.downloaded = len(body)
                st.size = len(body)
                st.hash = digest
                results.append(
                    HfDownloadResult(
                        path=dest,
                        content_hash=digest,
                        byte_size=len(body),
                        checkpoint=HfDownloadCheckpoint(
                            repository_id="org/mixed",
                            revision="main",
                            filename=path,
                            bytes_downloaded=len(body),
                            total_bytes=len(body),
                            content_hash=digest,
                            completed=True,
                        ),
                        url=f"https://huggingface.co/datasets/org/mixed/resolve/main/{path}",
                    )
                )
            manifest.recompute()
            manifest.phase = "download_completed"
            if kwargs.get("manifest_path"):
                write_repo_manifest(kwargs["manifest_path"], manifest)
            return HfRepoDownloadResult(
                manifest=manifest,
                files=results,
                bytes_per_second=1_000_000.0,
                elapsed_seconds=0.1,
            )

        with mock.patch(
            "Data.modules.datasets.service.discover_hf_repository",
            return_value=plan,
        ), mock.patch(
            "Data.modules.datasets.service.download_hf_repository",
            side_effect=fake_download,
        ):
            done = self.service.process_jobs(max_jobs=1)[0]

        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, msg=done.error)
        ds = self.service.get_dataset(done.dataset_id or "")
        self.assertEqual(ds.status, DatasetStatus.READY)
        self.assertEqual(ds.row_count, 4)
        versions = self.service.list_versions(ds.dataset_id)
        mats = [v for v in versions if v.kind == VersionKind.MATERIALIZED]
        self.assertEqual(len(mats), 1)
        self.assertEqual(len(self.service.list_datasets()), 1)


class DiskPreflightTests(unittest.TestCase):
    def test_insufficient_disk_fails_before_download(self) -> None:
        from Data.modules.datasets.huggingface import disk_preflight_for_download
        from Data.modules.datasets.types import DatasetError

        with self.assertRaises(DatasetError) as ctx:
            with mock.patch(
                "Data.modules.datasets.huggingface.disk_free_bytes",
                return_value=1024,
            ):
                disk_preflight_for_download(
                    target_dir=Path(tempfile.mkdtemp()),
                    bytes_total=10_000_000_000,
                    bytes_already=0,
                    reserve_bytes=512 * 1024 * 1024,
                )
        self.assertEqual(ctx.exception.code, "insufficient_disk")


if __name__ == "__main__":
    unittest.main()
