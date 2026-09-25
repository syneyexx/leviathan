"""TaskModel — structured orchestration metadata (not private CoT)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from Data.modules.context.compaction import extract_hard_constraints
from Data.modules.reasoning import ReasoningEngine, ReasoningPlan

from .types import RiskClass


_FRESHNESS_TERMS = {
    "current",
    "latest",
    "newest",
    "today",
    "actueel",
    "nieuwste",
    "huidige",
    "live",
    "up to date",
    "up-to-date",
}
_RESEARCH_TERMS = {
    "research",
    "onderzoek",
    "analyse",
    "deep dive",
    "uitgebreid",
    "vergelijk",
    "compare",
    "versus",
    " vs ",
    "zoek uit",
    "investigate",
    "evidence",
    "bewijs",
    "bronnen",
    "sources",
}
_TOOL_TERMS = {
    "run",
    "execute",
    "invoke",
    "call tool",
    "use tool",
    "browser",
    "fetch",
    "shell",
    "pytest",
    "npm",
}
_CODING_TERMS = {
    "code",
    "implement",
    "refactor",
    "bug",
    "fix",
    "patch",
    "compile",
    "test",
    "functie",
    "class",
}
_PERSONAL_TERMS = {
    "my ",
    "mine",
    "ik ",
    "mijn ",
    "remember",
    "onthoud",
    "preference",
    "voorkeur",
}


@dataclass
class TaskModel:
    """Canonical task understanding for cognitive orchestration."""

    task_id: str
    run_id: str | None
    raw_request: str
    goal: str
    domain: str
    task_type: str
    intent: str = "general"
    requested_outputs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    required_outputs: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    time_scope: str | None = None
    location_scope: str | None = None
    risk_class: RiskClass = RiskClass.LOW
    side_effect_expectations: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    requires_current_information: bool = False
    requires_external_information: bool = False
    requires_personal_context: bool = False
    requires_files: bool = False
    requires_tools: bool = False
    requires_actions: bool = False
    requires_research: bool = False
    requires_coding: bool = False
    candidate_specialists: list[str] = field(default_factory=list)
    language: str = "auto"
    output_format: str = "prose"
    time_sensitivity: str = "normal"
    resource_expectation: str = "light"
    privacy_class: str = "standard"
    initial_uncertainty: float = 0.5
    preferred_execution_mode: str = "in_process"
    allowed_delegation: list[str] = field(default_factory=list)
    research_mode: str = "none"  # none | assisted | deep
    metadata: dict[str, Any] = field(default_factory=dict)
    legacy_plan: ReasoningPlan | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "raw_request": self.raw_request[:2000],
            "goal": self.goal,
            "intent": self.intent,
            "domain": self.domain,
            "task_type": self.task_type,
            "requested_outputs": list(self.requested_outputs),
            "required_outputs": list(self.required_outputs or self.requested_outputs),
            "constraints": list(self.constraints),
            "hard_constraints": list(self.hard_constraints),
            "preferences": list(self.preferences),
            "success_criteria": list(self.success_criteria),
            "entities": list(self.entities),
            "time_scope": self.time_scope,
            "location_scope": self.location_scope,
            "risk_class": self.risk_class.value,
            "side_effect_expectations": list(self.side_effect_expectations),
            "required_evidence": list(self.required_evidence),
            "known_facts": list(self.known_facts),
            "unknowns": list(self.unknowns),
            "ambiguities": list(self.ambiguities),
            "assumptions": list(self.assumptions),
            "dependencies": list(self.dependencies),
            "requires_current_information": self.requires_current_information,
            "requires_external_information": self.requires_external_information,
            "requires_personal_context": self.requires_personal_context,
            "requires_files": self.requires_files,
            "requires_tools": self.requires_tools,
            "requires_actions": self.requires_actions,
            "requires_research": self.requires_research,
            "requires_coding": self.requires_coding,
            "candidate_specialists": list(self.candidate_specialists),
            "language": self.language,
            "output_format": self.output_format,
            "time_sensitivity": self.time_sensitivity,
            "resource_expectation": self.resource_expectation,
            "privacy_class": self.privacy_class,
            "initial_uncertainty": self.initial_uncertainty,
            "preferred_execution_mode": self.preferred_execution_mode,
            "allowed_delegation": list(self.allowed_delegation),
            "research_mode": self.research_mode,
            "metadata": self.metadata,
            "legacy_plan": self.legacy_plan.public_summary() if self.legacy_plan else None,
            "truth": {
                "task_model_is_not_private_cot": True,
                "model_claim_is_not_completion": True,
                "hard_constraints_must_survive_compaction": True,
            },
        }


_WRITE_TERMS = {
    "write",
    "edit",
    "patch",
    "delete",
    "remove",
    "create file",
    "modify",
    "commit",
    "deploy",
    "publish",
    "send",
    "execute",
    "run tests",
    "fix",
}
_HIGH_RISK_TERMS = {
    "production",
    "drop table",
    "rm -rf",
    "credentials",
    "secret",
    "api key",
    "broker",
    "trade",
    "wire transfer",
}
_AMBIGUITY_MARKERS = {
    "maybe",
    "or something",
    "not sure",
    "whatever",
    "somehow",
    "?",
}


class TaskModelBuilder:
    """Build TaskModel from a user request.

    Hybrid understanding: deterministic parsing + ReasoningEngine classification
    + optional validated neural/heuristic semantic advisor.
    Does not claim authority over tools or completion. Advisor never owns risk /
    hard constraints / side effects.
    """

    def __init__(
        self,
        reasoner: ReasoningEngine | None = None,
        *,
        advisor: Any | None = None,
        enable_heuristic_advisor: bool = False,
    ) -> None:
        self.reasoner = reasoner or ReasoningEngine()
        self.advisor = advisor
        if self.advisor is None and enable_heuristic_advisor:
            from .neural_advisors import HeuristicTaskAdvisor

            self.advisor = HeuristicTaskAdvisor()

    def build(
        self,
        raw_request: str,
        *,
        has_knowledge: bool = False,
        run_id: str | None = None,
        conversation_id: str | None = None,
        deep_recall_enabled: bool = False,
        constraints: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskModel:
        text = (raw_request or "").strip()
        lowered = text.lower()
        plan = self.reasoner.analyze(
            text,
            has_knowledge,
            deep_recall_enabled=deep_recall_enabled,
        )
        domain = plan.intent
        task_type = self._task_type(plan, text)
        risk = self._risk_class(text, domain)
        uncertainty = self._uncertainty(text, plan)
        criteria = self._success_criteria(domain, task_type, text)
        side_effects = self._side_effects(text, domain)
        unknowns = self._unknowns(text, domain)
        ambiguities = self._ambiguities(text)
        allowed = self._allowed_delegation(domain, risk)
        resource = "heavy" if plan.complexity == "high" or domain in {"coding", "research"} else (
            "medium" if plan.complexity == "medium" else "light"
        )
        preferred = "external_worker" if domain in {"coding", "research", "training"} and plan.complexity != "low" else "in_process"
        extracted = extract_hard_constraints(text)
        merged_constraints = list(dict.fromkeys([*(constraints or []), *extracted]))

        requires_current = any(t in lowered for t in _FRESHNESS_TERMS)
        requires_research = domain == "research" or any(t in lowered for t in _RESEARCH_TERMS)
        requires_tools = any(t in lowered for t in _TOOL_TERMS) or bool(side_effects)
        requires_coding = domain == "coding" or any(t in lowered for t in _CODING_TERMS)
        requires_personal = any(t in lowered for t in _PERSONAL_TERMS)
        requires_files = bool(re.search(r"\.[a-zA-Z0-9]{1,8}\b", text)) or "bestand" in lowered or "file" in lowered
        requires_external = requires_current or requires_research or "web" in lowered or "internet" in lowered

        research_mode = "none"
        if requires_research and (plan.complexity == "high" or "diep" in lowered or "deep" in lowered or "uitgebreid" in lowered):
            research_mode = "deep"
        elif requires_research or requires_current or (domain in {"knowledge", "question"} and plan.complexity != "low"):
            research_mode = "assisted"

        if research_mode == "deep" and "research" not in allowed:
            allowed.append("research")
        if requires_coding and "coding" not in allowed:
            allowed.append("coding")

        candidates = list(allowed)
        entities = self._entities(text)
        language = self._language(text)
        assumptions = self._assumptions(text, domain, requires_current)
        preferences = self._preferences(text, merged_constraints)
        outputs = self._outputs(domain, task_type, research_mode)

        # Freshness raises uncertainty — stored knowledge may be stale.
        if requires_current:
            uncertainty = min(1.0, uncertainty + 0.2)
            unknowns.append("current external information may be required")

        task = TaskModel(
            task_id=str(uuid.uuid4()),
            run_id=run_id,
            raw_request=text,
            goal=self._goal(text, domain),
            intent=domain,
            domain=domain,
            task_type=task_type,
            requested_outputs=outputs,
            required_outputs=outputs,
            constraints=merged_constraints,
            hard_constraints=list(extracted),
            preferences=preferences,
            success_criteria=criteria,
            entities=entities,
            time_scope="current" if requires_current else None,
            location_scope=None,
            risk_class=risk,
            side_effect_expectations=side_effects,
            required_evidence=self._required_evidence(domain, risk, side_effects, research_mode),
            known_facts=[],
            unknowns=unknowns,
            ambiguities=ambiguities,
            assumptions=assumptions,
            dependencies=[],
            requires_current_information=requires_current,
            requires_external_information=requires_external,
            requires_personal_context=requires_personal,
            requires_files=requires_files,
            requires_tools=requires_tools,
            requires_actions=requires_tools or requires_coding,
            requires_research=requires_research or research_mode != "none",
            requires_coding=requires_coding,
            candidate_specialists=candidates,
            language=language,
            output_format="structured" if "vergelijk" in lowered or "compare" in lowered else "prose",
            time_sensitivity="urgent" if any(
                t in lowered for t in ("asap", "urgent", "now", "nu meteen")
            ) else "normal",
            resource_expectation=resource,
            privacy_class="sensitive" if any(t in lowered for t in _HIGH_RISK_TERMS) else "standard",
            initial_uncertainty=uncertainty,
            preferred_execution_mode=preferred,
            allowed_delegation=allowed,
            research_mode=research_mode,
            metadata={
                **(metadata or {}),
                "conversation_id": conversation_id,
                "legacy_complexity": plan.complexity,
                "use_knowledge": plan.use_knowledge,
                "hard_constraints": extracted,
                "permissions": self._permissions(merged_constraints, side_effects, risk),
                "uncertainties": unknowns + ambiguities,
                "freshness_required": requires_current,
            },
            legacy_plan=plan,
        )
        return self._apply_advisor(task, text)

    def _apply_advisor(self, task: TaskModel, text: str) -> TaskModel:
        if self.advisor is None:
            return task
        from .neural_advisors import apply_task_advice, validate_task_advice

        try:
            raw = self.advisor.advise_task(text, task)
        except Exception:  # noqa: BLE001
            meta = dict(task.metadata or {})
            meta["task_advice_error"] = "advisor_raised"
            return replace(task, metadata=meta)
        advice = validate_task_advice(
            raw if isinstance(raw, dict) else None,
            base=task,
            source=str(getattr(self.advisor, "source", "advisor")),
        )
        return apply_task_advice(task, advice)

    def _permissions(
        self,
        constraints: list[str],
        side_effects: list[str],
        risk: RiskClass,
    ) -> dict[str, Any]:
        joined = " ".join(constraints).lower()
        write_blocked = any(
            t in joined
            for t in (
                "wijzig nooit",
                "never modify",
                "never change",
                "do not modify",
                "nooit bestanden",
                "buiten de projectmap",
            )
        )
        return {
            "filesystem_write": ("filesystem_write" in side_effects) and not write_blocked,
            "network": "network_mutation" not in side_effects or risk != RiskClass.CRITICAL,
            "approval_required": risk in {RiskClass.HIGH, RiskClass.CRITICAL} or bool(side_effects),
            "workspace_bound": "projectmap" in joined or "project map" in joined or "workspace" in joined,
        }

    def _goal(self, text: str, domain: str) -> str:
        first = text.split("\n", 1)[0].strip()
        if len(first) > 240:
            first = first[:237] + "…"
        return first or f"Handle {domain} request"

    def _task_type(self, plan: ReasoningPlan, text: str) -> str:
        lowered = text.lower()
        if plan.intent == "coding":
            if any(t in lowered for t in ("fix", "bug", "broken", "fail")):
                return "coding_repair"
            if any(t in lowered for t in ("implement", "add", "create", "write")):
                return "coding_implement"
            return "coding_inspect"
        if plan.intent == "research" or any(t in lowered for t in ("onderzoek", "research", "vergelijk")):
            if "vergelijk" in lowered or "compare" in lowered or " vs " in lowered:
                return "research_comparison"
            return "research_synthesis"
        if plan.intent == "knowledge":
            return "knowledge_query"
        if plan.intent == "question":
            return "factual_question"
        if plan.complexity == "low" and len(text.split()) < 8:
            return "simple_chat"
        return "general"

    def _risk_class(self, text: str, domain: str) -> RiskClass:
        lowered = text.lower()
        if any(t in lowered for t in _HIGH_RISK_TERMS):
            return RiskClass.CRITICAL
        if domain == "coding" and any(t in lowered for t in _WRITE_TERMS):
            return RiskClass.HIGH
        if domain in {"coding", "research"}:
            return RiskClass.MEDIUM
        if any(t in lowered for t in _WRITE_TERMS):
            return RiskClass.MEDIUM
        return RiskClass.LOW

    def _uncertainty(self, text: str, plan: ReasoningPlan) -> float:
        base = {"low": 0.25, "medium": 0.5, "high": 0.7}.get(plan.complexity, 0.5)
        if "?" in text:
            base = min(1.0, base + 0.1)
        if any(m in text.lower() for m in _AMBIGUITY_MARKERS):
            base = min(1.0, base + 0.15)
        return round(base, 3)

    def _success_criteria(self, domain: str, task_type: str, text: str) -> list[str]:
        if task_type == "simple_chat":
            return ["helpful direct reply"]
        if domain == "coding":
            criteria = ["root cause or change identified"]
            if any(t in text.lower() for t in ("test", "fix", "bug")):
                criteria.extend(["regression covered or tests observed", "no silent unverified success"])
            else:
                criteria.append("workspace observations recorded")
            return criteria
        if domain == "research" or task_type.startswith("research"):
            return [
                "sources or evidence referenced",
                "conflicts surfaced when present",
                "claims not flattened into fake certainty",
                "hard constraints preserved",
            ]
        if domain == "knowledge":
            return ["answer grounded in retrieved knowledge when available"]
        return ["answer addresses the stated goal"]

    def _side_effects(self, text: str, domain: str) -> list[str]:
        lowered = text.lower()
        effects: list[str] = []
        if domain == "coding" or any(t in lowered for t in ("write", "edit", "patch", "delete")):
            effects.append("filesystem_write")
        if any(t in lowered for t in ("run", "execute", "pytest", "npm", "shell")):
            effects.append("subprocess")
        if any(t in lowered for t in ("publish", "post", "send", "email")):
            effects.append("network_mutation")
        return effects

    def _required_evidence(
        self,
        domain: str,
        risk: RiskClass,
        side_effects: list[str],
        research_mode: str,
    ) -> list[str]:
        needed: list[str] = []
        if domain == "research" or research_mode != "none":
            needed.append("source_or_evidence_ref")
        if "filesystem_write" in side_effects:
            needed.append("effect_or_patch_receipt")
        if "subprocess" in side_effects:
            needed.append("observation_ref")
        if risk in {RiskClass.HIGH, RiskClass.CRITICAL}:
            needed.append("verification_report")
        return needed

    def _unknowns(self, text: str, domain: str) -> list[str]:
        unknowns: list[str] = []
        if domain == "coding" and not re.search(r"\.[a-zA-Z0-9]{1,8}\b", text):
            unknowns.append("target file paths not specified")
        if domain == "research" and "source" not in text.lower() and "bron" not in text.lower():
            unknowns.append("preferred sources not specified")
        return unknowns

    def _ambiguities(self, text: str) -> list[str]:
        found: list[str] = []
        lowered = text.lower()
        if " or " in lowered and "?" in text:
            found.append("alternative interpretations present")
        if any(m in lowered for m in ("somehow", "whatever", "not sure")):
            found.append("underspecified user preference")
        return found

    def _assumptions(self, text: str, domain: str, requires_current: bool) -> list[str]:
        assumptions: list[str] = []
        if not requires_current:
            assumptions.append("stable knowledge may suffice unless contradicted")
        else:
            assumptions.append("freshness required — prefer current external sources when permitted")
        if domain == "research":
            assumptions.append("evidence must remain linked to sources")
        return assumptions

    def _preferences(self, text: str, constraints: list[str]) -> list[str]:
        prefs: list[str] = []
        lowered = text.lower()
        if "nederlands" in lowered or "dutch" in lowered:
            prefs.append("respond in Dutch")
        if "kort" in lowered or "brief" in lowered or "concise" in lowered:
            prefs.append("prefer concise answer")
        for c in constraints:
            if c.lower().startswith("prefer") or "alleen" in c.lower():
                prefs.append(c)
        return prefs

    def _entities(self, text: str) -> list[str]:
        # Deterministic: quoted terms + capitalized multi-word / CamelCase tokens.
        entities: list[str] = []
        for m in re.findall(r"[\"'“”]([^\"'“”]{2,80})[\"'“”]", text):
            entities.append(m.strip())
        for m in re.findall(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b", text):
            if m.lower() not in {"i", "a"} and m not in entities:
                entities.append(m)
        return entities[:16]

    def _language(self, text: str) -> str:
        dutch = len(re.findall(r"\b(de|het|een|van|voor|met|wat|hoe|waarom|onderzoek|gebruik)\b", text, re.I))
        english = len(re.findall(r"\b(the|and|what|how|why|research|please|use)\b", text, re.I))
        if dutch > english and dutch >= 2:
            return "nl"
        if english > dutch and english >= 2:
            return "en"
        return "auto"

    def _allowed_delegation(self, domain: str, risk: RiskClass) -> list[str]:
        allowed: list[str] = []
        if domain == "coding":
            allowed.append("coding")
        if domain == "research":
            allowed.append("research")
        if risk in {RiskClass.HIGH, RiskClass.CRITICAL}:
            allowed.append("reviewer")
        return allowed

    def _outputs(self, domain: str, task_type: str, research_mode: str) -> list[str]:
        if task_type == "simple_chat":
            return ["text_reply"]
        if domain == "coding":
            return ["diagnosis_or_patch", "test_observation"]
        if domain == "research" or research_mode == "deep":
            return ["evidence_backed_synthesis", "citations"]
        if research_mode == "assisted":
            return ["text_reply", "citations"]
        return ["text_reply"]
