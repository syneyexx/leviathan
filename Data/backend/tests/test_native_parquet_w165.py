"""W165 — native Parquet/Arrow data plane ops (parquet_validate parity)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.datasets.compute_planner import ComputeBackend, ComputeBackendPlanner
from Data.modules.datasets.memory_policy import DatasetMemoryPolicy
from Data.modules.workers.native_compute import (
    PARQUET_OPERATIONS,
    SUPPORTED_OPERATIONS,
    NativeCapabilities,
    NativeStatus,
    build_task_document,
    resolve_native_binary,
    run_native_task,
)


def _maybe_build_binary() -> Path | None:
    existing = resolve_native_binary()
    if existing is not None:
        return existing
    script = Path(__file__).resolve().parents[3] / "scripts" / "build_native_data_plane.py"
    if not script.is_file():
        return None
    cargo = subprocess.run(["cargo", "--version"], capture_output=True, check=False)
    if cargo.returncode != 0:
        return None
    proc = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    if proc.returncode != 0:
        proc2 = subprocess.run(
            [os.environ.get("PYTHON", "python3"), str(script), "--unlocked"],
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        if proc2.returncode != 0:
            return None
    return resolve_native_binary()


BINARY = _maybe_build_binary()


def _skip_without_binary() -> None:
    if BINARY is None:
        raise unittest.SkipTest(
            "leviathan-data-plane binary missing (cargo build unavailable) — "
            "skipping parquet_validate parity honestly"
        )


def _write_tiny_parquet(path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"id": ["r1", "r2"], "text": ["hello", "world"]})
    pq.write_table(table, path)


class TestParquetOpsAllowlist(unittest.TestCase):
    def test_ops_registered(self) -> None:
        for op in (
            "dataset.parquet_validate",
            "dataset.parquet_hash",
            "dataset.parquet_to_jsonl",
        ):
            self.assertIn(op, SUPPORTED_OPERATIONS)
            self.assertIn(op, PARQUET_OPERATIONS)


class TestParquetPlannerPreference(unittest.TestCase):
    def test_large_parquet_prefers_rust(self) -> None:
        policy = DatasetMemoryPolicy(native_mode="auto", rust_threshold_bytes=1000)
        caps = NativeCapabilities(
            status=NativeStatus.AVAILABLE,
            protocol_version=1,
            operations=list(PARQUET_OPERATIONS),
        )
        planner = ComputeBackendPlanner(policy=policy, capabilities=caps)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.parquet"
            path.write_bytes(b"x" * 5000)
            plan = planner.plan(
                "dataset.parquet_validate",
                input_path=path,
                input_bytes=5000,
            )
        self.assertEqual(plan.backend, ComputeBackend.RUST_NATIVE)
        self.assertIn("parquet", plan.detail.lower())

    def test_small_parquet_path_still_prefers_rust(self) -> None:
        """Even below threshold, a .parquet path prefers native for parquet_* ops."""
        policy = DatasetMemoryPolicy(native_mode="auto", rust_threshold_bytes=10_000_000)
        caps = NativeCapabilities(
            status=NativeStatus.AVAILABLE,
            protocol_version=1,
            operations=list(PARQUET_OPERATIONS),
        )
        planner = ComputeBackendPlanner(policy=policy, capabilities=caps)
        plan = planner.plan(
            "dataset.parquet_validate",
            input_path="/tmp/sample.parquet",
            input_bytes=100,
        )
        self.assertEqual(plan.backend, ComputeBackend.RUST_NATIVE)


class TestParquetValidateParity(unittest.TestCase):
    def test_parquet_validate_when_binary_available(self) -> None:
        _skip_without_binary()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "tiny.parquet"
            _write_tiny_parquet(inp)
            out = root / "validate.json"
            task = build_task_document(
                task_id="pq-val-1",
                operation="dataset.parquet_validate",
                input_path=inp,
                temporary_path=out,
                allowed_roots=[str(root)],
                input_format="parquet",
            )
            result = run_native_task(task, binary=BINARY, work_dir=root / "work")
            self.assertTrue(result.ok, result.error_message or result.stderr)
            assert result.receipt is not None
            self.assertEqual(result.receipt["recordsIn"], 2)
            report = result.receipt.get("result") or {}
            if not report and out.is_file():
                report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report.get("rowCount"), 2)
            self.assertEqual(report.get("rowKind"), "text")
            fields = (report.get("schema") or {}).get("fields") or []
            names = {f.get("name") for f in fields}
            self.assertIn("id", names)
            self.assertIn("text", names)

    def test_skip_message_when_binary_absent(self) -> None:
        """Document honest skip path when binary cannot be resolved."""
        with mock.patch(
            "Data.backend.tests.test_native_parquet_w165.BINARY",
            None,
        ):
            # Re-import style: call skip helper under patch of module BINARY.
            import Data.backend.tests.test_native_parquet_w165 as mod

            with mock.patch.object(mod, "BINARY", None):
                with self.assertRaises(unittest.SkipTest) as ctx:
                    mod._skip_without_binary()
                self.assertIn("honestly", str(ctx.exception).lower())


class TestIterVersionRecordsParquet(unittest.TestCase):
    def test_format_hint_and_suffix(self) -> None:
        from Data.modules.datasets.materialize import iter_version_records

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.parquet"
            _write_tiny_parquet(path)
            by_hint = list(iter_version_records(path, format_hint="parquet"))
            self.assertEqual(len(by_hint), 2)
            self.assertEqual(by_hint[0].id, "r1")
            by_suffix = list(iter_version_records(path))
            self.assertEqual(len(by_suffix), 2)


if __name__ == "__main__":
    unittest.main()
