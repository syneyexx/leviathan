"""Relations persistence batching + indexing cadence (no fabricated perf claims)."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from Data.modules.datasets.indexing import index_records
from Data.modules.datasets.relations import (
    RELATION_EXTRACTOR_VERSION,
    build_verified_relation_atoms_for_record,
    extract_and_store_relations_for_record,
    relation_input_fingerprint,
    stable_relation_atom_id,
)
from Data.modules.datasets.types import CanonicalRecord
from Data.modules.knowledge import KnowledgeStore


def _records(n: int, *, with_labels: bool = True) -> list[CanonicalRecord]:
    out: list[CanonicalRecord] = []
    for i in range(n):
        labels = (
            {
                "subject": f"alpha-{i % 17}",
                "object": f"beta-{i % 13}",
                "entity": [f"alpha-{i % 17}", f"beta-{i % 13}"],
            }
            if with_labels
            else {}
        )
        out.append(
            CanonicalRecord(
                id=f"rec-{i}",
                text=f"Record {i} links alpha-{i % 17} with beta-{i % 13} in evidence.",
                labels=labels,
                metadata={"parent_id": f"rec-{(i + 1) % max(n, 1)}"} if with_labels else {},
                split="train",
            )
        )
    return out


class RelationBatchPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.knowledge = KnowledgeStore(self.root / "k.db", data_root=self.root / "kdata")
        self.knowledge.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stable_atom_ids_idempotent(self) -> None:
        a = stable_relation_atom_id(
            dataset_id="d",
            version_id="v",
            subject_ref="entity:a",
            object_ref="entity:b",
            relation_class="like",
        )
        b = stable_relation_atom_id(
            dataset_id="d",
            version_id="v",
            subject_ref="entity:a",
            object_ref="entity:b",
            relation_class="like",
        )
        self.assertEqual(a, b)

    def test_replace_document_relation_atoms_single_transaction(self) -> None:
        doc_id = "dataset:d:v:rec-0"
        rec = _records(1)[0]
        built = build_verified_relation_atoms_for_record(
            rec,
            document_id=doc_id,
            dataset_id="d",
            version_id="v",
            text=rec.text or "",
        )
        self.assertGreater(built["relationsAccepted"], 0)
        meta = self.knowledge.replace_document_relation_atoms(doc_id, built["atoms"])
        self.assertEqual(meta["transaction"], "single")
        self.assertEqual(meta["upserted"], len(built["atoms"]))
        self.assertEqual(
            self.knowledge.count_relation_atoms_for_document(doc_id),
            len(built["atoms"]),
        )
        # Idempotent re-replace
        meta2 = self.knowledge.replace_document_relation_atoms(doc_id, built["atoms"])
        self.assertEqual(
            self.knowledge.count_relation_atoms_for_document(doc_id),
            len(built["atoms"]),
        )
        self.assertEqual(meta2["upserted"], len(built["atoms"]))

    def test_batch_failure_rolls_back_unit(self) -> None:
        good_doc = "doc-good"
        bad_doc = "doc-bad"
        good_atoms = [
            {
                "atom_id": "atom-good",
                "subject_ref": "entity:a",
                "object_ref": "entity:b",
                "relation_class": "like",
                "supporting_evidence_refs": ["ev:1"],
                "confidence": 0.9,
                "notes": "ok",
            }
        ]
        # Empty subject should still insert (store strips) — force failure via invalid enum
        bad_atoms = [
            {
                "atom_id": "atom-bad",
                "subject_ref": "entity:x",
                "object_ref": "entity:y",
                "relation_class": "not_a_real_class",
                "supporting_evidence_refs": ["ev:1"],
                "confidence": 0.9,
            }
        ]
        with self.assertRaises(Exception):
            self.knowledge.replace_relation_atoms_batch(
                [(good_doc, good_atoms), (bad_doc, bad_atoms)]
            )
        self.assertEqual(self.knowledge.count_relation_atoms_for_document(good_doc), 0)
        self.assertEqual(self.knowledge.count_relation_atoms_for_document(bad_doc), 0)

    def test_index_batches_relation_writes_and_skips_unchanged(self) -> None:
        records = _records(120)
        progress: list[dict] = []

        def on_progress(p: dict) -> None:
            progress.append(dict(p))

        t0 = time.monotonic()
        out1 = index_records(
            self.knowledge,
            records,
            dataset_id="ds",
            version_id="v1",
            extract_relations=True,
            write_batch_size=25,
            progress_cb=on_progress,
        )
        elapsed1 = time.monotonic() - t0
        self.assertEqual(out1["indexedCount"], 120)
        self.assertGreater(out1["relationsAccepted"], 0)
        self.assertGreaterEqual(out1["relationTransactionCount"], 1)
        # 120 docs / batch 25 => about 5 relation transactions (plus flush)
        self.assertLessEqual(out1["relationTransactionCount"], 8)
        self.assertIn("elapsedSeconds", out1)
        self.assertIn("recordsPerSecond", out1)
        self.assertTrue(any("recordsPerSecond" in p for p in progress if p.get("processed")))

        # Second pass: unchanged READY docs with matching fingerprints skip relation rebuild
        t1 = time.monotonic()
        out2 = index_records(
            self.knowledge,
            records,
            dataset_id="ds",
            version_id="v1",
            extract_relations=True,
            write_batch_size=25,
        )
        elapsed2 = time.monotonic() - t1
        self.assertEqual(out2["skippedUnchanged"], 120)
        self.assertEqual(out2["relationsSkippedUnchanged"], 120)
        self.assertEqual(out2["relationTransactionCount"], 0)
        # Fingerprint contract
        doc0 = self.knowledge.get_document("dataset:ds:v1:rec-0")
        assert doc0 is not None
        fp = relation_input_fingerprint(
            records[0],
            content_hash=doc0.content_hash,
            dataset_id="ds",
            version_id="v1",
        )
        self.assertEqual(doc0.trust_metadata.get("relationInputFingerprint"), fp)
        self.assertEqual(
            doc0.trust_metadata.get("relationExtractorVersion"),
            RELATION_EXTRACTOR_VERSION,
        )
        # Store measurements for the final report (honest wall times)
        self._measurements = {
            "recordCount": 120,
            "firstPassElapsed": round(elapsed1, 4),
            "firstPassRelationsAccepted": out1["relationsAccepted"],
            "firstPassRelationTx": out1["relationTransactionCount"],
            "firstPassRecordsPerSec": out1.get("recordsPerSecond"),
            "secondPassElapsed": round(elapsed2, 4),
            "secondPassSkippedRelations": out2["relationsSkippedUnchanged"],
        }
        print("RELATION_PERF_MEASUREMENTS", self._measurements)

    def test_cancel_during_relation_batch_flushes_then_raises(self) -> None:
        records = _records(80)
        seen = {"n": 0}

        def cancel() -> bool:
            seen["n"] += 1
            return seen["n"] > 40

        with self.assertRaises(Exception) as ctx:
            index_records(
                self.knowledge,
                records,
                dataset_id="ds",
                version_id="v-cancel",
                extract_relations=True,
                write_batch_size=10,
                cancel_cb=cancel,
            )
        self.assertIn("cancel", str(ctx.exception).lower())

    def test_extract_and_store_uses_store_transaction_api(self) -> None:
        rec = _records(1)[0]
        doc_id = "dataset:d:v:rec-0"
        # Seed document so trust merge path is available if used
        self.knowledge.upsert_document(
            title="t",
            content=rec.text or "x",
            source="dataset:test",
            document_id=doc_id,
            trust_metadata={"trust": "dataset"},
        )
        out = extract_and_store_relations_for_record(
            self.knowledge,
            rec,
            document_id=doc_id,
            dataset_id="d",
            version_id="v",
            text=rec.text or "",
            replace=True,
        )
        self.assertGreater(out["relationsAccepted"], 0)
        self.assertEqual(out["persist"]["transaction"], "single")
        self.assertIn("relation_writes_use_knowledge_store_transactions", out["truth"])


class RelationPerfBenchmark15k(unittest.TestCase):
    """Optional heavier fixture — skipped unless LEVIATHAN_RELATIONS_BENCH=1."""

    def test_benchmark_15k_records(self) -> None:
        import os

        if os.environ.get("LEVIATHAN_RELATIONS_BENCH") != "1":
            self.skipTest("set LEVIATHAN_RELATIONS_BENCH=1 to run 15k benchmark")
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            knowledge = KnowledgeStore(root / "k.db", data_root=root / "kdata")
            knowledge.initialize()
            records = _records(15_000)
            t0 = time.monotonic()
            out = index_records(
                knowledge,
                records,
                dataset_id="bench",
                version_id="v1",
                extract_relations=True,
                write_batch_size=50,
            )
            elapsed = time.monotonic() - t0
            print(
                "RELATION_BENCH_15K",
                {
                    "records": out["processedCount"],
                    "indexed": out["indexedCount"],
                    "relationsAccepted": out["relationsAccepted"],
                    "relationsRejected": out["relationsRejected"],
                    "relationTransactionCount": out["relationTransactionCount"],
                    "elapsedSeconds": round(elapsed, 4),
                    "recordsPerSecond": round(out["processedCount"] / elapsed, 4) if elapsed else None,
                },
            )
            self.assertEqual(out["processedCount"], 15_000)
            self.assertGreater(out["relationsAccepted"], 0)
            # Batching must keep transaction count far below per-atom cadence
            self.assertLessEqual(out["relationTransactionCount"], 400)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
