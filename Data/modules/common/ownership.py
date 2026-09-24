"""Canonical ownership matrix — encoded for architecture conformance tests.

One owner per canonical responsibility. Prefer EXTEND over NEW.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OwnershipRule:
    concern: str
    owner_module: str
    rule: str
    forbidden_duplicates: tuple[str, ...] = ()


# Wave 0 freeze of the unified ownership matrix (U001–U020 / section 6).
CANONICAL_OWNERSHIP: tuple[OwnershipRule, ...] = (
    OwnershipRule(
        concern="overall_task_lifecycle",
        owner_module="run",
        rule="Domain records may keep domain state; overall run truth resolves through one run_id",
        forbidden_duplicates=("lifecycle_engine", "task_runtime"),
    ),
    OwnershipRule(
        concern="schedulable_work",
        owner_module="jobs",
        rule="All background/worker execution uses JobRuntime substrate",
        forbidden_duplicates=("private_queue", "fleet_manager_per_domain"),
    ),
    OwnershipRule(
        concern="cognitive_orchestration",
        owner_module="cognition",
        rule="Plans/meta-control; no private execution backdoor",
        forbidden_duplicates=("extended_thinking_runtime",),
    ),
    OwnershipRule(
        concern="specialist_agents",
        owner_module="agents",
        rule="Strategy/DAG nodes over Cognition/Jobs/Gateway",
        forbidden_duplicates=("agent_job_system", "agent_database"),
    ),
    OwnershipRule(
        concern="capability_registry",
        owner_module="execution",
        rule="CapabilityCatalog is the single executable capability registry",
        forbidden_duplicates=("CapabilityCatalog", "ToolRegistry", "UniversalToolRegistry"),
    ),
    OwnershipRule(
        concern="capability_effects",
        owner_module="execution",
        rule="ExecutionGateway is the single dispatch/effect boundary",
        forbidden_duplicates=("ExecutionGateway", "EffectGateway"),
    ),
    OwnershipRule(
        concern="technical_approvals",
        owner_module="approvals",
        rule="Neutral AuthorityProfile configuration; no content ideology",
        forbidden_duplicates=("content_moderation_engine",),
    ),
    OwnershipRule(
        concern="behavior_profile",
        owner_module="settings",
        rule="BehaviorProfile (SYSTEM_PROMPT) is separate from AuthorityProfile",
        forbidden_duplicates=("hardcoded_moral_filter",),
    ),
    OwnershipRule(
        concern="model_control_plane",
        owner_module="models",
        rule="One Model Control Plane; native/ is not a second model platform",
        forbidden_duplicates=("ModelControlPlane", "ModelRegistry"),
    ),
    OwnershipRule(
        concern="model_runtime_adapters",
        owner_module="model_runtime",
        rule="Provider/runtime adapters only",
    ),
    OwnershipRule(
        concern="context_compiler",
        owner_module="context",
        rule="All model calls consume a ContextPack from one compiler",
        forbidden_duplicates=("private_prompt_assembler",),
    ),
    OwnershipRule(
        concern="persistent_memory",
        owner_module="memory",
        rule="Exact scoped memory only",
    ),
    OwnershipRule(
        concern="documents_corpora_rag",
        owner_module="knowledge",
        rule="Vector store remains an index, not canonical truth",
    ),
    OwnershipRule(
        concern="evidence",
        owner_module="evidence",
        rule="One evidence representation",
    ),
    OwnershipRule(
        concern="completion_verification",
        owner_module="verification",
        rule="Evidence-/outcome-based completion",
    ),
    OwnershipRule(
        concern="artifacts",
        owner_module="artifacts",
        rule="Versioned/content-addressed lineage",
    ),
    OwnershipRule(
        concern="datasets",
        owner_module="datasets",
        rule="Raw→transform→split→export lineage",
    ),
    OwnershipRule(
        concern="training",
        owner_module="training",
        rule="One training control plane",
    ),
    OwnershipRule(
        concern="research",
        owner_module="research",
        rule="Domain semantics; shares infrastructure",
    ),
    OwnershipRule(
        concern="coding",
        owner_module="coding",
        rule="Domain semantics / CodingCognitiveStrategy; shares One Brain infrastructure",
        forbidden_duplicates=("coding_memory.db", "private_coding_rag", "private_coding_gateway"),
    ),
    OwnershipRule(
        concern="one_brain_access_fabric",
        owner_module="brain",
        rule="Brain is shared access/contracts/projection facade — not canonical storage or a second CognitiveRuntime",
        forbidden_duplicates=("BrainV2", "second_knowledge_store", "second_memory_store"),
    ),
    OwnershipRule(
        concern="domain_cognitive_strategy",
        owner_module="cognition",
        rule="DomainCognitiveStrategy specializes reasoning under one CognitiveRuntime",
        forbidden_duplicates=("CognitionV2", "CodingAgentV2", "second_cognitive_runtime"),
    ),
    OwnershipRule(
        concern="browser",
        owner_module="browser",
        rule="Domain worker/provider; no private gateway",
    ),
    OwnershipRule(
        concern="mcp",
        owner_module="mcp",
        rule="One bridge / many servers",
    ),
    OwnershipRule(
        concern="plugins",
        owner_module="plugins",
        rule="Declarative over ModuleManager; no second loader",
    ),
    OwnershipRule(
        concern="module_loader",
        owner_module="module_manager",
        rule="One module loader",
    ),
    OwnershipRule(
        concern="automation",
        owner_module="workflows",
        rule="Triggers canonical Runs/Jobs (schedules companion)",
    ),
    OwnershipRule(
        concern="evaluation",
        owner_module="evaluation",
        rule="One empirical platform",
    ),
    OwnershipRule(
        concern="telemetry",
        owner_module="observability",
        rule="Metrics is helper/exporter, not competing truth",
    ),
    OwnershipRule(
        concern="canonical_metadata_database",
        owner_module="backend",
        rule="One canonical metadata database per local deployment; no competing truth DB",
        forbidden_duplicates=("research.db", "memory.db", "training.db", "agent.db"),
    ),
)

# Modules that may define these class names (relative to Data/modules/).
SINGLETON_CLASS_OWNERS: dict[str, str] = {
    "CapabilityCatalog": "execution",
    "ExecutionGateway": "execution",
    "JobRuntime": "jobs",
    "RunStore": "run",
    "ModelControlPlane": "models",
    "EvidenceService": "evidence",
    "VerificationEngine": "verification",
    "McpBridge": "mcp",
    "BrainAccessFacade": "brain",
    "StrategyRegistry": "cognition",
}

# Private worker/agent DBs are forbidden as permanent paths.
FORBIDDEN_PRIVATE_DB_FILENAMES: frozenset[str] = frozenset(
    {
        "research.db",
        "memory.db",
        "training.db",
        "agent.db",
        "agents.db",
        "browser.db",
        "coding.db",
        "coding_memory.db",
        "media.db",
        "voice.db",
    }
)


def ownership_public_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "rules": [
            {
                "concern": rule.concern,
                "owner_module": rule.owner_module,
                "rule": rule.rule,
                "forbidden_duplicates": list(rule.forbidden_duplicates),
            }
            for rule in CANONICAL_OWNERSHIP
        ],
        "singleton_class_owners": dict(SINGLETON_CLASS_OWNERS),
        "truth": {
            "one_owner_per_concern": True,
            "extend_over_new": True,
            "external_first_is_not_second_architecture": True,
        },
    }
