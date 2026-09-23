"""Tests for research/dataset assimilation and staged retrieval wiring."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    SourceType,
    VersionKind,
    VersionStatus,
)
from Data.modules.intelligence import KnowledgeAssimilationService
from Data.modules.knowledge import (
    HybridRetriever,
    KnowledgeStore,
    RetrievalMode,
    RetrievalQuery,
    StagedRetriever,
    build_embedding_provider,
    resolve_use_reranker,
)
from Data.modules.research import ResearchService, ResearchStatus
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import (
    ClaimStatus,
    ParseStatus,
    ResearchClaim,
    ResearchEvidence,
    ResearchSource,
    SourceType as ResearchSourceType,
)
from Data.modules.research.web import UnconfiguredWebProvider


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


class ResearchPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "lev.db"
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.root / "k",
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        self.assimilation = KnowledgeAssimilationService(database_path=self.db)
        self.events: list[tuple[str, str, dict[str, Any]]] = []

        def _emit(category: str, name: str, **kwargs: Any) -> None:
            self.events.append((category, name, dict(kwargs.get("payload") or {})))

        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.service = ResearchService(
            self.store,
            knowledge=self.knowledge,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            assimilation_service=self.assimilation,
            observability_emit=_emit,
            auto_promote_verified_knowledge=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_project_with_claim(
        self,
        *,
        status: ClaimStatus = ClaimStatus.SUPPORTED,
        supporting: list[str] | None = None,
        contradicting: list[str] | None = None,
        speculative: bool = False,
        suffix: str = "1",
    ) -> str:
        project = self.service.create_project(
            topic="Does local research promote verified claims?",
            objective="Assimilation provenance",
            depth="quick",
            allow_web=False,
        )
        source_id = f"src-{suffix}"
        evidence_id = f"ev-{suffix}"
        claim_id = f"claim-{suffix}"
        source = ResearchSource(
            source_id=source_id,
            project_id=project.project_id,
            source_type=ResearchSourceType.SEED,
            created_at=project.created_at,
            title="Fixture source",
            original_uri=f"fixture://claim-{suffix}",
            canonical_uri=f"fixture://claim-{suffix}",
            parse_status=ParseStatus.OK,
        )
        self.store.upsert_source(source)
        evidence = ResearchEvidence(
            evidence_id=evidence_id,
            project_id=project.project_id,
            source_id=source_id,
            span_text="Verified claim: LEVIATHAN promotes evidence-backed research claims.",
            created_at=project.created_at,
            retrieval_method="fixture",
        )
        self.store.add_evidence(evidence)
        claim = ResearchClaim(
            claim_id=claim_id,
            project_id=project.project_id,
            proposition="LEVIATHAN promotes evidence-backed research claims.",
            status=status,
            created_at=project.created_at,
            updated_at=project.created_at,
            supporting_evidence_ids=list(
                supporting if supporting is not None else [evidence_id]
            ),
            contradicting_evidence_ids=list(contradicting or []),
            metadata={"speculative": speculative} if speculative else {},
        )
        self.store.upsert_claim(claim)
        # Mark completed without full runner — exercise promotion path directly.
        project.status = ResearchStatus.COMPLETED
        self.store.save_project(project)
        return project.project_id

    def test_research_promotion_creates_knowledge_doc_with_provenance(self) -> None:
        project_id = self._seed_project_with_claim()
        project = self.service.get_project(project_id)
        self.service._maybe_promote_knowledge(project)

        refreshed = self.service.get_project(project_id)
        receipt = (refreshed.model_profile or {}).get("knowledge_promotion") or {}
        self.assertTrue(receipt.get("ok") or receipt.get("success_count", 0) > 0)
        self.assertGreaterEqual(int(receipt.get("success_count") or 0), 1)
        doc_ids = list(receipt.get("document_ids") or [])
        self.assertTrue(doc_ids)

        doc_id = doc_ids[0]
        doc = self.knowledge.get_document(doc_id)
        self.assertIsNotNone(doc)
        trust = dict(getattr(doc, "trust_metadata", None) or {})
        if not trust and hasattr(doc, "public_dict"):
            trust = dict((doc.public_dict().get("trust_metadata") or {}))
        # Provenance must point at assimilation / research project.
        self.assertTrue(
            trust.get("research_project_id") == project_id
            or "research" in str(getattr(doc, "source", "")),
            msg=f"missing provenance on {doc}",
        )
        promoted = [e for e in self.events if e[1] == "knowledge_promoted"]
        self.assertTrue(promoted)

    def test_contradicted_and_unsupported_claims_rejected(self) -> None:
        project_id = self._seed_project_with_claim(
            status=ClaimStatus.DISPUTED,
            supporting=["ev-disp"],
            contradicting=["ev-x"],
            suffix="disp",
        )
        project = self.service.get_project(project_id)
        self.service._maybe_promote_knowledge(project)
        receipt = (self.service.get_project(project_id).model_profile or {}).get(
            "knowledge_promotion"
        ) or {}
        self.assertEqual(int(receipt.get("success_count") or 0), 0)
        skipped = {s.get("reason") for s in (receipt.get("skipped") or [])}
        self.assertIn("contradicted", skipped)

        project_id2 = self._seed_project_with_claim(
            status=ClaimStatus.UNSUPPORTED, suffix="unsup"
        )
        # Force unique claim id by direct assimilate call
        claims = self.store.list_claims(project_id2)
        receipt2 = self.assimilation.assimilate_research_project(
            self.service.get_project(project_id2),
            claims=claims,
            evidence=self.store.list_evidence(project_id2),
            knowledge_store=self.knowledge,
        )
        self.assertEqual(receipt2.success_count, 0)
        reasons = {s.get("reason") for s in receipt2.skipped}
        self.assertTrue(any("speculative" in (r or "") or "status_not_promotable" in (r or "") for r in reasons))


class DatasetIndexEmbeddingPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "ds.db"
        self.corpus = _layout(self.root / "corpus")
        self.knowledge = KnowledgeStore(self.db, data_root=self.root / "k")
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            allowed_import_roots=[self.corpus.root],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_handle_index_uses_embedding_provider_status(self) -> None:
        # KnowledgeStore exposes embedding_provider, not embeddings.
        self.assertTrue(hasattr(self.knowledge, "embedding_provider"))
        self.assertFalse(hasattr(self.knowledge, "embeddings") and getattr(self.knowledge, "embeddings", None) is not None)

        status_calls: list[str] = []

        class _Prov:
            provider_id = "test"

            def available(self) -> bool:
                return False

            def status(self) -> dict[str, Any]:
                status_calls.append("status")
                return {"provider_id": "test", "available": False, "is_semantic": False}

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                raise RuntimeError("unavailable")

            def embed_query(self, text: str) -> list[float]:
                raise RuntimeError("unavailable")

        self.knowledge.embedding_provider = _Prov()  # type: ignore[assignment]

        ds = self.store.create_dataset(name="idx", source_type=SourceType.LOCAL)
        path = self.corpus.datasets_materialized / ds.dataset_id / "canonical.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"id":"1","text":"hello world example for indexing","metadata":{}}\n',
            encoding="utf-8",
        )
        ver = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="mat-v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
            storage_path=str(path),
        )
        job = self.service.enqueue_index(ds.dataset_id, ver.version_id)
        # Run handler directly
        filled = self.store.get_job(job.job_id)
        assert filled is not None
        result = self.service._handle_index(filled)
        self.assertIn("indexId", result)
        self.assertTrue(status_calls, msg="embedding_provider.status() must be consulted")

    def test_auto_index_enqueued_when_ready(self) -> None:
        self.service.datasets_auto_index_ready_to_knowledge = True
        ds = self.store.create_dataset(name="auto", source_type=SourceType.LOCAL)
        path = self.corpus.datasets_materialized / ds.dataset_id / "canonical.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"id":"1","text":"auto index content about neural retrieval","metadata":{}}\n',
            encoding="utf-8",
        )
        outcome = {
            "rowCount": 1,
            "byteSize": path.stat().st_size,
            "contentHash": "abc",
            "validation": {"valid": True, "rowCount": 1},
        }
        with mock.patch.object(self.service, "enqueue_index", wraps=self.service.enqueue_index) as enq:
            published = self.service._publish_materialized_version(
                ds.dataset_id, dest=path, outcome=outcome
            )
        self.assertIn("autoIndex", published)
        self.assertTrue(published["autoIndex"].get("enqueued"))
        self.assertTrue(enq.called)

        # Second call should skip already indexed / pending
        again = self.service._maybe_auto_index_ready_version(
            ds.dataset_id, published["versionId"]
        )
        self.assertEqual(again.get("reason"), "already_indexed")


class StagedRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"
        embeddings = build_embedding_provider(kind="hash", hash_dimensions=32)
        self.store = KnowledgeStore(
            self.db,
            data_root=self.root / "data",
            chunk_max_chars=300,
            chunk_overlap=20,
            embedding_provider=embeddings,
        )
        self.store.initialize()
        self.store.upsert_document(
            title="Exact phrase doc",
            content="LEVIATHAN staged retrieval early exit probe token alphabeta",
            source="fixture",
        )
        self.store.upsert_document(
            title="Broader topic",
            content="Hybrid retrieval fuses lexical ranks with dense embeddings using RRF.",
            source="fixture",
        )
        self.hybrid = HybridRetriever(self.store, embeddings=embeddings)
        self.staged = StagedRetriever(self.hybrid, rerank_policy="off")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_early_exit_for_high_confidence_trivial(self) -> None:
        self.staged.early_exit_enabled = True
        result = self.staged.search("alphabeta", limit=3)
        self.assertTrue(result.stages)
        self.assertEqual(result.stages[0].stage, "A")
        # Unique token must retrieve the seeded document.
        self.assertGreaterEqual(len(result.hits), 1)
        if result.early_exit:
            self.assertEqual(result.coverage, "high")
            stage_actions = [s.action for s in result.stages]
            self.assertIn("early_exit", stage_actions)

    def test_hybrid_path_smoke(self) -> None:
        # Longer / lower-confidence query should run hybrid stage.
        result = self.staged.search(
            "How does hybrid retrieval fuse lexical and dense ranks?",
            limit=5,
        )
        actions = {s.action for s in result.stages}
        self.assertIn("hybrid", actions)
        self.assertFalse(result.early_exit)
        self.assertIsNotNone(result.embedding_is_semantic)
        self.assertFalse(result.embedding_is_semantic)  # hash provider
        # Rerank policy off
        self.assertFalse(result.rerank_applied)

    def test_resolve_use_reranker_policy(self) -> None:
        self.assertFalse(resolve_use_reranker("off", reranker_available=True))
        self.assertFalse(resolve_use_reranker("always", reranker_available=False))
        self.assertTrue(resolve_use_reranker("always", reranker_available=True))
        self.assertTrue(resolve_use_reranker("auto", reranker_available=True))

    def test_hybrid_retriever_honors_use_reranker_flag(self) -> None:
        q = RetrievalQuery(
            text="hybrid retrieval",
            limit=3,
            use_reranker=False,
            mode=RetrievalMode.HYBRID,
        )
        hits = self.hybrid.search(q)
        self.assertIsInstance(hits, list)


if __name__ == "__main__":
    unittest.main()
