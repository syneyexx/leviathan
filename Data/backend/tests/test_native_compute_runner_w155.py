"""W155 — native compute runner, capabilities, planner, path security."""

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
    PROTOCOL_VERSION,
    NativeCapabilities,
    NativeStatus,
    build_task_document,
    probe_capabilities,
    resolve_native_binary,
    run_native_task,
    validate_receipt,
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
    # Prefer unlocked first-time if lock missing; build script uses --locked by default.
    proc = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if proc.returncode != 0:
        # Retry unlocked if lock/toolchain mismatch
        proc2 = subprocess.run(
            [os.environ.get("PYTHON", "python3"), str(script), "--unlocked"],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        if proc2.returncode != 0:
            return None
    return resolve_native_binary()


BINARY = _maybe_build_binary()


def _skip_without_binary() -> None:
    if BINARY is None:
        raise unittest.SkipTest("leviathan-data-plane binary missing (cargo build unavailable)")


class TestNativeCapabilities(unittest.TestCase):
    def test_build_missing_when_absent(self) -> None:
        with mock.patch(
            "Data.modules.workers.native_compute.resolve_native_binary",
            return_value=None,
        ):
            caps = probe_capabilities()
        self.assertEqual(caps.status, NativeStatus.BUILD_MISSING)

    def test_disabled(self) -> None:
        caps = probe_capabilities(disabled=True)
        self.assertEqual(caps.status, NativeStatus.DISABLED)

    def test_live_handshake(self) -> None:
        _skip_without_binary()
        caps = probe_capabilities(binary=BINARY)
        self.assertEqual(caps.status, NativeStatus.AVAILABLE)
        self.assertEqual(caps.protocol_version, PROTOCOL_VERSION)
        self.assertIn("dataset.validate", caps.operations)
        self.assertEqual(caps.backend.get("name"), "rust_native")


class TestReceiptValidation(unittest.TestCase):
    def test_receipt_fields(self) -> None:
        receipt = {
            "protocolVersion": PROTOCOL_VERSION,
            "taskId": "t1",
            "operation": "dataset.hash",
            "status": "ok",
            "recordsIn": 1,
            "recordsOut": 1,
            "bytesIn": 10,
            "bytesOut": 10,
            "durationMs": 1,
            "peakRssBytes": 1000,
            "spillBytes": 0,
            "backend": {"name": "rust_native", "version": "0.1.0"},
        }
        self.assertEqual(validate_receipt(receipt, task_id="t1", operation="dataset.hash"), [])
        bad = dict(receipt)
        bad["protocolVersion"] = 99
        self.assertTrue(validate_receipt(bad, task_id="t1", operation="dataset.hash"))


class TestComputePlanner(unittest.TestCase):
    def test_python_mode(self) -> None:
        policy = DatasetMemoryPolicy(native_mode="python", rust_threshold_bytes=1024)
        caps = NativeCapabilities(status=NativeStatus.AVAILABLE, protocol_version=1, operations=list())
        plan = ComputeBackendPlanner(policy=policy, capabilities=caps).plan(
            "dataset.hash", input_bytes=10_000_000
        )
        self.assertEqual(plan.backend, ComputeBackend.PYTHON_STREAMING)
        self.assertEqual(plan.fallback_reason, "native_mode_python")

    def test_auto_threshold(self) -> None:
        policy = DatasetMemoryPolicy(native_mode="auto", rust_threshold_bytes=1000)
        caps = NativeCapabilities(
            status=NativeStatus.AVAILABLE,
            protocol_version=1,
            operations=["dataset.hash"],
        )
        planner = ComputeBackendPlanner(policy=policy, capabilities=caps)
        small = planner.plan("dataset.hash", input_bytes=100)
        self.assertEqual(small.backend, ComputeBackend.PYTHON_STREAMING)
        self.assertEqual(small.fallback_reason, "below_rust_threshold")
        large = planner.plan("dataset.hash", input_bytes=5000)
        self.assertEqual(large.backend, ComputeBackend.RUST_NATIVE)
        self.assertIsNone(large.fallback_reason)

    def test_rust_mode_fallback_when_missing(self) -> None:
        policy = DatasetMemoryPolicy(native_mode="rust")
        caps = NativeCapabilities(status=NativeStatus.BUILD_MISSING, detail="no bin")
        plan = ComputeBackendPlanner(policy=policy, capabilities=caps).plan("dataset.hash")
        self.assertEqual(plan.backend, ComputeBackend.PYTHON_STREAMING)
        self.assertIn("build_missing", (plan.fallback_reason or "").lower())


class TestPathSecurityAndOps(unittest.TestCase):
    def test_reject_parent_traversal_via_native(self) -> None:
        _skip_without_binary()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "in.jsonl"
            inp.write_text('{"id":"1","text":"a","metadata":{}}\n', encoding="utf-8")
            out = root / "out.jsonl"
            task = build_task_document(
                task_id="sec1",
                operation="dataset.hash",
                input_path=str(root / ".." / "etc" / "passwd"),
                temporary_path=str(out),
                allowed_roots=[str(root)],
            )
            # Even if path string contains .., runner still invokes; native must reject.
            result = run_native_task(task, binary=BINARY, timeout_seconds=30, work_dir=root / "work")
            self.assertFalse(result.ok)
            self.assertIn(
                (result.error_code or ""),
                {"NATIVE_PATH_REJECTED", "NATIVE_INPUT_MISSING"},
            )

    def test_hash_and_split_parity_smoke(self) -> None:
        _skip_without_binary()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "in.jsonl"
            lines = [
                json.dumps({"id": f"r{i}", "text": f"row-{i}", "metadata": {}}, ensure_ascii=False)
                for i in range(20)
            ]
            inp.write_text("\n".join(lines) + "\n", encoding="utf-8")

            hash_out = root / "hash.json"
            task = build_task_document(
                task_id="h1",
                operation="dataset.hash",
                input_path=inp,
                temporary_path=hash_out,
                allowed_roots=[str(root)],
            )
            result = run_native_task(task, binary=BINARY, work_dir=root / "w1")
            self.assertTrue(result.ok, result.error_message or result.stderr)
            self.assertEqual(result.receipt["recordsIn"], 20)
            self.assertTrue(result.receipt.get("contentHash"))

            split_out = root / "split.jsonl"
            task2 = build_task_document(
                task_id="s1",
                operation="dataset.split",
                input_path=inp,
                temporary_path=split_out,
                allowed_roots=[str(root)],
                options={"seed": 7, "trainRatio": 0.8, "valRatio": 0.1, "testRatio": 0.1},
            )
            result2 = run_native_task(task2, binary=BINARY, work_dir=root / "w2")
            self.assertTrue(result2.ok, result2.error_message or result2.stderr)
            self.assertEqual(result2.receipt["recordsOut"], 20)
            # Python parity for first record bucket label
            from Data.modules.datasets.splits import assign_split_label
            from Data.modules.datasets.types import CanonicalRecord

            expected = assign_split_label(CanonicalRecord(id="r0", text="row-0"), seed=7)
            first = json.loads(split_out.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first["split"], expected)

    def test_transform_strip(self) -> None:
        _skip_without_binary()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "in.jsonl"
            inp.write_text(
                json.dumps({"id": "1", "text": "  Hello  ", "metadata": {}}) + "\n",
                encoding="utf-8",
            )
            out = root / "out.jsonl"
            task = build_task_document(
                task_id="x1",
                operation="dataset.transform",
                input_path=inp,
                temporary_path=out,
                allowed_roots=[str(root)],
                options={"transforms": [{"name": "strip_whitespace", "params": {"strip": True}}]},
            )
            result = run_native_task(task, binary=BINARY, work_dir=root / "w")
            self.assertTrue(result.ok, result.error_message)
            row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["text"], "Hello")

    def test_dedupe_external(self) -> None:
        _skip_without_binary()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "in.jsonl"
            rows = [
                {"id": "1", "text": "alpha", "metadata": {}},
                {"id": "2", "text": "beta", "metadata": {}},
                {"id": "3", "text": "alpha", "metadata": {}},
            ]
            inp.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
            out = root / "out.jsonl"
            task = build_task_document(
                task_id="d1",
                operation="dataset.dedupe",
                input_path=inp,
                temporary_path=out,
                allowed_roots=[str(root)],
                limits={"memoryBytes": 8 * 1024 * 1024, "spillBytes": 64 * 1024 * 1024},
            )
            result = run_native_task(task, binary=BINARY, work_dir=root / "w")
            self.assertTrue(result.ok, result.error_message or result.stderr)
            self.assertEqual(result.receipt["recordsOut"], 2)
            self.assertGreaterEqual(result.receipt.get("spillBytes", 0), 0)


class TestBinaryAllowlist(unittest.TestCase):
    def test_rejects_outside_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "leviathan-data-plane"
            fake.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
            fake.chmod(0o755)
            with mock.patch(
                "Data.modules.workers.native_compute.default_binary_candidates",
                return_value=[],
            ):
                found = resolve_native_binary(explicit=fake, env={})
            self.assertIsNone(found)
            # Even when defaults exist, an outside explicit path must not be selected as itself.
            found2 = resolve_native_binary(explicit=fake, env={})
            if found2 is not None:
                self.assertNotEqual(found2.resolve(), fake.resolve())


if __name__ == "__main__":
    unittest.main()
