"""Round 1 — Trust foundation regression gates (F01–F07, F14, F16, F18, F20)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.cognition import (
    CognitiveObservation,
    CognitiveObservationKind,
    CognitiveRuntime,
    CognitiveRunStatus,
    CompletionEngine,
    TaskModelBuilder,
)
from Data.modules.cognition.model_adapter import build_control_plane_model_caller
from Data.modules.coding import extract_capabilities
from Data.modules.evidence import EvidenceStatus, EvidenceStore
from Data.modules.evidence.types import EvidenceKind
from Data.modules.isolation import IsolationGuard, IsolationMode, IsolationRequest
from Data.modules.knowledge import HybridRetriever, RetrievalHit
from Data.modules.training import (
    FlywheelControlPlane,
    PromotionError,
    build_artifact_manifest,
    verify_artifact_integrity,
)
from Data.modules.training.types import ArtifactRecord
from Data.modules.models.store import ModelStore
from Data.modules.verification import VerificationEngine, VerificationRequirement


class CompletionFalsePositiveTests(unittest.TestCase):
    def test_prose_passed_does_not_satisfy_test_criterion(self) -> None:
        task = TaskModelBuilder().build(
            "Fix the reconnect bug and ensure tests pass with evidence"
        )
        decision = CompletionEngine().evaluate(
            task,
            observations=[],
            response_text=(
                "No tests passed; all tests failed. I cannot answer the goal correctly."
            ),
            verification_passed=None,
        )
        test_criteria = [c for c in decision.criteria if "test" in c.criterion.lower()]
        goal_criteria = [
            c
            for c in decision.criteria
            if any(k in c.criterion.lower() for k in ("goal", "address", "answer"))
        ]
        self.assertTrue(test_criteria)
        self.assertTrue(all(not c.met for c in test_criteria))
        if goal_criteria:
            self.assertTrue(all(not c.met for c in goal_criteria))
        self.assertNotEqual(decision.status, CognitiveRunStatus.COMPLETED_VERIFIED)
        self.assertNotEqual(decision.status, CognitiveRunStatus.COMPLETED_UNVERIFIED)

    def test_structured_test_receipt_can_pass(self) -> None:
        task = TaskModelBuilder().build(
            "Fix the reconnect bug and ensure tests pass with evidence"
        )
        obs = CognitiveObservation(
            kind=CognitiveObservationKind.TOOL_RESULT,
            observation_id="obs-1",
            summary="tests executed",
            success=True,
            payload={"capability_id": "coding.run_tests", "tests_passed": True, "exit_code": 0},
            evidence_refs=["obs:obs-1"],
        )
        decision = CompletionEngine().evaluate(
            task,
            observations=[obs],
            response_text="Tests are green; reconnect race is fixed.",
            verification_passed=None,
        )
        test_criteria = [c for c in decision.criteria if "test" in c.criterion.lower()]
        self.assertTrue(test_criteria)
        self.assertTrue(all(c.met for c in test_criteria))


class CitationContradictionTests(unittest.TestCase):
    def test_negated_evidence_is_contradicted_not_supported(self) -> None:
        hit = RetrievalHit(
            document_id="d1",
            chunk_id="c1",
            chunk_index=0,
            title="security",
            source="doc",
            content="The service does not store passwords securely.",
            score=1.0,
            modality="lexical",
            original_path=None,
            document_hash=None,
            chunk_hash="h1",
        )
        check = HybridRetriever.verify_citation(
            "The service stores passwords securely.",
            hit,
        )
        self.assertEqual(check.status, "CONTRADICTED")
        self.assertFalse(check.entailed)
        self.assertTrue(
            check.public_dict()["truth"]["lexical_overlap_does_not_override_contradiction"]
        )

    def test_research_graph_contradiction_not_supported(self) -> None:
        from Data.modules.research.graph import citation_entailment_check

        check = citation_entailment_check(
            "The service stores passwords securely.",
            "The service does not store passwords securely.",
        )
        self.assertEqual(check["status"], "CONTRADICTED")
        self.assertFalse(check["passed"])
        self.assertTrue(check["truth"]["lexical_overlap_does_not_override_contradiction"])


class ToolExplanationTests(unittest.TestCase):
    def test_example_json_in_prose_does_not_execute(self) -> None:
        text = (
            'Here is an example; do not execute it:\n'
            '{"tool":"file.delete", "arguments": {"path": "/tmp/x"}}\n'
        )
        caps = extract_capabilities(text)
        self.assertEqual(caps, [])

    def test_disclaimer_before_fenced_json_does_not_execute(self) -> None:
        text = '''
Here is an example; do not execute it:
```json
{"capability_id": "file.delete", "arguments": {"path": "x.txt"}}
```
'''
        caps = extract_capabilities(text)
        self.assertEqual(caps, [])

    def test_fenced_capability_without_disclaimer_still_parses(self) -> None:
        text = '''
```json
{"capability_id": "file.read", "arguments": {"path": "a.py"}}
```
'''
        caps = extract_capabilities(text)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].capability_id, "file.read")


class ArtifactMutationIntegrityTests(unittest.TestCase):
    def test_mutating_weight_invalidates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "adapter"
            root.mkdir()
            weight = root / "adapter_model.safetensors"
            weight.write_bytes(b"WEIGHT_V1")
            (root / "adapter_config.json").write_text('{"r":8}', encoding="utf-8")
            manifest = build_artifact_manifest(root)
            self.assertTrue(manifest["manifest_hash"])
            artifact = ArtifactRecord(
                artifact_id="art-1",
                job_id="job-1",
                artifact_type="adapter",
                path=str(root),
                base_model_ref="base",
                dataset_version_id=None,
                method="lora",
                config_hash="cfg",
                content_hash=manifest["manifest_hash"],
                model_card_path=None,
                evaluation={"manifest_hash": manifest["manifest_hash"]},
                compatibility={},
                registered_model_id=None,
                created_at="2020-01-01T00:00:00Z",
            )
            ok = verify_artifact_integrity(artifact)
            self.assertTrue(ok.passed)
            # Mutate protected weight.
            weight.write_bytes(b"WEIGHT_V2_MUTATED")
            bad = verify_artifact_integrity(artifact)
            self.assertFalse(bad.passed)
            self.assertNotEqual(bad.manifest_hash, manifest["manifest_hash"])


class PromotionCandidateBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "promo.db"
        MigrationRunner(self.db).apply_all()
        self.models = ModelStore(self.db)
        now = "2026-09-23T00:00:00+00:00"
        self.models.upsert_provider(
            {
                "provider_id": "local_trained",
                "name": "Local",
                "provider_type": "local_artifact",
                "endpoint": "local://trained",
                "enabled": True,
                "auto_connect": False,
                "timeout_seconds": 1.0,
                "refresh_interval_seconds": 3600.0,
                "health": "unknown",
                "capabilities": {},
                "metadata": {},
            }
        )
        for mid, name in (("champion-a", "Champion"), ("challenger-b", "Challenger")):
            self.models.upsert_model(
                {
                    "model_id": mid,
                    "display_name": name,
                    "provider_id": "local_trained",
                    "runtime_id": None,
                    "source": "trained",
                    "object_type": "adapter",
                    "format": "fixture",
                    "capabilities": {},
                    "lifecycle_state": "available",
                    "health": "unknown",
                    "active": False,
                    "loaded": False,
                    "local_path": None,
                    "last_discovered_at": now,
                    "tags": ["trained"],
                    "metadata": {},
                    "created_at": now,
                }
            )
        self.models.set_active_model("champion-a")
        self.flywheel = FlywheelControlPlane(self.db, model_store=self.models, evaluation=None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_promote_wrong_candidate_id_denied(self) -> None:
        proposal = self.flywheel.propose_challenger(
            challenger_model_id="challenger-b",
            rationale="test",
            champion_model_id="champion-a",
        )
        with self.assertRaises(PromotionError) as ctx:
            self.flywheel.promote(
                proposal.proposal_id,
                decided_by="operator",
                require_eval_gate=False,
                candidate_model_id="champion-a",  # wrong — A's eval cannot promote B
            )
        self.assertEqual(ctx.exception.code, "candidate_mismatch")
        self.assertEqual(self.models.get_active_model_id(), "champion-a")


class VerificationContractTests(unittest.TestCase):
    def test_cognition_uses_verify_not_verify_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ev.db"
            MigrationRunner(db).apply_all()
            store = EvidenceStore(db)
            store.initialize()
            engine = VerificationEngine(store)
            self.assertTrue(hasattr(engine, "verify"))
            self.assertFalse(hasattr(engine, "verify_claims"))

            # Missing evidence → not PASSED
            report = engine.verify(
                [
                    VerificationRequirement(
                        requirement_id="r1",
                        description="need artifact",
                        evidence_kind=EvidenceKind.ARTIFACT_HASH.value,
                        artifact_id="missing",
                    )
                ]
            )
            self.assertNotEqual(report.outcome.value, "PASSED")

            store.create(
                kind=EvidenceKind.ARTIFACT_HASH,
                claim="hash ok",
                status=EvidenceStatus.VERIFIED,
                artifact_id="art-ok",
                content_hash="abc",
            )
            ok = engine.verify(
                [
                    VerificationRequirement(
                        requirement_id="r2",
                        description="artifact",
                        evidence_kind=EvidenceKind.ARTIFACT_HASH.value,
                        artifact_id="art-ok",
                    )
                ]
            )
            self.assertEqual(ok.outcome.value, "PASSED")

            runtime = CognitiveRuntime(
                enabled=True,
                shadow=False,
                verification_engine=engine,
                model_caller=lambda **kwargs: "answer",
            )
            # _verify with no typed requirements must not claim pass
            state = runtime.submit("hello", run=False)
            run_state = runtime._runs[state["run_id"]]
            self.assertFalse(runtime._verify(run_state))


class IsolationHonestyTests(unittest.TestCase):
    def test_os_enforcement_not_claimed_from_config(self) -> None:
        settings = Settings.from_env()
        guard = IsolationGuard(settings)
        report = guard.evaluate(
            IsolationRequest(requested=(IsolationMode.PROCESS, IsolationMode.WORKSPACE))
        )
        payload = report.public_dict()
        self.assertTrue(payload["truth"]["application_intended_is_not_os_enforced"])
        self.assertEqual(payload["metadata"]["os_enforced"], [])
        self.assertFalse(payload["metadata"]["os_enforcement_measured"])


class ProductionModelCallerWiringTests(unittest.TestCase):
    def test_adapter_marked_as_production_caller(self) -> None:
        plane = mock.Mock()
        llm = mock.Mock()
        llm.settings = mock.Mock(llm_timeout_seconds=5.0)
        caller = build_control_plane_model_caller(plane, llm)
        self.assertTrue(getattr(caller, "__leviathan_production_caller__", False))

    def test_composition_wires_model_caller(self) -> None:
        # Importing the app composition must attach a production model caller.
        from Data.backend import main as backend_main

        self.assertIsNotNone(backend_main.cognition_runtime.model_caller)
        self.assertTrue(
            getattr(
                backend_main.cognition_runtime.model_caller,
                "__leviathan_production_caller__",
                False,
            )
        )


class BudgetTokenTruthTests(unittest.TestCase):
    def test_provider_usage_preferred_over_estimate(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            model_caller=lambda **kwargs: {
                "text": "hello world answer",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "usage_source": "provider",
            },
        )
        result = runtime.submit("hello")
        usage = result["usage"]
        self.assertEqual(usage["token_usage_source"], "provider")
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 5)
        self.assertFalse(usage["truth"]["estimate_is_not_provider_usage"])


if __name__ == "__main__":
    unittest.main()
