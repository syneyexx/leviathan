"""Wave 1 memory-safety regression tests — bounded reads, streaming shards, AST guards."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.datasets.formats import detect_format
from Data.modules.datasets.shards import (
    ShardIngestCheckpoint,
    build_shard_plan,
    ingest_shards,
)
from Data.modules.datasets.streaming_io import read_prefix, stream_copy_and_hash
from Data.modules.datasets.trading_classification import _sample_columns_from_path
from Data.modules.datasets.types import DetectedFormat, DatasetError
from Data.modules.source_ingestion.handlers.structured import StructuredDataHandler
from Data.modules.source_ingestion.settings import SourceIngestionSettings
from Data.modules.source_ingestion.types import (
    DetectionConfidence,
    DetectionResult,
    MemberOutcome,
    SourceKind,
)


# ---------------------------------------------------------------------------
# Instrumented Path that forbids whole-file materialization
# ---------------------------------------------------------------------------


class _BoundedPath(type(Path())):  # type: ignore[misc]
    """Path subclass that fails if read_bytes/read_text are called."""

    reads: list[int]

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls, *args, **kwargs)

    def read_bytes(self):  # noqa: D401
        raise AssertionError("read_bytes() must not be called on large-data paths")

    def read_text(self, *args, **kwargs):  # noqa: D401
        raise AssertionError("read_text() must not be called on large-data paths")


class ReadPrefixTests(unittest.TestCase):
    def test_read_prefix_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.bin"
            # Sparse-friendly: write a small header then seek — on most FS this
            # creates a large logical file without allocating multi-GB RAM.
            with path.open("wb") as fh:
                fh.write(b"PAR1")
                fh.seek(10 * 1024 * 1024 - 1)
                fh.write(b"\0")
            # Instrument open to count bytes actually read via read_prefix.
            raw = read_prefix(path, 4)
            self.assertEqual(raw, b"PAR1")
            self.assertEqual(len(raw), 4)
            # Full read would be 10 MiB; prefix must stay tiny.
            self.assertLess(len(raw), 100)

    def test_detect_format_parquet_uses_prefix_not_read_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.parquet"
            with path.open("wb") as fh:
                fh.write(b"PAR1")
                fh.seek(5 * 1024 * 1024 - 1)
                fh.write(b"\0")
            # Patch Path.read_bytes on the concrete file via monkeypatch of
            # formats.read_prefix already; also assert detect_format succeeds.
            with mock.patch("Data.modules.datasets.formats.read_prefix", wraps=read_prefix) as rp:
                det = detect_format(path)
            self.assertEqual(det.format, DetectedFormat.PARQUET)
            self.assertEqual(det.details.get("magic"), "PAR1")
            # Must have requested at most 4 bytes for magic.
            self.assertTrue(rp.called)
            self.assertEqual(rp.call_args.args[1], 4)

    def test_detect_format_text_sample_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            with path.open("wb") as fh:
                fh.write(b'{"id":"1","text":"hello"}\n')
                fh.seek(8 * 1024 * 1024 - 1)
                fh.write(b"\0")
            sample = 64_000
            with mock.patch("Data.modules.datasets.formats.read_prefix", wraps=read_prefix) as rp:
                det = detect_format(path, sample_bytes=sample)
            self.assertEqual(det.format, DetectedFormat.JSONL)
            self.assertEqual(rp.call_args.args[1], sample)

    def test_trading_classification_json_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.json"
            payload = b'{"open":1,"high":2,"low":0,"close":1.5,"volume":9}'
            with path.open("wb") as fh:
                fh.write(payload)
                # Pad with spaces (valid JSON trailing whitespace) so the file
                # is large while a bounded prefix remains parseable.
                fh.write(b" " * (4 * 1024 * 1024 - len(payload)))
            with mock.patch(
                "Data.modules.datasets.streaming_io.read_prefix", wraps=read_prefix
            ) as rp:
                cols = _sample_columns_from_path(path, max_bytes=256_000)
            self.assertIn("open", cols)
            self.assertTrue(any(c.args[1] == 256_000 for c in rp.call_args_list))
            # Prove Path.read_bytes was not used
            with mock.patch.object(
                Path, "read_bytes", side_effect=AssertionError("read_bytes forbidden")
            ):
                cols2 = _sample_columns_from_path(path, max_bytes=256_000)
            self.assertIn("open", cols2)


class ShardStreamingTests(unittest.TestCase):
    def test_ingest_never_calls_read_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(2):
                p = root / f"src_{i}.bin"
                # ~2 MiB each — larger than typical chunk interest for this test
                with p.open("wb") as fh:
                    fh.write(os.urandom(64))
                    fh.seek(2 * 1024 * 1024 - 1)
                    fh.write(b"\0")
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)

            original_read_bytes = Path.read_bytes

            def _forbid(self):  # noqa: ANN001
                raise AssertionError("Path.read_bytes must not be used during shard ingest")

            with mock.patch.object(Path, "read_bytes", _forbid):
                with mock.patch.object(Path, "write_bytes", side_effect=AssertionError("write_bytes forbidden")):
                    ckpt, outs = ingest_shards(plan, chunk_size=64 * 1024)
            self.assertEqual(ckpt.status, "completed")
            self.assertEqual(len(outs), 2)
            for entry in outs:
                self.assertTrue(Path(entry["path"]).exists())
                self.assertEqual(len(entry["content_hash"]), 64)

            # restore safety (mock ends)
            self.assertIs(Path.read_bytes, original_read_bytes)

    def test_interrupt_leaves_no_partial_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(3):
                p = root / f"s{i}.txt"
                p.write_bytes(f"body-{i}".encode() * 1000)
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            ckpt, outs = ingest_shards(plan, interrupt_after=1)
            self.assertEqual(ckpt.status, "interrupted")
            self.assertEqual(len(outs), 1)
            # No .partial files left behind
            leftovers = list(dest.glob("*.partial"))
            self.assertEqual(leftovers, [])

    def test_resume_revalidates_deleted_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(3):
                p = root / f"s{i}.txt"
                p.write_text(f"shard-{i}-payload", encoding="utf-8")
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            ckpt, outs = ingest_shards(plan, interrupt_after=2)
            self.assertEqual(ckpt.next_index, 2)
            # Delete a completed artifact before resume
            Path(outs[0]["path"]).unlink()
            ckpt2, outs2 = ingest_shards(plan, checkpoint=ckpt)
            self.assertEqual(ckpt2.status, "completed")
            self.assertEqual(len(outs2), 3)
            for entry in outs2:
                self.assertTrue(Path(entry["path"]).is_file())

    def test_resume_revalidates_corrupt_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for i in range(2):
                p = root / f"s{i}.txt"
                p.write_text(f"shard-{i}-payload", encoding="utf-8")
                sources.append(p)
            dest = root / "dest"
            plan = build_shard_plan(sources, dest)
            ckpt, outs = ingest_shards(plan, interrupt_after=1)
            # Corrupt the published shard
            Path(outs[0]["path"]).write_bytes(b"CORRUPT")
            ckpt2, outs2 = ingest_shards(plan, checkpoint=ckpt)
            self.assertEqual(ckpt2.status, "completed")
            from Data.modules.datasets.streaming_io import hash_file_streaming

            for entry in outs2:
                self.assertTrue(Path(entry["path"]).is_file())
                digest, size = hash_file_streaming(entry["path"])
                self.assertEqual(digest, entry["content_hash"])
                self.assertEqual(size, entry["bytes"])

    def test_wrong_checkpoint_plan_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "s0.txt"
            p.write_text("x", encoding="utf-8")
            plan = build_shard_plan([p], root / "dest")
            bad = ShardIngestCheckpoint(plan_id="other-plan", next_index=0)
            with self.assertRaises(ValueError):
                ingest_shards(plan, checkpoint=bad)


class LargeJsonFallbackTests(unittest.TestCase):
    def test_large_unsupported_json_refuses_full_read(self) -> None:
        from Data.modules.datasets.canonicalize import iter_json_array_streaming

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obj.json"
            # Single object (not array / wrapper) — streaming selectors yield nothing
            # and must refuse rather than path.read_text().
            path.write_text('{"hello":"world","nested":{"a":1}}', encoding="utf-8")
            # Force large-path by calling streaming iterator directly
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("read_text forbidden")):
                with self.assertRaises(DatasetError) as ctx:
                    list(iter_json_array_streaming(path, source="obj.json"))
            self.assertEqual(ctx.exception.code, "unsupported_json_shape")


class StructuredErrorPathTests(unittest.TestCase):
    def test_error_path_uses_bounded_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            with path.open("wb") as fh:
                fh.write(b"{not-json")
                fh.seek(3 * 1024 * 1024 - 1)
                fh.write(b"\0")
            handler = StructuredDataHandler()
            detection = DetectionResult(
                kind=SourceKind.STRUCTURED,
                mime_type="application/json",
                extension=".json",
                confidence=DetectionConfidence.HIGH,
            )
            settings = SourceIngestionSettings()
            # Force small enough that we don't route-by-size before parse attempt.
            # dataset_route_min_bytes default is 32MiB; INLINE is 2MiB — our file is 3MiB
            # so it should route rather than parse. Use a tiny file for error-path test.
            path.write_bytes(b"{not-json")
            with mock.patch(
                "Data.modules.source_ingestion.handlers.structured.read_prefix",
                wraps=read_prefix,
            ) as rp:
                art = handler.ingest(
                    path,
                    detection=detection,
                    relative_path="bad.json",
                    settings=settings,
                )
            self.assertEqual(art.outcome, MemberOutcome.FAILED)
            self.assertTrue(rp.called)
            self.assertEqual(rp.call_args.args[1], 1024)

    def test_large_csv_routes_not_materializes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.csv"
            with path.open("wb") as fh:
                fh.write(b"a,b,c\n1,2,3\n")
                fh.seek(3 * 1024 * 1024 - 1)
                fh.write(b"\0")
            handler = StructuredDataHandler()
            detection = DetectionResult(
                kind=SourceKind.STRUCTURED,
                mime_type="text/csv",
                extension=".csv",
                confidence=DetectionConfidence.HIGH,
            )
            settings = SourceIngestionSettings()
            art = handler.ingest(
                path,
                detection=detection,
                relative_path="big.csv",
                settings=settings,
            )
            self.assertEqual(art.outcome, MemberOutcome.ROUTED)
            self.assertEqual(art.route_target, "dataset")


class AstGuardTests(unittest.TestCase):
    """Static guard: large-data owners must not use path.read_bytes()[:N]."""

    OWNERS = (
        Path("Data/modules/datasets/formats.py"),
        Path("Data/modules/datasets/shards.py"),
        Path("Data/modules/datasets/trading_classification.py"),
        Path("Data/modules/datasets/canonicalize.py"),
        Path("Data/modules/source_ingestion/handlers/structured.py"),
    )

    def test_no_read_bytes_slice_pattern(self) -> None:
        root = Path(__file__).resolve().parents[3]  # repo root from Data/backend/tests
        # Fallback if layout differs
        if not (root / "Data").is_dir():
            root = Path("/workspace")
        violations: list[str] = []
        for rel in self.OWNERS:
            path = root / rel
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                # Match: something.read_bytes()[...]
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if isinstance(func, ast.Attribute) and func.attr == "read_bytes":
                        violations.append(f"{rel}:{node.lineno}")
                # Match: something.read_bytes() assigned then sliced is harder;
                # also forbid bare .read_bytes() calls in shards.py production path.
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "read_bytes" and "shards.py" in str(rel):
                        violations.append(f"{rel}:{node.lineno}:read_bytes_call")
        self.assertEqual(violations, [], msg=f"Forbidden patterns: {violations}")


if __name__ == "__main__":
    unittest.main()
