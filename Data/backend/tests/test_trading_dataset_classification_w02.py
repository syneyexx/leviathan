"""WAVE 02 — trading dataset semantic classification and routing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.trading_classification import (
    DatasetDomain,
    DatasetRouteTarget,
    TradingDatasetKind,
    classify_trading_dataset,
)
from Data.modules.datasets.types import DatasetError, DatasetJobStatus
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider


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


class TradingClassificationUnitTests(unittest.TestCase):
    def test_ohlcv_columns_route_to_market_sim(self) -> None:
        c = classify_trading_dataset(
            name="btc_usdt_1m.csv",
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        self.assertEqual(c.domain, DatasetDomain.TRADING)
        self.assertEqual(c.trading_kind, TradingDatasetKind.MARKET_OHLCV)
        self.assertEqual(c.route, DatasetRouteTarget.MARKET_SIM_INGEST)

    def test_trading_book_routes_to_knowledge(self) -> None:
        c = classify_trading_dataset(
            name="Market Microstructure Paper.pdf",
            format_name="pdf",
        )
        self.assertEqual(c.domain, DatasetDomain.TRADING)
        self.assertEqual(c.trading_kind, TradingDatasetKind.TRADING_KNOWLEDGE)
        self.assertEqual(c.route, DatasetRouteTarget.KNOWLEDGE_INDEX)

    def test_trajectory_metadata_bridge(self) -> None:
        c = classify_trading_dataset(
            name="run",
            metadata={"kind": "trading_trajectory"},
        )
        self.assertEqual(c.trading_kind, TradingDatasetKind.TRAJECTORY_DATA)
        self.assertEqual(c.route, DatasetRouteTarget.TRAINING_BRIDGE)

    def test_unknown_trading_holds(self) -> None:
        c = classify_trading_dataset(name="trading_dump.bin")
        self.assertEqual(c.domain, DatasetDomain.TRADING)
        self.assertEqual(c.trading_kind, TradingDatasetKind.UNKNOWN_TRADING)
        self.assertEqual(c.route, DatasetRouteTarget.HOLD_OPERATOR)


class TradingClassificationServiceTests(unittest.TestCase):
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

        class _K:
            data_root = self.data_root

        class _RI:
            datasets_auto_index_ready_to_knowledge = True
            dataset_jobs_runner = "none"

        class _S:
            knowledge = _K()
            research_integration = _RI()

        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=_S(),  # type: ignore[arg-type]
            allowed_import_roots=[self.data_root, self.corpus.root],
        )
        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ohlcv_import_classifies_and_blocks_knowledge_auto_index(self) -> None:
        path = self.data_root / "AAPL_1d_ohlcv.csv"
        path.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2024-01-01,1,2,0.5,1.5,100\n"
            "2024-01-02,1.5,2.5,1,2,110\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(str(path), name="AAPL_1d_ohlcv", materialize=True)
        ds_id = result["dataset"]["datasetId"]
        classification = self.service.ensure_dataset_classification(ds_id)
        self.assertEqual(classification.trading_kind, TradingDatasetKind.MARKET_OHLCV)
        self.assertEqual(classification.route, DatasetRouteTarget.MARKET_SIM_INGEST)
        ver = self.service.pick_usable_version(ds_id)
        assert ver is not None
        auto = self.service._maybe_auto_index_ready_version(ds_id, ver.version_id)
        self.assertIsNotNone(auto)
        self.assertFalse(auto.get("enqueued"))
        self.assertEqual(auto.get("reason"), "routed_away_from_knowledge")
        with self.assertRaises(DatasetError) as ctx:
            self.service.enqueue_learn_to_brain(ds_id)
        self.assertEqual(ctx.exception.code, "classification_route_blocks_knowledge")

    def test_knowledge_text_still_indexes(self) -> None:
        path = self.data_root / "trading_risk_management_book.jsonl"
        path.write_text(
            json.dumps({"id": "1", "text": "volatility contraction precedes expansion"}) + "\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(
            str(path), name="trading_risk_management_book", materialize=True
        )
        ds_id = result["dataset"]["datasetId"]
        c = self.service.ensure_dataset_classification(ds_id)
        self.assertEqual(c.trading_kind, TradingDatasetKind.TRADING_KNOWLEDGE)
        job = self.service.enqueue_learn_to_brain(ds_id)
        done = self.service.process_jobs(max_jobs=3)[-1]
        self.assertEqual(done.job_id, job.job_id)
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)

    def test_operator_override_and_api(self) -> None:
        path = self.data_root / "mystery.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        result = self.service.import_local_sync(str(path), name="mystery", materialize=True)
        ds_id = result["dataset"]["datasetId"]
        res = self.client.post(
            f"/api/datasets/{ds_id}/classification/override",
            json={
                "domain": "TRADING",
                "tradingKind": "MARKET_OHLCV",
                "reason": "operator confirmed ohlcv",
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["classification"]["tradingKind"], "MARKET_OHLCV")
        self.assertTrue(body["classification"]["operatorOverride"])
        got = self.client.get(f"/api/datasets/{ds_id}/classification")
        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.json()["marketSimIngestRecommended"])
        self.assertFalse(got.json()["knowledgeAutoIndexAllowed"])

    def test_provenance_fields_persisted(self) -> None:
        path = self.data_root / "news_headlines.jsonl"
        path.write_text(
            json.dumps({"id": "1", "text": "Fed hikes rates", "published_at": "2024-01-01"})
            + "\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(
            str(path), name="market_news_feed", materialize=True
        )
        ds_id = result["dataset"]["datasetId"]
        c = self.service.ensure_dataset_classification(ds_id, force=True)
        self.assertEqual(c.trading_kind, TradingDatasetKind.NEWS)
        ds = self.service.get_dataset(ds_id)
        persisted = (ds.metadata or {}).get("classification") or {}
        self.assertEqual(persisted.get("tradingKind"), "NEWS")
        self.assertIn("method", persisted)
        self.assertIn("confidence", persisted)
        self.assertIn("route", persisted)


if __name__ == "__main__":
    unittest.main()
