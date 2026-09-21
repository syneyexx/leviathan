from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import (
    ApprovalService,
    ApprovalStatus,
    ApprovalStore,
    PolicyEngine,
)
from Data.modules.function_runtime.types import SideEffect


class ApprovalsPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalStore(Path(self.tmp.name) / "approvals.db")
        self.store.initialize()
        self.service = ApprovalService(self.store, PolicyEngine())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_read_policy_does_not_require_approval(self) -> None:
        decision = self.service.evaluate_policy((SideEffect.READ,))
        self.assertFalse(decision.requires_approval)

    def test_write_policy_requires_approval(self) -> None:
        decision = self.service.evaluate_policy((SideEffect.WRITE,))
        self.assertTrue(decision.requires_approval)
        self.assertIn("WRITE", decision.gated_effects)

    def test_request_approve_and_verify(self) -> None:
        pending = self.service.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="tester",
        )
        self.assertEqual(pending.status, ApprovalStatus.PENDING)
        approved = self.service.approve(pending.approval_id, decided_by="ops")
        self.assertEqual(approved.status, ApprovalStatus.APPROVED)
        self.assertTrue(
            self.service.is_approved(
                approved.approval_id,
                capability_id="artifact.create_text",
                side_effects=(SideEffect.WRITE,),
            )
        )
        self.assertFalse(
            self.service.is_approved(
                approved.approval_id,
                capability_id="other.capability",
                side_effects=(SideEffect.WRITE,),
            )
        )

    def test_deny_blocks_is_approved(self) -> None:
        pending = self.service.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
        )
        denied = self.service.deny(pending.approval_id, decided_by="ops", reason="no")
        self.assertEqual(denied.status, ApprovalStatus.DENIED)
        self.assertFalse(
            self.service.is_approved(
                denied.approval_id,
                capability_id="artifact.create_text",
                side_effects=(SideEffect.WRITE,),
            )
        )

    def test_single_use_consume(self) -> None:
        pending = self.service.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            single_use=True,
        )
        self.service.approve(pending.approval_id)
        consumed = self.service.consume_if_single_use(pending.approval_id)
        assert consumed is not None
        self.assertEqual(consumed.status, ApprovalStatus.CONSUMED)
        self.assertFalse(
            self.service.is_approved(
                pending.approval_id,
                capability_id="artifact.create_text",
                side_effects=(SideEffect.WRITE,),
            )
        )


if __name__ == "__main__":
    unittest.main()
