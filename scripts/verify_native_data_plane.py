#!/usr/bin/env python3
"""Machine-readable verifier for the Leviathan native / streaming data plane.

Checks produce real evidence (file paths, grep hits, handshake JSON). Exit 0
only when every required check PASSes. Writes
``Data/backend/tests/native_data_plane_verify_report.json``.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "Data" / "backend" / "tests" / "native_data_plane_verify_report.json"
MODULES = ROOT / "Data" / "modules" / "datasets"
BACKEND = ROOT / "Data" / "backend"
HANDLERS_FILE = MODULES / "service.py"
FORBIDDEN_DB_NAMES = (
    "knowledge.db",
    "trading.db",
    "simulation.db",
    "portfolio.db",
    "datasets.db",
    "control.db",
    "agents.db",
    "semantic.db",
    "native.db",
    "learning.db",
    "research.db",
)
REQUIRED_MODULES = {
    "storage_authority": MODULES / "storage_authority.py",
    "scratch": MODULES / "scratch.py",
    "streaming_io": MODULES / "streaming_io.py",
    "memory_policy": MODULES / "memory_policy.py",
    "semantic_types": MODULES / "semantic_types.py",
    "semantic_profiler": MODULES / "semantic_profiler.py",
    "semantic_engine": MODULES / "semantic_engine.py",
    "semantic_enrichment": MODULES / "semantic_enrichment.py",
    "catalog": MODULES / "catalog.py",
    "recovery": MODULES / "recovery.py",
    "compute_planner": MODULES / "compute_planner.py",
    "publish": MODULES / "publish.py",
    "jobs_admission": MODULES / "jobs.py",
    "native_compute": ROOT / "Data" / "modules" / "workers" / "native_compute.py",
    "workers_dashboard": ROOT / "Data" / "modules" / "workers" / "dashboard.py",
}
HANDLER_NAMES = (
    "_handle_validate",
    "_handle_dedupe",
    "_handle_transform",
    "_handle_split",
    "_handle_export",
    "_handle_tokenize_stats",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check(check_id: str, status: str, evidence: Any, *, required: bool = True) -> dict[str, Any]:
    return {
        "id": check_id,
        "required": required,
        "status": status,
        "evidence": evidence,
    }


def _binary_candidates() -> list[Path]:
    native = ROOT / "Data" / "native"
    name = "leviathan-data-plane"
    return [
        native / "bin" / name,
        native / "bin" / f"{name}.exe",
        native / "target" / "release" / name,
        native / "target" / "debug" / name,
    ]


def check_native_handshake() -> dict[str, Any]:
    found = next((p for p in _binary_candidates() if p.is_file()), None)
    if found is None:
        return _check(
            "native_binary_handshake",
            "SKIP",
            {
                "reason": "binary_not_built",
                "candidates": [str(p.relative_to(ROOT)) for p in _binary_candidates()],
            },
            required=False,
        )
    try:
        proc = subprocess.run(  # noqa: S603
            [str(found), "--capabilities", "--json"],
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _check(
            "native_binary_handshake",
            "FAIL",
            {"binary": str(found.relative_to(ROOT)), "error": str(exc)},
        )
    if proc.returncode != 0:
        return _check(
            "native_binary_handshake",
            "FAIL",
            {
                "binary": str(found.relative_to(ROOT)),
                "exitCode": proc.returncode,
                "stderr": (proc.stderr or "")[:500],
            },
        )
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return _check(
            "native_binary_handshake",
            "FAIL",
            {"binary": str(found.relative_to(ROOT)), "jsonError": str(exc)},
        )
    ops = set(doc.get("operations") or [])
    required_ops = {
        "dataset.validate",
        "dataset.hash",
        "dataset.transform",
        "dataset.split",
        "dataset.export",
        "dataset.dedupe",
        "dataset.parquet_validate",
        "dataset.parquet_hash",
        "dataset.parquet_to_jsonl",
    }
    missing = sorted(required_ops - ops)
    ok = int(doc.get("protocolVersion") or 0) == 1 and not missing
    return _check(
        "native_binary_handshake",
        "PASS" if ok else "FAIL",
        {
            "binary": str(found.relative_to(ROOT)),
            "protocolVersion": doc.get("protocolVersion"),
            "operations": sorted(ops),
            "missingOperations": missing,
            "backend": doc.get("backend"),
        },
    )


def check_no_competing_domain_dbs() -> dict[str, Any]:
    """Scan active Python code for permanent competing domain DB authorities."""
    hits: list[str] = []
    scan_roots = [MODULES, BACKEND / "routes", ROOT / "Data" / "modules" / "workers"]
    # Protective / definition sites that mention forbidden names intentionally.
    protective_markers = (
        "FORBIDDEN_COMPETING_DB_NAMES",
        "assert_no_competing_domain_db",
        "competing domain",
        "competing_domain",
        "not a business authority",
        "scratch must not",
        "refuse competing",
    )
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "HADES" in path.parts or "editor" in path.parts:
                continue
            if path.name.startswith("test_"):
                continue
            if path.name == "storage_authority.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            rel = str(path.relative_to(ROOT))
            # Module that only guards against competing names is OK.
            if any(m in text for m in protective_markers):
                # Still flag if it actually opens sqlite to a forbidden filename as authority.
                opens_forbidden = False
                for i, line in enumerate(text.splitlines(), 1):
                    if "sqlite3.connect" not in line and "connect(" not in line:
                        continue
                    if any(name in line for name in FORBIDDEN_DB_NAMES):
                        opens_forbidden = True
                        hits.append(f"{rel}:{i}:{line.strip()[:120]}")
                if not opens_forbidden:
                    continue
                continue
            for name in FORBIDDEN_DB_NAMES:
                patterns = (f'"{name}"', f"'{name}'", f"/{name}")
                if not any(p in text for p in patterns):
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if name not in line:
                        continue
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if any(m in line for m in protective_markers):
                        continue
                    # Membership guards like ``if name in {"knowledge.db", ...}`` are protective.
                    if " in {" in line or " in (" in line or ".lower() in" in line:
                        continue
                    if "connect" in line or "database" in line.lower() or "db_path" in line or "Path(" in line:
                        hits.append(f"{rel}:{i}:{stripped[:120]}")
    authority = MODULES / "storage_authority.py"
    has_module = authority.is_file()
    forbid_present = False
    if has_module:
        auth_text = authority.read_text(encoding="utf-8")
        forbid_present = "FORBIDDEN_COMPETING_DB_NAMES" in auth_text and all(
            name in auth_text for name in FORBIDDEN_DB_NAMES[:5]
        )
    # Deduplicate hits
    uniq_hits = sorted(set(hits))
    status = "PASS" if has_module and forbid_present and not uniq_hits else "FAIL"
    return _check(
        "no_competing_permanent_domain_dbs",
        status,
        {
            "storageAuthorityModule": str(authority.relative_to(ROOT)) if has_module else None,
            "forbidListPresent": forbid_present,
            "competingHits": uniq_hits[:20],
            "scannedNames": list(FORBIDDEN_DB_NAMES),
        },
    )


def _handler_calls_load_materialized(source: str) -> list[str]:
    """Return handler method names that call load_materialized_jsonl directly."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"parse_error:{exc}"]
    offenders: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name not in HANDLER_NAMES:
                continue
            for child in ast.walk(item):
                if isinstance(child, ast.Call):
                    func = child.func
                    name = None
                    if isinstance(func, ast.Name):
                        name = func.id
                    elif isinstance(func, ast.Attribute):
                        name = func.attr
                    if name == "load_materialized_jsonl":
                        offenders.append(item.name)
                        break
    return offenders


def check_streaming_handlers() -> dict[str, Any]:
    if not HANDLERS_FILE.is_file():
        return _check(
            "streaming_production_handlers",
            "FAIL",
            {"missing": str(HANDLERS_FILE.relative_to(ROOT))},
        )
    text = HANDLERS_FILE.read_text(encoding="utf-8")
    offenders = _handler_calls_load_materialized(text)
    # Compatibility helper may still wrap load_materialized_jsonl — that is OK
    # if production handlers do not call it.
    helper_ok = "_load_version_records" in text and "Compatibility helper" in text
    uses_iter = all(
        name in text and ("iter_version_records" in text or "iter_" in text)
        for name in ("_handle_validate", "_handle_export")
    )
    status = "PASS" if not offenders and uses_iter else "FAIL"
    return _check(
        "streaming_production_handlers",
        status,
        {
            "service": str(HANDLERS_FILE.relative_to(ROOT)),
            "handlerLoadMaterializedOffenders": offenders,
            "compatibilityHelperDocumented": helper_ok,
            "validateUsesStreaming": "validate_records(self.iter_version_records" in text
            or "iter_version_records" in text,
            "exportUsesStreaming": "export_jsonl(self.iter_version_records" in text
            or "_try_native_operation" in text,
        },
    )


def check_required_modules() -> dict[str, Any]:
    present: dict[str, str] = {}
    missing: list[str] = []
    for key, path in REQUIRED_MODULES.items():
        if path.is_file():
            present[key] = str(path.relative_to(ROOT))
        else:
            missing.append(key)
    # Scratch isolation: ScratchManager must declare ephemeral + not authority.
    scratch_ok = False
    scratch_path = REQUIRED_MODULES["scratch"]
    if scratch_path.is_file():
        scratch_text = scratch_path.read_text(encoding="utf-8")
        scratch_ok = (
            "EPHEMERAL_SCRATCH" in scratch_text
            and "notCanonicalAuthority" in scratch_text
            and "ScratchManager" in scratch_text
        )
    status = "PASS" if not missing and scratch_ok else "FAIL"
    return _check(
        "storage_scratch_semantic_modules",
        status,
        {
            "present": present,
            "missing": missing,
            "scratchIsolationMarkers": scratch_ok,
        },
    )


def check_settings_native_compute() -> dict[str, Any]:
    config = BACKEND / "config.py"
    catalog = ROOT / "Data" / "modules" / "settings" / "catalog.py"
    cfg_text = config.read_text(encoding="utf-8") if config.is_file() else ""
    cat_text = catalog.read_text(encoding="utf-8") if catalog.is_file() else ""
    has_cls = "class NativeComputeSettings" in cfg_text
    has_field = "native_compute: NativeComputeSettings" in cfg_text
    has_summary = '"native_compute"' in cfg_text and "memory_budget_mb" in cfg_text
    required_keys = (
        "native_compute.mode",
        "native_compute.memory_budget_mb",
        "native_compute.max_record_mb",
        "native_compute.threads",
        "native_compute.batch_rows",
        "native_compute.rust_threshold_mb",
    )
    missing_keys = [k for k in required_keys if k not in cat_text]
    has_catalog = not missing_keys
    status = "PASS" if has_cls and has_field and has_summary and has_catalog else "FAIL"
    return _check(
        "native_compute_settings",
        status,
        {
            "NativeComputeSettings": has_cls,
            "settingsField": has_field,
            "publicSummary": has_summary,
            "catalogKeys": has_catalog,
            "missingCatalogKeys": missing_keys,
        },
    )


def check_admission_cancel_orphan() -> dict[str, Any]:
    jobs = MODULES / "jobs.py"
    publish = MODULES / "publish.py"
    native = ROOT / "Data" / "modules" / "workers" / "native_compute.py"
    dash = ROOT / "Data" / "modules" / "workers" / "dashboard.py"
    service = HANDLERS_FILE
    jobs_text = jobs.read_text(encoding="utf-8") if jobs.is_file() else ""
    pub_text = publish.read_text(encoding="utf-8") if publish.is_file() else ""
    nat_text = native.read_text(encoding="utf-8") if native.is_file() else ""
    svc_text = service.read_text(encoding="utf-8") if service.is_file() else ""
    dash_text = dash.read_text(encoding="utf-8") if dash.is_file() else ""
    markers = {
        "MEMORY_HEAVY": "MEMORY_HEAVY" in jobs_text and "reservedRamBytes" in jobs_text,
        "softRssWatchdog": "MEMORY_RSS_GRACE_FACTOR" in nat_text or "peak_rss" in nat_text,
        "cancel": "cancel_event" in nat_text or "cancelRequested" in svc_text,
        "orphanReconcile": "reconcile_orphans" in pub_text and "reconcile_data_plane_orphans" in svc_text,
        "nativeProbe": "def probe(" in nat_text,
        "dashboardNative": "nativeCompute" in dash_text,
        "publicComputeSummary": "_public_compute_summary" in svc_text,
    }
    status = "PASS" if all(markers.values()) else "FAIL"
    return _check("admission_cancel_orphan_native_probe", status, markers)


def check_worker_recycle() -> dict[str, Any]:
    worker = MODULES / "worker.py"
    text = worker.read_text(encoding="utf-8") if worker.is_file() else ""
    has_env = "MAX_JOBS_BEFORE_RECYCLE" in text
    has_clear = "_clear_large_job_refs" in text
    status = "PASS" if has_env and has_clear else "FAIL"
    return _check(
        "worker_recycling_w152_light",
        status,
        {
            "worker": str(worker.relative_to(ROOT)) if worker.is_file() else None,
            "recycleEnvPresent": has_env,
            "clearLargeRefsPresent": has_clear,
        },
    )


def main() -> int:
    checks = [
        check_native_handshake(),
        check_no_competing_domain_dbs(),
        check_streaming_handlers(),
        check_required_modules(),
        check_settings_native_compute(),
        check_admission_cancel_orphan(),
        check_worker_recycle(),
    ]
    required_failed = [
        c for c in checks if c.get("required", True) and c.get("status") != "PASS"
    ]
    optional_skipped = [c for c in checks if not c.get("required", True) and c.get("status") == "SKIP"]
    overall = "PASS" if not required_failed else "FAIL"
    report = {
        "schemaVersion": 1,
        "program": "native_data_plane_memory_architecture",
        "generatedAt": _utcnow(),
        "overall": overall,
        "requiredFailedCount": len(required_failed),
        "optionalSkippedCount": len(optional_skipped),
        "checks": checks,
        "truth": {
            "exitZeroOnlyOnEvidencePass": True,
            "hardcodedPassForbidden": True,
            "nativeHandshakeOptionalWhenUnbuilt": True,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall": overall, "report": str(REPORT_PATH)}, indent=2))
    for c in checks:
        print(f"  [{c['status']}] {c['id']}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
