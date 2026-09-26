"""TaskModel — structured orchestration metadata (not private CoT)."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from Data.modules.context.compaction import extract_hard_constraints
from Data.modules.reasoning import ReasoningEngine, ReasoningPlan
from Data.modules.verification.types import (
    CriterionVerificationStatus,
    VerifierKind,
)

from .types import RiskClass


@dataclass(frozen=True)
class AcceptanceCriterion:
    """Typed acceptance predicate — completion authority is evidence-based.

    Legacy free-text ``success_criteria`` strings remain for compatibility readers;
    unsupported legacy semantics stay UNVERIFIED and never auto-pass.
    """

    criterion_id: str
    predicate: str
    description: str
    expected_artifact: str | None = None
    expected_effect: str | None = None
    verifier_kind: VerifierKind = VerifierKind.OBSERVATION
    scope: str = "run"
    required_evidence: tuple[str, ...] = ()
    status: CriterionVerificationStatus = CriterionVerificationStatus.UNVERIFIED

    def public_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "predicate": self.predicate,
            "description": self.description,
            "expected_artifact": self.expected_artifact,
            "expected_effect": self.expected_effect,
            "verifier_kind": self.verifier_kind.value,
            "scope": self.scope,
            "required_evidence": list(self.required_evidence),
            "status": self.status.value,
            "truth": {
                "model_text_does_not_satisfy_criterion": True,
                "legacy_string_is_not_typed_predicate": True,
            },
        }


def acceptance_criterion_from_mapping(raw: Mapping[str, Any] | AcceptanceCriterion) -> AcceptanceCriterion:
    if isinstance(raw, AcceptanceCriterion):
        return raw
    data = dict(raw or {})
    try:
        verifier = VerifierKind(str(data.get("verifier_kind") or VerifierKind.OBSERVATION.value))
    except ValueError:
        verifier = VerifierKind.LEGACY_UNSUPPORTED
    try:
        status = CriterionVerificationStatus(
            str(data.get("status") or CriterionVerificationStatus.UNVERIFIED.value)
        )
    except ValueError:
        status = CriterionVerificationStatus.UNVERIFIED
    criterion_id = str(data.get("criterion_id") or data.get("id") or "").strip()
    description = str(data.get("description") or data.get("criterion") or criterion_id or "criterion")
    if not criterion_id:
        criterion_id = f"crit:{description[:48]}"
    return AcceptanceCriterion(
        criterion_id=criterion_id,
        predicate=str(data.get("predicate") or "unknown"),
        description=description,
        expected_artifact=data.get("expected_artifact"),
        expected_effect=data.get("expected_effect"),
        verifier_kind=verifier,
        scope=str(data.get("scope") or "run"),
        required_evidence=tuple(str(x) for x in (data.get("required_evidence") or ())),
        status=status,
    )


def coerce_acceptance_criteria(
    raw: Sequence[Any] | None,
    *,
    legacy_strings: Sequence[str] | None = None,
) -> list[AcceptanceCriterion]:
    """Compatibility reader: typed dicts/objects preferred; legacy strings mapped or UNVERIFIED."""
    out: list[AcceptanceCriterion] = []
    if raw:
        for item in raw:
            if isinstance(item, AcceptanceCriterion):
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(acceptance_criterion_from_mapping(item))
            elif isinstance(item, str) and item.strip():
                out.append(legacy_string_to_criterion(item.strip()))
    elif legacy_strings:
        for item in legacy_strings:
            if item and str(item).strip():
                out.append(legacy_string_to_criterion(str(item).strip()))
    return out


def legacy_string_to_criterion(text: str) -> AcceptanceCriterion:
    """Map known legacy string criteria; unsupported semantics → unverified."""
    c_low = text.lower().strip()
    cid = f"legacy:{hashlib.sha1(c_low.encode('utf-8')).hexdigest()[:10]}"
    if "helpful direct reply" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="helpful_reply",
            description=text,
            verifier_kind=VerifierKind.RESPONSE_PRESENCE,
            scope="conversation",
        )
    if "test" in c_low or "regression covered" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="tests_passed",
            description=text,
            expected_effect="tests_passed",
            verifier_kind=VerifierKind.TEST_RECEIPT,
            scope="workspace",
            required_evidence=("trusted_test_receipt",),
        )
    if "source" in c_low or "evidence" in c_low or "grounded" in c_low or "claim" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="claim_supported",
            description=text,
            verifier_kind=VerifierKind.EVIDENCE_STORE,
            scope="run",
            required_evidence=("independent_claim_support",),
        )
    if "conflict" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="conflict_surfaced",
            description=text,
            verifier_kind=VerifierKind.OBSERVATION,
            scope="run",
        )
    if "unverif" in c_low or "silent" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="honesty_no_silent_success",
            description=text,
            verifier_kind=VerifierKind.HONESTY,
            scope="run",
        )
    if "artifact" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="artifact_present",
            description=text,
            verifier_kind=VerifierKind.ARTIFACT,
            scope="artifact",
            required_evidence=("artifact_receipt",),
        )
    if "approval" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="approval_respected",
            description=text,
            verifier_kind=VerifierKind.OBSERVATION,
            scope="run",
        )
    if "observation" in c_low or "workspace" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="observations_recorded",
            description=text,
            verifier_kind=VerifierKind.OBSERVATION,
            scope="workspace",
        )
    if "goal" in c_low or "address" in c_low or "answer" in c_low or "root cause" in c_low or "change identified" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="goal_addressed",
            description=text,
            verifier_kind=VerifierKind.RESPONSE_PRESENCE,
            scope="conversation",
        )
    if "hard constraints" in c_low or "fake certainty" in c_low or "flattened" in c_low:
        return AcceptanceCriterion(
            criterion_id=cid,
            predicate="honesty_no_silent_success",
            description=text,
            verifier_kind=VerifierKind.HONESTY,
            scope="run",
        )
    # Unsupported legacy free-text — never word-match to a pass.
    return AcceptanceCriterion(
        criterion_id=cid,
        predicate="unknown",
        description=text,
        verifier_kind=VerifierKind.LEGACY_UNSUPPORTED,
        scope="run",
        status=CriterionVerificationStatus.UNVERIFIED,
    )


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
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
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
    needs_brain_retrieval: bool = False
    needs_memory: bool = False
    needs_browser: bool = False
    needs_code_execution: bool = False
    needs_calculation: bool = False
    needs_specialists: bool = False
    needs_verification: bool = False
    requires_side_effect: bool = False
    freshness_requirement: str = "none"  # none | preferred | required
    complexity: str = "low"
    expected_answer_type: str = "prose"
    verification_mode: str = "NONE"  # NONE | LIGHT | REQUIRED | CORROBORATED
    execution_class: str = "DIRECT"  # DIRECT | CONTEXTUAL | TOOL_REQUIRED | CURRENT_INFO | COMPLEX_REASONING | MULTI_DOMAIN | VERIFICATION_REQUIRED | WORK
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
            "acceptance_criteria": [c.public_dict() for c in self.acceptance_criteria],
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
            "needs_brain_retrieval": self.needs_brain_retrieval,
            "needs_memory": self.needs_memory,
            "needs_browser": self.needs_browser,
            "needs_code_execution": self.needs_code_execution,
            "needs_calculation": self.needs_calculation,
            "needs_specialists": self.needs_specialists,
            "needs_verification": self.needs_verification,
            "requires_side_effect": self.requires_side_effect,
            "freshness_requirement": self.freshness_requirement,
            "complexity": self.complexity,
            "expected_answer_type": self.expected_answer_type,
            "verification_mode": self.verification_mode,
            "execution_class": self.execution_class,
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

    Hybrid understanding: deterministic parsing + ReasoningEngine classification.
    Does not claim authority over tools or completion.
    """

    def __init__(self, reasoner: ReasoningEngine | None = None) -> None:
        self.reasoner = reasoner or ReasoningEngine()

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
        typed_criteria = self._acceptance_criteria(domain, task_type, text, criteria)
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

        needs_browser = any(t in lowered for t in ("browser", "klik", "click", "screenshot", "navigate", "webpage", "webpagina"))
        needs_calculation = bool(
            re.search(r"\b\d+\s*[\+\-\*/×÷]\s*\d+\b", text)
            or any(t in lowered for t in ("bereken", "calculate", "som van", "percentage van", "sqrt", "gemiddelde"))
        )
        needs_code_execution = requires_coding or any(t in lowered for t in ("pytest", "npm test", "run script", "execute code"))
        self_inspect = any(
            t in lowered
            for t in (
                "welk model",
                "which model",
                "hoeveel %",
                "how much of your brain",
                "system inspect",
                "wat gebruik je nu",
                "how much ram",
                "active agents",
            )
        )
        needs_brain = (
            plan.use_knowledge
            or domain in {"knowledge", "research"}
            or has_knowledge
            or any(t in lowered for t in ("brain", "kennis", "knowledge", "onthoud", "herinner"))
        ) and task_type != "simple_chat"
        needs_memory = requires_personal or any(t in lowered for t in ("remember", "onthoud", "earlier", "previously", "earder", "vorige"))
        needs_specialists = (
            requires_research
            or requires_coding
            or research_mode == "deep"
            or plan.complexity == "high"
            or self_inspect
        )
        needs_verification = (
            requires_current
            or requires_research
            or research_mode != "none"
            or risk in {RiskClass.HIGH, RiskClass.CRITICAL}
            or self_inspect
            or requires_files
        )
        requires_side_effect = bool(side_effects)
        freshness = "required" if requires_current else ("preferred" if requires_external else "none")
        complexity = str(plan.complexity or "low")
        # Self-inspect / calculation / current-info beat the short-message DIRECT path.
        if self_inspect:
            execution_class = "TOOL_REQUIRED"
            verification_mode = "REQUIRED"
        elif needs_calculation and not requires_research and task_type != "coding_repair":
            execution_class = "TOOL_REQUIRED"
            verification_mode = "LIGHT"
        elif requires_current:
            execution_class = "CURRENT_INFO"
            verification_mode = "REQUIRED"
        elif task_type == "simple_chat":
            execution_class = "DIRECT"
            verification_mode = "NONE"
        elif requires_tools or needs_browser or needs_code_execution:
            execution_class = "TOOL_REQUIRED"
            verification_mode = "REQUIRED" if needs_verification else "LIGHT"
        elif needs_specialists and (requires_research or requires_coding):
            execution_class = "MULTI_DOMAIN" if (requires_research and requires_coding) else "COMPLEX_REASONING"
            verification_mode = "CORROBORATED" if research_mode == "deep" else "REQUIRED"
        elif needs_verification:
            execution_class = "VERIFICATION_REQUIRED"
            verification_mode = "REQUIRED"
        elif needs_brain or needs_memory:
            execution_class = "CONTEXTUAL"
            verification_mode = "LIGHT"
        else:
            execution_class = "DIRECT"
            verification_mode = "NONE"
        if preferred == "external_worker" or research_mode == "deep":
            if execution_class in {"DIRECT", "CONTEXTUAL"}:
                execution_class = "WORK"

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

        return TaskModel(
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
            acceptance_criteria=typed_criteria,
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
            needs_brain_retrieval=bool(needs_brain),
            needs_memory=bool(needs_memory),
            needs_browser=bool(needs_browser),
            needs_code_execution=bool(needs_code_execution),
            needs_calculation=bool(needs_calculation),
            needs_specialists=bool(needs_specialists),
            needs_verification=bool(needs_verification),
            requires_side_effect=requires_side_effect,
            freshness_requirement=freshness,
            complexity=complexity,
            expected_answer_type=(
                "structured" if "vergelijk" in lowered or "compare" in lowered else "prose"
            ),
            verification_mode=verification_mode,
            execution_class=execution_class,
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

    def _acceptance_criteria(
        self,
        domain: str,
        task_type: str,
        text: str,
        legacy: list[str],
    ) -> list[AcceptanceCriterion]:
        """Typed predicates with stable IDs — preferred completion authority."""
        typed: list[AcceptanceCriterion] = []
        if task_type == "simple_chat":
            typed.append(
                AcceptanceCriterion(
                    criterion_id="crit:helpful_reply",
                    predicate="helpful_reply",
                    description="helpful direct reply",
                    verifier_kind=VerifierKind.RESPONSE_PRESENCE,
                    scope="conversation",
                )
            )
            return typed
        if domain == "coding":
            typed.append(
                AcceptanceCriterion(
                    criterion_id="crit:coding_root_cause",
                    predicate="goal_addressed",
                    description="root cause or change identified",
                    verifier_kind=VerifierKind.RESPONSE_PRESENCE,
                    scope="conversation",
                )
            )
            if any(t in text.lower() for t in ("test", "fix", "bug")):
                typed.append(
                    AcceptanceCriterion(
                        criterion_id="crit:tests_passed",
                        predicate="tests_passed",
                        description="regression covered or tests observed",
                        expected_effect="tests_passed",
                        verifier_kind=VerifierKind.TEST_RECEIPT,
                        scope="workspace",
                        required_evidence=("trusted_test_receipt",),
                    )
                )
                typed.append(
                    AcceptanceCriterion(
                        criterion_id="crit:no_silent_success",
                        predicate="honesty_no_silent_success",
                        description="no silent unverified success",
                        verifier_kind=VerifierKind.HONESTY,
                        scope="run",
                    )
                )
            else:
                typed.append(
                    AcceptanceCriterion(
                        criterion_id="crit:workspace_observations",
                        predicate="observations_recorded",
                        description="workspace observations recorded",
                        verifier_kind=VerifierKind.OBSERVATION,
                        scope="workspace",
                    )
                )
            return typed
        if domain == "research" or task_type.startswith("research"):
            return [
                AcceptanceCriterion(
                    criterion_id="crit:claim_supported",
                    predicate="claim_supported",
                    description="sources or evidence referenced",
                    verifier_kind=VerifierKind.EVIDENCE_STORE,
                    scope="run",
                    required_evidence=("independent_claim_support",),
                ),
                AcceptanceCriterion(
                    criterion_id="crit:conflicts_surfaced",
                    predicate="conflict_surfaced",
                    description="conflicts surfaced when present",
                    verifier_kind=VerifierKind.OBSERVATION,
                    scope="run",
                ),
                AcceptanceCriterion(
                    criterion_id="crit:no_fake_certainty",
                    predicate="honesty_no_silent_success",
                    description="claims not flattened into fake certainty",
                    verifier_kind=VerifierKind.HONESTY,
                    scope="run",
                ),
                AcceptanceCriterion(
                    criterion_id="crit:hard_constraints",
                    predicate="honesty_no_silent_success",
                    description="hard constraints preserved",
                    verifier_kind=VerifierKind.HONESTY,
                    scope="run",
                ),
            ]
        if domain == "knowledge":
            return [
                AcceptanceCriterion(
                    criterion_id="crit:knowledge_grounded",
                    predicate="claim_supported",
                    description="answer grounded in retrieved knowledge when available",
                    verifier_kind=VerifierKind.EVIDENCE_STORE,
                    scope="run",
                    required_evidence=("independent_claim_support",),
                )
            ]
        # Prefer typed mapping of legacy strings so unknown free-text stays unverified.
        return coerce_acceptance_criteria(None, legacy_strings=legacy)

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
