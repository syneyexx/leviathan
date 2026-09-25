"""General Intelligence Orchestra — AgentFleet specialist definitions (not a second runtime).

CognitiveRuntime remains top-level orchestration authority. These seeds register
bounded specialists under the existing AgentFleet ORCHESTRATOR representation.
"""

from __future__ import annotations

from typing import Any


GENERAL_INTELLIGENCE_ORCHESTRA_KEY = "general_intelligence_orchestra"

# Specialist systemKeys used by CognitiveRuntime dynamic delegation.
GI_SPECIALIST_KEYS = (
    "gi_knowledge",
    "gi_web_research",
    "gi_tool",
    "gi_fact_verifier",
    "gi_critic",
    "gi_system_inspector",
    "gi_synthesis",
)


def general_intelligence_orchestra_seed() -> list[dict[str, Any]]:
    """Idempotent AgentFleet seed specs for the general assistant orchestra."""
    specialists = [
        {
            "name": "Knowledge Specialist",
            "kind": "specialist",
            "role": "Brain / Knowledge / Memory / Evidence",
            "description": "Retrieves from Brain, Knowledge, Memory, and Evidence — never invents hits.",
            "capabilities": ["knowledge.search", "system.inspect"],
            "tags": ["knowledge", "brain", "memory", "evidence", "gi"],
            "model_ref": None,
            "metadata": {"systemKey": "gi_knowledge", "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY},
        },
        {
            "name": "Web Research Specialist",
            "kind": "research",
            "role": "Current / External Information",
            "description": "Uses Research + web.search/web.fetch via shared workers — never fabricates results.",
            "capabilities": ["web.search", "web.fetch", "research.retrieve", "research.verify"],
            "tags": ["web", "research", "current", "gi"],
            "model_ref": None,
            "metadata": {"systemKey": "gi_web_research", "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY},
        },
        {
            "name": "Tool Specialist",
            "kind": "specialist",
            "role": "Capability Mapping",
            "description": "Maps plan needs to CapabilityCatalog tools; executes only via ExecutionGateway.",
            "capabilities": ["compute.numeric", "math.calculate", "file.read", "workspace.list"],
            "tags": ["tools", "capabilities", "gi"],
            "model_ref": None,
            "metadata": {"systemKey": "gi_tool", "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY},
        },
        {
            "name": "Fact Verifier",
            "kind": "specialist",
            "role": "Claim / Evidence Matching",
            "description": "Checks claims against real Evidence — critic passed=true is not proof.",
            "capabilities": ["research.verify", "system.inspect"],
            "tags": ["verification", "claims", "gi"],
            "model_ref": None,
            "metadata": {"systemKey": "gi_fact_verifier", "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY},
        },
        {
            "name": "GI Critic",
            "kind": "specialist",
            "role": "Contradiction / Gap Analysis",
            "description": "Looks for contradictions, unsupported leaps, missing evidence — analysis not proof.",
            "capabilities": ["knowledge.search"],
            "tags": ["critic", "review", "gi"],
            "model_ref": None,
            "metadata": {
                "systemKey": "gi_critic",
                "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY,
                "model_role_hint": "critic",
            },
        },
        {
            "name": "System Inspector",
            "kind": "specialist",
            "role": "Runtime Telemetry",
            "description": "Answers factual questions about LEVIATHAN using system.inspect telemetry only.",
            "capabilities": ["system.inspect"],
            "tags": ["system", "inspect", "telemetry", "gi"],
            "model_ref": None,
            "metadata": {"systemKey": "gi_system_inspector", "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY},
        },
        {
            "name": "Synthesis Specialist",
            "kind": "specialist",
            "role": "Multi-source Synthesis Assist",
            "description": "Assists large multi-source synthesis; parent CognitiveRuntime owns final voice.",
            "capabilities": ["knowledge.search", "research.synthesize"],
            "tags": ["synthesis", "gi"],
            "model_ref": None,
            "metadata": {"systemKey": "gi_synthesis", "orchestra": GENERAL_INTELLIGENCE_ORCHESTRA_KEY},
        },
    ]
    orchestra = {
        "name": "LEVIATHAN General Intelligence Orchestra",
        "kind": "orchestrator",
        "role": "General Assistant Orchestra",
        "description": (
            "Bounded specialist orchestra under CognitiveRuntime. "
            "Dynamic selection — not every role on every request."
        ),
        "capabilities": [],
        "tags": ["orchestra", "gi", "assistant"],
        "model_ref": None,
        "metadata": {
            "systemKey": GENERAL_INTELLIGENCE_ORCHESTRA_KEY,
            "truth": {
                "not_a_second_cognitive_runtime": True,
                "parent_cognition_owns_final_response": True,
            },
        },
        "orchestrator": {
            "memberAgentIds": [],  # filled after specialist create by ensure_* 
            "strategy": "parallel_bounded",
            "maxDelegationDepth": 2,
            "parallelismLimit": 3,
            "failureStrategy": "continue",
            "budgets": {
                "max_specialists": 4,
                "max_parallel_specialists": 3,
                "max_model_calls": 12,
                "max_tool_calls": 20,
                "max_replans": 2,
                "max_research_jobs": 2,
                "max_wall_time_seconds": 180,
            },
        },
    }
    return [*specialists, orchestra]


def select_gi_specialists(task_public: dict[str, Any], *, max_specialists: int = 4) -> list[str]:
    """Pick specialist systemKeys from a TaskModel.public_dict() — bounded."""
    selected: list[str] = []
    execution_class = str(task_public.get("execution_class") or "DIRECT")
    if execution_class == "DIRECT":
        return []
    if task_public.get("needs_brain_retrieval") or task_public.get("needs_memory"):
        selected.append("gi_knowledge")
    if task_public.get("requires_current_information") or task_public.get("requires_research"):
        selected.append("gi_web_research")
    if (
        task_public.get("requires_tools")
        or task_public.get("needs_calculation")
        or task_public.get("needs_code_execution")
        or task_public.get("needs_browser")
    ):
        selected.append("gi_tool")
    if any(
        t in str(task_public.get("raw_request") or "").lower()
        for t in ("welk model", "which model", "hoeveel %", "brain", "system inspect", "active agents")
    ):
        selected.append("gi_system_inspector")
    if task_public.get("needs_verification") or str(task_public.get("verification_mode") or "") in {
        "REQUIRED",
        "CORROBORATED",
    }:
        selected.append("gi_fact_verifier")
        selected.append("gi_critic")
    if execution_class in {"MULTI_DOMAIN", "COMPLEX_REASONING", "WORK"} or task_public.get(
        "research_mode"
    ) == "deep":
        selected.append("gi_synthesis")
    # Dedupe preserve order, enforce budget.
    out: list[str] = []
    for key in selected:
        if key not in out:
            out.append(key)
        if len(out) >= max(0, int(max_specialists)):
            break
    return out
