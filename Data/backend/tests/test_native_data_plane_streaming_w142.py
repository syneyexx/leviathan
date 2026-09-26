"""Stage 1 — Python bounded-memory / streaming data-plane foundations."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Data.modules.datasets.dedupe import exact_dedupe, exact_dedupe_external_to_list, record_fingerprint
from Data.modules.datasets.export import export_jsonl
from Data.modules.datasets.materialize import (
    iter_materialized_jsonl,
    iter_version_records,
    load_materialized_jsonl,
    write_canonical_jsonl_stream,
)
from Data.modules.datasets.memory_policy import resolve_dataset_memory_policy
from Data.modules.datasets.pii import scan_records_pii
from Data.modules.datasets.publish import PublishState, publish_atomic, prepare_output_path
from Data.modules.datasets.scratch import ScratchManager
from Data.modules.datasets.splits import assign_split_label, iter_deterministic_split
from Data.modules.datasets.storage_authority import (
    FORBIDDEN_COMPETING_DB_NAMES,
    StorageClass,
    assert_no_competing_domain_db,
    storage_authority_public_dict,
)
from Data.modules.datasets.streaming_io import iter_bounded_text_lines
from Data.modules.datasets.tokenize_stats import compute_token_stats
from Data.modules.datasets.transforms import apply_transforms_streaming
from Data.modules.datasets.types import CanonicalRecord, DatasetError
from Data.modules.datasets.validation import validate_records


def _rec(i: int, text: str | None = None) -> CanonicalRecord:
    return CanonicalRecord(id=f"r{i}", text=text if text is not None else f"row-{i}")


class TestStreamingFoundations(unittest.TestCase):
    def test_validate_true_error_counts_beyond_sample(self) -> None:
        def gen():
            for i in range(500):
                yield CanonicalRecord(id="", text="")  # missing id + empty

        report = validate_records(gen(), max_issues=10)
        self.assertEqual(report["rowCount"], 500)
        self.assertGreater(report["errorCount"], 10)
        self.assertTrue(report["issuesTruncated"])
        self.assertLessEqual(len(report["issues"]), 10)

    def test_validate_single_pass_iterable(self) -> None:
        consumed = {"n": 0}

        def once():
            for i in range(20):
                consumed["n"] += 1
                yield _rec(i)

        it = once()
        report = validate_records(it)
        self.assertEqual(report["rowCount"], 20)
        self.assertEqual(consumed["n"], 20)
        with self.assertRaises(StopIteration):
            next(it)

    def test_pii_streaming(self) -> None:
        def gen():
            yield CanonicalRecord(id="1", text="contact me at alice@example.com")
            for i in range(100):
                yield _rec(i)

        report = scan_records_pii(gen(), max_findings=5)
        self.assertEqual(report["recordCount"], 101)
        self.assertGreaterEqual(report["recordsWithFindings"], 1)

    def test_export_single_pass(self) -> None:
        class Once:
            def __init__(self):
                self.calls = 0

            def __iter__(self):
                if self.calls:
                    raise AssertionError("iterator consumed twice")
                self.calls += 1
                for i in range(50):
                    yield _rec(i)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.jsonl"
            result = export_jsonl(Once(), dest)
            self.assertEqual(result["rowCount"], 50)
            self.assertTrue(dest.is_file())

    def test_transform_streaming_lineage(self) -> None:
        stream, lineage_fn = apply_transforms_streaming(
            [_rec(i, text=f"  hello {i}  ") for i in range(10)],
            [{"name": "strip_whitespace", "params": {"strip": True}}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.jsonl"
            outcome = write_canonical_jsonl_stream(stream, dest, validate=False)
            self.assertEqual(outcome["rowCount"], 10)
        lineage = lineage_fn()
        self.assertEqual(lineage[0]["inputCount"], 10)
        self.assertEqual(lineage[0]["outputCount"], 10)

    def test_split_streaming_deterministic(self) -> None:
        records = [_rec(i) for i in range(100)]
        a_it, a_sum = iter_deterministic_split(records, seed=7)
        b_it, b_sum = iter_deterministic_split(records, seed=7)
        a = list(a_it)
        b = list(b_it)
        self.assertEqual([r.split for r in a], [r.split for r in b])
        self.assertEqual(a_sum["counts"], b_sum["counts"])
        self.assertEqual(assign_split_label(_rec(0), seed=7), a[0].split)

    def test_token_stats_bounded_approximate(self) -> None:
        def gen():
            for i in range(250):
                yield _rec(i, text=("word " * (i % 20 + 1)))

        stats = compute_token_stats(gen(), exact_max_rows=50, reservoir_size=30)
        self.assertEqual(stats["rowCount"], 250)
        self.assertTrue(stats["approximate"])
        self.assertEqual(stats["quantileMethod"], "reservoir_sample")
        self.assertIn("minTokens", stats)
        self.assertIn("maxTokens", stats)

    def test_external_dedupe_exact(self) -> None:
        records = [
            _rec(1, "alpha"),
            _rec(2, "beta"),
            _rec(3, "alpha"),
            _rec(4, "gamma"),
            _rec(5, "beta"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            kept, stats = exact_dedupe_external_to_list(records, scratch_dir=Path(tmp), job_id="j1")
        self.assertEqual(len(kept), 3)
        self.assertEqual(stats["removedCount"], 2)
        self.assertEqual(stats["memoryMode"], "external_sqlite_scratch")
        # Parity with in-memory
        mem_kept, mem_stats = exact_dedupe(records)
        self.assertEqual([r.id for r in kept], [r.id for r in mem_kept])
        self.assertEqual(stats["removedCount"], mem_stats["removedCount"])
        self.assertEqual(record_fingerprint(records[0]), record_fingerprint(records[2]))

    def test_bounded_line_refuses_huge_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.jsonl"
            # Write a line larger than 1 KiB limit
            path.write_bytes(b"x" * 2048 + b"\n")
            with self.assertRaises(DatasetError) as ctx:
                list(iter_bounded_text_lines(path, max_record_bytes=1024))
            self.assertEqual(ctx.exception.code, "RECORD_TOO_LARGE")

    def test_full_load_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corp.jsonl"
            # Create file larger than refuse threshold by writing many lines
            with path.open("w", encoding="utf-8") as fh:
                for i in range(5000):
                    fh.write(json.dumps({"id": f"r{i}", "text": "x" * 200}) + "\n")
            size = path.stat().st_size
            self.assertGreater(size, 100_000)
            with self.assertRaises(DatasetError) as ctx:
                load_materialized_jsonl(path, max_bytes=50_000)
            self.assertEqual(ctx.exception.code, "DATASET_FULL_MATERIALIZATION_REFUSED")
            # Iterator still works
            n = sum(1 for _ in iter_materialized_jsonl(path, max_record_bytes=1024 * 1024))
            self.assertEqual(n, 5000)

    def test_storage_authority_forbids_competing_dbs(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_competing_domain_db(Path("knowledge.db"))
        self.assertIn("knowledge.db", FORBIDDEN_COMPETING_DB_NAMES)
        truth = storage_authority_public_dict()
        self.assertTrue(truth["truth"]["competingDomainDatabasesForbidden"])
        self.assertEqual(StorageClass.EPHEMERAL_SCRATCH.value, "EPHEMERAL_SCRATCH")

    def test_scratch_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = ScratchManager(Path(tmp) / "scratch", max_scratch_bytes=10_000_000)
            session = mgr.open_session("job-abc")
            p = session.path("exact_dedupe.sqlite")
            p.write_text("x")
            session.write_manifest()
            self.assertTrue((session.root / "scratch-manifest.json").is_file())
            self.assertTrue(mgr.cleanup_session("job-abc"))
            self.assertFalse(session.root.exists())

    def test_publish_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.jsonl"
            prepared = prepare_output_path(dest)
            prepared.write_text('{"id":"1","text":"a"}\n', encoding="utf-8")
            result = publish_atomic(prepared, dest)
            self.assertEqual(result["publishState"], PublishState.PUBLISHED.value)
            self.assertTrue(dest.is_file())
            self.assertFalse(prepared.exists())

    def test_memory_policy_defaults(self) -> None:
        policy = resolve_dataset_memory_policy()
        self.assertGreater(policy.max_record_bytes, 0)
        self.assertEqual(policy.enforcement, "SOFT_ENFORCED")
        pub = policy.public_dict()
        self.assertFalse(pub["truth"]["hardOsEnforcement"])

    def test_iter_version_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.jsonl"
            write_canonical_jsonl_stream([_rec(i) for i in range(5)], path, validate=False)
            rows = list(iter_version_records(path))
            self.assertEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
