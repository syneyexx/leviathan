"""F9 — Independent verification with research/file receipt truth coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Data.modules.artifacts import ArtifactStore
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.types import (
    CognitiveObservation,
    CognitiveObservationKind,
    CognitiveRunStatus,
    EpistemicType,
)
from Data.modules.cognition.verification_bridge import (
    build_verification_plan,
    collapse_or_groups,
    collect_run_refs,
    materialize_evidence_claims,
)
from Data.modules.evidence import EvidenceService, EvidenceStore
from Data.modules.evidence.types import EvidenceKind, EvidenceStatus
from Data.modules.verification import (
    VerificationEngine,
    VerificationOutcome,
    VerificationRequirement,
)


class EvidenceKindExtensionTests(unittest.TestCase):
    def test_new_kinds_exist(self) -> None:
        self.assertEqual(EvidenceKind.CAPABILITY_RECEIPT.value, "CAPABILITY_RECEIPT")
        self.assertEqual(EvidenceKind.RESEARCH_SOURCE.value, "RESEARCH_SOURCE")


class ReceiptAndResearchClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "e.db"
        self.store = EvidenceStore(self.db)
        self.store.initialize()
        self.artifacts = ArtifactStore(self.db, root / "artifacts")
        self.artifacts.initialize()
        self.evidence = EvidenceService(self.store, artifacts=self.artifacts)
        self.engine = VerificationEngine(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_capability_receipt_attested_passes(self) -> None:
        rec = self.evidence.claim_capability_receipt(
            receipt_id="rcpt-1",
            run_id="run-a",
            receipt_status="COMPLETED",
            side_effects=["filesystem_write"],
        )
        self.assertEqual(rec.kind, EvidenceKind.CAPABILITY_RECEIPT)
        self.assertEqual(rec.status, EvidenceStatus.VERIFIED)
        report = self.engine.verify(
            [VerificationEngine.require_capability_receipt("rcpt-1")],
            run_id="run-a",
        )
        self.assertEqual(report.outcome, VerificationOutcome.PASSED)
        self.assertTrue(report.public_dict()["truth"]["research_and_file_receipts_supported"])

    def test_capability_receipt_missing_fails(self) -> None:
        class EmptyLookup:
            def get(self, _rid: str):
                return None

        rec = self.evidence.claim_capability_receipt(
            receipt_id="missing",
            receipt_lookup=EmptyLookup(),
        )
        self.assertEqual(rec.status, EvidenceStatus.FAILED)
        report = self.engine.verify(
            [VerificationEngine.require_capability_receipt("missing")],
        )
        self.assertEqual(report.outcome, VerificationOutcome.FAILED)

    def test_file_exists_and_research_source(self) -> None:
        path = Path(self.tmp.name) / "out.txt"
        path.write_text("hello", encoding="utf-8")
        file_rec = self.evidence.claim_file_exists(path=str(path), run_id="run-b")
        self.assertEqual(file_rec.status, EvidenceStatus.VERIFIED)

        research = self.evidence.claim_research_source(
            research_evidence_id="ev-research-1",
            run_id="run-b",
            attested=True,
            source_id="src-1",
        )
        self.assertEqual(research.kind, EvidenceKind.RESEARCH_SOURCE)
        self.assertEqual(research.status, EvidenceStatus.VERIFIED)

        report = self.engine.verify(
            [
                VerificationEngine.require_file(str(path)),
                VerificationEngine.require_research_source("ev-research-1"),
            ],
            run_id="run-b",
        )
        self.assertEqual(report.outcome, VerificationOutcome.PASSED)

    def test_unattested_research_fails(self) -> None:
        rec = self.evidence.claim_research_source(
            research_evidence_id="fake",
            attested=False,
        )
        self.assertEqual(rec.status, EvidenceStatus.FAILED)


class VerificationBridgeTests(unittest.TestCase):
    def test_collect_research_and_receipt_refs(self) -> None:
        obs = [
            CognitiveObservation(
                kind=CognitiveObservationKind.AGENT_RESULT,
                observation_id="o1",
                summary="research done",
                success=True,
                evidence_refs=("e:abc-123",),
                artifact_refs=("research_project:proj-1",),
                payload={"metadata": {"project_id": "proj-1"}},
            ),
            CognitiveObservation(
                kind=CognitiveObservationKind.TOOL_RESULT,
                observation_id="o2",
                summary="wrote file",
                success=True,
                evidence_refs=("receipt:rcpt-9", "file:/tmp/x"),
                payload={
                    "capability_id": "fs.write",
                    "result": {
                        "status": "COMPLETED",
                        "side_effects": ["filesystem_write"],
                        "telemetry": {"receipt_id": "rcpt-9"},
                        "output": {"path": "/tmp/x"},
                    },
                },
            ),
        ]
        collected = collect_run_refs(observations=obs)
        self.assertIn("abc-123", collected.research_ids)
        self.assertTrue(collected.research_attestations["abc-123"].get("attested"))
        self.assertIn("rcpt-9", collected.receipt_ids)
        self.assertIn("/tmp/x", collected.file_paths)
        self.assertEqual(collected.receipt_attestations["rcpt-9"]["status"], "COMPLETED")

    def test_logical_or_group_collapse(self) -> None:
        plan = build_verification_plan(
            required_evidence=["source_or_evidence_ref"],
            observations=[],
        )
        self.assertIn("source_or_evidence_ref", plan["or_groups"])
        self.assertGreaterEqual(len(plan["or_groups"]["source_or_evidence_ref"]), 2)
        self.assertTrue(plan["truth"]["research_and_file_receipts_covered"])

        # Simulate engine results: ARTIFACT path PASS, others UNMEASURED
        from Data.modules.verification.types import RequirementResult, VerificationReport

        members = plan["or_groups"]["source_or_evidence_ref"]
        results = []
        for mid in members:
            if mid.endswith("ARTIFACT_HASH"):
                results.append(
                    RequirementResult(
                        requirement_id=mid,
                        outcome=VerificationOutcome.PASSED,
                        matched_evidence_ids=("e1",),
                    )
                )
            else:
                results.append(
                    RequirementResult(
                        requirement_id=mid,
                        outcome=VerificationOutcome.UNMEASURED,
                    )
                )
        report = VerificationReport(
            report_id="r1",
            outcome=VerificationOutcome.UNMEASURED,
            created_at="now",
            requirements=tuple(results),
        )
        collapsed = collapse_or_groups(report, plan["or_groups"])
        self.assertEqual(collapsed.outcome, VerificationOutcome.PASSED)

    def test_materialize_research_and_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            path = root / "f.txt"
            path.write_text("x", encoding="utf-8")
            store = EvidenceStore(root / "e.db")
            store.initialize()
            evidence = EvidenceService(store)
            obs = [
                CognitiveObservation(
                    kind=CognitiveObservationKind.AGENT_RESULT,
                    observation_id="o1",
                    summary="ok",
                    success=True,
                    evidence_refs=(f"e:res-1", f"file:{path}"),
                )
            ]
            collected = collect_run_refs(observations=obs)
            created = materialize_evidence_claims(
                collected, evidence_service=evidence, run_id="run-z"
            )
            self.assertGreaterEqual(len(created), 2)
            kinds = {c.kind for c in created}
            self.assertIn(EvidenceKind.RESEARCH_SOURCE, kinds)
            self.assertIn(EvidenceKind.FILE_EXISTS, kinds)
        finally:
            tmp.cleanup()


class RuntimeIndependentVerificationTests(unittest.TestCase):
    def test_verify_research_receipt_path(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            store = EvidenceStore(root / "e.db")
            store.initialize()
            evidence = EvidenceService(store)
            engine = VerificationEngine(store)
            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                verification_engine=engine,
                evidence_service=evidence,
            )
            status = runtime.submit(
                "Research the latest fusion energy claims with sources",
                run=False,
            )
            state = runtime._require(status["run_id"])
            # Ensure research required_evidence is present
            self.assertIn("source_or_evidence_ref", state.task.required_evidence)
            state.observations.append(
                CognitiveObservation(
                    kind=CognitiveObservationKind.AGENT_RESULT,
                    observation_id="obs-r",
                    summary="research completed with sources",
                    success=True,
                    evidence_refs=("e:ledger-1",),
                    artifact_refs=("research_project:p1",),
                    source_type=EpistemicType.EVIDENCE,
                    payload={"metadata": {"project_id": "p1"}},
                )
            )
            state.status = CognitiveRunStatus.REASONING
            # Transition path: VERIFYING allowed from REASONING
            passed = runtime._verify(state)
            self.assertTrue(passed)
            # Evidence materialized
            rows = store.list(run_id=state.run_id, limit=20)
            self.assertTrue(any(r.kind == EvidenceKind.RESEARCH_SOURCE for r in rows))
        finally:
            tmp.cleanup()

    def test_verify_file_receipt_path(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            written = root / "patch.diff"
            written.write_text("diff", encoding="utf-8")
            store = EvidenceStore(root / "e.db")
            store.initialize()
            evidence = EvidenceService(store)
            engine = VerificationEngine(store)
            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                verification_engine=engine,
                evidence_service=evidence,
            )
            status = runtime.submit("Write a file to disk please", run=False)
            state = runtime._require(status["run_id"])
            # Force effect requirement
            state.task.required_evidence = list(state.task.required_evidence) + [
                "effect_or_patch_receipt"
            ]
            state.observations.append(
                CognitiveObservation(
                    kind=CognitiveObservationKind.TOOL_RESULT,
                    observation_id="obs-t",
                    summary="wrote file",
                    success=True,
                    evidence_refs=(f"receipt:r-1", f"file:{written}"),
                    payload={
                        "capability_id": "fs.write",
                        "result": {
                            "status": "COMPLETED",
                            "side_effects": ["filesystem_write"],
                            "telemetry": {"receipt_id": "r-1"},
                            "output": {"path": str(written)},
                        },
                    },
                )
            )
            state.status = CognitiveRunStatus.REASONING
            self.assertTrue(runtime._verify(state))
        finally:
            tmp.cleanup()

    def test_model_text_alone_never_passes(self) -> None:
        store = EvidenceStore(Path(tempfile.mkdtemp()) / "e.db")
        store.initialize()
        engine = VerificationEngine(store)
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=True,
            iterative=False,
            verification_engine=engine,
            evidence_service=EvidenceService(store),
        )
        status = runtime.submit("Research something important with sources", run=False)
        state = runtime._require(status["run_id"])
        state.response_text = "Trust me, everything is verified."
        state.observations.append(
            CognitiveObservation(
                kind=CognitiveObservationKind.MODEL_RESULT,
                observation_id="m1",
                summary=state.response_text,
                success=True,
                source_type=EpistemicType.MODEL_INFERENCE,
            )
        )
        state.status = CognitiveRunStatus.REASONING
        self.assertFalse(runtime._verify(state))


if __name__ == "__main__":
    unittest.main()
