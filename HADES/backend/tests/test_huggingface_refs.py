"""Regression coverage for Hugging Face dataset reference normalization.

ADDED_NOT_EXECUTED — GitHub Actions are intentionally not used for this change
because the repository owner reported a billing error.
"""

from __future__ import annotations

import unittest

from huggingface_refs import normalize_huggingface_dataset_ref


class HuggingFaceDatasetReferenceTests(unittest.TestCase):
    def test_canonical_dataset_id_is_unchanged(self) -> None:
        self.assertEqual(
            normalize_huggingface_dataset_ref("m-a-p/CodeFeedback-Filtered-Instruction"),
            "m-a-p/CodeFeedback-Filtered-Instruction",
        )

    def test_dataset_page_url_becomes_canonical_id(self) -> None:
        self.assertEqual(
            normalize_huggingface_dataset_ref(
                "https://huggingface.co/datasets/m-a-p/CodeFeedback-Filtered-Instruction"
            ),
            "m-a-p/CodeFeedback-Filtered-Instruction",
        )

    def test_trailing_slash_query_and_fragment_are_ignored(self) -> None:
        self.assertEqual(
            normalize_huggingface_dataset_ref(
                "https://www.huggingface.co/datasets/acme/example/?foo=bar#readme"
            ),
            "acme/example",
        )

    def test_rejects_arbitrary_remote_url(self) -> None:
        with self.assertRaises(ValueError):
            normalize_huggingface_dataset_ref("https://example.com/datasets/acme/example")

    def test_rejects_model_url_and_deep_dataset_paths(self) -> None:
        for value in (
            "https://huggingface.co/acme/example",
            "https://huggingface.co/datasets/acme/example/tree/main",
            "https://huggingface.co/datasets/acme/example/blob/main/data.jsonl",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_huggingface_dataset_ref(value)

    def test_rejects_url_credentials_and_nonstandard_port(self) -> None:
        for value in (
            "https://user:secret@huggingface.co/datasets/acme/example",
            "https://huggingface.co:8443/datasets/acme/example",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_huggingface_dataset_ref(value)


if __name__ == "__main__":
    unittest.main()
