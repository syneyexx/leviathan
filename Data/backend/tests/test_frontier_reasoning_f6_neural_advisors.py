"""F6 — Neural TaskModel / planner advisors (validated, non-owning)."""

from __future__ import annotations

import unittest

from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.neural_advisors import (
    CallableTaskAdvisor,
    HeuristicPlanAdvisor,
    HeuristicTaskAdvisor,
    apply_task_advice,
    merge_plan_advice,
    validate_plan_advice,
    validate_task_advice,
)
from Data.modules.cognition.planner import CognitivePlanner
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import PlanStep, ReasoningStrategy, RiskClass


class TaskAdviceValidationTests(unittest.TestCase):
    def test_rejects_forbidden_authority_fields(self) -> None:
        base = TaskModelBuilder().build("hello")
        advice = validate_task_advice(
            {
                "risk_class": "CRITICAL",
                "hard_constraints": ["delete everything"],
                "unknowns": ["need clarify X"],
                "entities": ["X"],
            },
            base=base,
            source="fixture",
        )
        self.assertTrue(advice.accepted)
        self.assertIn("risk_class", advice.rejected_fields)
        self.assertIn("hard_constraints", advice.rejected_fields)
        merged = apply_task_advice(base, advice)
        self.assertEqual(merged.risk_class, base.risk_class)
        self.assertEqual(merged.hard_constraints, base.hard_constraints)
        self.assertIn("need clarify X", merged.unknowns)
        self.assertTrue(merged.metadata.get("neural_task_advice_applied"))

    def test_cannot_downgrade_research_mode(self) -> None:
        base = TaskModelBuilder().build("deep research into quantum computing")
        # Force deep on base if not already
        if base.research_mode != "deep":
            from dataclasses import replace

            base = replace(base, research_mode="deep", requires_research=True)
        advice = validate_task_advice({"research_mode": "none"}, base=base)
        self.assertIn("research_mode_downgrade", advice.rejected_fields)
        self.assertIsNone(advice.research_mode)

    def test_builder_applies_heuristic_advisor(self) -> None:
        builder = TaskModelBuilder(advisor=HeuristicTaskAdvisor())
        task = builder.build('Compare "Alpha" vs "Beta" for latest market fit')
        self.assertIn("Alpha", task.entities)
        self.assertIn("Beta", task.entities)
        self.assertTrue(task.requires_current_information or task.requires_research)
        self.assertTrue((task.metadata or {}).get("task_advice", {}).get("accepted"))


class PlanAdviceValidationTests(unittest.TestCase):
    def test_rejects_incomplete_and_unknown_capabilities(self) -> None:
        advice = validate_plan_advice(
            [
                {"objective": "no acceptance"},  # reject
                {
                    "step_id": "a1",
                    "objective": "Check freshness",
                    "acceptance_condition": "freshness recorded",
                    "likely_capabilities": ["knowledge.search", "rm -rf", "shell.root"],
                    "dependencies": ["s1"],
                    "risk_class": "LOW",
                },
            ],
            strategy=ReasoningStrategy.RETRIEVE_THEN_ANSWER,
            risk_floor=RiskClass.MEDIUM,
            existing_step_ids=["s1"],
        )
        self.assertTrue(advice.accepted)
        self.assertEqual(advice.rejected_count, 1)
        self.assertEqual(len(advice.steps), 1)
        self.assertEqual(advice.steps[0].likely_capabilities, ("knowledge.search",))
        # Risk cannot go below floor.
        self.assertEqual(advice.steps[0].risk_class, RiskClass.MEDIUM)

    def test_planner_appends_validated_advisory_steps(self) -> None:
        planner = CognitivePlanner(advisor=HeuristicPlanAdvisor())
        task = TaskModelBuilder(advisor=HeuristicTaskAdvisor()).build(
            "What is the latest news about fusion energy?"
        )
        decision = MetaController().decide(task)
        plan = planner.plan(task, decision)
        advisory = [
            s for s in plan.steps if isinstance(s.resource_estimate, dict) and s.resource_estimate.get("advisory")
        ]
        self.assertGreaterEqual(len(advisory), 1)
        self.assertTrue(any(a.startswith("plan_advice_accepted:") for a in plan.assumptions))
        # Template steps remain first.
        self.assertFalse(plan.steps[0].resource_estimate.get("advisory"))

    def test_merge_keeps_template_owner(self) -> None:
        from Data.modules.cognition.types import CognitivePlan

        base = CognitivePlan(
            plan_id="p1",
            strategy=ReasoningStrategy.DIRECT,
            steps=[
                PlanStep(
                    step_id="s1",
                    objective="Answer",
                    acceptance_condition="reply",
                    risk_class=RiskClass.LOW,
                )
            ],
        )
        advice = validate_plan_advice(
            [
                {
                    "step_id": "s1",  # collision → renamed
                    "objective": "Extra check",
                    "acceptance_condition": "checked",
                }
            ],
            strategy=ReasoningStrategy.DIRECT,
            risk_floor=RiskClass.LOW,
            existing_step_ids=["s1"],
        )
        merged = merge_plan_advice(base, advice)
        self.assertEqual(merged.steps[0].step_id, "s1")
        self.assertEqual(merged.steps[0].objective, "Answer")
        self.assertEqual(len(merged.steps), 2)
        self.assertNotEqual(merged.steps[1].step_id, "s1")


class ModelAdvisorParseTests(unittest.TestCase):
    def test_callable_task_advisor_parses_json(self) -> None:
        def caller(**kwargs):
            return '{"entities":["Neptune"],"unknowns":["orbital period details"],"risk_class":"CRITICAL"}'

        advisor = CallableTaskAdvisor(model_caller=caller)
        base = TaskModelBuilder().build("Tell me about Neptune")
        raw = advisor.advise_task(base.raw_request, base)
        advice = validate_task_advice(raw, base=base, source="model")
        merged = apply_task_advice(base, advice)
        self.assertIn("Neptune", merged.entities)
        self.assertIn("risk_class", advice.rejected_fields)
        self.assertNotEqual(merged.risk_class, RiskClass.CRITICAL)


if __name__ == "__main__":
    unittest.main()
