from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.evidence import EvidenceService, EvidenceStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.observations import ObservationStore
from Data.modules.verification import (
    VerificationEngine,
    VerificationOutcome,
    VerificationReportStore,
)


class IntegrationHarnessTests(unittest.TestCase):
    """Phase 42 — end-to-end foundation path without fabricated success."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "i.db"
        self.artifacts = ArtifactStore(self.db, root / "artifacts")
        self.artifacts.initialize()
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.observations = ObservationStore(self.db)
        self.observations.initialize()
        self.evidence_store = EvidenceStore(self.db)
        self.evidence_store.initialize()
        self.evidence = EvidenceService(
            self.evidence_store,
            artifacts=self.artifacts,
            observations=self.observations,
        )
        registry = build_default_registry()
        self.runtime = FunctionRuntime(registry, max_concurrency=2, warm_cache_size=1)
        catalog = build_default_catalog()
        self.gateway = ExecutionGateway(
            catalog=catalog,
            function_runtime=self.runtime,
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
            observation_store=self.observations,
        )
        self.verification = VerificationEngine(self.evidence_store)
        self.reports = VerificationReportStore(self.db)
        self.reports.initialize()

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    def test_approval_gateway_evidence_verification_chain(self) -> None:
        denied = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "integration", "filename": "i.txt"},
                run_id="run-int",
            )
        )
        self.assertEqual(denied.status, CapabilityStatus.REJECTED)

        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="integration",
            reason="phase42 harness",
        )
        approved = self.approvals.approve(pending.approval_id, decided_by="integration")
        self.assertEqual(approved.status.value, "APPROVED")

        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "integration", "filename": "i.txt"},
                run_id="run-int",
                approval_id=approved.approval_id,
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        assert result.output is not None
        artifact_id = result.output.get("artifact_id")
        if artifact_id is None and isinstance(result.output.get("artifact"), dict):
            artifact_id = result.output["artifact"].get("artifact_id")
        self.assertIsNotNone(artifact_id)

        evidence = self.evidence.claim_artifact_hash(artifact_id=artifact_id, run_id="run-int")
        self.assertEqual(evidence.status.value, "VERIFIED")

        report = self.verification.verify(
            [VerificationEngine.require_artifact(artifact_id)],
            run_id="run-int",
        )
        self.reports.save(report)
        self.assertEqual(report.outcome, VerificationOutcome.PASSED)
        self.assertIsNotNone(self.reports.get(report.report_id))

        # Observation ledger is optional in this path; do not invent records.
        _ = self.observations.list_observations(limit=20)


if __name__ == "__main__":
    unittest.main()
