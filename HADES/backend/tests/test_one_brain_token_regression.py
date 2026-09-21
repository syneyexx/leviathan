"""Mandatory token/model-call regression tests for One Brain."""

from __future__ import annotations

import unittest

from capability_intel.contracts import CanonicalCapability
from capability_intel.planner import plan_requirements
from capability_intel.policy import policy_allows
from capability_intel.ranking import rank_capabilities
from capability_intel.service import CapabilityIntelligence, reset_service
from capability_intel.skills import retrieve_skills
from hades_brain.cost import reset_ledger
from hades_brain.evidence import evaluate_verification, should_stop_reasoning
from hades_brain.mission import cross_domain_handoff
from hades_brain.service import get_brain, reset_brain
from hades_brain.tool_context import bound_tools_for_model, reset_schema_cache
from mcpmarket.connector import MCPMarketConnector, reset_connector
from plugin_runtime_v2 import evaluate_global_side_effect_policies


def _cap(**kwargs) -> CanonicalCapability:
    kwargs.setdefault("canonical_id", kwargs.get("name", "cap"))
    kwargs.setdefault("kind", "tool")
    kwargs.setdefault("name", kwargs["canonical_id"])
    kwargs.setdefault("health", "available")
    kwargs.setdefault("availability", True)
    kwargs.setdefault("provider_id", kwargs.get("plugin_id") or "p")
    return CanonicalCapability(**kwargs)


class OneBrainTokenRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_brain()
        reset_service()
        reset_ledger()
        reset_connector()
        reset_schema_cache()
        self.market_calls = 0

        def fetch(url: str) -> tuple[int, str]:
            self.market_calls += 1
            slug = url.rstrip("/").split("/")[-1]
            return 200, f"<html><h1>{slug}</h1><p>by vendor. A useful MCP server for {slug} integration tasks.</p></html>"

        self.connector = MCPMarketConnector(fetch=fetch)

    def tearDown(self) -> None:
        reset_brain()
        reset_service()
        reset_ledger()
        reset_connector()

    def test_explicit_provider_zero_routing_llm(self) -> None:
        plan = plan_requirements("Use Desktop Commander to list files")
        decision = rank_capabilities(
            "Use Desktop Commander to list files",
            [
                _cap(canonical_id="dc.list", name="Desktop Commander", plugin_id="desktop-commander", intents=["inspect_code"]),
                _cap(canonical_id="other.search", name="Other Search", plugin_id="other", intents=["inspect_code"]),
            ],
            plan=plan,
        )
        self.assertTrue(decision.explicit_honored)
        self.assertFalse(decision.model_called)
        self.assertFalse(plan.model_adjudication)

    def test_blocked_policy_zero_downstream_model_calls(self) -> None:
        record = _cap(canonical_id="net.tool", name="Web crawl", plugin_id="crawler", effects=["network"], side_effect_class="network")
        plugin = {
            "id": "crawler",
            "enabled": True,
            "status": "ready",
            "trust": "verified",
            "permissions": ["network"],
            "manifest": {"autonomous": True},
        }
        tool = {"name": "Web crawl", "metadata": {"autonomous": True, "permissions": ["network"]}}
        allowed, _reason = policy_allows(
            record,
            plugin=plugin,
            tool=tool,
            settings={"network_policy": "block"},
            invocation_type="autonomous",
        )
        self.assertFalse(allowed)
        verdict = evaluate_global_side_effect_policies(
            contract={"effects": ["network"]},
            settings={"network_policy": "block"},
            invocation_type="autonomous",
            approved_by_user=True,
        )
        self.assertFalse(verdict["allowed"])
        # No marketplace, no routing LLM, no verifier after a policy deny.
        self.assertEqual(self.market_calls, 0)

    def test_simple_capability_lookup_is_deterministic(self) -> None:
        plan = plan_requirements("search repository files with Desktop Commander")
        decision = rank_capabilities(
            "search repository files with Desktop Commander",
            [_cap(canonical_id="dc.search", name="Desktop Commander", plugin_id="desktop-commander", intents=["inspect_code", "code.search"])],
            plan=plan,
        )
        self.assertFalse(decision.model_called)
        self.assertGreater(decision.selected[0].score, 0)

    def test_static_skill_retrieval_does_not_load_unrelated_skills(self) -> None:
        skills = [
            _cap(canonical_id="python.debug", kind="skill", name="Python debugging", description="pdb and race conditions", plugin_id="a", domains=["debugging"]),
            _cap(canonical_id="excel.pivot", kind="skill", name="Excel pivots", description="spreadsheet formulas", plugin_id="b", domains=["office"]),
            _cap(canonical_id="unrelated.cook", kind="skill", name="Cooking", description="recipes", plugin_id="c"),
        ]
        got = retrieve_skills("python deadlock race condition", skills, max_items=2)
        names = {item["name"] for item in got}
        self.assertIn("Python debugging", names)
        self.assertNotIn("Cooking", names)
        self.assertLessEqual(len(got), 2)

    def test_simple_chat_is_not_a_multi_agent_team(self) -> None:
        observed = get_brain().observe("Explain how a hash map works")
        self.assertEqual(observed.get("agents"), 0)
        self.assertFalse(observed.get("composed", False) or observed.get("plan", {}).get("simple") is False)
        self.assertFalse(observed.get("model_called"))

    def test_one_agent_task_does_not_spawn_a_second_without_reason(self) -> None:
        intel = CapabilityIntelligence()
        composed = intel.compose("Find the race condition, fix it and prove the fix.")
        agents = int((composed.get("mission") or {}).get("usage", {}).get("agents") or 0)
        self.assertLessEqual(agents, 3)
        self.assertFalse(composed.get("model_called"))

    def test_deterministic_verification_skips_verifier_llm(self) -> None:
        outcome = evaluate_verification(
            domain="coding",
            execution_success=True,
            evidence={"tests_passed": True, "build_ok": True},
            agent_claims=["I verified it"],
        )
        self.assertTrue(should_stop_reasoning(outcome))
        self.assertFalse(outcome.verifier_model_called)

    def test_mcp_server_with_200_tools_is_shortlisted(self) -> None:
        tools = [
            {"plugin_id": "mcp:big", "name": f"tool_{i}", "description": "generic utility", "input_schema": {"type": "object", "properties": {f"field_{j}": {"type": "string"} for j in range(12)}}}
            for i in range(200)
        ]
        tools[7]["name"] = "text_to_speech"
        tools[7]["description"] = "Convert text to speech audio"
        bound = bound_tools_for_model(tools, query="text to speech audio")
        self.assertLessEqual(bound["shortlist_count"], 8)
        self.assertEqual(bound["considered"], 200)
        self.assertGreaterEqual(bound["omitted"], 192)
        self.assertFalse(bound["model_called"])
        names = [item["name"] for item in bound["tools"]]
        self.assertIn("text_to_speech", names)
        self.assertEqual(bound["shortlist_count"], 8)
        for item in bound["tools"]:
            self.assertTrue(item.get("full_schema"))

    def test_marketplace_search_is_cached_inside_a_mission(self) -> None:
        first = self.connector.search("context7", mission_id="mission-a")
        second = self.connector.search("context7", mission_id="mission-a")
        self.assertEqual(self.market_calls, 1)
        self.assertTrue(second.get("duplicate_query_prevented"))
        self.assertFalse(first.get("model_called"))
        self.assertFalse(second.get("model_called"))

    def test_cross_domain_handoff_is_refs_not_transcript(self) -> None:
        payload = cross_domain_handoff(
            from_domain="research",
            to_domain="media",
            goal="Turn the report into a video",
            artifact_refs=["artifact:report"],
            evidence_refs=["evidence:cite"],
            extra={"transcript": "secret full history", "messages": ["a", "b"]},
        )
        blob = str(payload)
        self.assertNotIn("secret full history", blob)
        self.assertFalse(payload["full_transcript"])
        self.assertEqual(payload["artifact_refs"], ["artifact:report"])


if __name__ == "__main__":
    unittest.main()
