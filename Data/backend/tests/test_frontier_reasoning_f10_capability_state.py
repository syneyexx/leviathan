"""F10 — Cognitive CapabilityState matrix (generate / execute / network / …)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.cognition.action_selector import ActionSelector
from Data.modules.cognition.capability_state import (
    AxisState,
    CapabilityAxis,
    CapabilityState,
    derive_capability_state,
)
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.store import CognitionStore
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import (
    CognitiveAction,
    CognitiveActionKind,
    CognitiveRunStatus,
    RiskClass,
)


class CapabilityStateContractTests(unittest.TestCase):
    def test_public_dict_marks_cognition_matrix(self) -> None:
        state = CapabilityState(
            generate=AxisState.ALLOWED,
            execute=AxisState.REQUIRES_APPROVAL,
            network=AxisState.DENIED,
            delegate=AxisState.DENIED,
            write_filesystem=AxisState.DENIED,
            authority_ceiling="HIGH",
            approval_required=True,
            reasons=("outbound_network_denied",),
        )
        public = state.public_dict()
        self.assertTrue(public["truth"]["capability_state_is_cognition_matrix"])
        self.assertTrue(public["truth"]["discoverable_is_not_authorized"])
        self.assertTrue(public["truth"]["model_text_cannot_grant_axes"])
        self.assertTrue(public["truth"]["not_provider_capability_probe"])
        self.assertEqual(public["matrix"]["network"], "denied")
        self.assertTrue(state.allows(CapabilityAxis.GENERATE))
        self.assertTrue(state.blocks(CapabilityAxis.NETWORK))

    def test_derive_denies_network_when_outbound_off(self) -> None:
        task = TaskModelBuilder().build("Research the latest news on fusion")
        cs = derive_capability_state(
            task=task,
            model_available=True,
            execution_gateway_available=True,
            delegation_enabled=True,
            network_outbound_allowed=False,
            cognition_enabled=True,
        )
        self.assertEqual(cs.network, AxisState.DENIED)
        self.assertIn("outbound_network_denied", cs.reasons)

    def test_derive_execute_unavailable_without_gateway(self) -> None:
        task = TaskModelBuilder().build("hello")
        cs = derive_capability_state(
            task=task,
            model_available=True,
            execution_gateway_available=False,
            delegation_enabled=False,
            network_outbound_allowed=False,
            cognition_enabled=True,
        )
        self.assertEqual(cs.execute, AxisState.UNAVAILABLE)
        self.assertEqual(cs.delegate, AxisState.DENIED)
        self.assertEqual(cs.generate, AxisState.ALLOWED)

    def test_high_risk_requires_approval_on_execute(self) -> None:
        task = TaskModelBuilder().build("hello")
        task.risk_class = RiskClass.HIGH
        task.metadata = {
            **(task.metadata or {}),
            "permissions": {
                "filesystem_write": True,
                "approval_required": True,
                "network": True,
            },
        }
        cs = derive_capability_state(
            task=task,
            model_available=True,
            execution_gateway_available=True,
            delegation_enabled=True,
            network_outbound_allowed=True,
            cognition_enabled=True,
        )
        self.assertTrue(cs.approval_required)
        self.assertEqual(cs.execute, AxisState.REQUIRES_APPROVAL)
        self.assertEqual(cs.write_filesystem, AxisState.REQUIRES_APPROVAL)


class ActionSelectorCapabilityGateTests(unittest.TestCase):
    def test_filters_invoke_when_execute_unavailable(self) -> None:
        task = TaskModelBuilder().build("run a tool please")
        decision = MetaController().decide(task)
        cs = CapabilityState(
            generate=AxisState.ALLOWED,
            execute=AxisState.UNAVAILABLE,
            network=AxisState.DENIED,
            delegate=AxisState.DENIED,
            write_filesystem=AxisState.DENIED,
        )
        selector = ActionSelector()
        # Build candidates via select — should not return INVOKE when blocked
        from Data.modules.cognition.belief_state import BeliefState
        from Data.modules.cognition.working_memory import WorkingMemory

        action = selector.select(
            task=task,
            decision=decision,
            plan=None,
            beliefs=BeliefState(),
            working_memory=WorkingMemory(),
            observations=[],
            budgets_remaining={
                "iterations": 5,
                "model_calls": 5,
                "tool_calls": 5,
                "agent_delegations": 0,
                "replans": 1,
                "retries": 1,
                "retrieval_rounds": 2,
                "critic_passes": 1,
                "model_tokens": 1000,
                "wall_ok": 1,
            },
            capability_state=cs,
        )
        self.assertNotEqual(action.kind, CognitiveActionKind.INVOKE_CAPABILITY)


class RuntimeCapabilityStateTests(unittest.TestCase):
    def test_submit_exposes_capability_state(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=True,
            iterative=False,
            network_outbound_allowed=False,
        )
        status = runtime.submit("Research latest climate data", run=False)
        self.assertIn("capability_state", status)
        cs = status["capability_state"]
        self.assertTrue(status["truth"]["capability_state_is_cognition_matrix"])
        self.assertEqual(cs["network"], "denied")
        self.assertTrue(cs["truth"]["not_provider_capability_probe"])

    def test_block_delegate_when_delegation_disabled(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=True,
            iterative=False,
            delegation_enabled=False,
        )
        status = runtime.submit("Research something", run=False)
        state = runtime._require(status["run_id"])
        state.status = CognitiveRunStatus.REASONING
        action = CognitiveAction(
            kind=CognitiveActionKind.DELEGATE_AGENT,
            action_id="a1",
            rationale="test",
            arguments={"agent_kind": "research", "allow_web": False},
        )
        obs = runtime._execute_action(state, action, history=None)
        self.assertIsNotNone(obs)
        assert obs is not None
        self.assertFalse(obs.success)
        self.assertIn("DELEGATE", obs.error or "")

    def test_block_network_web_delegate(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=True,
            iterative=False,
            delegation_enabled=True,
            network_outbound_allowed=False,
        )
        status = runtime.submit("Research something", run=False)
        state = runtime._require(status["run_id"])
        state.status = CognitiveRunStatus.REASONING
        action = CognitiveAction(
            kind=CognitiveActionKind.DELEGATE_AGENT,
            action_id="a2",
            rationale="test",
            arguments={"agent_kind": "research", "allow_web": True},
        )
        obs = runtime._execute_action(state, action, history=None)
        self.assertIsNotNone(obs)
        assert obs is not None
        self.assertEqual(obs.error, "COGNITION_CAPABILITY_NETWORK_DENIED")

    def test_persist_and_hydrate_capability_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cognition.db"
            MigrationRunner(db).apply_all()
            store = CognitionStore(db_path=db)
            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                store=store,
                network_outbound_allowed=True,
                delegation_enabled=True,
            )
            status = runtime.submit("hello", run=False)
            run_id = status["run_id"]
            live = runtime._require(run_id)
            live.status = CognitiveRunStatus.SHADOW
            runtime._persist_update(live, final=True)
            runtime._runs.clear()
            hydrated = runtime._hydrate_from_store(run_id)
            self.assertEqual(
                hydrated.capability_state.generate.value,
                live.capability_state.generate.value,
            )
            public = hydrated.public_status()
            self.assertIn("capability_state", public)
            store.close()


if __name__ == "__main__":
    unittest.main()
