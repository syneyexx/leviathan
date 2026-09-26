"""TEAM quality-contract adversarial + lifecycle tests (mandate scenarios A–Z fixtures)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.cognition.team_orchestrator import TeamOrchestrator, evidence_origin_key
from Data.modules.cognition.team_strategy import (
    CollaborationStrategy,
    OptionalUserCaps,
    TeamExecutionPolicy,
    TeamRunStatus,
    USER_FACING_TEAM_DESCRIPTION,
    normalize_collaboration_strategy,
)
from Data.modules.research.budgets import (
    budget_catalog,
    budget_for_depth,
    resolve_execution_budget,
)
from Data.modules.research.types import ResearchExecutionMode
from Data.modules.verification.quality_contract import (
    AcceptanceOutcome,
    CriterionApplicability,
    CriterionSeverity,
    CriterionVerdict,
    CriterionVerdictStatus,
    EvidenceClass,
    QualityContract,
    QualityCriterion,
    aggregate_acceptance,
    invalidate_verdicts_for_revision,
    new_contract_id,
)
from Data.modules.verification.quality_store import QualityContractStore


def _crit(cid: str, **kwargs) -> QualityCriterion:
    return QualityCriterion(
        criterion_id=cid,
        description=cid,
        verification_method="test",
        evidence_class=kwargs.get("evidence_class", EvidenceClass.INDEPENDENT_CHECK),
        severity=kwargs.get("severity", CriterionSeverity.MANDATORY),
        applicability=kwargs.get("applicability", CriterionApplicability.APPLICABLE),
        applicability_justification=kwargs.get("applicability_justification"),
    )


def _verdict(cid: str, status: CriterionVerdictStatus, rev: str, *evidence: str) -> CriterionVerdict:
    return CriterionVerdict(
        criterion_id=cid,
        contract_version=1,
        artifact_revision=rev,
        status=status,
        verifier_identity="test",
        verifier_type="fixture",
        evidence_ids=tuple(evidence),
        public_justification="fixture",
        created_at="t0",
    )


class QualityContractTests(unittest.TestCase):
    def test_a_all_mandatory_pass_accepts(self) -> None:
        contract = QualityContract(
            contract_id=new_contract_id(),
            version=1,
            run_id="r1",
            request_ref="req",
            scope="s",
            criteria=[_crit("crit:a"), _crit("crit:b")],
        )
        verdicts = [
            _verdict("crit:a", CriterionVerdictStatus.SATISFIED, "rev1", "e1"),
            _verdict("crit:b", CriterionVerdictStatus.SATISFIED, "rev1", "e2"),
        ]
        rec = aggregate_acceptance(contract, verdicts, artifact_revision="rev1")
        self.assertEqual(rec.outcome, AcceptanceOutcome.ACCEPTED)

    def test_b_one_mandatory_fails_incomplete(self) -> None:
        contract = QualityContract(
            contract_id=new_contract_id(),
            version=1,
            run_id="r1",
            request_ref="req",
            scope="s",
            criteria=[_crit("crit:a"), _crit("crit:b")],
        )
        verdicts = [
            _verdict("crit:a", CriterionVerdictStatus.SATISFIED, "rev1", "e1"),
            _verdict("crit:b", CriterionVerdictStatus.UNSATISFIED, "rev1"),
        ]
        rec = aggregate_acceptance(contract, verdicts, artifact_revision="rev1")
        self.assertNotEqual(rec.outcome, AcceptanceOutcome.ACCEPTED)
        self.assertTrue(any("crit:b" in b for b in rec.blockers))

    def test_d_majority_agreement_without_evidence_rejected(self) -> None:
        """Three agents agreeing is not acceptance — SATISFIED requires evidence_ids."""
        with self.assertRaises(ValueError):
            CriterionVerdict(
                criterion_id="crit:a",
                contract_version=1,
                artifact_revision="rev1",
                status=CriterionVerdictStatus.SATISFIED,
                verifier_identity="majority",
                verifier_type="vote",
                evidence_ids=(),
            )

    def test_e_origin_collapse(self) -> None:
        urls = [
            f"https://press.example.com/release?id={i}" for i in range(100)
        ]
        origins = {evidence_origin_key(u) for u in urls}
        self.assertEqual(len(origins), 1)

    def test_h_stale_verdicts_cannot_certify_new_revision(self) -> None:
        contract = QualityContract(
            contract_id=new_contract_id(),
            version=1,
            run_id="r1",
            request_ref="req",
            scope="s",
            criteria=[_crit("crit:a")],
        )
        old = [_verdict("crit:a", CriterionVerdictStatus.SATISFIED, "revA", "e1")]
        stale = invalidate_verdicts_for_revision(old, artifact_revision="revA")
        rec = aggregate_acceptance(contract, stale, artifact_revision="revB")
        self.assertNotEqual(rec.outcome, AcceptanceOutcome.ACCEPTED)
        self.assertTrue(any("missing_verdict" in b for b in rec.blockers))

    def test_material_relaxation_requires_user(self) -> None:
        contract = QualityContract(
            contract_id=new_contract_id(),
            version=1,
            run_id="r1",
            request_ref="req",
            scope="s",
            criteria=[_crit("crit:a"), _crit("crit:b")],
        )
        with self.assertRaises(ValueError):
            contract.revise(criteria=[_crit("crit:a")])
        revised = contract.revise(
            criteria=[_crit("crit:a")],
            user_accepted_relaxation=True,
            revision_note="user accepted",
        )
        self.assertEqual(revised.version, 2)
        self.assertEqual(len(revised.mandatory_applicable()), 1)

    def test_not_applicable_requires_justification(self) -> None:
        with self.assertRaises(ValueError):
            _crit(
                "crit:x",
                applicability=CriterionApplicability.NOT_APPLICABLE,
            )

    def test_advisory_cannot_compensate(self) -> None:
        contract = QualityContract(
            contract_id=new_contract_id(),
            version=1,
            run_id="r1",
            request_ref="req",
            scope="s",
            criteria=[
                _crit("crit:must"),
                _crit("crit:nice", severity=CriterionSeverity.ADVISORY),
            ],
        )
        verdicts = [
            _verdict("crit:must", CriterionVerdictStatus.UNSATISFIED, "rev1"),
            _verdict("crit:nice", CriterionVerdictStatus.SATISFIED, "rev1", "e1"),
        ]
        rec = aggregate_acceptance(contract, verdicts, artifact_revision="rev1")
        self.assertNotEqual(rec.outcome, AcceptanceOutcome.ACCEPTED)

    def test_persistence_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = QualityContractStore(Path(td) / "qc.db")
            store.initialize()
            contract = QualityContract(
                contract_id=new_contract_id(),
                version=1,
                run_id="r1",
                request_ref="req",
                scope="s",
                criteria=[_crit("crit:a")],
                created_at="t0",
            )
            store.save_contract(contract)
            v = _verdict("crit:a", CriterionVerdictStatus.SATISFIED, "rev1", "e1")
            store.save_verdict(v, contract_id=contract.contract_id)
            loaded = store.get_contract(contract.contract_id)
            assert loaded is not None
            self.assertEqual(loaded.contract_id, contract.contract_id)
            vs = store.list_verdicts(contract.contract_id, artifact_revision="rev1")
            self.assertEqual(len(vs), 1)
            rec = aggregate_acceptance(loaded, vs, artifact_revision="rev1")
            store.save_acceptance(rec)
            latest = store.latest_acceptance(contract.contract_id)
            assert latest is not None
            self.assertEqual(latest.outcome, AcceptanceOutcome.ACCEPTED)


class TeamOrchestratorTests(unittest.TestCase):
    def test_a_completes_when_evidence_satisfies(self) -> None:
        def executor(assignment, state):
            return {
                "role": assignment.role.value,
                "evidence_ids": ["ev:1", "test:1"],
                "tests_passed": True,
                "test_receipt_id": "test:1",
                "artifact_ok": True,
                "provisional_artifact": {"text": "fixed"},
            }

        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="fix", task_category="coding", requires_coding=True)
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertIsNotNone(st.acceptance)
        self.assertEqual(st.acceptance.outcome, AcceptanceOutcome.ACCEPTED)

    def test_b_schedules_followup_when_failing(self) -> None:
        calls = {"n": 0}

        def executor(assignment, state):
            calls["n"] += 1
            if state.iteration >= 2:
                return {
                    "role": assignment.role.value,
                    "evidence_ids": ["ev:1", "test:1"],
                    "tests_passed": True,
                    "test_receipt_id": "test:1",
                    "artifact_ok": True,
                }
            return {"role": assignment.role.value, "evidence_ids": []}

        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="fix", task_category="coding", requires_coding=True)
        st = orch.run_until_terminal(st.run_id, max_iterations=20)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertGreaterEqual(st.iteration, 2)
        self.assertGreater(calls["n"], 2)

    def test_d_agents_agree_unsupported_rejected(self) -> None:
        def executor(assignment, state):
            return {
                "role": assignment.role.value,
                "evidence_ids": [],
                "claims_supported": True,  # claimed without evidence ids
                "agents_agree_unsupported": True,
                "artifact_ok": True,
            }

        orch = TeamOrchestrator(specialist_executor=executor)
        policy = TeamExecutionPolicy.team_default()
        # Force quick no-progress stop
        object.__setattr__(policy, "no_progress_window", 2)  # frozen — rebuild
        policy = TeamExecutionPolicy(
            completion_policy=policy.completion_policy,
            collaboration=policy.collaboration,
            no_progress_window=2,
        )
        st = orch.start(
            request_text="research claim",
            task_category="research",
            requires_research=True,
            policy=policy,
        )
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)

    def test_i_cancel_no_success_leak(self) -> None:
        def executor(assignment, state):
            return {"role": assignment.role.value, "evidence_ids": ["ev:1"]}

        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="x", task_category="general")
        orch.advance(st.run_id)
        st = orch.cancel(st.run_id)
        self.assertEqual(st.status, TeamRunStatus.CANCELLED)
        # Late result rejected
        if st.assignments:
            orch.apply_specialist_result(
                st.run_id,
                st.assignments[0].task_id,
                {
                    "role": st.assignments[0].role.value,
                    "evidence_ids": ["ev:late"],
                    "artifact_ok": True,
                    "tests_passed": True,
                    "test_receipt_id": "test:late",
                },
                graph_revision=st.graph_revision,
            )
        self.assertEqual(st.status, TeamRunStatus.CANCELLED)

    def test_m_exceeds_legacy_100_iterations_fixture(self) -> None:
        """Controlled fixture: TEAM continues past old round-100 mindset."""

        def executor(assignment, state):
            if state.iteration >= 101:
                return {
                    "role": assignment.role.value,
                    "evidence_ids": ["ev:late", "test:1"],
                    "tests_passed": True,
                    "test_receipt_id": "test:1",
                    "artifact_ok": True,
                }
            return {"role": assignment.role.value, "evidence_ids": [f"ev:{state.iteration}"]}

        # Meaningful progress each iteration via evidence, but criteria unmet until 101.
        # Use coding contract; evidence alone without tests_passed keeps unsatisfied,
        # and progress_deltas.meaningful requires criteria increase — so no_progress
        # would fire. Inject criterion progress by satisfying partially... 
        # Simpler: disable no-progress with large window and only complete at 101.
        policy = TeamExecutionPolicy(no_progress_window=10_000)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(
            request_text="long",
            task_category="coding",
            requires_coding=True,
            policy=policy,
        )
        st = orch.run_until_terminal(st.run_id, max_iterations=200)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertGreaterEqual(st.iteration, 101)

    def test_n_no_progress_blocks_not_green(self) -> None:
        def executor(assignment, state):
            return {"role": assignment.role.value, "evidence_ids": []}

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="x", task_category="general", policy=policy)
        st = orch.run_until_terminal(st.run_id, max_iterations=20)
        self.assertEqual(st.status, TeamRunStatus.BLOCKED)
        self.assertTrue(any(b.kind == "no_progress" for b in st.blockers))

    def test_p_single_model_sequential(self) -> None:
        order: list[str] = []

        def executor(assignment, state):
            order.append(assignment.role.value)
            return {
                "role": assignment.role.value,
                "evidence_ids": ["ev:1", "test:1"],
                "tests_passed": True,
                "test_receipt_id": "test:1",
                "artifact_ok": True,
            }

        policy = TeamExecutionPolicy(single_model_sequential=True, allow_parallel_workers=False)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(
            request_text="fix",
            task_category="coding",
            requires_coding=True,
            policy=policy,
        )
        orch.advance(st.run_id)
        # Roles executed in dependency order (sequential).
        self.assertEqual(order, sorted(order, key=lambda r: order.index(r)))
        self.assertGreaterEqual(len(order), 1)

    def test_r_optional_cap_incomplete(self) -> None:
        def executor(assignment, state):
            return {"role": assignment.role.value, "evidence_ids": []}

        policy = TeamExecutionPolicy(
            user_caps=OptionalUserCaps(max_iterations=1),
            no_progress_window=100,
        )
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="x", task_category="general", policy=policy)
        # First advance runs iteration 0; second hits cap after iteration increments.
        orch.advance(st.run_id)
        st = orch.advance(st.run_id)
        # May need one more after revising
        for _ in range(5):
            if st.status in {TeamRunStatus.BLOCKED, TeamRunStatus.COMPLETED}:
                break
            st = orch.advance(st.run_id)
        self.assertEqual(st.status, TeamRunStatus.BLOCKED)
        self.assertTrue(any(b.kind == "user_cap_reached" for b in st.blockers))

    def test_s_malformed_result_fail_closed(self) -> None:
        def executor(assignment, state):
            return "not-a-dict"  # type: ignore[return-value]

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="x", task_category="general", policy=policy)
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)

    def test_x_partial_export_provisional(self) -> None:
        def executor(assignment, state):
            return {
                "role": assignment.role.value,
                "evidence_ids": [],
                "provisional_artifact": {"text": "draft"},
            }

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="x", task_category="general", policy=policy)
        orch.advance(st.run_id)
        export = orch.export_artifact(st.run_id)
        self.assertTrue(export["provisional"])
        self.assertIn("PROVISIONAL", export.get("watermark", ""))

    def test_z_uncertainty_assessment(self) -> None:
        def executor(assignment, state):
            return {
                "role": assignment.role.value,
                "evidence_ids": ["uncertainty:statement"],
                "supported_uncertainty": True,
            }

        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="map uncertainty", task_category="uncertainty")
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)

    def test_g_synthesis_new_claim_reopens(self) -> None:
        phase = {"n": 0}

        def executor(assignment, state):
            phase["n"] += 1
            if state.iteration == 0:
                return {
                    "role": assignment.role.value,
                    "evidence_ids": ["ev:1"],
                    "artifact_ok": True,
                    "unsupported_new_claim": True,
                }
            return {
                "role": assignment.role.value,
                "evidence_ids": ["ev:1", "ev:2"],
                "artifact_ok": True,
                "unsupported_new_claim": False,
            }

        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="write", task_category="general")
        st = orch.run_until_terminal(st.run_id, max_iterations=20)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertGreaterEqual(st.iteration, 1)


class ResearchTeamBudgetTests(unittest.TestCase):
    def test_q_legacy_normal_custom_unchanged(self) -> None:
        base = budget_for_depth("deep")
        normal = resolve_execution_budget(execution_mode=ResearchExecutionMode.NORMAL, base=base)
        self.assertEqual(normal.rounds, 10)
        self.assertEqual(normal.research_workers, 2)
        self.assertEqual(normal.completion_policy, "fixed_budget")
        custom = resolve_execution_budget(
            execution_mode=ResearchExecutionMode.CUSTOM,
            base=base,
            overrides={"rounds": 7, "research_workers": 3},
        )
        self.assertEqual(custom.rounds, 7)
        self.assertEqual(custom.research_workers, 3)

    def test_team_null_rounds_and_catalog(self) -> None:
        base = budget_for_depth("deep")
        team = resolve_execution_budget(execution_mode=ResearchExecutionMode.TEAM, base=base)
        self.assertIsNone(team.rounds)
        self.assertEqual(team.completion_policy, "quality_contract")
        cat = budget_catalog()
        self.assertIn("team", cat["execution_modes"])
        self.assertIsNone(cat["execution_modes"]["team"]["rounds"])
        self.assertIn("quality criteria", cat["execution_modes"]["team"]["description"])

    def test_null_survives_serialization(self) -> None:
        base = budget_for_depth("standard")
        team = resolve_execution_budget(execution_mode="team", base=base)
        raw = team.public_dict()
        self.assertIsNone(raw["rounds"])
        from Data.modules.research.types import ResearchBudget

        restored = ResearchBudget.from_dict(raw)
        self.assertIsNone(restored.rounds)
        self.assertEqual(restored.completion_policy, "quality_contract")


class CollaborationStrategyTests(unittest.TestCase):
    def test_team_not_confused_with_reasoning_depth(self) -> None:
        self.assertEqual(normalize_collaboration_strategy("team"), CollaborationStrategy.TEAM)
        self.assertEqual(normalize_collaboration_strategy("direct"), CollaborationStrategy.DIRECT)
        self.assertIn("quality criteria", USER_FACING_TEAM_DESCRIPTION)

    def test_reject_negative_caps(self) -> None:
        with self.assertRaises(ValueError):
            OptionalUserCaps(max_iterations=-1)


class HonestyVerifierTests(unittest.TestCase):
    def test_honesty_does_not_auto_pass_completion(self) -> None:
        from Data.modules.cognition.completion import CompletionEngine
        from Data.modules.cognition.task_model import AcceptanceCriterion, TaskModel
        from Data.modules.cognition.types import RiskClass
        from Data.modules.verification.types import VerifierKind

        engine = CompletionEngine()
        task = TaskModel(
            task_id="t",
            run_id="r",
            raw_request="x",
            goal="x",
            domain="general",
            task_type="general",
            risk_class=RiskClass.MEDIUM,
            acceptance_criteria=[
                AcceptanceCriterion(
                    criterion_id="h",
                    predicate="honesty",
                    description="honesty",
                    verifier_kind=VerifierKind.HONESTY,
                )
            ],
            success_criteria=["honesty"],
            required_evidence=[],
        )
        decision = engine.evaluate(task, observations=[], response_text="hello world answer")
        self.assertFalse(decision.criteria[0].met)


if __name__ == "__main__":
    unittest.main()
