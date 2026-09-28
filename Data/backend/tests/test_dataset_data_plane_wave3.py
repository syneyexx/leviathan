"""Wave 3 — dataset execution fence, HF boundary, artifacts, workspace scans.

Generic ``file_io`` is not on this tree. Large filesystem work fails closed
in the control plane instead of growing a second filesystem runtime.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from Data.modules.artifacts.store import MAX_INLINE_ARTIFACT_BYTES, ArtifactStore
from Data.modules.coding.workspace import (
    WorkspaceScanExternalRequired,
    list_entries,
    search_files,
)
from Data.modules.datasets.contamination import scan_contamination
from Data.modules.datasets.huggingface import (
    HfDownloadCheckpoint,
    assert_public_hf_url,
    download_hf_file,
)
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.types import CanonicalRecord, DatasetError
from Data.modules.datasets.worker import resolve_runner_mode, should_start_inprocess_runner
from Data.modules.execution.workload import api_may_execute_inline
from Data.modules.workers.pools import pool_for_capability


class DatasetOwnershipTests(unittest.TestCase):
    def test_dataset_process_is_dataset_pool_and_not_inline(self) -> None:
        self.assertEqual(pool_for_capability("dataset.process"), "dataset")
        self.assertEqual(pool_for_capability("dataset.export"), "dataset")
        self.assertNotEqual(pool_for_capability("dataset.process"), "general")
        self.assertFalse(api_may_execute_inline("dataset.process"))
        self.assertEqual(pool_for_capability("provider.hf.list"), "provider_io")

    def test_inprocess_alias_is_test_only(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_DATASET_JOBS_RUNNER": "inprocess"}):
            self.assertEqual(resolve_runner_mode(), "inprocess_test")
            self.assertTrue(should_start_inprocess_runner())
        with mock.patch.dict(os.environ, {"LEVIATHAN_DATASET_JOBS_RUNNER": "external"}):
            self.assertEqual(resolve_runner_mode(), "external")
            self.assertFalse(should_start_inprocess_runner())

    def test_kernel_backed_service_refuses_inline_drain(self) -> None:
        service = DatasetService.__new__(DatasetService)
        service.jobs = object()
        with mock.patch.dict(os.environ, {"LEVIATHAN_DATASET_JOBS_RUNNER": "external"}):
            self.assertTrue(service.production_dataset_inline_forbidden())
            with self.assertRaises(DatasetError) as ctx:
                service.process_jobs()
        self.assertEqual(ctx.exception.code, "DATASET_EXECUTION_UNAVAILABLE")
        self.assertEqual(ctx.exception.http_status, 503)

    def test_hf_list_does_not_call_httpx_from_control_plane(self) -> None:
        service = DatasetService.__new__(DatasetService)
        service.jobs = None
        with mock.patch("Data.modules.datasets.huggingface.list_hf_dataset_files") as listed:
            with self.assertRaises(DatasetError) as ctx:
                service.list_hf_files("org/name")
        listed.assert_not_called()
        self.assertEqual(ctx.exception.http_status, 503)

        service.jobs = object()
        with mock.patch(
            "Data.modules.provider_io.readiness.provider_io_workers_ready",
            return_value=False,
        ):
            with mock.patch("Data.modules.datasets.huggingface.list_hf_dataset_files") as listed:
                with self.assertRaises(DatasetError) as ctx:
                    service.list_hf_files("org/name")
        listed.assert_not_called()
        self.assertEqual(ctx.exception.http_status, 503)


class HuggingFaceBoundaryTests(unittest.TestCase):
    def test_host_policy_rejects_private_and_non_https(self) -> None:
        assert_public_hf_url("https://huggingface.co/datasets/org/name")
        assert_public_hf_url("https://cdn-lfs.huggingface.co/foo")
        with self.assertRaises(DatasetError):
            assert_public_hf_url("http://huggingface.co/datasets/org/name")
        with self.assertRaises(DatasetError):
            assert_public_hf_url("https://127.0.0.1/datasets/org/name")
        with self.assertRaises(DatasetError):
            assert_public_hf_url("https://evil.example/datasets/org/name")

    def test_auth_failure_is_not_retried_and_token_is_redacted(self) -> None:
        secret = "hf_supersecrettokenvalue123456"
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                401,
                content=f"nope token={secret} Authorization: Bearer {secret}".encode(),
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.txt"
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.txt",
                dest_path=dest,
                token=secret,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                checkpoint=HfDownloadCheckpoint(
                    repository_id="org/ds", revision="main", filename="file.txt"
                ),
            )
        self.assertEqual(ctx.exception.code, "hf_auth")
        self.assertEqual(calls["n"], 1)
        self.assertNotIn(secret, str(ctx.exception))
        self.assertNotIn(secret, ctx.exception.message)


class WorkspaceScanTests(unittest.TestCase):
    def test_small_list_inline_and_large_recursive_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "a.txt").write_text("alpha\n", encoding="utf-8")
        entries = list_entries(root, recursive=False, max_entries=20)
        self.assertTrue(any(item["path"].endswith("a.txt") for item in entries))
        with self.assertRaises(WorkspaceScanExternalRequired):
            list_entries(root, recursive=True, max_entries=10_000)

    def test_python_search_streams_and_skips_symlink_escape(self) -> None:
        root = Path(tempfile.mkdtemp())
        inside = root / "notes.txt"
        inside.write_text("needle here\n" + ("x" * 1000) + "\n", encoding="utf-8")
        outside = Path(tempfile.mkdtemp()) / "secret.txt"
        outside.write_text("needle outside\n", encoding="utf-8")
        link = root / "escape.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            link = None

        def _boom(*_a, **_k):
            raise AssertionError("whole-file read_bytes is forbidden")

        with mock.patch("shutil.which", return_value=None):
            with mock.patch.object(Path, "read_bytes", _boom):
                result = search_files(root, "needle", max_hits=10)
        paths = [hit["path"] for hit in result["hits"]]
        self.assertEqual(result["method"], "python")
        self.assertTrue(any(path.endswith("notes.txt") for path in paths))
        self.assertFalse(any("secret" in path or path.endswith("escape.txt") for path in paths))
        self.assertLess(result["bytesScanned"], 8 * 1024 * 1024)


class ArtifactLargeFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ArtifactStore(root / "a.db", root / "artifacts")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_small_bytes_still_work_and_oversize_is_rejected(self) -> None:
        record = self.store.create_from_bytes(
            data=b"hello",
            artifact_type="text",
            producer="test",
            filename="hello.txt",
        )
        self.assertTrue(self.store.verify_hash(record.artifact_id))
        with mock.patch(
            "Data.modules.artifacts.store.MAX_INLINE_ARTIFACT_BYTES",
            4,
        ):
            with self.assertRaises(ValueError):
                self.store.create_from_bytes(
                    data=b"12345",
                    artifact_type="text",
                    producer="test",
                    filename="big.txt",
                )
        self.assertGreater(MAX_INLINE_ARTIFACT_BYTES, 4)

    def test_copy_and_adopt_stream_files(self) -> None:
        root = Path(self.tmp.name)
        source = root / "source.bin"
        payload = b"abc" * 1000
        source.write_bytes(payload)
        copied = self.store.create_from_file(
            source=source,
            artifact_type="bin",
            producer="test",
        )
        self.assertTrue(source.is_file())
        self.assertEqual(Path(copied.path).read_bytes(), payload)
        self.assertEqual(copied.metadata.get("ingest"), "copy")

        staged = root / "staged.bin"
        staged.write_bytes(b"adopt-me")
        adopted = self.store.adopt_staged_file(
            source=staged,
            artifact_type="bin",
            producer="test",
            filename="staged.bin",
        )
        self.assertFalse(staged.exists())
        self.assertEqual(Path(adopted.path).read_bytes(), b"adopt-me")
        self.assertEqual(adopted.metadata.get("ingest"), "adopt")
        with self.assertRaises(ValueError):
            self.store.create_from_file(
                source=source,
                artifact_type="bin",
                producer="test",
                filename="../evil.txt",
            )


class ContaminationTruthTests(unittest.TestCase):
    def test_missing_reference_is_not_clean(self) -> None:
        report = scan_contamination(
            [CanonicalRecord(id="r1", text="hello world")],
            [],
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.evidence_class, "UNMEASURED")
        self.assertEqual(report.public_dict()["evidenceClass"], "UNMEASURED")

    def test_known_overlap_fails(self) -> None:
        report = scan_contamination(
            [CanonicalRecord(id="r1", text="exact sealed prompt")],
            [{"case_id": "c1", "prompt": "exact sealed prompt"}],
        )
        self.assertEqual(report.evidence_class, "EXACT")
        self.assertFalse(report.passed)
        self.assertGreaterEqual(len(report.hits), 1)


if __name__ == "__main__":
    unittest.main()
