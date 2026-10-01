"""Wave 8 — Dedupe / transforms / provenance (P1-008, P1-009)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.datasets.dedupe import (
    DEDUPE_REASON_EXACT_CONTENT,
    WINNER_POLICY_FIRST,
    exact_dedupe,
    exact_dedupe_external_to_list,
    record_fingerprint,
)
from Data.modules.datasets.transforms import (
    RESERVED_CANONICAL_METADATA_KEYS,
    apply_transforms,
)
from Data.modules.datasets.types import CanonicalRecord, DatasetError


def _rec(
    rid: str,
    text: str,
    *,
    split: str | None = None,
    metadata: dict | None = None,
) -> CanonicalRecord:
    return CanonicalRecord(
        id=rid,
        text=text,
        metadata=dict(metadata or {}),
        split=split,
    )


class DatasetProvenanceW8Tests(unittest.TestCase):
    def test_p1_008_set_metadata_preserves_reserved_canonical_keys(self) -> None:
        reserved = {
            "source": {"kind": "import"},
            "sourcePath": "/data/train.jsonl",
            "sourceHash": "deadbeef",
            "datasetId": "ds-1",
            "versionId": "ver-1",
            "lineage": [{"name": "import"}],
            "trust": "dataset",
        }
        rec = _rec("r1", "hello", metadata=dict(reserved))
        out, lineage = apply_transforms(
            [rec],
            [
                {
                    "name": "set_metadata",
                    "params": {
                        "metadata": {
                            "source": "ATTACK",
                            "sourcePath": "/evil",
                            "sourceHash": "0000",
                            "datasetId": "hijack",
                            "versionId": "hijack",
                            "lineage": [],
                            "trust": "forged",
                            "tag": "ok",
                        }
                    },
                }
            ],
        )
        self.assertEqual(len(out), 1)
        meta = out[0].metadata
        for key in RESERVED_CANONICAL_METADATA_KEYS:
            self.assertEqual(meta[key], reserved[key], key)
        self.assertEqual(meta.get("tag"), "ok")
        # Reserved attempts land under user namespace.
        self.assertEqual(meta["user"]["source"], "ATTACK")
        self.assertEqual(meta["user"]["datasetId"], "hijack")
        self.assertEqual(len(lineage), 1)

    def test_p1_008_set_metadata_operator_namespace(self) -> None:
        rec = _rec(
            "r1",
            "hello",
            metadata={"sourcePath": "/kept", "datasetId": "ds"},
        )
        out, _ = apply_transforms(
            [rec],
            [
                {
                    "name": "set_metadata",
                    "params": {
                        "namespace": "operator",
                        "metadata": {"sourcePath": "/op", "label": "reviewed"},
                    },
                }
            ],
        )
        meta = out[0].metadata
        self.assertEqual(meta["sourcePath"], "/kept")
        self.assertEqual(meta["datasetId"], "ds")
        self.assertEqual(meta["operator"]["sourcePath"], "/op")
        self.assertEqual(meta["label"], "reviewed")

    def test_p1_008_invalid_namespace_rejected(self) -> None:
        with self.assertRaises(DatasetError) as ctx:
            apply_transforms(
                [_rec("r1", "x")],
                [
                    {
                        "name": "set_metadata",
                        "params": {
                            "namespace": "trust",
                            "metadata": {"a": 1},
                        },
                    }
                ],
            )
        self.assertEqual(ctx.exception.code, "invalid_transform")

    def test_p1_009_dedupe_preserves_lineage_and_exposes_reason(self) -> None:
        records = [
            _rec(
                "a",
                "same",
                split="train",
                metadata={
                    "sourcePath": "/a.jsonl",
                    "sourceHash": "h1",
                    "datasetId": "ds",
                },
            ),
            _rec("b", "other", split="train"),
            _rec(
                "c",
                "same",
                split="train",
                metadata={
                    "sourcePath": "/c.jsonl",
                    "sourceHash": "h2",
                    "datasetId": "ds",
                },
            ),
        ]
        kept, stats = exact_dedupe(records)
        self.assertEqual([r.id for r in kept], ["a", "b"])
        self.assertEqual(stats["winnerPolicy"], WINNER_POLICY_FIRST)
        self.assertTrue(stats["lineagePreserved"])
        self.assertEqual(stats["reasons"][DEDUPE_REASON_EXACT_CONTENT], 1)
        self.assertEqual(stats["removedCount"], 1)
        winner = kept[0]
        lineage = winner.metadata.get("lineage") or []
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0]["reason"], DEDUPE_REASON_EXACT_CONTENT)
        self.assertEqual(lineage[0]["winnerId"], "a")
        self.assertEqual(lineage[0]["collapsedId"], "c")
        self.assertTrue(lineage[0]["crossSource"])
        self.assertFalse(lineage[0]["crossSplit"])
        self.assertEqual(winner.metadata.get("dedupeReason"), DEDUPE_REASON_EXACT_CONTENT)
        self.assertEqual(stats["collapseEvents"][0]["collapsedId"], "c")

    def test_p1_009_cross_split_duplication_detected(self) -> None:
        records = [
            _rec("train-1", "leak", split="train", metadata={"sourcePath": "/train"}),
            _rec("test-1", "leak", split="test", metadata={"sourcePath": "/test"}),
        ]
        kept, stats = exact_dedupe(records)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].id, "train-1")
        self.assertEqual(stats["crossSplitDuplicateCount"], 1)
        self.assertTrue(kept[0].metadata.get("crossSplitDedupe"))
        entry = kept[0].metadata["lineage"][0]
        self.assertTrue(entry["crossSplit"])
        self.assertEqual(entry["winnerSplit"], "train")
        self.assertEqual(entry["collapsedSplit"], "test")

    def test_p1_009_deterministic_winner_first_occurrence(self) -> None:
        records = [
            _rec("z", "dup", split="train"),
            _rec("a", "dup", split="train"),
            _rec("m", "dup", split="val"),
        ]
        kept, stats = exact_dedupe(records)
        self.assertEqual([r.id for r in kept], ["z"])
        self.assertEqual(stats["winnerPolicy"], WINNER_POLICY_FIRST)
        self.assertEqual(stats["removedCount"], 2)
        self.assertEqual(stats["crossSplitDuplicateCount"], 1)
        # Same input → same winner
        kept2, _ = exact_dedupe(records)
        self.assertEqual(kept2[0].id, kept[0].id)

    def test_p1_009_external_dedupe_parity_with_lineage(self) -> None:
        records = [
            _rec("w", "alpha", split="train", metadata={"sourceHash": "1"}),
            _rec("x", "beta", split="train"),
            _rec("y", "alpha", split="test", metadata={"sourceHash": "2"}),
        ]
        mem_kept, mem_stats = exact_dedupe(records)
        with tempfile.TemporaryDirectory() as tmp:
            ext_kept, ext_stats = exact_dedupe_external_to_list(
                records, scratch_dir=Path(tmp), job_id="w8"
            )
        self.assertEqual([r.id for r in ext_kept], [r.id for r in mem_kept])
        self.assertEqual(ext_stats["removedCount"], mem_stats["removedCount"])
        self.assertEqual(
            ext_stats["crossSplitDuplicateCount"],
            mem_stats["crossSplitDuplicateCount"],
        )
        self.assertTrue(ext_stats["lineagePreserved"])
        self.assertEqual(ext_kept[0].metadata["lineage"][0]["collapsedId"], "y")
        self.assertEqual(record_fingerprint(records[0]), record_fingerprint(records[2]))


if __name__ == "__main__":
    unittest.main()
