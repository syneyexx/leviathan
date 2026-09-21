"""Ownership map: one brain, not one monolith.

Existing modules keep their internals. This table is the canonical
intelligence substrate — wrappers exist only when they add semantics.
"""

from __future__ import annotations

from typing import Any

from capability_intel.taxonomy import NATIVE_PROVIDER_ID

SUBSTRATE: dict[str, dict[str, str]] = {
    "capability_registry": {
        "owner": "capability_intel.registry.CapabilityRegistry",
        "status": "already_canonical",
        "note": "Native, plugin and MCP records share CanonicalCapability.",
    },
    "skill_knowledge_retrieval": {
        "owner": "capability_intel.skills + reasoning.retrieval",
        "status": "already_canonical",
        "note": "Skills are bounded untrusted fragments. Embeddings stay in retrieval.",
    },
    "agent_registry": {
        "owner": "capability_intel.contracts.AgentContract + hades_brain.agent_protocol",
        "status": "canonical_with_domain_projection",
        "note": "Domain roles project into CanonicalAgent; they are not deleted.",
    },
    "mission_runtime": {
        "owner": "capability_intel.collaboration.MissionState",
        "status": "already_canonical",
        "note": "Domain metadata extends; lifecycle owner is singular.",
    },
    "collaboration_protocol": {
        "owner": "capability_intel.collaboration",
        "status": "already_canonical",
        "note": "Structured message types; compact handoffs.",
    },
    "context_compiler": {
        "owner": "reasoning.context + reasoning.chat_context",
        "status": "already_canonical",
        "note": "Domain collectors allowed; compiler budget semantics shared.",
    },
    "model_intelligence": {
        "owner": "reasoning.model_router",
        "status": "already_canonical",
        "note": "Domains specify requirements; they do not own routers.",
    },
    "tool_mcp_runtime": {
        "owner": "mcp_host + PluginManager",
        "status": "already_canonical",
        "note": "MCPMarket never executes tools.",
    },
    "memory_learning": {
        "owner": "database memories + platform_db knowledge + domain stores",
        "status": "shared_semantics_specialized_tables",
        "note": "Do not collapse tables. Expose claim/evidence/provenance.",
    },
    "policy_trust_approval": {
        "owner": "plugin_runtime_v2 + approvals + mcp_host.policy",
        "status": "already_canonical",
        "note": "Marketplace never grants trust.",
    },
    "evidence_verification": {
        "owner": "capability_intel.orchestration.verification_result + domain engines",
        "status": "shared_concepts_domain_truth",
        "note": "Tests/statistics/renders/citations remain domain proof.",
    },
    "budgets": {
        "owner": "capability_intel.taxonomy.DEFAULT_BUDGETS + reasoning.budgets",
        "status": "already_canonical",
    },
    "resource_node_intelligence": {
        "owner": "compute_fabric.LocalExecutor + host_capability",
        "status": "local_only",
        "note": "No speculative distributed fabric. Advertise local node metadata.",
    },
    "observability": {
        "owner": "reasoning.usage_telemetry + capability_intel.health + hades_brain.cost",
        "status": "extended",
        "note": "Exact tokens when provider reports them; otherwise unknown/estimated.",
    },
    "cognitive_runtime": {
        "owner": "cognitive.runtime.CognitiveRuntime",
        "status": "extended",
        "note": (
            "Ten cognitive pillars (self-model, perception, epistemic, ontology, immune, "
            "mental models, homeostasis, self-repair, scientific method, credit) — "
            "façade over existing evidence/budget/security owners; not a second Brain."
        ),
    },
    "mcpmarket": {
        "owner": "mcpmarket.connector.MCPMarketConnector",
        "status": "external_discovery_only",
        "note": "Untrusted catalog. Execution through MCP Host after operator approval.",
    },
}


def substrate_overview() -> dict[str, Any]:
    return {
        "native_provider": NATIVE_PROVIDER_ID,
        "monolith": False,
        "components": dict(SUBSTRATE),
    }
