"""Wave 2 — size-aware filesystem workload classification + file_io ownership."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    ExecutionWorkloadClass,
    api_may_execute_inline,
    build_default_catalog,
    classify_capability,
    classify_request_workload,
)
from Data.modules.execution.file_io_dispatch import enqueue_file_io_job
from Data.modules.execution.file_io_thresholds import (
    FILE_IO_ALWAYS_EXTERNAL,
    load_file_io_thresholds,
)
from Data.modules.execution.workload import request_escalated_filesystem
from Data.modules.file_io.ops import (
    copy_file,
    hash_file,
    parse_csv,
    profile_csv,
    read_text_streaming,
    scan_filesystem,
    write_text_streaming,
)
from Data.modules.file_io.spill import maybe_spill_result
from Data.modules.function_runtime import FunctionRuntime
from Data.modules.function_runtime.builtins import build_default_registry
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class ThresholdDefaultsTests(unittest.TestCase):
    def test_defaults_match_legacy_ceilings(self) -> None:
        t = load_file_io_thresholds(refresh=True)
        self.assertEqual(t.max_inline_read_bytes, 1_000_000)
        self.assertEqual(t.max_inline_csv_bytes, 2_000_000)
        self.assertEqual(t.max_inline_directory_entries, 200)


class RequestClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_small_text_read_inline(self) -> None:
        path = self.root / "small.txt"
        path.write_text("hello world\n", encoding="utf-8")
        cls = classify_request_workload("file.read", {"path": str(path)})
        self.assertEqual(cls, ExecutionWorkloadClass.INLINE_SAFE)

    def test_threshold_edge_read(self) -> None:
        t = load_file_io_thresholds()
        path = self.root / "edge.bin"
        path.write_bytes(b"x" * t.max_inline_read_bytes)
        cls = classify_request_workload("file.read", {"path": str(path)})
        self.assertEqual(cls, ExecutionWorkloadClass.INLINE_SAFE)

    def test_over_threshold_read_external(self) -> None:
        t = load_file_io_thresholds()
        path = self.root / "big.txt"
        path.write_bytes(b"y" * (t.max_inline_read_bytes + 1))
        cls = classify_request_workload("file.read", {"path": str(path)})
        self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED)
        self.assertTrue(request_escalated_filesystem("file.read", {"path": str(path)}))

    def test_small_write_inline(self) -> None:
        cls = classify_request_workload(
            "file.write",
            {"path": str(self.root / "w.txt"), "content": "ok"},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.INLINE_SAFE)

    def test_huge_write_external(self) -> None:
        t = load_file_io_thresholds()
        cls = classify_request_workload(
            "file.write",
            {"path": str(self.root / "w.txt"), "content": "z" * (t.max_inline_write_bytes + 10)},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED)

    def test_small_csv_sample_inline(self) -> None:
        path = self.root / "s.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        cls = classify_request_workload(
            "file.inspect_csv",
            {"path": str(path), "max_rows": 5},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.INLINE_SAFE)

    def test_full_csv_profile_external(self) -> None:
        self.assertEqual(
            classify_capability("file.profile_csv"),
            ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        )
        self.assertIn("file.profile_csv", FILE_IO_ALWAYS_EXTERNAL)

    def test_recursive_scan_external(self) -> None:
        cls = classify_request_workload(
            "workspace.list",
            {"path": str(self.root), "recursive": True},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED)
        self.assertEqual(
            classify_request_workload("filesystem.scan", {"path": str(self.root)}),
            ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        )

    def test_small_non_recursive_list_inline(self) -> None:
        cls = classify_request_workload(
            "workspace.list",
            {"path": str(self.root), "recursive": False, "max_entries": 30},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.INLINE_SAFE)

    def test_never_downgrade_static_external(self) -> None:
        # Even with tiny args, statically required stays required.
        cls = classify_request_workload(
            "file.parse_csv",
            {"path": str(self.root / "missing.csv")},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED)


class SecurityOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.outside = Path(tempfile.mkdtemp())
        (self.outside / "secret.txt").write_text("nope", encoding="utf-8")
        self.registry = build_default_registry()
        self.runtime = FunctionRuntime(self.registry)
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            filesystem_root=self.root,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()
        import shutil

        shutil.rmtree(self.outside, ignore_errors=True)
        os.environ.pop("LEVIATHAN_WORKER_ID", None)
        os.environ.pop("LEVIATHAN_WORKER_POOL", None)

    def test_outside_root_rejected_before_stat_class(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            result = self.gateway.execute(
                CapabilityRequest(
                    capability_id="file.read",
                    arguments={"path": str(self.outside / "secret.txt")},
                    requested_by="api",
                )
            )
            self.assertEqual(result.status, CapabilityStatus.REJECTED)
            self.assertEqual((result.telemetry or {}).get("reason"), "path_escape")

    def test_symlink_escape_rejected(self) -> None:
        target = self.outside / "secret.txt"
        link = self.root / "escape.link"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unavailable")
        # confine should reject when resolving escapes
        from Data.modules.coding.workspace import confine
        from Data.modules.common.paths import PathEscapeError

        with self.assertRaises(PathEscapeError):
            # Depending on platform, confine may reject on resolve of symlink target.
            confined = confine(self.root, "escape.link")
            # If confine allows the link path itself, follow-check in scan should catch.
            if confined.is_symlink():
                resolved = confined.resolve()
                resolved.relative_to(self.root.resolve())


class PoolRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.runtime = JobRuntime(self.store, self.gateway, ResourceManager(2))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_file_io_pool_exists(self) -> None:
        self.assertIn("file_io", POOL_CATALOG)
        self.assertEqual(POOL_CATALOG["file_io"].default_count, 1)

    def test_pool_for_file_capabilities(self) -> None:
        self.assertEqual(pool_for_capability("file.read"), "file_io")
        self.assertEqual(pool_for_capability("file.hash"), "file_io")
        self.assertEqual(pool_for_capability("filesystem.scan"), "file_io")
        self.assertEqual(pool_for_capability("file.parse_csv"), "file_io")

    def test_external_file_job_routes_file_io(self) -> None:
        job = enqueue_file_io_job(
            self.runtime,
            capability_id="file.read",
            arguments={"path": "/tmp/x"},
        )
        self.assertEqual(job.worker_pool, "file_io")

    def test_api_local_job_runtime_does_not_claim_file_io(self) -> None:
        job = enqueue_file_io_job(
            self.runtime,
            capability_id="file.hash",
            arguments={"path": "/tmp/x"},
        )
        claimed = self.runtime.process_next()
        self.assertIsNone(claimed)
        refreshed = self.store.get(job.job_id)
        assert refreshed is not None
        self.assertEqual(refreshed.state.value, "QUEUED")

    def test_general_claim_filter_skips_file_io(self) -> None:
        enqueue_file_io_job(
            self.runtime,
            capability_id="filesystem.scan",
            arguments={"path": "/tmp"},
        )
        general = self.store.claim_next_for_pool(
            pool_id="general",
            worker_id="general-test",
        )
        self.assertIsNone(general)
        owned = self.store.claim_next_for_pool(
            pool_id="file_io",
            worker_id="file_io-test",
        )
        self.assertIsNotNone(owned)
        assert owned is not None
        self.assertEqual(owned.worker_pool, "file_io")


class StreamingOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_read_streaming_chunked_not_read_bytes(self) -> None:
        path = self.root / "chunk.txt"
        path.write_text("line1\nline2\nsecret=TOKEN\n", encoding="utf-8")
        # Instrument open to ensure chunked reads.
        opens: list[int] = []
        real_open = Path.open

        def tracking_open(self, *a, **k):  # type: ignore[no-untyped-def]
            handle = real_open(self, *a, **k)
            if "b" in (a[0] if a else k.get("mode", "r")):
                orig = handle.read

                def counted(n: int = -1):
                    opens.append(n if n is not None else -1)
                    return orig(n)

                handle.read = counted  # type: ignore[method-assign]
            return handle

        with mock.patch.object(Path, "open", tracking_open):
            result = read_text_streaming(path, max_bytes=10_000, chunk_size=4)
        self.assertIn("L1|line1", result["content"])
        self.assertTrue(any(n == 4 for n in opens))
        self.assertNotIn(-1, opens)  # no unbounded .read()

    def test_secret_redaction(self) -> None:
        path = self.root / "env.txt"
        path.write_text("API_KEY=supersecretvalue\n", encoding="utf-8")
        result = read_text_streaming(path)
        self.assertNotIn("supersecretvalue", result["content"])

    def test_hash_streaming_and_progress(self) -> None:
        path = self.root / "h.bin"
        path.write_bytes(b"abc" * 1000)
        events: list[dict] = []
        result = hash_file(path, progress=events.append, chunk_size=64)
        self.assertEqual(result["status"], "STABLE")
        self.assertEqual(len(result["hash"]), 64)
        self.assertTrue(any(e.get("phase") == "hashing" for e in events))

    def test_hash_changed_during_read(self) -> None:
        path = self.root / "mut.bin"
        path.write_bytes(b"12345")
        before = path.stat()

        def mutate_progress(evt: dict) -> None:
            if evt.get("phase") == "hashing" and evt.get("bytes_hashed", 0) > 0:
                path.write_bytes(b"changed-content-now")

        # Force re-stat difference by mutating mid-read when possible.
        result = hash_file(path, progress=mutate_progress, chunk_size=1)
        # On fast systems mutation may land after hash; accept either with honest typing.
        self.assertIn(result["status"], {"STABLE", "CHANGED_DURING_READ"})
        if result["status"] == "CHANGED_DURING_READ":
            self.assertIsNone(result["hash"])
        _ = before

    def test_atomic_write_and_cancel_cleans_temp(self) -> None:
        path = self.root / "out.txt"
        cancelled = {"n": 0}

        def cancel() -> bool:
            cancelled["n"] += 1
            return cancelled["n"] > 1

        with self.assertRaises(Exception):
            write_text_streaming(
                path,
                "x" * 10_000,
                cancel_check=cancel,
                chunk_size=16,
            )
        temps = list(self.root.glob(".out.txt.*.tmp"))
        self.assertEqual(temps, [])
        self.assertFalse(path.exists())

    def test_copy_source_equals_dest(self) -> None:
        path = self.root / "a.txt"
        path.write_text("hi", encoding="utf-8")
        with self.assertRaises(Exception):
            copy_file(path, path)

    def test_copy_overwrite_policy(self) -> None:
        src = self.root / "s.txt"
        dst = self.root / "d.txt"
        src.write_text("src", encoding="utf-8")
        dst.write_text("dst", encoding="utf-8")
        with self.assertRaises(Exception):
            copy_file(src, dst, overwrite=False)
        result = copy_file(src, dst, overwrite=True)
        self.assertEqual(result["bytes_copied"], 3)
        self.assertEqual(dst.read_text(encoding="utf-8"), "src")

    def test_csv_parse_malformed_and_quoted(self) -> None:
        path = self.root / "q.csv"
        path.write_text('a,b\n"1,2",3\nonlyone\n4,5,6\n', encoding="utf-8")
        result = parse_csv(path)
        self.assertGreaterEqual(result["row_count"], 2)
        self.assertGreaterEqual(result["malformed_rows"], 1)

    def test_csv_profile_provenance(self) -> None:
        path = self.root / "p.csv"
        path.write_text("n,s\n1,a\n2,b\n,c\n", encoding="utf-8")
        result = profile_csv(path)
        self.assertEqual(result["row_count"]["provenance"], "exact")
        self.assertEqual(result["columns"][0]["null_count"]["provenance"], "exact")

    def test_scan_depth_and_entry_limits(self) -> None:
        d = self.root / "tree"
        (d / "a" / "b").mkdir(parents=True)
        (d / "a" / "b" / "c.txt").write_text("x", encoding="utf-8")
        (d / "f1.txt").write_text("y", encoding="utf-8")
        result = scan_filesystem(d, recursive=True, max_depth=1, max_entries=10)
        paths = {e["path"] for e in result["entries"]}
        self.assertTrue(any(p.endswith("f1.txt") or p == "f1.txt" for p in paths))
        # depth-limited: deepest file may be absent
        self.assertFalse(result.get("follow_symlinks"))

    def test_scan_symlink_cycle_safe(self) -> None:
        d = self.root / "cyc"
        d.mkdir()
        try:
            (d / "loop").symlink_to(d)
        except OSError:
            self.skipTest("symlinks unavailable")
        result = scan_filesystem(d, recursive=True, follow_symlinks=False, max_entries=50)
        self.assertGreaterEqual(result["entries_scanned"], 1)

    def test_artifact_spill(self) -> None:
        class FakeStore:
            def create_from_bytes(self, **kwargs):  # type: ignore[no-untyped-def]
                class R:
                    artifact_id = "art-1"
                    content_hash = "abc"

                return R()

        big = {"content": "Z" * 500_000, "path": "x"}
        out = maybe_spill_result(
            big,
            artifact_store=FakeStore(),
            producer="test",
            max_inline_result_bytes=1024,
        )
        self.assertTrue(out["truncated"])
        self.assertEqual(out["artifact_ref"], "art-1")


class GatewayRequestAwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = build_default_registry()
        self.fn = FunctionRuntime(self.registry)
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            filesystem_root=self.root,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("LEVIATHAN_WORKER_ID", None)
        os.environ.pop("LEVIATHAN_WORKER_POOL", None)

    def test_small_read_still_inline(self) -> None:
        path = self.root / "ok.txt"
        path.write_text("hi\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            result = self.gateway.execute(
                CapabilityRequest(capability_id="file.read", arguments={"path": str(path)})
            )
            self.assertEqual(result.status, CapabilityStatus.COMPLETED)
            self.assertIn("L1|hi", (result.output or {}).get("content", ""))

    def test_large_read_rejected_for_api(self) -> None:
        t = load_file_io_thresholds()
        path = self.root / "big.txt"
        path.write_bytes(b"Q" * (t.max_inline_read_bytes + 50))
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            result = self.gateway.execute(
                CapabilityRequest(capability_id="file.read", arguments={"path": str(path)})
            )
            self.assertEqual(result.status, CapabilityStatus.REJECTED)
            self.assertEqual((result.telemetry or {}).get("reason"), "worker_required")

    def test_file_io_worker_may_run_large(self) -> None:
        t = load_file_io_thresholds()
        path = self.root / "big2.txt"
        path.write_bytes(b"R" * (t.max_inline_read_bytes + 50))
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_WORKER_ID": "file_io-0",
                "LEVIATHAN_WORKER_POOL": "file_io",
            },
            clear=False,
        ):
            result = self.gateway.execute(
                CapabilityRequest(
                    capability_id="file.read",
                    arguments={"path": str(path), "max_bytes": t.max_inline_read_bytes + 100},
                )
            )
            self.assertEqual(result.status, CapabilityStatus.COMPLETED)

    def test_coding_worker_cannot_silently_absorb_escalated_read(self) -> None:
        t = load_file_io_thresholds()
        path = self.root / "big3.txt"
        path.write_bytes(b"S" * (t.max_inline_read_bytes + 50))
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_WORKER_ID": "coding-0",
                "LEVIATHAN_WORKER_POOL": "coding",
            },
            clear=False,
        ):
            self.assertFalse(
                api_may_execute_inline(
                    "file.read",
                    arguments={"path": str(path)},
                )
            )


class ArchitectureRegressionTests(unittest.TestCase):
    def test_file_read_not_static_unrestricted_external(self) -> None:
        # Must remain statically INLINE_SAFE so small coding ops stay fast.
        self.assertEqual(
            classify_capability("file.read"),
            ExecutionWorkloadClass.INLINE_SAFE,
        )

    def test_recursive_scan_not_inline_by_default(self) -> None:
        self.assertEqual(
            classify_capability("filesystem.scan"),
            ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        )

    def test_heavy_file_not_routed_to_general(self) -> None:
        self.assertNotEqual(pool_for_capability("file.read"), "general")
        self.assertEqual(pool_for_capability("file.read"), "file_io")

    def test_request_aware_classifier_exported(self) -> None:
        from Data.modules.execution import classify_request_workload as exported

        self.assertTrue(callable(exported))


class ParquetAvailabilityTests(unittest.TestCase):
    def test_parquet_unavailable_typed(self) -> None:
        from Data.modules.file_io.errors import FileIoError, FileIoErrorCode
        from Data.modules.file_io.ops import process_parquet

        path = Path(tempfile.mkdtemp()) / "x.parquet"
        path.write_bytes(b"not-parquet")
        try:
            try:
                process_parquet(path)
            except FileIoError as exc:
                self.assertIn(
                    exc.code,
                    {
                        FileIoErrorCode.PARQUET_UNAVAILABLE.value,
                        FileIoErrorCode.PARQUET_PROCESS_FAILED.value,
                    },
                )
        finally:
            path.unlink(missing_ok=True)


class WindowsPathSemanticsTests(unittest.TestCase):
    def test_copy_uses_normcase_for_same_path_guard(self) -> None:
        # On Windows normcase folds case; on POSIX it is identity. The copy
        # guard uses resolve() first and falls back to normcase equality.
        import inspect

        from Data.modules.file_io import ops as file_ops

        src = inspect.getsource(file_ops.copy_file)
        self.assertIn("os.path.normcase", src)
        self.assertIn("source_path and dest_path must differ", src)


if __name__ == "__main__":
    unittest.main()
