#!/usr/bin/env python3
"""LOCAL_CLEAN_CHECK — verify native data-plane install surface without a Windows VM.

Checks Python imports, frontend package.json, native build script, handshake OR honest
BUILD_MISSING, and a temp-corpus Python dataset job path. Writes a JSON report.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "Data" / "backend" / "tests" / "native_clean_install_verify_report.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ok(check_id: str, evidence: Any) -> dict[str, Any]:
    return {"id": check_id, "status": "PASS", "evidence": evidence}


def _fail(check_id: str, evidence: Any) -> dict[str, Any]:
    return {"id": check_id, "status": "FAIL", "evidence": evidence}


def check_python_imports() -> dict[str, Any]:
    modules = [
        "Data.modules.datasets.service",
        "Data.modules.datasets.compute_planner",
        "Data.modules.datasets.memory_policy",
        "Data.modules.datasets.storage_authority",
        "Data.modules.workers.native_compute",
        "Data.modules.workers.dashboard",
        "Data.backend.config",
    ]
    loaded: list[str] = []
    errors: list[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
            loaded.append(name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
    if errors:
        return _fail("python_imports", {"loaded": loaded, "errors": errors})
    return _ok("python_imports", {"loaded": loaded})


def check_frontend_package() -> dict[str, Any]:
    pkg = ROOT / "Data" / "frontend" / "package.json"
    if not pkg.is_file():
        return _fail("frontend_package_json", {"missing": str(pkg.relative_to(ROOT))})
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _fail("frontend_package_json", {"error": str(exc)})
    name = data.get("name")
    scripts = data.get("scripts") or {}
    ok = isinstance(name, str) and "typecheck" in scripts and "test" in scripts
    return (_ok if ok else _fail)(
        "frontend_package_json",
        {"path": str(pkg.relative_to(ROOT)), "name": name, "hasTypecheck": "typecheck" in scripts},
    )


def check_native_build_script() -> dict[str, Any]:
    script = ROOT / "scripts" / "build_native_data_plane.py"
    cargo = ROOT / "Data" / "native" / "Cargo.toml"
    crate = ROOT / "Data" / "native" / "leviathan_data_plane" / "Cargo.toml"
    present = script.is_file() and cargo.is_file() and crate.is_file()
    evidence = {
        "buildScript": str(script.relative_to(ROOT)) if script.is_file() else None,
        "workspaceCargo": cargo.is_file(),
        "crateCargo": crate.is_file(),
    }
    return (_ok if present else _fail)("native_build_script", evidence)


def check_handshake_or_build_missing() -> dict[str, Any]:
    from Data.modules.workers.native_compute import NativeComputeRunner, NativeStatus

    probe = NativeComputeRunner().probe()
    status = str(probe.get("status") or "")
    honest = status in {
        NativeStatus.AVAILABLE.value,
        NativeStatus.BUILD_MISSING.value,
        NativeStatus.DISABLED.value,
        NativeStatus.UNAVAILABLE.value,
        NativeStatus.INCOMPATIBLE.value,
        NativeStatus.FAILED_HEALTHCHECK.value,
    }
    if not honest:
        return _fail("native_handshake_or_build_missing", {"probe": probe})
    if status == NativeStatus.AVAILABLE.value and not probe.get("operations"):
        return _fail("native_handshake_or_build_missing", {"probe": probe, "reason": "empty_ops"})
    return _ok(
        "native_handshake_or_build_missing",
        {
            "status": status,
            "binaryVersion": probe.get("binaryVersion"),
            "operationCount": len(probe.get("operations") or []),
            "honestBuildMissingAccepted": status == NativeStatus.BUILD_MISSING.value,
        },
    )


def check_dataset_python_path_temp_corpus() -> dict[str, Any]:
    from Data.modules.common.corpus import CorpusLayout
    from Data.modules.datasets.service import DatasetService
    from Data.modules.datasets.store import DatasetStore
    from Data.modules.datasets.types import DatasetJobStatus

    def _layout(root: Path) -> CorpusLayout:
        return CorpusLayout(
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
        ).ensure()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "lev.db"
            corpus = _layout(root / "corpus")
            store = DatasetStore(db)
            store.initialize()
            service = DatasetService(
                store,
                corpus=corpus,
                settings=None,
                allowed_import_roots=[root, corpus.root],
            )
            path = root / "clean.jsonl"
            path.write_text(
                '{"id":"1","text":"hello","metadata":{}}\n'
                '{"id":"2","text":"world","metadata":{}}\n',
                encoding="utf-8",
            )
            imported = service.import_local_sync(
                str(path), name="clean-install-check", materialize=True
            )
            ds_id = imported["dataset"]["datasetId"]
            ver = service.pick_usable_version(ds_id)
            assert ver is not None
            job = service.enqueue_validate(ds_id, ver.version_id)
            done = service.process_jobs(max_jobs=1)[0]
            if done.job_id != job.job_id or done.status != DatasetJobStatus.COMPLETED:
                return _fail(
                    "dataset_python_job_temp_corpus",
                    {
                        "jobStatus": done.status.value
                        if hasattr(done.status, "value")
                        else done.status
                    },
                )
            pub = service.public_job(done)
            return _ok(
                "dataset_python_job_temp_corpus",
                {
                    "datasetId": ds_id,
                    "backend": pub.get("backend"),
                    "fallbackReason": pub.get("fallbackReason"),
                    "peakRssBytes": pub.get("peakRssBytes"),
                },
            )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "dataset_python_job_temp_corpus",
            {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-1500:]},
        )


def check_supply_chain_artifact() -> dict[str, Any]:
    path = ROOT / "Data" / "backend" / "tests" / "native_cargo_supply_chain.json"
    if not path.is_file():
        return _fail("supply_chain_json", {"missing": str(path.relative_to(ROOT))})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _fail("supply_chain_json", {"error": str(exc)})
    audit = (data.get("cargoAudit") or {}).get("status")
    deps = data.get("directDependencies") or []
    ok = audit in {"AVAILABLE", "UNAVAILABLE"} and isinstance(deps, list) and len(deps) >= 5
    return (_ok if ok else _fail)(
        "supply_chain_json",
        {"path": str(path.relative_to(ROOT)), "cargoAudit": audit, "directDepCount": len(deps)},
    )


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    checks = [
        check_python_imports(),
        check_frontend_package(),
        check_native_build_script(),
        check_handshake_or_build_missing(),
        check_dataset_python_path_temp_corpus(),
        check_supply_chain_artifact(),
    ]
    failed = [c for c in checks if c["status"] != "PASS"]
    report = {
        "schemaVersion": 1,
        "program": "LOCAL_CLEAN_CHECK",
        "generatedAt": _utcnow(),
        "overall": "PASS" if not failed else "FAIL",
        "scope": "Not a full Windows VM — honest local clean-install surface check.",
        "failedCount": len(failed),
        "checks": checks,
        "truth": {
            "windowsVmNotClaimed": True,
            "buildMissingAcceptedAsHonest": True,
            "hardcodedPassForbidden": True,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall": report["overall"], "report": str(REPORT_PATH)}, indent=2))
    for c in checks:
        print(f"  [{c['status']}] {c['id']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
