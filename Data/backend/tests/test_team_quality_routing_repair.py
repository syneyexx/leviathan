"""Production-path TEAM quality routing — conversational vs strict contracts."""

from __future__ import annotations

import unittest

from Data.modules.cognition.team_orchestrator import TeamOrchestrator
from Data.modules.cognition.team_strategy import (
    CollaborationStrategy,
    TeamExecutionPolicy,
    TeamRole,
    TeamRunStatus,
    TeamSpecialistResult,
    build_default_contract_for_request,
    mark_criterion_not_applicable,
    normalize_collaboration_strategy,
    select_roles_for_task,
)
from Data.modules.cognition.team_task_profile import (
    build_team_task_profile,
)
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
    new_contract_id,
)


REPRO_NL = "Hey, hoe is het met jou? Wie ben jij? Wat kan je allemaal?"


def _conversational_executor(assignment, state):
    text = (
        "Hallo! Ik ben LEVIATHAN, een lokale team-assistent. "
        "Ik kan uitleggen, redeneren en samenvatten binnen de beschikbare runtime-mogelijkheden."
    )
    return TeamSpecialistResult(
        role=assignment.role.value,
        task_id=assignment.task_id,
        summary=text,
        provisional_artifact={"text": text, "provisional": True},
    ).to_dict()


class TeamTaskProfileTests(unittest.TestCase):
    def test_repro_is_self_description_lightweight(self) -> None:
        profile = build_team_task_profile(REPRO_NL)
        self.assertEqual(profile.category, "self_description")
        self.assertTrue(profile.lightweight)
        self.assertFalse(profile.requires_external_research)

    def test_multilingual_conversation(self) -> None:
        for msg in ("Hoi!", "Hoe gaat het?", "Hello, who are you?", "Wat kun jij?"):
            profile = build_team_task_profile(msg)
            self.assertTrue(
                profile.lightweight,
                msg=f"{msg} -> {profile.category}",
            )
            self.assertFalse(profile.requires_external_research)

    def test_factual_current_stays_strict(self) -> None:
        profile = build_team_task_profile("Wat is de huidige prijs van Bitcoin?")
        self.assertIn(profile.category, {"factual", "research"})
        self.assertTrue(profile.requires_external_research)
        self.assertFalse(profile.lightweight)

    def test_research_stays_strict(self) -> None:
        profile = build_team_task_profile(
            "Onderzoek de nieuwste kwartaalresultaten van NVIDIA."
        )
        self.assertEqual(profile.category, "research")
        self.assertTrue(profile.requires_external_research)

    def test_coding_stays_strict(self) -> None:
        profile = build_team_task_profile(
            "Fix deze functie en bewijs met tests dat hij werkt."
        )
        self.assertIn(profile.category, {"coding", "repair"})
        self.assertTrue(profile.requires_code_execution)

    def test_quantitative_stays_strict(self) -> None:
        profile = build_team_task_profile("Bereken 17.5% van 43,281.")
        self.assertEqual(profile.category, "quantitative")
        self.assertTrue(profile.requires_calculation)

    def test_general_explanation_lightweight(self) -> None:
        profile = build_team_task_profile("Leg recursie eenvoudig uit.")
        self.assertTrue(profile.lightweight)
        self.assertFalse(profile.requires_external_research)


class ConversationalTeamContractTests(unittest.TestCase):
    def test_a_exact_repro_completes(self) -> None:
        orch = TeamOrchestrator(specialist_executor=_conversational_executor)
        profile = build_team_task_profile(REPRO_NL)
        st = orch.start(request_text=REPRO_NL, profile=profile)
        st = orch.run_until_terminal(st.run_id, max_iterations=8)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertIsNotNone(st.acceptance)
        self.assertEqual(st.acceptance.outcome, AcceptanceOutcome.ACCEPTED)
        self.assertTrue((st.final_artifact or {}).get("text"))
        # Genuine TEAM — not silently DIRECT.
        roles = {a.role for a in st.assignments}
        self.assertIn(TeamRole.ANALYST, roles)
        self.assertIn(TeamRole.SYNTHESIZER, roles)
        self.assertIn(TeamRole.VERIFIER, roles)
        self.assertNotIn(TeamRole.RESEARCHER, roles)

    def test_b_casual_and_self_description_complete(self) -> None:
        for msg in ("Hoi!", "Hello, who are you?", "Tell me about your capabilities."):
            orch = TeamOrchestrator(specialist_executor=_conversational_executor)
            st = orch.start(request_text=msg)
            st = orch.run_until_terminal(st.run_id, max_iterations=8)
            self.assertEqual(st.status, TeamRunStatus.COMPLETED, msg=msg)

    def test_llm_artifact_ok_alone_is_not_proof(self) -> None:
        def executor(assignment, state):
            return {
                "role": assignment.role.value,
                "artifact_ok": True,  # bare model assertion — no text
                "evidence_ids": [],
            }

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text=REPRO_NL, policy=policy)
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)

    def test_research_not_auto_satisfied_by_conversation_rules(self) -> None:
        def executor(assignment, state):
            return TeamSpecialistResult(
                role=assignment.role.value,
                summary="BTC is probably around 100k",
                provisional_artifact={"text": "BTC is probably around 100k"},
            ).to_dict()

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(
            request_text="Wat is de huidige prijs van Bitcoin?",
            policy=policy,
        )
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertTrue(
            any(
                c.evidence_class
                in {EvidenceClass.CLAIM_SUPPORT, EvidenceClass.CITATION_AUDIT}
                for c in st.contract.criteria
            )
        )

    def test_coding_requires_test_receipt(self) -> None:
        def executor(assignment, state):
            return TeamSpecialistResult(
                role=assignment.role.value,
                summary="fixed",
                provisional_artifact={"text": "fixed"},
            ).to_dict()

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(
            request_text="Fix deze functie en bewijs met tests dat hij werkt.",
            policy=policy,
        )
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)

    def test_quantitative_requires_calc_receipt(self) -> None:
        def executor(assignment, state):
            return TeamSpecialistResult(
                role=assignment.role.value,
                summary="about 7574",
                provisional_artifact={"text": "about 7574"},
            ).to_dict()

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="Bereken 17.5% van 43,281.", policy=policy)
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)

    def test_unsupported_claim_agreement_rejected(self) -> None:
        def executor(assignment, state):
            return {
                "role": assignment.role.value,
                "evidence_ids": [],
                "claims_supported": True,
                "agents_agree_unsupported": True,
                "provisional_artifact": {"text": "agents agree without evidence"},
            }

        policy = TeamExecutionPolicy(no_progress_window=2)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(
            request_text="Research NVIDIA earnings",
            task_category="research",
            requires_research=True,
            policy=policy,
        )
        st = orch.run_until_terminal(st.run_id, max_iterations=10)
        self.assertNotEqual(st.status, TeamRunStatus.COMPLETED)

    def test_genuine_stagnation_blocks(self) -> None:
        def executor(assignment, state):
            return TeamSpecialistResult(
                role=assignment.role.value,
                summary="",
                notes="no output",
            ).to_dict()

        policy = TeamExecutionPolicy(no_progress_window=3)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text=REPRO_NL, policy=policy)
        st = orch.run_until_terminal(st.run_id, max_iterations=20)
        self.assertEqual(st.status, TeamRunStatus.BLOCKED)
        self.assertTrue(st.blockers)

    def test_fake_rewording_is_not_progress(self) -> None:
        n = {"i": 0}

        def executor(assignment, state):
            n["i"] += 1
            # Same substantive emptiness regarding research evidence; only wording changes.
            return {
                "role": assignment.role.value,
                "evidence_ids": [],
                "provisional_artifact": {
                    "text": f"Still unsupported claim wording variant {n['i']}"
                },
                "claims_supported": False,
            }

        policy = TeamExecutionPolicy(no_progress_window=3)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(
            request_text="Onderzoek de nieuwste kwartaalresultaten van NVIDIA.",
            policy=policy,
        )
        st = orch.run_until_terminal(st.run_id, max_iterations=20)
        self.assertEqual(st.status, TeamRunStatus.BLOCKED)

    def test_not_applicable_excluded_from_mandatory(self) -> None:
        base = QualityCriterion(
            criterion_id="crit:citation_audit",
            description="citations",
            verification_method="audit",
            evidence_class=EvidenceClass.CITATION_AUDIT,
            severity=CriterionSeverity.MANDATORY,
        )
        na = mark_criterion_not_applicable(
            base, justification="conversational task — no citations required"
        )
        deliverable = QualityCriterion(
            criterion_id="crit:deliverable_present",
            description="response",
            verification_method="inspect",
            evidence_class=EvidenceClass.ARTIFACT_INSPECTION,
        )
        contract = QualityContract(
            contract_id=new_contract_id(),
            version=1,
            run_id="r",
            request_ref="r",
            scope="hi",
            criteria=[deliverable, na],
        )
        self.assertEqual(len(contract.mandatory_applicable()), 1)
        verdicts = [
            CriterionVerdict(
                criterion_id="crit:deliverable_present",
                contract_version=1,
                artifact_revision="rev1",
                status=CriterionVerdictStatus.SATISFIED,
                verifier_identity="t",
                verifier_type="t",
                evidence_ids=("artifact:inspect",),
                public_justification="ok",
                created_at="t0",
            )
        ]
        rec = aggregate_acceptance(contract, verdicts, artifact_revision="rev1")
        self.assertEqual(rec.outcome, AcceptanceOutcome.ACCEPTED)
        self.assertEqual(na.applicability, CriterionApplicability.NOT_APPLICABLE)

    def test_followup_progress_resets_streak(self) -> None:
        def executor(assignment, state):
            if state.iteration >= 1:
                return _conversational_executor(assignment, state)
            return TeamSpecialistResult(
                role=assignment.role.value,
                summary="",
                notes="empty first pass",
            ).to_dict()

        policy = TeamExecutionPolicy(no_progress_window=5)
        orch = TeamOrchestrator(specialist_executor=executor)
        st = orch.start(request_text="Hoi!", policy=policy)
        st = orch.run_until_terminal(st.run_id, max_iterations=20)
        self.assertEqual(st.status, TeamRunStatus.COMPLETED)
        self.assertEqual(st.no_progress_streak, 0)
        self.assertGreaterEqual(st.iteration, 1)

    def test_team_not_silent_direct(self) -> None:
        self.assertEqual(
            normalize_collaboration_strategy("team"), CollaborationStrategy.TEAM
        )
        roles = select_roles_for_task(
            task_category="conversational",
            profile=build_team_task_profile("Hello"),
        )
        self.assertGreaterEqual(len(roles), 3)
        self.assertIn(TeamRole.ORCHESTRATOR, roles)

    def test_contract_conversational_has_no_citation_gate(self) -> None:
        profile = build_team_task_profile(REPRO_NL)
        contract = build_default_contract_for_request(
            run_id="r1",
            request_ref="r1",
            request_text=REPRO_NL,
            profile=profile,
        )
        ids = {c.criterion_id for c in contract.criteria}
        self.assertIn("crit:deliverable_present", ids)
        self.assertIn("crit:request_addressed", ids)
        self.assertIn("crit:synthesis_rechecked", ids)
        self.assertNotIn("crit:citation_audit", ids)
        self.assertNotIn("crit:claims_supported", ids)


class TypedSpecialistResultTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        raw = TeamSpecialistResult(
            role="synthesizer",
            summary="hello",
            provisional_artifact={"text": "hello"},
            evidence_refs=["ev:1"],
        ).to_dict()
        self.assertEqual(raw["schema"], "TeamSpecialistResult.v1")
        again = TeamSpecialistResult.from_mapping(raw)
        self.assertEqual(again.summary, "hello")
        self.assertTrue(again.provisional_artifact)


if __name__ == "__main__":
    unittest.main()
