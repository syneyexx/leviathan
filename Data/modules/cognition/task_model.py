"""TaskModel — structured orchestration metadata (not private CoT)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from Data.modules.reasoning import ReasoningEngine, ReasoningPlan

from .types import RiskClass


@dataclass
class TaskModel:
    """Canonical task understanding for cognitive orchestration."""

    task_id: str
    run_id: str | None
    raw_request: str
    goal: str
    domain: str
    task_type: str
    requested_outputs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    risk_class: RiskClass = RiskClass.LOW
    side_effect_expectations: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    time_sensitivity: str = "normal"
    resource_expectation: str = "light"
    privacy_class: str = "standard"
    initial_uncertainty: float = 0.5
    preferred_execution_mode: str = "in_process"
    allowed_delegation: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    legacy_plan: ReasoningPlan | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "raw_request": self.raw_request[:2000],
            "goal": self.goal,
            "domain": self.domain,
            "task_type": self.task_type,
            "requested_outputs": list(self.requested_outputs),
            "constraints": list(self.constraints),
            "success_criteria": list(self.success_criteria),
            "risk_class": self.risk_class.value,
            "side_effect_expectations": list(self.side_effect_expectations),
            "required_evidence": list(self.required_evidence),
            "known_facts": list(self.known_facts),
            "unknowns": list(self.unknowns),
            "ambiguities": list(self.ambiguities),
            "dependencies": list(self.dependencies),
            "time_sensitivity": self.time_sensitivity,
            "resource_expectation": self.resource_expectation,
            "privacy_class": self.privacy_class,
            "initial_uncertainty": self.initial_uncertainty,
            "preferred_execution_mode": self.preferred_execution_mode,
            "allowed_delegation": list(self.allowed_delegation),
            "metadata": self.metadata,
            "legacy_plan": self.legacy_plan.public_summary() if self.legacy_plan else None,
            "truth": {
                "task_model_is_not_private_cot": True,
                "model_claim_is_not_completion": True,
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

    Uses ReasoningEngine as a lightweight classifier for domain/intent
    compatibility; does not claim authority over tools or completion.
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

        return TaskModel(
            task_id=str(uuid.uuid4()),
            run_id=run_id,
            raw_request=text,
            goal=self._goal(text, domain),
            domain=domain,
            task_type=task_type,
            requested_outputs=self._outputs(domain, task_type),
            constraints=list(constraints or []),
            success_criteria=criteria,
            risk_class=risk,
            side_effect_expectations=side_effects,
            required_evidence=self._required_evidence(domain, risk, side_effects),
            known_facts=[],
            unknowns=unknowns,
            ambiguities=ambiguities,
            dependencies=[],
            time_sensitivity="urgent" if any(t in text.lower() for t in ("asap", "urgent", "now")) else "normal",
            resource_expectation=resource,
            privacy_class="sensitive" if any(t in text.lower() for t in _HIGH_RISK_TERMS) else "standard",
            initial_uncertainty=uncertainty,
            preferred_execution_mode=preferred,
            allowed_delegation=allowed,
            metadata={
                **(metadata or {}),
                "conversation_id": conversation_id,
                "legacy_complexity": plan.complexity,
                "use_knowledge": plan.use_knowledge,
            },
            legacy_plan=plan,
        )

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
        if plan.intent == "research":
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
        if domain == "research":
            return [
                "sources or evidence referenced",
                "conflicts surfaced when present",
                "claims not flattened into fake certainty",
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

    def _required_evidence(self, domain: str, risk: RiskClass, side_effects: list[str]) -> list[str]:
        needed: list[str] = []
        if domain == "research":
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
        if domain == "research" and "source" not in text.lower():
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

    def _allowed_delegation(self, domain: str, risk: RiskClass) -> list[str]:
        allowed: list[str] = []
        if domain == "coding":
            allowed.append("coding")
        if domain == "research":
            allowed.append("research")
        if risk in {RiskClass.HIGH, RiskClass.CRITICAL}:
            allowed.append("reviewer")
        return allowed

    def _outputs(self, domain: str, task_type: str) -> list[str]:
        if task_type == "simple_chat":
            return ["text_reply"]
        if domain == "coding":
            return ["diagnosis_or_patch", "test_observation"]
        if domain == "research":
            return ["evidence_backed_synthesis"]
        return ["text_reply"]
