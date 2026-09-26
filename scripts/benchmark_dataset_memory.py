#!/usr/bin/env python3
"""Memory regression harness for dataset data-plane operations.

Generates incremental synthetic JSONL under a tempfile, runs validate / export /
dedupe via DatasetService job APIs, and records peak RSS (resource /proc).

Does not commit giant fixtures — all corpora are ephemeral.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "Data" / "backend" / "tests" / "dataset_memory_benchmark_report.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rss_bytes() -> int:
    """Best-effort current RSS in bytes (Linux /proc preferred)."""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    # kB
                    parts = line.split()
                    return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # ru_maxrss is kilobytes on Linux, bytes on macOS — prefer /proc above.
    return int(usage.ru_maxrss) * 1024


def _peak_tracker():
    peak = {"bytes": _rss_bytes()}

    def sample() -> int:
        cur = _rss_bytes()
        if cur > peak["bytes"]:
            peak["bytes"] = cur
        return cur

    return peak, sample


def _layout(root: Path):
    from Data.modules.common.corpus import CorpusLayout

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


def _build_service(tmp: Path):
    from Data.modules.datasets.service import DatasetService
    from Data.modules.datasets.store import DatasetStore
    from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
    from Data.modules.knowledge.store import KnowledgeStore

    data_root = tmp / "ModelData"
    data_root.mkdir(parents=True, exist_ok=True)
    db = tmp / "bench.db"
    corpus = _layout(data_root / "leviathan")
    knowledge = KnowledgeStore(
        db,
        data_root=data_root,
        embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
    )
    knowledge.initialize()
    store = DatasetStore(db)
    store.initialize()

    class _NC:
        mode = "python"
        memory_budget_mb = 256
        max_record_mb = 4
        batch_rows = 2048
        threads = 2
        rust_threshold_mb = 64

    class _RI:
        datasets_auto_index_ready_to_knowledge = False
        datasets_recovery_auto_reindex = False
        datasets_recovery_max_auto_jobs = 0
        dataset_jobs_runner = "none"

    class _K:
        def __init__(self, root: Path) -> None:
            self.data_root = root

    class _S:
        def __init__(self, root: Path) -> None:
            self.knowledge = _K(root)
            self.research_integration = _RI()
            self.native_compute = _NC()

    settings = _S(data_root)
    service = DatasetService(
        store,
        corpus=corpus,
        knowledge=knowledge,
        settings=settings,  # type: ignore[arg-type]
        allowed_import_roots=[data_root, corpus.root],
    )
    return service, data_root


def _write_jsonl(path: Path, rows: int, payload_chars: int = 64) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    pad = "x" * max(1, payload_chars)
    with path.open("w", encoding="utf-8") as fh:
        for i in range(rows):
            fh.write(
                json.dumps({"id": f"r{i}", "text": f"{pad}-{i}", "metadata": {}}) + "\n"
            )
    return path.stat().st_size


def run_sizes(sizes: list[int], *, out_path: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="lev-mem-bench-") as tmp_name:
        tmp = Path(tmp_name)
        service, data_root = _build_service(tmp)
        for rows in sizes:
            peak, sample = _peak_tracker()
            sample()
            src = data_root / f"synth_{rows}.jsonl"
            byte_size = _write_jsonl(src, rows)
            t0 = time.perf_counter()
            imported = service.import_local_sync(str(src), name=f"synth_{rows}", materialize=True)
            ds_id = imported["dataset"]["datasetId"]
            ver = service.pick_usable_version(ds_id)
            assert ver is not None
            sample()

            vjob = service.enqueue_validate(ds_id, ver.version_id)
            vdone = service.process_jobs(max_jobs=1)[0]
            sample()
            ejob = service.enqueue_export(ds_id, ver.version_id)
            edone = service.process_jobs(max_jobs=1)[0]
            sample()
            djob = service.enqueue_dedupe(ds_id, ver.version_id)
            ddone = service.process_jobs(max_jobs=1)[0]
            sample()
            elapsed = time.perf_counter() - t0
            v_backend = (vdone.result or {}).get("backend")
            e_backend = (edone.result or {}).get("backend")
            d_backend = (ddone.result or {}).get("backend")
            results.append(
                {
                    "rows": rows,
                    "inputBytes": byte_size,
                    "datasetId": ds_id,
                    "elapsedSeconds": round(elapsed, 4),
                    "peakRssBytes": peak["bytes"],
                    "peakRssMiB": round(peak["bytes"] / (1024 * 1024), 3),
                    "validate": {
                        "jobId": vjob.job_id,
                        "status": vdone.status.value,
                        "backend": v_backend,
                    },
                    "export": {
                        "jobId": ejob.job_id,
                        "status": edone.status.value,
                        "backend": e_backend,
                    },
                    "dedupe": {
                        "jobId": djob.job_id,
                        "status": ddone.status.value,
                        "backend": d_backend,
                    },
                }
            )
    report = {
        "schemaVersion": 1,
        "generatedAt": _utcnow(),
        "host": {
            "pid": os.getpid(),
            "rssProbe": "proc_self_status_VmRSS_or_resource",
        },
        "sizes": sizes,
        "results": results,
        "truth": {
            "fixturesCommitted": False,
            "hardOsEnforcement": False,
            "peakIsProcessRssNotCgroup": True,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default="200,1000,5000",
        help="Comma-separated row counts (keep small; default 200,1000,5000)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    sizes = [int(x.strip()) for x in str(args.sizes).split(",") if x.strip()]
    if not sizes or any(s <= 0 for s in sizes):
        print("invalid --sizes", file=sys.stderr)
        return 2
    # Guard against accidental giant runs in CI / agent loops.
    if max(sizes) > 50_000:
        print("refusing sizes > 50000 (use a dedicated profiling env)", file=sys.stderr)
        return 2
    report = run_sizes(sizes, out_path=args.out)
    print(json.dumps({"ok": True, "out": str(args.out), "points": len(report["results"])}, indent=2))
    return 0


if __name__ == "__main__":
    # Ensure repo root imports resolve when invoked as a script.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
