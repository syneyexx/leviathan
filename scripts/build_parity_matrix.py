#!/usr/bin/env python3
"""W183 — build Python vs Rust parity matrix for dataset data-plane ops.

Runs validate / hash / split / transform / export / dedupe on shared fixtures
and records content-hash (or structural) parity into
``Data/backend/tests/parity_matrix.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "Data" / "backend" / "tests" / "parity_matrix.json"

OPS = (
    "dataset.validate",
    "dataset.hash",
    "dataset.split",
    "dataset.transform",
    "dataset.export",
    "dataset.dedupe",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_fixture(path: Path, rows: int = 32) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(rows):
        # Duplicate every 8th row for dedupe parity
        text = f"row-payload-{i // 8 if i % 8 == 0 and i > 0 else i}"
        if i % 8 == 0 and i > 0:
            text = f"row-payload-{(i // 8) * 8}"
        lines.append(
            json.dumps(
                {"id": f"r{i}", "text": f"  {text}  ", "metadata": {"i": i}},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    # Explicit duplicate of r0 payload under new id
    lines.append(
        json.dumps(
            {"id": "dup0", "text": "  row-payload-0  ", "metadata": {"i": 0}},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _python_hash(path: Path) -> str:
    from Data.modules.datasets.materialize import iter_materialized_jsonl, records_content_hash

    return records_content_hash(iter_materialized_jsonl(path))


def _python_validate(path: Path) -> dict[str, Any]:
    from Data.modules.datasets.materialize import iter_materialized_jsonl
    from Data.modules.datasets.validation import validate_records

    return validate_records(iter_materialized_jsonl(path))


def _python_transform(path: Path, dest: Path) -> str:
    from Data.modules.datasets.materialize import iter_materialized_jsonl, write_canonical_jsonl_stream
    from Data.modules.datasets.transforms import apply_transforms_streaming

    records, _lineage = apply_transforms_streaming(
        iter_materialized_jsonl(path),
        [{"name": "strip_whitespace", "params": {"strip": True}}],
    )
    outcome = write_canonical_jsonl_stream(records, dest, validate=False)
    return str(outcome["contentHash"])


def _python_split(path: Path, dest: Path) -> str:
    from Data.modules.datasets.materialize import iter_materialized_jsonl, write_canonical_jsonl_stream
    from Data.modules.datasets.splits import iter_deterministic_split

    records, _summary = iter_deterministic_split(
        iter_materialized_jsonl(path),
        seed=7,
        train_ratio=0.8,
        val_ratio=0.1,
        test_ratio=0.1,
    )
    outcome = write_canonical_jsonl_stream(records, dest, validate=False)
    return str(outcome["contentHash"])


def _python_export(path: Path, dest: Path) -> str:
    from Data.modules.datasets.export import export_version_jsonl

    outcome = export_version_jsonl(path, dest)
    return str(outcome["contentHash"])


def _python_dedupe(path: Path, dest: Path) -> str:
    from Data.modules.datasets.dedupe import iter_exact_dedupe_external
    from Data.modules.datasets.materialize import iter_materialized_jsonl, write_canonical_jsonl_stream
    from Data.modules.datasets.scratch import ScratchManager

    scratch = ScratchManager(path.parent / ".scratch-parity")
    kept, _stats = iter_exact_dedupe_external(
        iter_materialized_jsonl(path),
        scratch_manager=scratch,
        job_id="parity-dedupe",
    )
    outcome = write_canonical_jsonl_stream(kept, dest, validate=False)
    return str(outcome["contentHash"])


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _native_op(
    *,
    binary: Path,
    operation: str,
    input_path: Path,
    output_path: Path,
    work_dir: Path,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from Data.modules.workers.native_compute import build_task_document, run_native_task

    task = build_task_document(
        task_id=f"parity-{operation.replace('.', '-')}",
        operation=operation,
        input_path=input_path,
        temporary_path=output_path,
        allowed_roots=[str(input_path.parent), str(work_dir)],
        options=options or {},
    )
    result = run_native_task(task, binary=binary, work_dir=work_dir, timeout_seconds=120)
    receipt = result.receipt or {}
    content_hash = receipt.get("contentHash") or (receipt.get("result") or {}).get("contentHash")
    return {
        "ok": bool(result.ok),
        "contentHash": content_hash,
        "recordsIn": receipt.get("recordsIn"),
        "recordsOut": receipt.get("recordsOut"),
        "error": result.error_message or result.error_code,
        "receiptStatus": receipt.get("status"),
    }


def _resolve_binary() -> Path | None:
    from Data.modules.workers.native_compute import resolve_native_binary

    existing = resolve_native_binary()
    if existing is not None:
        return existing
    script = ROOT / "scripts" / "build_native_data_plane.py"
    if not script.is_file():
        return None
    import subprocess

    proc = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script), "--unlocked"],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if proc.returncode != 0:
        return None
    return resolve_native_binary()


def build_matrix(*, rows: int = 32, out_path: Path = DEFAULT_OUT) -> dict[str, Any]:
    binary = _resolve_binary()
    entries: list[dict[str, Any]] = []
    intentional: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="lev-parity-") as tmp_name:
        root = Path(tmp_name)
        fixture = root / "fixture.jsonl"
        _write_fixture(fixture, rows=rows)

        # --- hash ---
        py_hash = _python_hash(fixture)
        rust_hash = None
        hash_status = "SKIP"
        hash_notes = ""
        if binary is None:
            hash_notes = "native binary unavailable"
            intentional.append(
                {
                    "operation": "dataset.hash",
                    "reason": "RUST_BINARY_MISSING",
                    "detail": hash_notes,
                }
            )
        else:
            rust_out = root / "hash.json"
            rust = _native_op(
                binary=binary,
                operation="dataset.hash",
                input_path=fixture,
                output_path=rust_out,
                work_dir=root / "w-hash",
            )
            rust_hash = rust.get("contentHash")
            if rust_out.is_file() and not rust_hash:
                try:
                    rust_hash = json.loads(rust_out.read_text(encoding="utf-8")).get("contentHash")
                except (OSError, json.JSONDecodeError):
                    pass
            if rust.get("ok") and rust_hash == py_hash:
                hash_status = "PASS"
            else:
                hash_status = "FAIL"
                hash_notes = rust.get("error") or f"py={py_hash} rust={rust_hash}"
                if rust.get("ok"):
                    intentional.append(
                        {
                            "operation": "dataset.hash",
                            "reason": "HASH_MISMATCH_INVESTIGATE",
                            "detail": hash_notes,
                        }
                    )
        entries.append(
            {
                "operation": "dataset.hash",
                "status": hash_status,
                "pythonHash": py_hash,
                "rustHash": rust_hash,
                "notes": hash_notes,
            }
        )

        # --- validate ---
        py_val = _python_validate(fixture)
        val_status = "SKIP"
        val_notes = ""
        rust_val_rows = None
        if binary is None:
            val_notes = "native binary unavailable"
            intentional.append(
                {
                    "operation": "dataset.validate",
                    "reason": "RUST_BINARY_MISSING",
                    "detail": val_notes,
                }
            )
        else:
            rust_out = root / "validate.out"
            rust = _native_op(
                binary=binary,
                operation="dataset.validate",
                input_path=fixture,
                output_path=rust_out,
                work_dir=root / "w-val",
            )
            rust_val_rows = rust.get("recordsIn")
            # Validate: compare row counts + success (validate has no content hash)
            if rust.get("ok") and int(rust_val_rows or -1) == int(py_val.get("rowCount") or -2):
                val_status = "PASS"
            else:
                val_status = "FAIL"
                val_notes = rust.get("error") or "rowCount mismatch"
        entries.append(
            {
                "operation": "dataset.validate",
                "status": val_status,
                "python": {"valid": py_val.get("valid"), "rowCount": py_val.get("rowCount")},
                "rust": {"ok": binary is not None, "recordsIn": rust_val_rows},
                "notes": val_notes,
                "parityMetric": "rowCount_and_success",
            }
        )

        # --- transform / split / export / dedupe ---
        for operation, py_fn, options in (
            (
                "dataset.transform",
                _python_transform,
                {"transforms": [{"name": "strip_whitespace", "params": {"strip": True}}]},
            ),
            (
                "dataset.split",
                _python_split,
                {"seed": 7, "trainRatio": 0.8, "valRatio": 0.1, "testRatio": 0.1},
            ),
            ("dataset.export", _python_export, {}),
            ("dataset.dedupe", _python_dedupe, {}),
        ):
            py_dest = root / f"py-{operation.split('.')[-1]}.jsonl"
            t0 = time.perf_counter()
            try:
                py_h = py_fn(fixture, py_dest)
                py_err = None
            except Exception as exc:  # noqa: BLE001
                py_h = None
                py_err = str(exc)
            py_ms = round((time.perf_counter() - t0) * 1000, 2)

            status = "SKIP"
            notes = ""
            rust_h = None
            if binary is None:
                notes = "native binary unavailable"
                intentional.append(
                    {
                        "operation": operation,
                        "reason": "RUST_BINARY_MISSING",
                        "detail": notes,
                    }
                )
            elif py_err:
                status = "FAIL"
                notes = f"python_error: {py_err}"
            else:
                rust_dest = root / f"rust-{operation.split('.')[-1]}.jsonl"
                rust = _native_op(
                    binary=binary,
                    operation=operation,
                    input_path=fixture,
                    output_path=rust_dest,
                    work_dir=root / f"w-{operation.split('.')[-1]}",
                    options=options,
                )
                rust_h = rust.get("contentHash")
                if rust.get("ok") and rust_h and rust_h == py_h:
                    status = "PASS"
                elif rust.get("ok") and rust_dest.is_file() and py_dest.is_file():
                    # Fallback: compare output file hashes when receipt hash missing
                    if _file_sha256(rust_dest) == _file_sha256(py_dest):
                        status = "PASS"
                        rust_h = rust_h or _file_sha256(rust_dest)
                        notes = "parity via output file sha256"
                    else:
                        status = "FAIL"
                        notes = rust.get("error") or f"py={py_h} rust={rust_h}"
                        # Document intentional differences only when clearly labeled
                        if operation == "dataset.dedupe" and rust.get("ok"):
                            intentional.append(
                                {
                                    "operation": operation,
                                    "reason": "HASH_MISMATCH_INVESTIGATE",
                                    "detail": notes,
                                }
                            )
                else:
                    status = "FAIL"
                    notes = rust.get("error") or f"py={py_h} rust={rust_h}"

            entries.append(
                {
                    "operation": operation,
                    "status": status,
                    "pythonHash": py_h,
                    "rustHash": rust_h,
                    "pythonMs": py_ms,
                    "notes": notes,
                }
            )

    comparable = [e for e in entries if e.get("status") in {"PASS", "FAIL"}]
    all_pass = all(e.get("status") == "PASS" for e in comparable) if comparable else False
    report = {
        "schemaVersion": 1,
        "wave": "W183",
        "generatedAt": _utcnow(),
        "fixtureRows": rows,
        "nativeBinary": str(binary) if binary else None,
        "operations": entries,
        "intentionalDifferences": intentional,
        "summary": {
            "total": len(entries),
            "pass": sum(1 for e in entries if e.get("status") == "PASS"),
            "fail": sum(1 for e in entries if e.get("status") == "FAIL"),
            "skip": sum(1 for e in entries if e.get("status") == "SKIP"),
            "allComparablePass": all_pass,
        },
        "truth": {
            "comparableOpsMustPassOrBeDocumented": True,
            "rustMissingIsDocumentedSkip": binary is None,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=32)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    report = build_matrix(rows=max(4, int(args.rows)), out_path=args.out)
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(args.out),
                "summary": report.get("summary"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
