"""W182 — Rust native stress: force rust hash/validate/export; measure wall/RSS."""

from __future__ import annotations

import json
import os
import resource
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.compute_planner import ComputeBackend
from Data.modules.datasets.memory_policy import DatasetMemoryPolicy
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus, DatasetJobType
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.knowledge.store import KnowledgeStore
from Data.modules.workers.native_compute import (
    build_task_document,
    resolve_native_binary,
    run_native_task,
)


ROOT = Path(__file__).resolve().parents[3]


def _maybe_build_binary() -> Path | None:
    existing = resolve_native_binary()
    if existing is not None:
        return existing
    script = ROOT / "scripts" / "build_native_data_plane.py"
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
        timeout=600,
    )
    if proc.returncode != 0:
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
SKIP_REASON = (
    None
    if BINARY is not None
    else "leviathan-data-plane binary missing after build attempt "
    "(cargo unavailable or build failed) — honest skip for W182"
)


def _rss_bytes() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


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


class _NC:
    mode = "rust"
    memory_budget_mb = 512
    max_record_mb = 4
    batch_rows = 4096
    threads = 2
    rust_threshold_mb = 1


class _RI:
    datasets_auto_index_ready_to_knowledge = False
    datasets_recovery_auto_reindex = False
    datasets_recovery_max_auto_jobs = 0
    dataset_jobs_runner = "none"
    dataset_index_batch_size = 50
    dataset_max_relations_per_doc = 8
    dataset_extract_relations = False


class _K:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root


class _S:
    def __init__(self, data_root: Path) -> None:
        self.knowledge = _K(data_root)
        self.research_integration = _RI()
        self.native_compute = _NC()


class RustStressW182(unittest.TestCase):
    def setUp(self) -> None:
        if BINARY is None:
            self.skipTest(SKIP_REASON or "native binary unavailable")
        self.tmp = tempfile.TemporaryDirectory(prefix="lev-w182-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_force_rust_hash_validate_export_measures(self) -> None:
        data_root = self.root / "ModelData"
        data_root.mkdir(parents=True, exist_ok=True)
        db = self.root / "leviathan.db"
        corpus = _layout(data_root / "leviathan")
        knowledge = KnowledgeStore(
            db,
            data_root=data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        knowledge.initialize()
        store = DatasetStore(db)
        store.initialize()
        service = DatasetService(
            store,
            corpus=corpus,
            knowledge=knowledge,
            settings=_S(data_root),  # type: ignore[arg-type]
            allowed_import_roots=[data_root, corpus.root],
        )
        service.memory_policy = DatasetMemoryPolicy(
            memory_budget_bytes=512 * 1024 * 1024,
            max_record_bytes=4 * 1024 * 1024,
            native_mode="rust",
            rust_threshold_bytes=1,
        )

        src = data_root / "rust_stress.jsonl"
        rows = 5_000
        with src.open("w", encoding="utf-8") as fh:
            for i in range(rows):
                fh.write(
                    json.dumps({"id": f"r{i}", "text": f"rust-{i}", "metadata": {}}) + "\n"
                )

        imported = service.import_local_sync(str(src), name="rust_stress", materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        ver = service.pick_usable_version(ds_id)
        assert ver is not None
        assert ver.storage_path

        metrics: dict[str, dict[str, float | int | str | None]] = {}

        # Direct native hash for wall/RSS
        hash_out = self.root / "hash.json"
        t0 = time.perf_counter()
        rss0 = _rss_bytes()
        hash_result = run_native_task(
            build_task_document(
                task_id="w182-hash",
                operation="dataset.hash",
                input_path=ver.storage_path,
                temporary_path=hash_out,
                allowed_roots=[str(corpus.root), str(data_root), str(self.root)],
            ),
            binary=BINARY,
            work_dir=self.root / "native-work-hash",
            timeout_seconds=180,
        )
        metrics["hash"] = {
            "wallSeconds": round(time.perf_counter() - t0, 4),
            "rssDeltaBytes": _rss_bytes() - rss0,
            "ok": hash_result.ok,
            "backend": ComputeBackend.RUST_NATIVE.value,
        }
        self.assertTrue(hash_result.ok, hash_result.error_message or hash_result.stderr)

        # Force rust validate via DatasetService
        t0 = time.perf_counter()
        rss0 = _rss_bytes()
        vjob = service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=ds_id,
            version_id=ver.version_id,
            config={"forceBackend": "RUST_NATIVE"},
        )
        vdone = service.process_jobs(max_jobs=1)[0]
        metrics["validate"] = {
            "wallSeconds": round(time.perf_counter() - t0, 4),
            "rssDeltaBytes": _rss_bytes() - rss0,
            "ok": vdone.status == DatasetJobStatus.COMPLETED,
            "backend": (vdone.result or {}).get("backend"),
        }
        self.assertEqual(vdone.job_id, vjob.job_id)
        self.assertEqual(vdone.status, DatasetJobStatus.COMPLETED)
        self.assertEqual(
            (vdone.result or {}).get("backend"),
            ComputeBackend.RUST_NATIVE.value,
        )

        # Force rust export
        t0 = time.perf_counter()
        rss0 = _rss_bytes()
        ejob = service._queue_domain_job(
            job_type=DatasetJobType.EXPORT,
            dataset_id=ds_id,
            version_id=ver.version_id,
            config={"forceBackend": "RUST_NATIVE"},
        )
        edone = service.process_jobs(max_jobs=1)[0]
        metrics["export"] = {
            "wallSeconds": round(time.perf_counter() - t0, 4),
            "rssDeltaBytes": _rss_bytes() - rss0,
            "ok": edone.status == DatasetJobStatus.COMPLETED,
            "backend": (edone.result or {}).get("backend"),
        }
        self.assertEqual(edone.job_id, ejob.job_id)
        self.assertEqual(edone.status, DatasetJobStatus.COMPLETED)
        self.assertEqual(
            (edone.result or {}).get("backend"),
            ComputeBackend.RUST_NATIVE.value,
        )

        # Persist measurements under tests for operators (not a committed baseline claim)
        out = ROOT / "Data" / "backend" / "tests" / "rust_stress_w182_latest.json"
        out.write_text(
            json.dumps(
                {
                    "wave": "W182",
                    "rows": rows,
                    "binary": str(BINARY),
                    "metrics": metrics,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
