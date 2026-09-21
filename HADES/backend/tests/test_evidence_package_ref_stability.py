from __future__ import annotations

import unittest

from reasoning.contracts import ContextItem
from reasoning.evidence_package import _ref_for_context_item


class EvidencePackageRefStabilityTests(unittest.TestCase):
    def test_fallback_provenance_ref_uses_stable_digest(self) -> None:
        item = ContextItem(
            item_id="",
            kind="knowledge",
            content="content does not control this ref",
            provenance="fallback provenance",
        )
        self.assertEqual(_ref_for_context_item(item), "ctx:a2c08d58f9a4a730")

    def test_content_fallback_ref_is_stable_without_id_or_provenance(self) -> None:
        item = ContextItem(
            item_id="",
            kind="knowledge",
            content="same content without ids",
            provenance="",
        )
        self.assertEqual(_ref_for_context_item(item), "ctx:09088af190957a96")

    def test_existing_named_and_item_refs_remain_unchanged(self) -> None:
        named = ContextItem(
            item_id="ignored",
            kind="knowledge",
            content="x",
            provenance="knowledge:source-1",
        )
        item_ref = ContextItem(
            item_id="stable-item",
            kind="other",
            content="x",
            provenance="other provenance",
        )
        self.assertEqual(_ref_for_context_item(named), "knowledge:source-1")
        self.assertEqual(_ref_for_context_item(item_ref), "ctx:stable-item")


if __name__ == "__main__":
    unittest.main()
