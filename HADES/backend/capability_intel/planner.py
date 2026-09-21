"""Deterministic intent → capability requirement planner.

Escalation: exact/deterministic → lexical/metadata → (optional) semantic.
A planning LLM is never required.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import CapabilityRequirement, RequirementPlan

_TOKEN = re.compile(r"[a-zA-ZÀ-ÿ0-9_.-]+")

_GOAL_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("repair_repository_bug", ("fix the bug", "repair", "race condition", "deadlock", "concurrency bug", "los de bug", "herstel")),
    ("implement_feature", ("implement", "voeg toe", "add a", "feature")),
    ("explain_code", ("explain", "leg uit", "what does", "hoe werkt", "wat doet")),
    ("research", ("research", "onderzoek", "zoek bronnen")),
    ("retrieve", ("zoek in knowledge", "search memory", "haal op")),
]

_GOAL_REQUIREMENTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "repair_repository_bug": (
        ("software.reason", "skill", "goal_implies_skill"),
        ("code.search", "tool", "goal_implies_search"),
        ("code.modify", "tool", "goal_implies_modify"),
        ("tests.execute", "tool", "goal_implies_tests"),
        ("result.verify", "agent", "goal_implies_verify"),
    ),
    "implement_feature": (
        ("code.search", "tool", "goal_implies_search"),
        ("code.modify", "tool", "goal_implies_modify"),
    ),
    "explain_code": (("software.reason", "skill", "explain_only"),),
}

_REQUIREMENT_MARKERS: list[tuple[str, str | None, tuple[str, ...]]] = [
    ("repository.read", "tool", ("read the repo", "inspect", "zoek in de code", "search the repository", "codebase")),
    ("code.search", "tool", ("search", "find the", "grep", "zoek naar", "race condition", "where is")),
    ("software.reason", "skill", ("debug", "diagnos", "reason", "analyse")),
    ("code.modify", "tool", ("fix", "patch", "edit", "wijzig", "repair", "implement")),
    ("tests.execute", "tool", ("prove", "test", "pytest", "unittest", "bewijs")),
    ("result.verify", "agent", ("verify", "verifieer", "prove the fix", "acceptance")),
    ("knowledge.search", "knowledge", ("documentation", "docs", "knowledge")),
    ("mcp.call", "mcp_provider", ("mcp", "model context protocol")),
]

_DOMAIN_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("software.concurrency", ("race", "deadlock", "concurren", "lock ordering", "mutex", "thread")),
    ("debugging", ("bug", "debug", "diagnos", "fix", "repair", "race")),
    ("software.repository", ("repo", "repository", "codebase", "code")),
    ("software.python", ("python", "pytest")),
    ("software.test", ("test", "prove", "pytest", "unittest")),
]

_EXPLICIT_USE = re.compile(
    r"\b(?:use|gebruik|using|via)\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9 ._-]{1,60})",
    re.I,
)

_SIMPLE_EXPLAIN = (
    "explain", "leg uit", "what does", "wat doet", "what is", "wat is", "hoe werkt", "how does",
)
_MUTATION = ("fix", "patch", "edit", "write", "implement", "repair", "verwijder", "delete")


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def extract_explicit_providers(text: str) -> list[str]:
    found: list[str] = []
    stop = {"to", "for", "and", "with", "on", "in", "via", "using", "use", "the", "a", "an", "plugin", "tool", "agent"}
    for match in _EXPLICIT_USE.finditer(text):
        tokens = match.group(1).strip().rstrip(".,:;!?").split()
        kept: list[str] = []
        for token in tokens:
            if token.lower() in stop and kept:
                break
            if token.lower() in {"the", "a", "an"}:
                continue
            kept.append(token)
        name = " ".join(kept).strip()
        if not name or name.lower() in stop:
            continue
        found.append(name)
    return found[:6]


def plan_requirements(text: str, *, extra: dict[str, Any] | None = None) -> RequirementPlan:
    """Build a requirement plan without calling a model."""
    extra = extra or {}
    sample = str(text or "").strip()
    lower = sample.lower()
    goal = "answer"
    for name, markers in _GOAL_MARKERS:
        if _contains_any(lower, markers):
            goal = name
            break
    requirements: list[CapabilityRequirement] = []
    seen: set[str] = set()
    for capability, kind, markers in _REQUIREMENT_MARKERS:
        if not _contains_any(lower, markers):
            continue
        if capability in seen:
            continue
        seen.add(capability)
        requirements.append(CapabilityRequirement(capability=capability, kind_hint=kind, reason="lexical_marker"))
    for capability, kind, reason in _GOAL_REQUIREMENTS.get(goal, ()):
        if capability in seen:
            continue
        seen.add(capability)
        requirements.append(CapabilityRequirement(capability=capability, kind_hint=kind, reason=reason))
    explicit = extract_explicit_providers(sample)
    simple = _contains_any(lower, _SIMPLE_EXPLAIN) and not _contains_any(lower, _MUTATION)
    if simple:
        requirements = [item for item in requirements if item.capability not in {"code.modify", "tests.execute"}]
        if not any(item.capability == "software.reason" for item in requirements):
            requirements.append(CapabilityRequirement(capability="software.reason", kind_hint="skill", optional=True, reason="explain_only"))
        goal = "explain_code" if goal == "answer" else goal
    domains: list[str] = []
    for domain, markers in _DOMAIN_MARKERS:
        if _contains_any(lower, markers) and domain not in domains:
            domains.append(domain)
    if goal == "repair_repository_bug":
        for domain in ("software.repository", "debugging"):
            if domain not in domains:
                domains.append(domain)
    verification = _contains_any(lower, ("prove", "verify", "test", "bewijs", "verifieer")) or any(
        item.capability == "result.verify" for item in requirements
    )
    risk: list[str] = []
    if any(item.capability == "code.modify" for item in requirements):
        risk.append("modifies_workspace")
    if extra.get("high_risk"):
        risk.append("high_risk")
    notes = ["deterministic_planner"]
    if explicit:
        notes.append("explicit_provider_reference")
    if simple:
        notes.append("simple_fast_path")
    if not requirements and not simple:
        notes.append("no_capability_markers")
    return RequirementPlan(
        goal=goal,
        requirements=requirements,
        domains=domains,
        risk=risk,
        verification_required=verification,
        explicit_providers=explicit,
        simple=simple,
        model_adjudication=False,
        planner="deterministic",
        notes=notes,
    )
