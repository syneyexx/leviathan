from __future__ import annotations

import unittest

from capability_intel.contracts import CanonicalCapability
from capability_intel.planner import plan_requirements
from capability_intel.policy import filter_candidates, policy_allows
from capability_intel.ranking import rank_capabilities, score_capability
from capability_intel.service import reset_service
from plugin_runtime_v2 import evaluate_global_side_effect_policies


def _cap(**kwargs) -> CanonicalCapability:
    kwargs.setdefault("canonical_id", kwargs.get("name", "cap"))
    kwargs.setdefault("kind", "tool")
    kwargs.setdefault("name", kwargs["canonical_id"])
    kwargs.setdefault("health", "available")
    kwargs.setdefault("availability", True)
    kwargs.setdefault("provider_id", kwargs.get("plugin_id") or "p")
    return CanonicalCapability(**kwargs)


class CapabilityRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_service()

    def tearDown(self) -> None:
        reset_service()

    def test_simple_explain_is_a_cost_fast_path(self) -> None:
        plan = plan_requirements("Explain what this lock does")
        self.assertTrue(plan.simple)
        self.assertFalse(plan.model_adjudication)
        self.assertEqual(plan.planner, "deterministic")
        self.assertFalse(any(item.capability == "code.modify" for item in plan.requirements))

    def test_repair_and_prove_requires_verify(self) -> None:
        plan = plan_requirements("Find the race condition, fix it and prove the fix.")
        caps = {item.capability for item in plan.requirements}
        self.assertIn("code.search", caps)
        self.assertIn("code.modify", caps)
        self.assertIn("tests.execute", caps)
        self.assertIn("software.reason", caps)
        self.assertTrue(plan.verification_required)
        self.assertIn("modifies_workspace", plan.risk)
        self.assertIn("software.concurrency", plan.domains)

    def test_explicit_provider_honored_without_model(self) -> None:
        plan = plan_requirements("Use Desktop Commander to list files")
        self.assertIn("Desktop Commander", plan.explicit_providers)
        decision = rank_capabilities(
            "Use Desktop Commander to list files",
            [
                _cap(canonical_id="dc.list", name="Desktop Commander", plugin_id="desktop-commander", intents=["inspect_code"], kind="tool"),
                _cap(canonical_id="other.search", name="Other Search", plugin_id="other", intents=["inspect_code"], kind="tool"),
            ],
            plan=plan,
        )
        self.assertTrue(decision.explicit_honored)
        self.assertFalse(decision.model_called)
        self.assertEqual(decision.selected[0].capability.name, "Desktop Commander")
        self.assertIn("exact_reference", decision.selected[0].reasons)

    def test_hybrid_rank_uses_intent_domain_and_cost_not_only_lexical(self) -> None:
        plan = plan_requirements("Find the race condition, fix it and prove the fix.")
        cheap = _cap(
            canonical_id="native.inspect",
            name="Repository inspection",
            kind="tool",
            domains=["software.repository"],
            intents=["inspect_code", "code.search"],
            cost_class="cheap",
            side_effect_class="read",
            source="native",
            provider_id="hades.native",
        )
        expensive = _cap(
            canonical_id="remote.agent",
            name="Remote agent",
            kind="agent",
            domains=["generic"],
            intents=["chat"],
            cost_class="expensive",
            side_effect_class="network",
            latency_class="slow",
        )
        ranked = score_capability("search repository race condition", cheap, plan=plan)
        other = score_capability("search repository race condition", expensive, plan=plan)
        self.assertGreater(ranked.score, other.score)
        self.assertTrue(any(key in ranked.reasons for key in ("intent_match", "domain_match", "lexical_relevance", "semantic_relevance")))

    def test_policy_blocks_relevant_but_disallowed_provider(self) -> None:
        record = _cap(
            canonical_id="net.tool",
            name="Web crawl",
            plugin_id="crawler",
            kind="tool",
            effects=["network"],
            side_effect_class="network",
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
        )
        self.assertFalse(allowed)
        self.assertIn("block", reason)

    def test_health_and_known_dead_routes_are_rejected(self) -> None:
        live = _cap(canonical_id="a.tool", name="search", plugin_id="a")
        dead = _cap(canonical_id="b.tool", name="search", plugin_id="b", provider_id="b")
        from capability_intel.contracts import RankedCandidate

        selected, rejected = filter_candidates(
            [
                RankedCandidate(capability=live, score=10, eligible=True),
                RankedCandidate(capability=dead, score=12, eligible=True),
            ],
            plugins_by_id={
                "a": {"id": "a", "enabled": True, "status": "ready", "trust": "verified", "manifest": {"autonomous": True}},
            },
            known_dead={"b"},
        )
        self.assertTrue(any(item.rejected_reason == "known_dead_route" for item in rejected))

    def test_evaluate_global_policy_still_authoritative(self) -> None:
        verdict = evaluate_global_side_effect_policies(
            contract={"effects": ["network"]},
            settings={"network_policy": "block"},
            invocation_type="autonomous",
            approved_by_user=True,
        )
        self.assertFalse(verdict["allowed"])
