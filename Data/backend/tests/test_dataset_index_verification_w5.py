"""Wave 5 / P1-001 — Index integrity receipt before READY."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.indexing import (
    build_index_integrity_receipt,
    classify_verification_evidence,
    index_records,
    verify_index_integrity,
)
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    CanonicalRecord,
    DatasetJobStatus,
    DatasetError,
    IndexStatus,
)
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


class IndexIntegrityReceiptW5Tests(unittest.TestCase):
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
            embedding_provider = "hash"
            hash_dimensions = 32

        class _RI:
            datasets_auto_index_ready_to_knowledge = False
            dataset_jobs_runner = "none"
            dataset_index_batch_size = 5
            dataset_max_relations_per_doc = 12
            dataset_extract_relations = True

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
        self.service.datasets_auto_index_ready_to_knowledge = False

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _import_and_learn(self, name: str = "w5.jsonl") -> str:
        path = self.data_root / name
        path.write_text(
            "\n".join(
                json.dumps({"id": str(i), "text": f"integrity signal {i} alpha"})
                for i in range(1, 4)
            )
            + "\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(str(path), name=name, materialize=True)
        ds_id = result["dataset"]["datasetId"]
        ds = self.service.get_dataset(ds_id)
        meta = dict(ds.metadata or {})
        meta["forceKnowledgeIndex"] = True
        self.store.update_dataset(ds_id, metadata=meta)
        job = self.service.enqueue_learn_to_brain(ds_id)
        done_list = self.service.process_jobs(max_jobs=5)
        done = next((j for j in done_list if j.job_id == job.job_id), None)
        self.assertIsNotNone(done)
        assert done is not None
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        return ds_id

    def test_receipt_fields_and_pass_on_learn(self) -> None:
        ds_id = self._import_and_learn()
        indexes = self.store.list_indexes(ds_id)
        ready = [i for i in indexes if i.status == IndexStatus.READY]
        self.assertEqual(len(ready), 1)
        prov = ready[0].provenance or {}
        receipt = prov.get("integrityReceipt")
        self.assertIsInstance(receipt, dict)
        for key in (
            "datasetId",
            "versionId",
            "sourceFingerprint",
            "indexId",
            "expectedRecords",
            "uniqueDocumentCount",
            "presentDocumentCount",
            "chunkCount",
            "embeddingMode",
            "embeddingsSemantic",
            "relationsAccepted",
            "relationsRejected",
            "manifestHash",
            "completedAt",
            "verificationStatus",
            "evidenceClass",
        ):
            self.assertIn(key, receipt, key)
        self.assertEqual(receipt["verificationStatus"], "PASS")
        self.assertIn(receipt["evidenceClass"], {"EXACT", "SAMPLED"})
        self.assertTrue(receipt.get("receiptPath"))
        path = Path(str(receipt["receiptPath"]))
        self.assertTrue(path.exists())
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning["canonicalState"], "LEARNED")

    def test_verification_failure_blocks_ready_and_learned(self) -> None:
        path = self.data_root / "fail.jsonl"
        path.write_text(
            json.dumps({"id": "1", "text": "will fail verification"}) + "\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(str(path), name="fail.jsonl", materialize=True)
        ds_id = result["dataset"]["datasetId"]
        meta = dict(self.service.get_dataset(ds_id).metadata or {})
        meta["forceKnowledgeIndex"] = True
        self.store.update_dataset(ds_id, metadata=meta)

        def _fail(*_a, **_k):
            return build_index_integrity_receipt(
                dataset_id=ds_id,
                version_id="v",
                source_fingerprint="fp",
                index_id="idx",
                expected_records=1,
                unique_document_count=1,
                present_document_count=0,
                chunk_count=1,
                present_chunk_count=0,
                embedding_mode="lexical_only",
                embeddings_semantic=False,
                relations_accepted=0,
                relations_rejected=0,
                present_relation_count=0,
                manifest_hash="deadbeef",
                evidence_class="EXACT",
                verification_status="FAIL",
                verification_errors=["present_document_count=0 != unique_document_count=1"],
            )

        with mock.patch(
            "Data.modules.datasets.indexing.verify_index_integrity",
            side_effect=_fail,
        ):
            job = self.service.enqueue_learn_to_brain(ds_id)
            done_list = self.service.process_jobs(max_jobs=5)
            done = next((j for j in done_list if j.job_id == job.job_id), None)
            self.assertIsNotNone(done)
            assert done is not None
            self.assertEqual(done.status, DatasetJobStatus.FAILED)

        indexes = self.store.list_indexes(ds_id)
        self.assertTrue(indexes)
        self.assertTrue(all(i.status != IndexStatus.READY for i in indexes))
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertNotEqual(learning["canonicalState"], "LEARNED")
        self.assertFalse(learning["learned"])

    def test_evidence_class_honesty(self) -> None:
        self.assertEqual(
            classify_verification_evidence(
                present_docs_exact=True,
                present_chunks_exact=True,
                relations_exact=True,
            ),
            "EXACT",
        )
        self.assertEqual(
            classify_verification_evidence(
                present_docs_exact=False,
                present_chunks_exact=False,
                relations_exact=False,
                sampled_presence=True,
            ),
            "SAMPLED",
        )
        self.assertEqual(
            classify_verification_evidence(
                present_docs_exact=False,
                present_chunks_exact=False,
                relations_exact=False,
                sampled_presence=False,
            ),
            "UNMEASURED",
        )

    def test_doc_ids_bounded_sample_p1_010(self) -> None:
        records = [
            CanonicalRecord(id=str(i), text=f"row {i} content for indexing")
            for i in range(40)
        ]
        outcome = index_records(
            self.knowledge,
            records,
            dataset_id="ds-bound",
            version_id="ver-bound",
            extract_relations=False,
        )
        self.assertEqual(outcome["documentCount"], 40)
        self.assertLessEqual(len(outcome["documentIdsSample"]), 20)
        self.assertTrue(outcome["truth"]["document_ids_are_bounded_sample"])

    def test_resume_marker_missing_fails_closed_p1_012(self) -> None:
        records = [
            CanonicalRecord(id="a", text="alpha content"),
            CanonicalRecord(id="b", text="beta content"),
        ]
        with self.assertRaises(DatasetError) as ctx:
            index_records(
                self.knowledge,
                records,
                dataset_id="ds-resume",
                version_id="ver-resume",
                resume_after_record_id="MISSING-MARKER",
                extract_relations=False,
            )
        self.assertEqual(ctx.exception.code, "resume_marker_missing")

    def test_verify_index_integrity_direct_pass(self) -> None:
        records = [CanonicalRecord(id="1", text="direct verify body")]
        outcome = index_records(
            self.knowledge,
            records,
            dataset_id="ds-direct",
            version_id="ver-direct",
            extract_relations=False,
        )
        receipt = verify_index_integrity(
            self.knowledge,
            dataset_id="ds-direct",
            version_id="ver-direct",
            source_fingerprint="abc123",
            index_id="idx-1",
            outcome=outcome,
            manifest={"k": "v"},
            expected_records=1,
        )
        self.assertEqual(receipt["verificationStatus"], "PASS")
        self.assertEqual(receipt["evidenceClass"], "EXACT")
        self.assertEqual(receipt["presentDocumentCount"], 1)


if __name__ == "__main__":
    unittest.main()
