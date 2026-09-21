from __future__ import annotations

import unittest

from capability_intel.adapters.native import native_capabilities
from capability_intel.collaboration import MissionState
from capability_intel.contracts import AgentContract, CanonicalCapability
from capability_intel.planner import plan_requirements
from capability_intel.policy import policy_allows
from hades_brain.agent_protocol import from_agent_contract, from_trading_role, justify_additional_agent
from hades_brain.domain_runtime import MIGRATION_MATRIX, StaticDomainRuntime, migration_matrix
from hades_brain.evidence import evaluate_verification, should_stop_reasoning
from hades_brain.mission import compile_role_view, compose_domain_steps, cross_domain_handoff
from hades_brain.model_intelligence import requirements_from_domain, should_escalate
from hades_brain.service import get_brain, reset_brain
from hades_brain.substrate import substrate_overview
from hades_brain.traits import infer_traits
from plugin_runtime_v2 import evaluate_global_side_effect_policies


class _LabRole:
    role_id = "validator"
    mandate = "Independent evaluation of a trading experiment."
    reads = ("evaluations", "experiments")
    writes = ()
    forbidden = ("orders", "risk_limits")
    output_schema = {"verdict": "string"}


class OneBrainContractTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_brain()

    def tearDown(self) -> None:
        reset_brain()

    def test_substrate_is_not_a_monolith(self) -> None:
        overview = substrate_overview()
        self.assertFalse(overview["monolith"])
        self.assertIn("capability_registry", overview["components"])
        self.assertEqual(overview["components"]["tool_mcp_runtime"]["owner"].split(" +")[0], "mcp_host")

    def test_agent_contracts_project_across_domains(self) -> None:
        coding = from_agent_contract(
            AgentContract(canonical_id="hades.coding_agent", specialties=["coding"], accepts=["coding_task"], produces=["patch"]),
            domain="coding",
            responsibility="Investigate and patch",
        )
        trading = from_trading_role(_LabRole())
        self.assertEqual(coding.domain, "coding")
        self.assertEqual(trading.domain, "trading")
        self.assertIn("orders", trading.authority_limits)
        self.assertEqual(coding.identity, "hades.coding_agent")
        self.assertEqual(trading.contract.canonical_id, "trading.lab.validator")

    def test_named_role_is_not_enough_to_add_an_agent(self) -> None:
        self.assertIsNone(justify_additional_agent(
            unique_capability=False,
            specialist=False,
            parallel=False,
            independent_verify=False,
            authority_separation=False,
            information_gain=False,
        ))
        self.assertEqual(
            justify_additional_agent(
                unique_capability=False,
                specialist=False,
                parallel=False,
                independent_verify=True,
                authority_separation=False,
                information_gain=False,
            ),
            "independent_verification",
        )

    def test_domain_runtimes_remain_specialized(self) -> None:
        matrix = migration_matrix()
        self.assertIn("clock", matrix["trading"]["specialized"])
        self.assertIn("worktrees", matrix["coding"]["specialized"])
        self.assertIn("FFmpeg", matrix["media"]["specialized"])
        self.assertIn("citations", matrix["research"]["specialized"])
        runtime = StaticDomainRuntime("trading")
        accepted = runtime.accept_mission({"mission_id": "m1", "artifacts": [{"kind": "artifact_ref", "value": "run_1"}]})
        self.assertEqual(runtime.status(accepted["handle"])["status"], "accepted")
        self.assertEqual(runtime.artifacts(accepted["handle"])[0]["kind"], "artifact_ref")
        native_ids = {item.canonical_id for item in native_capabilities()}
        self.assertIn("hades.trading_lab", native_ids)
        self.assertIn("hades.media", native_ids)

    def test_cross_domain_handoff_uses_refs_not_transcript(self) -> None:
        payload = cross_domain_handoff(
            from_domain="research",
            to_domain="trading",
            goal="Analyze cited market structure",
            artifact_refs=["artifact:report"],
            evidence_refs=["evidence:cite-1"],
            extra={"transcript": "FULL HISTORY MUST NOT LEAK"},
        )
        self.assertFalse(payload["full_transcript"])
        self.assertNotIn("FULL HISTORY", str(payload))
        steps = compose_domain_steps(
            [
                {"domain": "research", "produces": ["artifact:report"]},
                {"domain": "trading"},
                {"domain": "media"},
            ]
        )
        self.assertEqual(steps[1]["artifact_refs"], ["artifact:report"])
        self.assertFalse(steps[1]["upstream_transcript"])

    def test_role_view_is_bounded(self) -> None:
        mission = MissionState(mission_id="m", goal="fix flaky test", artifacts=["diff:abc"], evidence=["test:log"], verification={"acceptance": ["tests_pass"]})
        view = compile_role_view(mission, role="coding.test_engineer", extra={"impacted_tests": ["test_flaky.py"], "task": "verify"})
        self.assertFalse(view["full_transcript"])
        self.assertIn("acceptance", view)
        self.assertEqual(view["impacted_tests"], ["test_flaky.py"])

    def test_shared_model_intelligence_is_requirement_only(self) -> None:
        req = requirements_from_domain("coding")
        self.assertTrue(req["supports_tools"])
        self.assertFalse(should_escalate(complexity="low", failure_evidence=False, tool_required=False, verification_gap=False))
        self.assertTrue(should_escalate(complexity="high", failure_evidence=False, tool_required=True, verification_gap=False))

    def test_policy_remains_authoritative(self) -> None:
        record = CanonicalCapability(
            canonical_id="net.tool",
            kind="tool",
            name="Web crawl",
            plugin_id="crawler",
            effects=["network"],
            side_effect_class="network",
            availability=True,
            health="available",
        )
        plugin = {
            "id": "crawler",
            "enabled": True,
            "status": "ready",
            "trust": "verified",
            "permissions": ["network"],
            "manifest": {"autonomous": True},
        }
        tool = {"name": "Web crawl", "metadata": {"autonomous": True, "permissions": ["network"]}}
        allowed, reason = policy_allows(
            record,
            plugin=plugin,
            tool=tool,
            settings={"network_policy": "block"},
            invocation_type="autonomous",
            permission_ok=lambda *_a, **_k: True,
        )
        self.assertFalse(allowed)
        self.assertTrue(reason)
        verdict = evaluate_global_side_effect_policies(
            contract={"effects": ["network"]},
            settings={"network_policy": "block"},
            invocation_type="autonomous",
            approved_by_user=True,
        )
        self.assertFalse(verdict["allowed"])

    def test_deterministic_verification_stops_reasoning(self) -> None:
        outcome = evaluate_verification(
            domain="coding",
            execution_success=True,
            evidence={"tests_passed": True, "refs": ["run:tests"]},
            agent_claims=["looks good"],
        )
        self.assertTrue(outcome.deterministic)
        self.assertFalse(outcome.verifier_model_called)
        self.assertTrue(should_stop_reasoning(outcome))

    def test_capability_traits_are_inferred(self) -> None:
        traits = infer_traits(kind="mcp_provider", side_effect_class="network", extras={"requires_auth": True})
        self.assertIn("executable", traits)
        self.assertIn("networked", traits)
        self.assertIn("requires_auth", traits)
        self.assertIn("side_effecting", traits)

    def test_simple_plan_stays_simple(self) -> None:
        plan = plan_requirements("Explain what a mutex is")
        self.assertTrue(plan.simple)
        brain = get_brain()
        observed = brain.observe("Explain what a mutex is")
        self.assertEqual(observed.get("agents"), 0)
        self.assertFalse(observed.get("model_called"))

    def test_all_product_domains_have_a_runtime_boundary(self) -> None:
        for domain in ("chat", "work", "coding", "trading", "media", "research", "plugins", "mcp"):
            self.assertIn(domain, MIGRATION_MATRIX)
            runtime = get_brain().domain(domain)
            caps = runtime.describe_capabilities()
            self.assertEqual(caps["domain"], domain)


if __name__ == "__main__":
    unittest.main()
