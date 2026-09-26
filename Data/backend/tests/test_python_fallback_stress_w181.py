"""W181 — Python fallback stress: native disabled, streaming ops on large corpus."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.compute_planner import ComputeBackend
from Data.modules.datasets.memory_policy import DatasetMemoryPolicy
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.knowledge.store import KnowledgeStore


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
    mode = "python"
    memory_budget_mb = 512
    max_record_mb = 4
    batch_rows = 4096
    threads = 2
    rust_threshold_mb = 10_000


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


def _write_corpus(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for i in range(rows):
            fh.write(
                json.dumps(
                    {"id": f"r{i}", "text": f"payload-{i % 97}", "metadata": {"i": i}},
                    ensure_ascii=False,
                )
                + "\n"
            )


class PythonFallbackStressW181(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lev-w181-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_python_streaming_50k_no_full_materialize_load(self) -> None:
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
        settings = _S(data_root)
        service = DatasetService(
            store,
            corpus=corpus,
            knowledge=knowledge,
            settings=settings,  # type: ignore[arg-type]
            allowed_import_roots=[data_root, corpus.root],
        )
        service.memory_policy = DatasetMemoryPolicy(
            memory_budget_bytes=512 * 1024 * 1024,
            max_record_bytes=4 * 1024 * 1024,
            native_mode="python",
            rust_threshold_bytes=10_000_000_000,
        )

        src = data_root / "stress_50k.jsonl"
        _write_corpus(src, 50_000)

        load_calls: list[str] = []

        def _forbidden_load(path, *args, **kwargs):
            # Allow tiny accidental probes under a few KB; refuse large corpus loads.
            try:
                size = Path(path).stat().st_size if path is not None else 0
            except OSError:
                size = 0
            load_calls.append(str(path))
            if size > 256 * 1024:
                raise AssertionError(
                    f"load_materialized_jsonl must not load large file ({size} bytes): {path}"
                )
            from Data.modules.datasets.materialize import load_materialized_jsonl as _real

            return _real(path, *args, **kwargs)

        env = {
            "LEVIATHAN_NATIVE_COMPUTE_DISABLED": "1",
            "LEVIATHAN_NATIVE_COMPUTE_MODE": "python",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch(
                "Data.modules.datasets.service.load_materialized_jsonl",
                side_effect=_forbidden_load,
            ):
                imported = service.import_local_sync(
                    str(src), name="stress_50k", materialize=True
                )
                ds_id = imported["dataset"]["datasetId"]
                ver = service.pick_usable_version(ds_id)
                assert ver is not None

                vjob = service.enqueue_validate(ds_id, ver.version_id)
                vdone = service.process_jobs(max_jobs=1)[0]
                self.assertEqual(vdone.job_id, vjob.job_id)
                self.assertEqual(vdone.status, DatasetJobStatus.COMPLETED)
                self.assertEqual(
                    (vdone.result or {}).get("backend"),
                    ComputeBackend.PYTHON_STREAMING.value,
                )

                tjob = service.enqueue_transform(
                    ds_id,
                    ver.version_id,
                    [{"name": "strip_whitespace", "params": {"strip": True}}],
                )
                tdone = service.process_jobs(max_jobs=1)[0]
                self.assertEqual(tdone.job_id, tjob.job_id)
                self.assertEqual(tdone.status, DatasetJobStatus.COMPLETED)
                transformed_id = (tdone.result or {}).get("versionId")
                self.assertTrue(transformed_id)

                sjob = service.enqueue_split(ds_id, transformed_id, seed=11)
                sdone = service.process_jobs(max_jobs=1)[0]
                self.assertEqual(sdone.job_id, sjob.job_id)
                self.assertEqual(sdone.status, DatasetJobStatus.COMPLETED)
                split_id = (sdone.result or {}).get("versionId")

                ejob = service.enqueue_export(ds_id, split_id or transformed_id)
                edone = service.process_jobs(max_jobs=1)[0]
                self.assertEqual(edone.job_id, ejob.job_id)
                self.assertEqual(edone.status, DatasetJobStatus.COMPLETED)
                self.assertEqual(
                    (edone.result or {}).get("backend"),
                    ComputeBackend.PYTHON_STREAMING.value,
                )

                djob = service.enqueue_dedupe(ds_id, ver.version_id)
                ddone = service.process_jobs(max_jobs=1)[0]
                self.assertEqual(ddone.job_id, djob.job_id)
                self.assertEqual(ddone.status, DatasetJobStatus.COMPLETED)

        # No large-file full loads observed
        self.assertEqual(load_calls, [])


if __name__ == "__main__":
    unittest.main()
