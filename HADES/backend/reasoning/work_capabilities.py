"""Fine-grained work-step capabilities and executor ownership.

Planner assignment must be capability-based: a step that requires
``plugin.execute`` may only be assigned to an executor that owns that
capability. Vague semantic similarity is not enough.
"""

from __future__ import annotations

from typing import Any, Literal


WorkCapability = Literal[
    "plugin.resolve",
    "plugin.health",
    "plugin.execute",
    "plugin.create",
    "plugin.convert",
    "knowledge.normalize",
    "knowledge.transform",
    "knowledge.create",
    "knowledge.persist",
    "knowledge.verify_persistence",
    "evidence.verify",
    "provenance.audit",
    "code.build",
    "compile",
    "memory.search",
    "knowledge.search",
    "web.research",
    "web.fetch",
    "plan.coordinate",
    "chat.answer",
]

# Executor → owned capabilities (real specialist ids already in the repo).
EXECUTOR_CAPABILITIES: dict[str, frozenset[str]] = {
    "tool_orchestrator": frozenset(
        {
            "plugin.resolve",
            "plugin.health",
            "plugin.execute",
        }
    ),
    "knowledge_builder": frozenset(
        {
            "knowledge.normalize",
            "knowledge.transform",
            "knowledge.create",
            "knowledge.persist",
            "knowledge.verify_persistence",
        }
    ),
    "evidence_auditor": frozenset({"evidence.verify", "provenance.audit"}),
    "critic": frozenset({"evidence.verify"}),
    "build": frozenset({"code.build", "compile"}),
    "coding_investigator": frozenset({"code.build"}),
    "coding_planner": frozenset({"plan.coordinate", "code.build"}),
    "coding_editor": frozenset({"code.build"}),
    "coding_test_engineer": frozenset({"code.build"}),
    "coding_debugger": frozenset({"code.build"}),
    "coding_security_reviewer": frozenset({"evidence.verify"}),
    "coding_api_reviewer": frozenset({"evidence.verify"}),
    "coding_final_reviewer": frozenset({"evidence.verify"}),
    "retrieval": frozenset({"memory.search", "knowledge.search"}),
    "plugin_converter": frozenset({"plugin.create", "plugin.convert"}),
    "web_scout": frozenset({"web.research", "web.fetch"}),
    "research_worker": frozenset({"web.research", "knowledge.search"}),
    "executor": frozenset({"plan.coordinate", "chat.answer"}),
    "chat": frozenset({"chat.answer"}),
    "memory_curator": frozenset({"knowledge.persist", "memory.search"}),
    "document_intel": frozenset({"knowledge.normalize", "knowledge.transform"}),
}

# Capability → preferred executors (first enabled wins).
CAPABILITY_OWNERS: dict[str, tuple[str, ...]] = {
    "plugin.resolve": ("tool_orchestrator",),
    "plugin.health": ("tool_orchestrator",),
    "plugin.execute": ("tool_orchestrator",),
    "plugin.create": ("plugin_converter",),
    "plugin.convert": ("plugin_converter",),
    "knowledge.normalize": ("knowledge_builder", "document_intel"),
    "knowledge.transform": ("knowledge_builder", "document_intel"),
    "knowledge.create": ("knowledge_builder",),
    "knowledge.persist": ("knowledge_builder", "memory_curator"),
    "knowledge.verify_persistence": ("knowledge_builder",),
    "evidence.verify": ("evidence_auditor", "critic"),
    "provenance.audit": ("evidence_auditor",),
    "code.build": ("build",),
    "compile": ("build",),
    "memory.search": ("retrieval", "memory_curator"),
    "knowledge.search": ("retrieval", "research_worker"),
    "web.research": ("web_scout", "research_worker"),
    "web.fetch": ("web_scout",),
    "plan.coordinate": ("executor",),
    "chat.answer": ("chat", "executor"),
}

# Deterministic capabilities that must not consume LLM/model budget.
DETERMINISTIC_CAPABILITIES: frozenset[str] = frozenset(
    {
        "plugin.resolve",
        "plugin.health",
        "plugin.execute",
        "knowledge.persist",
        "knowledge.verify_persistence",
        "memory.search",
        "knowledge.search",
        "web.fetch",
        "evidence.verify",
        "provenance.audit",
    }
)

# Instruction/title markers → required capability (ordered; first match wins).
_CAPABILITY_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    (
        "plugin.resolve",
        (
            "resolve existing",
            "resolve installed",
            "zoek de bestaande",
            "locate installed",
            "plugin registry",
            "installed plugin",
            "bestaande geïnstalleerde",
            "bestaande geinstalleerde",
            "lookup plugin",
            "resolve plugin",
            "vind geinstalleerde",
            "vind geïnstalleerde",
        ),
    ),
    (
        "plugin.health",
        (
            "plugin health",
            "health/availability",
            "beschikbaar en uitvoerbaar",
            "check newsfeeder health",
            "controleer of de plugin beschikbaar",
            "availability check",
            "plugin availability",
            "health check",
        ),
    ),
    (
        "plugin.execute",
        (
            "execute existing plugin",
            "invoke/execute",
            "voer de bestaande",
            "daadwerkelijk uit",
            "run plugin",
            "execute plugin",
            "invoke plugin",
            "plugin uitvoeren",
            "call tool",
            "run tool",
        ),
    ),
    (
        "knowledge.verify_persistence",
        (
            "verify readback",
            "read back",
            "readback",
            "verify persistence",
            "controleer persistence",
            "verify inserted",
            "db readback",
        ),
    ),
    (
        "knowledge.persist",
        (
            "persist knowledge",
            "persist knowledgeitems",
            "opslaan in knowledge",
            "sla kennis",
            "knowledge repository",
            "sqlite commit",
            "db insert",
        ),
    ),
    (
        "knowledge.transform",
        (
            "normalize returned",
            "convert returned",
            "omzetten naar",
            "naar knowledgeitem",
            "naar knowledgeitems",
            "knowledgeitems",
            "knowledge items",
            "normaliseer",
            "transform content",
        ),
    ),
    (
        "knowledge.create",
        (
            "create knowledgeitem",
            "maak knowledgeitem",
            "bouw knowledge",
        ),
    ),
    (
        "provenance.audit",
        (
            "provenance",
            "bron-audit",
            "bron audit",
        ),
    ),
    (
        "evidence.verify",
        (
            "evidence audit",
            "claimdekking",
            "unsupported claim",
            "contradictie",
            "evidence verify",
        ),
    ),
    (
        "plugin.convert",
        (
            "converteer",
            "convert to plugin",
            "adapter",
            ".hadesplugin",
        ),
    ),
    (
        "plugin.create",
        (
            "bouw een plugin",
            "maak een plugin",
            "create plugin",
            "build plugin",
            "nieuwe plugin",
        ),
    ),
    (
        "code.build",
        (
            "compile",
            "code build",
            "build system",
            "pytest",
            "refactor codebase",
        ),
    ),
    (
        "memory.search",
        (
            "zoek in memory",
            "memory search",
            "search memories",
        ),
    ),
    (
        "knowledge.search",
        (
            "zoek in kennis",
            "knowledge search",
            "search knowledge",
        ),
    ),
    (
        "web.research",
        (
            "web research",
            "crawl ",
            "duckduckgo",
            "actuele bron",
        ),
    ),
]


def executor_capabilities(agent_id: str) -> frozenset[str]:
    return EXECUTOR_CAPABILITIES.get(str(agent_id or "").strip(), frozenset())


def executor_supports(agent_id: str, capability: str | None) -> bool:
    if not capability:
        return True
    return str(capability) in executor_capabilities(agent_id)


def owners_for_capability(capability: str) -> tuple[str, ...]:
    return CAPABILITY_OWNERS.get(str(capability), ())


def pick_executor_for_capability(
    capability: str,
    *,
    enabled_agents: set[str] | None = None,
    preferred: str | None = None,
) -> str | None:
    enabled = enabled_agents
    preferred_norm = (preferred or "").strip()
    if preferred_norm and executor_supports(preferred_norm, capability):
        if enabled is None or preferred_norm in enabled:
            return preferred_norm
    for owner in owners_for_capability(capability):
        if enabled is None or owner in enabled:
            return owner
    return None


def infer_required_capability(instruction: str, *, title: str = "", kind: str = "") -> str | None:
    """Infer the fine-grained capability a step needs from its text/kind."""
    text = f"{title}\n{instruction}\n{kind}".lower()
    if not text.strip():
        return None
    for capability, markers in _CAPABILITY_MARKERS:
        if any(marker in text for marker in markers):
            return capability
    # Kind-based fallbacks.
    kind_l = (kind or "").strip().lower()
    if kind_l in {"plugins", "plugin_use", "tool_use"}:
        if any(tok in text for tok in ("health", "beschikbaar", "availability")):
            return "plugin.health"
        if any(tok in text for tok in ("execute", "invoke", "voer", "run")):
            return "plugin.execute"
        return "plugin.resolve"
    if kind_l in {"knowledge"}:
        if any(tok in text for tok in ("verify", "readback", "read back")):
            return "knowledge.verify_persistence"
        if any(tok in text for tok in ("persist", "opslaan", "repository")):
            return "knowledge.persist"
        return "knowledge.transform"
    return None


def is_deterministic_capability(capability: str | None) -> bool:
    return bool(capability) and str(capability) in DETERMINISTIC_CAPABILITIES


def capability_mismatch(
    *,
    agent_id: str,
    required_capability: str | None,
) -> dict[str, Any] | None:
    if not required_capability:
        return None
    if executor_supports(agent_id, required_capability):
        return None
    return {
        "assigned_executor": agent_id,
        "required_capability": required_capability,
        "executor_supports_capability": False,
        "owners": list(owners_for_capability(required_capability)),
        "executor_capabilities": sorted(executor_capabilities(agent_id)),
    }


def validate_step_capability_assignment(
    *,
    step_id: str,
    agent_id: str,
    required_capability: str | None,
) -> dict[str, Any] | None:
    """Return a mismatch diagnostic dict when assignment is invalid."""
    mismatch = capability_mismatch(agent_id=agent_id, required_capability=required_capability)
    if not mismatch:
        return None
    return {
        "step_id": step_id,
        "blocking_reason": "executor_capability_mismatch",
        **mismatch,
    }


def registry_snapshot() -> dict[str, Any]:
    return {
        "executors": {key: sorted(values) for key, values in EXECUTOR_CAPABILITIES.items()},
        "owners": {key: list(values) for key, values in CAPABILITY_OWNERS.items()},
        "deterministic": sorted(DETERMINISTIC_CAPABILITIES),
    }
