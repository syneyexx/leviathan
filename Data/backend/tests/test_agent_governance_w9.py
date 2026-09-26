"""W9 — Real agents + recursion governance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.agents import (
    AgentFleetService,
    AgentFleetStore,
    AgentRuntime,
    DelegationGovernor,
    DelegationViolation,
    authority_rank,
    clamp_authority,
    detect_cycle,
    split_budget,
)
from Data.modules.agents.fleet_types import AgentDefinitionKind, MissionStatus, OrchestratorConfig
from Data.modules.cognition.delegation import DelegationService, DelegateRequest
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.memory import MemoryScope


class AuthorityBudgetHelpersTests(unittest.TestCase):
    def test_child_authority_never_exceeds_parent(self) -> None:
        self.assertEqual(clamp_authority("CRITICAL", "MEDIUM"), "MEDIUM")
        self.assertEqual(clamp_authority("LOW", "HIGH"), "LOW")
        self.assertLessEqual(authority_rank("MEDIUM"), authority_rank("HIGH"))

    def test_split_budget_from_parent_only(self) -> None:
        child = split_budget({"max_tool_calls": 8, "max_model_calls": 4}, fraction=0.5)
        self.assertEqual(child["max_tool_calls"], 4)
        self.assertEqual(child["max_model_calls"], 2)
        # Cannot invent unknown parent keys via overrides.
        child2 = split_budget({"max_tool_calls": 4}, overrides={"secret_escalation": 99})
        self.assertNotIn("secret_escalation", child2)

    def test_cycle_detection(self) -> None:
        self.assertIsNone(detect_cycle(["cognition"], "research"))
        cycle = detect_cycle(["cognition", "research"], "research")
        self.assertEqual(cycle, ["research", "research"])


class DelegationGovernorTests(unittest.TestCase):
    def test_depth_exceeded(self) -> None:
        gov = DelegationGovernor(default_max_depth=2)
        decision = gov.authorize(
            parent_run_id="run-1",
            agent_kind="research",
            delegation_depth=2,
            max_delegation_depth=2,
            remaining_parent_budget={"slots": 1},
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.violation, DelegationViolation.DEPTH_EXCEEDED)

    def test_cycle_refused(self) -> None:
        gov = DelegationGovernor()
        decision = gov.authorize(
            parent_run_id="run-1",
            agent_kind="coding",
            delegation_depth=1,
            max_delegation_depth=5,
            remaining_parent_budget={"slots": 2},
            lineage=["cognition", "coding"],
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.violation, DelegationViolation.CYCLE_DETECTED)

    def test_authority_clamped_on_frame(self) -> None:
        gov = DelegationGovernor()
        decision = gov.authorize(
            parent_run_id="run-1",
            agent_kind="research",
            parent_authority="MEDIUM",
            requested_authority="CRITICAL",
            remaining_parent_budget={"max_tool_calls": 4},
            lineage=["cognition"],
        )
        self.assertTrue(decision.allowed)
        assert decision.frame is not None
        self.assertEqual(decision.frame.child_authority, "MEDIUM")
        self.assertTrue(decision.metadata.get("authority_clamped"))
        self.assertEqual(decision.frame.memory_scope, "AGENT_PRIVATE")

    def test_budget_exhausted(self) -> None:
        gov = DelegationGovernor()
        decision = gov.authorize(
            parent_run_id="run-1",
            agent_kind="research",
            remaining_parent_budget={"max_tool_calls": 0, "max_model_calls": 0},
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.violation, DelegationViolation.BUDGET_EXHAUSTED)


class DelegationServiceGovernanceTests(unittest.TestCase):
    def test_service_refuses_cycle_before_handler(self) -> None:
        called = {"n": 0}

        def handler(req: DelegateRequest):
            called["n"] += 1
            from Data.modules.cognition.delegation import DelegateResult

            return DelegateResult(
                delegation_id=req.delegation_id,
                status="COMPLETED",
                summary="should not run",
            )

        svc = DelegationService()
        svc.register("research", handler)
        req = DelegationService.build_request(
            goal="x",
            agent_kind="research",
            parent_run_id="p1",
            delegation_depth=1,
            max_delegation_depth=5,
            remaining_parent_budget={"max_tool_calls": 4},
            lineage=["cognition", "research"],
        )
        result = svc.delegate(req)
        self.assertEqual(result.status, "REFUSED")
        self.assertEqual(called["n"], 0)
        self.assertIn("CYCLE", result.error or "")

    def test_handler_receives_governed_child_budget(self) -> None:
        seen: dict = {}

        def handler(req: DelegateRequest):
            seen["budget"] = dict(req.child_budget)
            seen["authority"] = req.authority_ceiling
            seen["depth"] = req.delegation_depth
            from Data.modules.cognition.delegation import DelegateResult

            return DelegateResult(
                delegation_id=req.delegation_id,
                status="COMPLETED",
                summary="ok",
            )

        svc = DelegationService()
        svc.register("coding", handler)
        req = DelegationService.build_request(
            goal="fix",
            agent_kind="coding",
            parent_run_id="run-a",
            authority_ceiling="HIGH",
            remaining_parent_budget={"max_tool_calls": 8, "max_model_calls": 4},
            lineage=["cognition"],
        )
        result = svc.delegate(req)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(seen["depth"], 1)
        self.assertEqual(seen["authority"], "HIGH")
        self.assertEqual(seen["budget"]["max_tool_calls"], 4)
        self.assertIn("governance", result.metadata)


class FleetChildGovernanceTests(unittest.TestCase):
    def test_orchestrator_cycle_marks_child_failed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "fleet.db"
        from Data.backend.migrations import MigrationRunner

        MigrationRunner(db).apply_all()
        store = AgentFleetStore(db)
        catalog = build_default_catalog()
        gateway = ExecutionGateway(catalog=catalog)
        runtime = AgentRuntime(gateway=gateway, agents_enabled=True)
        fleet = AgentFleetService(store, runtime)
        fleet.initialize(seed_defaults=False)
        # Create member first so orchestrator validation can resolve it.
        child_def = fleet.create_agent(
            {
                "name": "ChildA",
                "kind": AgentDefinitionKind.GENERIC.value,
                "role": "worker",
            }
        )
        parent = fleet.create_agent(
            {
                "name": "Orch",
                "kind": AgentDefinitionKind.ORCHESTRATOR.value,
                "role": "orchestrator",
                "orchestrator": OrchestratorConfig(
                    member_agent_ids=[child_def.agent_id],
                    max_delegation_depth=3,
                    strategy="sequential",
                ).public_dict(),
            }
        )
        mission = fleet.launch_mission(
            agent_id=parent.agent_id,
            request="do work",
            dry_run=True,
            metadata={
                "delegation_lineage": [parent.agent_id, child_def.agent_id],
                "authority_ceiling": "MEDIUM",
                "remaining_budget": {"slots": 2},
                "max_delegation_depth": 3,
            },
        )
        # Force lineage already containing child id so next hop cycles.
        mission.metadata["delegation_lineage"] = [parent.agent_id, child_def.agent_id]
        refused = fleet._launch_child(mission, child_def.agent_id, depth=1, use_jobs=False)
        self.assertEqual(refused.status, MissionStatus.FAILED)
        self.assertIn("CYCLE", refused.error or "")


class MemoryScopeW9Tests(unittest.TestCase):
    def test_orchestrator_shared_scope_exists(self) -> None:
        self.assertEqual(MemoryScope.AGENT_PRIVATE.value, "AGENT_PRIVATE")
        self.assertEqual(MemoryScope.ORCHESTRATOR_SHARED.value, "ORCHESTRATOR_SHARED")


if __name__ == "__main__":
    unittest.main()
