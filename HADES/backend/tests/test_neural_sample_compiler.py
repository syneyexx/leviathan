"""Tests for Dataset Brain → neural sample compiler (Phase 2 foundation)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neural.samples import (
    HIDDEN_RECORD_KEYS,
    NeuralSampleCompileError,
    NeuralSampleCompiler,
    NeuralSampleType,
    deterministic_split,
    strip_hidden_fields,
)


class NeuralSampleCompilerTests(unittest.TestCase):
    def test_strips_hidden_reasoning_fields(self) -> None:
        row = {
            "instruction": "public task",
            "output": "public answer",
            "reasoning": "secret chain",
            "chain_of_thought": "also secret",
            "scratchpad": "nope",
        }
        safe = strip_hidden_fields(row)
        for key in HIDDEN_RECORD_KEYS:
            self.assertNotIn(key, {k.lower() for k in safe})
        self.assertIn("instruction", safe)
        self.assertIn("output", safe)

    def test_rejects_hidden_text_field_mapping(self) -> None:
        with self.assertRaises(NeuralSampleCompileError):
            NeuralSampleCompiler(
                dataset_id="ds_test",
                source_fingerprint="abc",
                mapping={"text_field": "chain_of_thought"},
            )

    def test_streaming_compile_excludes_hidden_and_splits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.jsonl"
            rows = [
                {"instruction": "A", "output": "1", "reasoning": "hidden-A"},
                {"query": "Q", "answer": "Ans"},
                {"problem_statement": "bug", "patch": "diff --git a"},
                {"text": ""},
            ]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            compiler = NeuralSampleCompiler(
                dataset_id="ds_abc",
                source_fingerprint="fp1",
                eval_ratio=0.5,
            )
            samples = list(compiler.iter_snapshot(path))
            self.assertEqual(len(samples), 3)
            texts = " ".join(s.text for s in samples)
            self.assertNotIn("hidden-A", texts)
            types = {s.sample_type for s in samples}
            self.assertIn(NeuralSampleType.INSTRUCTION_RESPONSE, types)
            self.assertIn(NeuralSampleType.QUERY_ANSWER, types)
            self.assertIn(NeuralSampleType.CODE_PATCH, types)
            self.assertTrue(all(s.source_fingerprint == "fp1" for s in samples))
            self.assertTrue(all(s.split in {"train", "eval"} for s in samples))

    def test_deterministic_split_stable(self) -> None:
        a = deterministic_split("ds:1:deadbeef", eval_ratio=0.2)
        b = deterministic_split("ds:1:deadbeef", eval_ratio=0.2)
        self.assertEqual(a, b)

    def test_does_not_load_entire_file_into_list_api(self) -> None:
        # Compiler exposes an iterator, not a materializing list API.
        self.assertTrue(hasattr(NeuralSampleCompiler, "iter_snapshot"))
        compiler = NeuralSampleCompiler(dataset_id="ds", source_fingerprint="x", max_rows=2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.jsonl"
            path.write_text(
                "".join(json.dumps({"text": f"row-{i}"}) + "\n" for i in range(10)),
                encoding="utf-8",
            )
            samples = list(compiler.iter_snapshot(path))
            self.assertEqual(len(samples), 2)


if __name__ == "__main__":
    unittest.main()
