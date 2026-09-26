"""W10 — dataset recovery: fresh DB, tombstone, source missing, corrupt catalog, reindex."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.catalog import catalog_path
from Data.modules.datasets.recovery import RecoveryState
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.sidecar import SIDECAR_FILENAME
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import IndexStatus
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


class _K:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root


class _RI:
    datasets_auto_index_ready_to_knowledge = False
    datasets_recovery_auto_reindex = False
    datasets_recovery_max_auto_jobs = 8
    dataset_jobs_runner = "none"


class _S:
    def __init__(self, data_root: Path) -> None:
        self.knowledge = _K(data_root)
        self.research_integration = _RI()


class RecoveryCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.data_root / "leviathan")
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.settings = _S(self.data_root)
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=self.settings,  # type: ignore[arg-type]
            allowed_import_roots=[self.data_root, self.corpus.root],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _import_animal_csv(self) -> str:
        path = self.data_root / "animals_recovery.csv"
        path.write_text(
            "species,population,region\n"
            "Ursus arctos,1200,Scandinavia\n"
            "Canis lupus,400,Yellowstone\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(str(path), name="animals_recovery", materialize=True)
        return result["dataset"]["datasetId"]

    def test_fresh_db_restores_from_sidecar_and_catalog(self) -> None:
        ds_id = self._import_animal_csv()
        ver = self.service.pick_usable_version(ds_id)
        assert ver is not None
        self.service.enrich_semantic_deterministic(ds_id, ver.version_id, sync_artifacts=True)
        recovery = self.service.sync_recovery_artifacts(ds_id)
        self.assertTrue(Path(recovery["sidecarPath"]).is_file())
        self.assertTrue(Path(recovery["catalogPath"]).is_file())

        preserved_raw = self.corpus.datasets_raw / ds_id
        self.assertTrue(preserved_raw.exists())
        catalog_file = catalog_path(self.corpus)
        catalog_bytes = catalog_file.read_bytes()
        sidecar_bytes = (preserved_raw / SIDECAR_FILENAME).read_bytes()

        with tempfile.TemporaryDirectory() as fresh_dir:
            fresh_db = Path(fresh_dir) / "fresh.db"
            fresh_store = DatasetStore(fresh_db)
            fresh_store.initialize()
            fresh_knowledge = KnowledgeStore(
                fresh_db,
                data_root=self.data_root,
                embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
            )
            fresh_knowledge.initialize()
            catalog_file.write_bytes(catalog_bytes)
            (preserved_raw / SIDECAR_FILENAME).write_bytes(sidecar_bytes)

            fresh = DatasetService(
                fresh_store,
                corpus=self.corpus,
                knowledge=fresh_knowledge,
                settings=self.settings,  # type: ignore[arg-type]
                allowed_import_roots=[self.data_root, self.corpus.root],
            )
            self.assertIsNone(fresh.store.get_dataset(ds_id))
            result = fresh.reconcile_sidecars()
            self.assertGreaterEqual(result["created"], 1)
            self.assertIn(ds_id, result["restoredDatasetIds"])
            restored = fresh.get_dataset(ds_id)
            self.assertTrue(
                (restored.metadata or {}).get("restoredFromSidecar")
                or (restored.metadata or {}).get("restoredFromCatalog")
            )
            assessment = fresh.assess_dataset_recovery(ds_id)
            self.assertIn(
                assessment["recoveryState"],
                {
                    RecoveryState.METADATA_RESTORED.value,
                    RecoveryState.REINDEX_REQUIRED.value,
                    RecoveryState.READY.value,
                },
            )
            learning = fresh.learning_state_for_dataset(ds_id)
            self.assertFalse(learning.get("learned"))
            if assessment["recoveryState"] == RecoveryState.REINDEX_REQUIRED.value:
                self.assertTrue(assessment["reindexRequired"])
                self.assertFalse(assessment["brainLearned"])

    def test_tombstone_blocks_resurrection(self) -> None:
        ds_id = self._import_animal_csv()
        self.service.sync_recovery_artifacts(ds_id)
        raw_dir = self.corpus.datasets_raw / ds_id
        self.service.delete_dataset(ds_id, write_tombstone_file=True)
        self.assertTrue((raw_dir / ".leviathan-dataset.deleted").is_file())
        result = self.service.reconcile_sidecars()
        self.assertGreaterEqual(result["skippedTombstone"], 1)
        self.assertIsNone(self.service.store.get_dataset(ds_id))
        assessment = self.service.assess_dataset_recovery(ds_id)
        self.assertEqual(assessment["recoveryState"], RecoveryState.UNSUPPORTED.value)
        self.assertTrue(assessment["tombstoned"])

    def test_source_missing_assessment(self) -> None:
        ds_id = self._import_animal_csv()
        ds = self.service.get_dataset(ds_id)
        if ds.raw_path:
            path = Path(ds.raw_path)
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        for f in self.store.list_files(ds_id):
            p = Path(f.path)
            if p.is_file():
                p.unlink(missing_ok=True)
        for ver in self.store.list_versions(ds_id):
            if ver.storage_path:
                Path(ver.storage_path).unlink(missing_ok=True)
        assessment = self.service.assess_dataset_recovery(ds_id)
        self.assertEqual(assessment["recoveryState"], RecoveryState.SOURCE_MISSING.value)
        self.assertFalse(assessment["sourcePresent"])

    def test_corrupt_catalog_does_not_touch_db(self) -> None:
        ds_id = self._import_animal_csv()
        before = self.service.get_dataset(ds_id)
        path = catalog_path(self.corpus)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        status = self.service.catalog_status()
        self.assertFalse(status.get("valid"))
        result = self.service.reconcile_sidecars()
        corrupt = [c for c in result.get("conflicts") or [] if c.get("reason") == "corrupt_catalog"]
        self.assertTrue(corrupt or status.get("code") == "catalog_corrupt")
        after = self.service.get_dataset(ds_id)
        self.assertEqual(after.dataset_id, before.dataset_id)
        self.assertEqual(after.name, before.name)

    def test_brain_reindex_required_not_learned(self) -> None:
        ds_id = self._import_animal_csv()
        ver = self.service.pick_usable_version(ds_id)
        assert ver is not None
        self.service.enrich_semantic_deterministic(ds_id, ver.version_id, sync_artifacts=True)
        assessment = self.service.assess_dataset_recovery(ds_id)
        self.assertEqual(assessment["recoveryState"], RecoveryState.REINDEX_REQUIRED.value)
        self.assertTrue(assessment["reindexRequired"])
        self.assertFalse(assessment["brainLearned"])
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertNotEqual(learning.get("canonicalState"), "LEARNED")
        self.assertFalse(learning.get("learned"))

        self.store.create_index(
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=IndexStatus.READY,
            provenance={"documentCount": 2, "chunkCount": 2},
        )
        assessment2 = self.service.assess_dataset_recovery(ds_id)
        self.assertIn(
            assessment2["recoveryState"],
            {RecoveryState.READY.value, RecoveryState.METADATA_RESTORED.value},
        )
        self.assertFalse(assessment2["reindexRequired"])

    def test_enqueue_missing_semantic_profiles(self) -> None:
        ds_id = self._import_animal_csv()
        result = self.service.enqueue_missing_semantic_profiles(limit=10)
        self.assertGreaterEqual(result["enqueuedCount"], 1)
        ids = {e["datasetId"] for e in result["enqueued"]}
        self.assertIn(ds_id, ids)
        ver = self.service.pick_usable_version(ds_id)
        assert ver is not None
        self.service.enrich_semantic_deterministic(ds_id, ver.version_id)
        result2 = self.service.enqueue_missing_semantic_profiles(limit=10)
        for item in result2["enqueued"]:
            self.assertNotEqual(item["datasetId"], ds_id)

    def test_hash_mismatch_conflict(self) -> None:
        ds_id = self._import_animal_csv()
        self.service.sync_recovery_artifacts(ds_id)
        sidecar_path = self.corpus.datasets_raw / ds_id / SIDECAR_FILENAME
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        payload["contentHash"] = "deadbeef" * 8
        sidecar_path.write_text(json.dumps(payload), encoding="utf-8")
        assessment = self.service.assess_dataset_recovery(ds_id)
        self.assertEqual(assessment["recoveryState"], RecoveryState.HASH_MISMATCH.value)


class RecoveryApiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from Data.backend.routes.datasets import build_datasets_router

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.data_root / "leviathan")
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=_S(self.data_root),  # type: ignore[arg-type]
            allowed_import_roots=[self.data_root, self.corpus.root],
        )
        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_semantic_and_recovery_routes(self) -> None:
        path = self.data_root / "route_animals.csv"
        path.write_text("species,n\nFox,3\nWolf,2\n", encoding="utf-8")
        imported = self.service.import_local_sync(str(path), name="route_animals", materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        ver = self.service.pick_usable_version(ds_id)
        assert ver is not None

        analyze = self.client.post(
            f"/api/datasets/{ds_id}/semantic/analyze",
            json={"versionId": ver.version_id, "syncArtifacts": True},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        body = analyze.json()
        self.assertIn("semanticProfile", body)
        self.assertIn("displayName", body["semanticProfile"])

        patch = self.client.patch(
            f"/api/datasets/{ds_id}/semantic",
            json={
                "displayName": "Route Animals Ops",
                "primaryCategory": "ANIMALS_BIOLOGY",
                "tags": ["fauna"],
            },
        )
        self.assertEqual(patch.status_code, 200, patch.text)
        self.assertEqual(patch.json()["semanticProfile"]["displayName"], "Route Animals Ops")

        recovery = self.client.get(f"/api/datasets/{ds_id}/recovery")
        self.assertEqual(recovery.status_code, 200, recovery.text)
        self.assertIn("recoveryState", recovery.json()["recovery"])

        listing = self.client.get("/api/datasets?includeBrain=false")
        self.assertEqual(listing.status_code, 200)
        row = next(d for d in listing.json()["datasets"] if d["datasetId"] == ds_id)
        self.assertEqual(row.get("displayName"), "Route Animals Ops")
        self.assertIn("primaryCategory", row)

        catalog = self.client.get("/api/datasets/catalog")
        self.assertEqual(catalog.status_code, 200)


if __name__ == "__main__":
    unittest.main()
