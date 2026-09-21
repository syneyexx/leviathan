"""Deterministic work-intent classification and plan templates.

Plugin USE vs CREATE must not rely on LLM guesswork. Existing-plugin
execution plans are built here so Work Runtime stays executable without
mis-routing to plugin_converter, evidence_auditor or knowledge_builder
for registry/lookup/execute steps.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from .work_capabilities import (
    infer_required_capability,
    pick_executor_for_capability,
)


WorkIntent = Literal[
    "USE_EXISTING_PLUGIN",
    "CREATE_PLUGIN",
    "CONVERT_PLUGIN",
    "WEB_RESEARCH",
    "BUILD_CODE",
    "KNOWLEDGE_INGESTION",
    "EVIDENCE_AUDIT",
    "NONE",
]

# Backward-compatible plugin-only intent.
PluginIntent = Literal["USE_EXISTING_PLUGIN", "CREATE_OR_CONVERT_PLUGIN", "NONE"]

# Creation signals (Dutch + English).
_CREATE_PATTERNS = (
    r"\bbouw\b.+\bplugin\b",
    r"\bmaak\b.+\bplugin\b",
    r"\bcreate\b.+\bplugin\b",
    r"\bbuild\b.+\bplugin\b",
    r"\bplugin\s+maken\b",
    r"\bnieuwe?\s+plugin\b",
    r"\bfrom\s+github\b.+\bplugin\b",
)

_CONVERT_PATTERNS = (
    r"\bconverteer\b",
    r"\bconvert\b.+\bplugin\b",
    r"\badapter\b.+\bplugin\b",
    r"\.hadesplugin\b",
    r"\btool\b.+\bnaar\b.+\bplugin\b",
    r"\bnaar\b.+\bplugin\b",
)

# Explicit use / execute / harvest signals.
_USE_PATTERNS = (
    r"\bgebruik\b",
    r"\bgebruik\s+bestaande\b",
    r"\bbestaande\b.+\bplugin\b",
    r"\bge[iï]nstalleerde\b.+\bplugin\b",
    r"\binstalled\b.+\bplugin\b",
    r"\bexisting\b.+\bplugin\b",
    r"\bvoer\b.+\buit\b",
    r"\brun\b.+\bplugin\b",
    r"\binvoke\b",
    r"\bhaal\b.+\buit\b",
    r"\bverwerk\b.+\boutput\b",
    r"\bprocess\b.+\boutput\b",
    r"\bexecute\b.+\bplugin\b",
    r"\bplugin\b.+\buitvoeren\b",
    r"\bnewsfeeder\b",
)

_NAMED_PLUGIN_HINTS = (
    "newsfeeder",
    "news_feeder",
    "humanizer",
    "puppeteer",
)


def classify_work_intent(prompt: str) -> WorkIntent:
    """Capability-aware intent classification (not simple single-keyword routing)."""
    text = (prompt or "").strip().lower()
    if not text:
        return "NONE"

    create_hit = any(re.search(pat, text) for pat in _CREATE_PATTERNS)
    convert_hit = any(re.search(pat, text) for pat in _CONVERT_PATTERNS)
    use_hit = any(re.search(pat, text) for pat in _USE_PATTERNS)
    has_plugin_token = "plugin" in text or any(name in text for name in _NAMED_PLUGIN_HINTS)

    # Evidence audit is explicit and primary only when asked for.
    if is_evidence_primary_task(prompt) and not (use_hit and has_plugin_token):
        return "EVIDENCE_AUDIT"

    # CREATE / CONVERT win over weak use tokens when build verbs dominate.
    if convert_hit and not (use_hit and any(tok in text for tok in ("bestaande", "existing", "installed", "geinstalleerde", "geïnstalleerde"))):
        return "CONVERT_PLUGIN"
    if create_hit and not use_hit:
        return "CREATE_PLUGIN"
    if create_hit and use_hit:
        if any(tok in text for tok in ("bouw", "maak", "create", "build", "nieuwe plugin", "nieuwe")):
            return "CREATE_PLUGIN"
        return "USE_EXISTING_PLUGIN"

    if use_hit and has_plugin_token:
        return "USE_EXISTING_PLUGIN"
    if has_plugin_token and any(
        tok in text
        for tok in (
            "uitvoeren",
            "execute",
            "invoke",
            "run",
            "installeerd",
            "installed",
            "bestaand",
            "existing",
            "output",
            "artikelen",
            "articles",
            "kennis",
            "knowledge",
        )
    ):
        return "USE_EXISTING_PLUGIN"

    if any(tok in text for tok in ("http://", "https://", "web research", "crawl ", "duckduckgo", "actuele bron", "freshness")):
        return "WEB_RESEARCH"
    if any(tok in text for tok in ("codebase", "refactor", "unit test", "pytest", "compiler", "typescript", "compile")):
        return "BUILD_CODE"
    if wants_knowledge_persist(prompt) and "plugin" not in text:
        return "KNOWLEDGE_INGESTION"
    if is_evidence_primary_task(prompt):
        return "EVIDENCE_AUDIT"
    return "NONE"


def classify_plugin_intent(prompt: str) -> PluginIntent:
    """Distinguish USE_EXISTING_PLUGIN from CREATE_OR_CONVERT_PLUGIN."""
    intent = classify_work_intent(prompt)
    if intent == "USE_EXISTING_PLUGIN":
        return "USE_EXISTING_PLUGIN"
    if intent in {"CREATE_PLUGIN", "CONVERT_PLUGIN"}:
        return "CREATE_OR_CONVERT_PLUGIN"
    return "NONE"


def extract_plugin_name_hint(prompt: str) -> str | None:
    """Best-effort plugin name from a natural-language instruction."""
    text = (prompt or "").strip()
    if not text:
        return None
    lower = text.lower()
    for hint in _NAMED_PLUGIN_HINTS:
        if hint in lower:
            if hint == "newsfeeder":
                return "NewsFeeder"
            return hint
    stopwords = {
        "bestaande",
        "existing",
        "installed",
        "geinstalleerde",
        "geïnstalleerde",
        "de",
        "een",
        "the",
        "a",
        "an",
        "nieuwe",
        "new",
        "registry",
        "workflow",
        "manager",
        "runtime",
        "local",
        "from",
        "with",
        "via",
        "voor",
        "naar",
        "and",
        "or",
        "tool",
        "tools",
        "plugin",
        "plugins",
        "step",
        "health",
        "resolve",
        "execute",
        "invoke",
        "target",
        "multi",
        "orchestr",
    }
    # Prefer explicitly quoted names from plan templates: plugin 'NewsFeeder'
    quoted = re.search(
        r"plugin\s+['\"]([A-Za-z][A-Za-z0-9_.-]{1,64})['\"]",
        text,
        flags=re.I,
    )
    if quoted:
        name = quoted.group(1).rstrip(".")
        if name.lower() not in stopwords:
            return name
    patterns = (
        r"resolve\s+installed\s+([A-Za-z][A-Za-z0-9_.-]{1,64})",
        r"(?:gebruik|voer|run|invoke|execute)\s+(?:de\s+)?([A-Za-z][A-Za-z0-9_.-]{1,64})\s*(?:plugin)?",
        r"plugin\s+([A-Za-z][A-Za-z0-9_.-]{1,64})",
        r"([A-Za-z][A-Za-z0-9_.-]{1,64})\s+plugin",
    )
    for pat in patterns:
        match = re.search(pat, text, flags=re.I)
        if match:
            name = match.group(1).rstrip(".")
            if name.lower() in stopwords:
                continue
            return name
    return None


def wants_knowledge_persist(prompt: str) -> bool:
    lower = (prompt or "").lower()
    return any(
        tok in lower
        for tok in (
            "kennis",
            "knowledge",
            "memory",
            "sla op",
            "opslaan",
            "persist",
            "bewaar",
            "ingest",
            "knowledgeitems",
            "knowledge items",
        )
    )


def is_evidence_primary_task(prompt: str) -> bool:
    """True only when the user actually asks for evidence/provenance audit."""
    lower = (prompt or "").lower()
    return any(
        tok in lower
        for tok in (
            "evidence audit",
            "provenance",
            "claimdekking",
            "unsupported claim",
            "contradictie",
            "contradiction",
            "bron-audit",
            "bron audit",
            "evidence auditor",
        )
    )


def build_existing_plugin_to_knowledge_plan(
    prompt: str,
    *,
    plugin_hint: str | None = None,
    default_agent: str = "tool_orchestrator",
) -> dict[str, Any]:
    """Deterministic executable plan for use-existing-plugin → knowledge.

    Capability-owned step agents:
    - tool_orchestrator: plugin.resolve / plugin.health / plugin.execute
    - knowledge_builder: knowledge.transform / knowledge.persist / knowledge.verify_persistence
    """
    hint = plugin_hint or extract_plugin_name_hint(prompt) or "target"
    persist = wants_knowledge_persist(prompt)
    steps: list[dict[str, Any]] = [
        {
            "step_id": "step-1",
            "title": f"Resolve installed {hint}",
            "instruction": (
                f"Resolve installed plugin '{hint}' from the local plugin registry. "
                "Do not create or convert a new plugin. Return plugin_id, status, tools."
            ),
            "agent_id": "tool_orchestrator",
            "kind": "plugins",
            "required_capability": "plugin.resolve",
            "depends_on": [],
            "expected_evidence": ["plugin_id", "tools"],
        },
        {
            "step_id": "step-2",
            "title": f"Check {hint} health/availability",
            "instruction": (
                f"Check {hint} health/availability via plugin runtime. "
                "Confirm the plugin is enabled, Ready and executable. Do not invent health."
            ),
            "agent_id": "tool_orchestrator",
            "kind": "plugins",
            "required_capability": "plugin.health",
            "depends_on": ["step-1"],
            "expected_evidence": ["health", "status"],
            "input_refs": ["step-1"],
        },
        {
            "step_id": "step-3",
            "title": f"Execute {hint}",
            "instruction": (
                f"Invoke/execute the resolved '{hint}' plugin via PluginManager. "
                "Return structured tool output. Do not invent results."
            ),
            "agent_id": "tool_orchestrator",
            "kind": "plugins",
            "required_capability": "plugin.execute",
            "depends_on": ["step-2"],
            "expected_evidence": ["tool_output"],
            "input_refs": ["step-2"],
        },
    ]
    if persist:
        steps.extend(
            [
                {
                    "step_id": "step-4",
                    "title": "Normalize returned articles into KnowledgeItems",
                    "instruction": (
                        "Convert/normalize the prior plugin tool output into KnowledgeItems "
                        "(title/content/provenance). Summarize/normalize only; do not look up or run plugins."
                    ),
                    "agent_id": "knowledge_builder",
                    "kind": "knowledge",
                    "required_capability": "knowledge.transform",
                    "depends_on": ["step-3"],
                    "expected_evidence": ["knowledge_items"],
                    "input_refs": ["step-3"],
                },
                {
                    "step_id": "step-5",
                    "title": "Persist KnowledgeItems",
                    "instruction": (
                        "Persist KnowledgeItems via the knowledge repository (DB insert + SQLite commit). "
                        "Deterministic persistence only; no LLM."
                    ),
                    "agent_id": "knowledge_builder",
                    "kind": "knowledge",
                    "required_capability": "knowledge.persist",
                    "depends_on": ["step-4"],
                    "expected_evidence": ["source_id"],
                    "input_refs": ["step-4"],
                },
                {
                    "step_id": "step-6",
                    "title": "Read back and verify persistence",
                    "instruction": (
                        "Read back inserted KnowledgeItem records and verify persistence "
                        "(source_id + chunk count). Deterministic DB readback only."
                    ),
                    "agent_id": "knowledge_builder",
                    "kind": "knowledge",
                    "required_capability": "knowledge.verify_persistence",
                    "depends_on": ["step-5"],
                    "expected_evidence": ["source_id", "chunks", "verified"],
                    "input_refs": ["step-5"],
                },
            ]
        )
    else:
        steps.append(
            {
                "step_id": "step-4",
                "title": "Summarize plugin execution result",
                "instruction": (
                    "Summarize the plugin execution result for the user. "
                    "Do not create plugins and do not claim persistence unless it happened."
                ),
                "agent_id": default_agent if default_agent in {"executor", "tool_orchestrator", "chat"} else "executor",
                "kind": "work",
                "required_capability": "chat.answer",
                "depends_on": ["step-3"],
                "expected_evidence": ["summary"],
                "input_refs": ["step-3"],
            }
        )

    criteria = [
        f"Bestaande plugin '{hint}' is opgelost zonder nieuwe plugin te maken.",
        "Plugin health/availability is gecontroleerd.",
        "Plugin is uitgevoerd via PluginManager (niet gesimuleerd).",
    ]
    if persist:
        criteria.append("Plugin-output is omgezet naar KnowledgeItems, persistent opgeslagen en geverifieerd.")
    else:
        criteria.append("Uitvoerresultaat is gerapporteerd zonder onbewezen succesclaims.")

    return {
        "goal": prompt.strip()[:2000],
        "acceptance_criteria": criteria,
        "steps": steps,
        "notes": [
            "deterministic_template=existing_plugin_to_knowledge",
            f"plugin_hint={hint}",
            "intent=USE_EXISTING_PLUGIN",
            "capability_based=true",
        ],
        "version": 1,
        "intent": "USE_EXISTING_PLUGIN",
    }


def assign_step_agent_for_instruction(
    instruction: str,
    *,
    title: str = "",
    kind: str = "",
    proposed: str | None = None,
    required_capability: str | None = None,
    enabled_agents: set[str] | None = None,
    preserve_capability: bool = True,
) -> str:
    """Assign executor by required capability; never leave plugin lookup on knowledge_builder."""
    enabled = enabled_agents or set()
    capability = required_capability or infer_required_capability(instruction, title=title, kind=kind)
    proposed_norm = (proposed or "").strip()

    if capability:
        chosen = pick_executor_for_capability(
            capability,
            enabled_agents=enabled or None,
            preferred=proposed_norm if preserve_capability else None,
        )
        if chosen:
            return chosen
        # Hard reject incompatible proposed executor for plugin capabilities.
        if capability.startswith("plugin.") and proposed_norm in {
            "knowledge_builder",
            "evidence_auditor",
            "plugin_converter",
            "web_scout",
            "build",
            "retrieval",
        }:
            fallback = pick_executor_for_capability(capability, enabled_agents=enabled or None)
            if fallback:
                return fallback

    # Legacy marker fallback (still capability-aware).
    text = f"{title}\n{instruction}".lower()
    lookup_markers = (
        "zoek de bestaande",
        "resolve existing",
        "locate installed",
        "plugin registry",
        "installed plugin",
        "lookup plugin",
        "resolve plugin",
    )
    execute_markers = ("voer", "execute", "invoke", "run plugin", "run tool", "call tool", "plugin uitvoeren")
    knowledge_markers = (
        "knowledgeitem",
        "knowledge item",
        "kennis",
        "persist",
        "opslaan",
        "sla op",
        "ingest",
        "convert returned",
        "omzetten",
        "normaliseer",
    )
    is_lookup = any(m in text for m in lookup_markers) or (
        "plugin" in text and any(m in text for m in ("zoek", "resolve", "locate", "vind", "registry"))
    )
    is_execute = any(m in text for m in execute_markers) and "plugin" in text
    is_knowledge = any(m in text for m in knowledge_markers) and not is_lookup and not (
        is_execute and "kennis" not in text and "knowledge" not in text
    )

    def _pick(*candidates: str) -> str | None:
        for cid in candidates:
            if not enabled or cid in enabled:
                return cid
        return None

    if is_lookup or (is_execute and proposed_norm in {"knowledge_builder", "evidence_auditor", "plugin_converter", "web_scout", "build", "retrieval"}):
        chosen = _pick("tool_orchestrator", "executor")
        if chosen:
            return chosen
    if is_knowledge:
        chosen = _pick("knowledge_builder", "memory_curator", "executor")
        if chosen:
            return chosen
    if proposed_norm and (not enabled or proposed_norm in enabled):
        return proposed_norm
    return _pick("executor", "chat") or "executor"


def preserve_required_capabilities(
    steps: list[dict[str, Any]],
    *,
    prior_steps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """When replanning, keep validated capability requirements and re-bind owners."""
    prior_by_id: dict[str, dict[str, Any]] = {}
    for index, step in enumerate(prior_steps or []):
        sid = str(step.get("step_id") or step.get("step_key") or f"step-{index + 1}")
        prior_by_id[sid] = step

    out: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        payload = dict(step)
        sid = str(payload.get("step_id") or payload.get("step_key") or f"step-{index + 1}")
        prior = prior_by_id.get(sid) or {}
        capability = (
            str(payload.get("required_capability") or "").strip()
            or str(prior.get("required_capability") or "").strip()
            or infer_required_capability(
                str(payload.get("instruction") or ""),
                title=str(payload.get("title") or ""),
                kind=str(payload.get("kind") or ""),
            )
            or ""
        )
        if capability:
            payload["required_capability"] = capability
            payload["agent_id"] = assign_step_agent_for_instruction(
                str(payload.get("instruction") or ""),
                title=str(payload.get("title") or ""),
                kind=str(payload.get("kind") or ""),
                proposed=str(payload.get("agent_id") or ""),
                required_capability=capability,
                preserve_capability=True,
            )
        out.append(payload)
    return out
