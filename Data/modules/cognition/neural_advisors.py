"""Neural semantic advisors for TaskModel + plans — advisory only.

Deterministic ``TaskModelBuilder`` / ``CognitivePlanner`` remain owners.
Advice is validated against allowlists; invalid fields are rejected, never
applied. Free-form model text never becomes plan or task authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, Sequence

from .task_model import TaskModel
from .types import CognitivePlan, PlanStep, ReasoningStrategy, RiskClass


_MAX_LIST_ITEMS = 8
_MAX_ITEM_CHARS = 240
_MAX_ADVISORY_STEPS = 4

_ALLOWED_RESEARCH_MODES = frozenset({"none", "assisted", "deep"})
_ALLOWED_CAPABILITIES = frozenset(
    {
        "knowledge.search",
        "memory.search",
        "research.run",
        "coding.session",
        "web.fetch",
        "evidence.lookup",
        "verification.run",
    }
)
_RISK_ORDER = {
    RiskClass.LOW: 0,
    RiskClass.MEDIUM: 1,
    RiskClass.HIGH: 2,
    RiskClass.CRITICAL: 3,
}


def _clip(text: str, n: int = _MAX_ITEM_CHARS) -> str:
    s = (text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _clean_str_list(raw: Any, *, limit: int = _MAX_LIST_ITEMS) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        text = _clip(item)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
        if len(out) >= limit:
            break
    return out


@dataclass(frozen=True)
class TaskModelAdvice:
    """Validated enrichments for a deterministic TaskModel."""

    unknowns: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()
    research_mode: str | None = None
    requires_research: bool | None = None
    requires_current_information: bool | None = None
    notes: tuple[str, ...] = ()
    rejected_fields: tuple[str, ...] = ()
    accepted: bool = False
    source: str = "none"

    def public_dict(self) -> dict[str, Any]:
        return {
            "unknowns": list(self.unknowns),
            "ambiguities": list(self.ambiguities),
            "entities": list(self.entities),
            "success_criteria": list(self.success_criteria),
            "assumptions": list(self.assumptions),
            "preferences": list(self.preferences),
            "research_mode": self.research_mode,
            "requires_research": self.requires_research,
            "requires_current_information": self.requires_current_information,
            "notes": list(self.notes),
            "rejected_fields": list(self.rejected_fields),
            "accepted": self.accepted,
            "source": self.source,
            "truth": {
                "advice_is_not_task_authority": True,
                "invalid_fields_rejected": True,
                "not_private_cot": True,
            },
        }


@dataclass(frozen=True)
class PlanAdvice:
    """Validated advisory plan steps (never replace template authority alone)."""

    steps: tuple[PlanStep, ...] = ()
    notes: tuple[str, ...] = ()
    rejected_count: int = 0
    accepted: bool = False
    source: str = "none"

    def public_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.public_dict() for s in self.steps],
            "notes": list(self.notes),
            "rejected_count": self.rejected_count,
            "accepted": self.accepted,
            "source": self.source,
            "truth": {
                "advice_is_not_plan_authority": True,
                "template_plan_remains_owner": True,
                "unvalidated_steps_rejected": True,
                "not_private_cot": True,
            },
        }


def validate_task_advice(
    raw: Mapping[str, Any] | None,
    *,
    base: TaskModel,
    source: str = "advisor",
) -> TaskModelAdvice:
    """Whitelist + clamp neural/heuristic task advice."""
    if not isinstance(raw, Mapping) or not raw:
        return TaskModelAdvice(accepted=False, source=source, notes=("empty_advice",))

    rejected: list[str] = []
    notes: list[str] = []

    # Forbidden authority fields — never accept.
    for forbidden in (
        "risk_class",
        "hard_constraints",
        "side_effect_expectations",
        "allowed_delegation",
        "privacy_class",
        "raw_request",
        "task_id",
        "run_id",
    ):
        if forbidden in raw:
            rejected.append(forbidden)

    unknowns = _clean_str_list(raw.get("unknowns"))
    ambiguities = _clean_str_list(raw.get("ambiguities"))
    entities = _clean_str_list(raw.get("entities"))
    success_criteria = _clean_str_list(raw.get("success_criteria"))
    assumptions = _clean_str_list(raw.get("assumptions"))
    preferences = _clean_str_list(raw.get("preferences"))

    research_mode = None
    if "research_mode" in raw and raw.get("research_mode") is not None:
        mode = str(raw.get("research_mode") or "").strip().lower()
        if mode in _ALLOWED_RESEARCH_MODES:
            # Never downgrade deep → none; only same or escalate.
            order = {"none": 0, "assisted": 1, "deep": 2}
            if order[mode] >= order.get(base.research_mode, 0):
                research_mode = mode
            else:
                rejected.append("research_mode_downgrade")
        else:
            rejected.append("research_mode")

    requires_research = None
    if "requires_research" in raw:
        if isinstance(raw.get("requires_research"), bool):
            # Can only escalate True; cannot force False over deterministic True.
            if raw["requires_research"] is True or base.requires_research is False:
                requires_research = bool(raw["requires_research"]) or base.requires_research
            else:
                rejected.append("requires_research_downgrade")
        else:
            rejected.append("requires_research")

    requires_current = None
    if "requires_current_information" in raw:
        if isinstance(raw.get("requires_current_information"), bool):
            if raw["requires_current_information"] is True or not base.requires_current_information:
                requires_current = bool(raw["requires_current_information"]) or base.requires_current_information
            else:
                rejected.append("requires_current_information_downgrade")
        else:
            rejected.append("requires_current_information")

    has_payload = any(
        [
            unknowns,
            ambiguities,
            entities,
            success_criteria,
            assumptions,
            preferences,
            research_mode is not None,
            requires_research is not None,
            requires_current is not None,
        ]
    )
    if not has_payload:
        notes.append("no_applyable_fields")
    else:
        notes.append("validated_whitelist_applied")

    return TaskModelAdvice(
        unknowns=tuple(unknowns),
        ambiguities=tuple(ambiguities),
        entities=tuple(entities),
        success_criteria=tuple(success_criteria),
        assumptions=tuple(assumptions),
        preferences=tuple(preferences),
        research_mode=research_mode,
        requires_research=requires_research,
        requires_current_information=requires_current,
        notes=tuple(notes),
        rejected_fields=tuple(rejected),
        accepted=has_payload,
        source=source,
    )


def apply_task_advice(task: TaskModel, advice: TaskModelAdvice) -> TaskModel:
    """Merge validated advice into a copy — never clears owner fields."""
    if not advice.accepted:
        meta = dict(task.metadata or {})
        meta["task_advice"] = advice.public_dict()
        return replace(task, metadata=meta)

    def _merge(existing: list[str], extra: Sequence[str]) -> list[str]:
        out = list(existing)
        seen = {x.lower() for x in out}
        for item in extra:
            key = item.lower()
            if key not in seen:
                out.append(item)
                seen.add(key)
        return out[: max(len(existing) + _MAX_LIST_ITEMS, _MAX_LIST_ITEMS * 2)]

    research_mode = advice.research_mode or task.research_mode
    requires_research = (
        task.requires_research
        if advice.requires_research is None
        else (task.requires_research or advice.requires_research)
    )
    requires_current = (
        task.requires_current_information
        if advice.requires_current_information is None
        else (task.requires_current_information or advice.requires_current_information)
    )
    if requires_current:
        requires_research = True

    meta = dict(task.metadata or {})
    meta["task_advice"] = advice.public_dict()
    meta["neural_task_advice_applied"] = True

    return replace(
        task,
        unknowns=_merge(task.unknowns, advice.unknowns),
        ambiguities=_merge(task.ambiguities, advice.ambiguities),
        entities=_merge(task.entities, advice.entities),
        success_criteria=_merge(task.success_criteria, advice.success_criteria),
        assumptions=_merge(task.assumptions, advice.assumptions),
        preferences=_merge(task.preferences, advice.preferences),
        research_mode=research_mode,
        requires_research=requires_research,
        requires_external_information=task.requires_external_information or requires_research or requires_current,
        requires_current_information=requires_current,
        metadata=meta,
    )


def _parse_risk(value: Any, *, floor: RiskClass) -> RiskClass:
    try:
        risk = RiskClass(str(value).strip().upper())
    except ValueError:
        return floor
    if _RISK_ORDER[risk] < _RISK_ORDER[floor]:
        return floor
    return risk


def validate_plan_advice(
    raw_steps: Any,
    *,
    strategy: ReasoningStrategy,
    risk_floor: RiskClass,
    existing_step_ids: Sequence[str] | None = None,
    source: str = "advisor",
) -> PlanAdvice:
    """Validate advisory steps; reject free-form / incomplete proposals."""
    if not isinstance(raw_steps, (list, tuple)) or not raw_steps:
        return PlanAdvice(accepted=False, source=source, notes=("empty_steps",))

    known_ids = set(existing_step_ids or ())
    accepted_steps: list[PlanStep] = []
    rejected = 0
    notes: list[str] = [f"strategy={strategy.value}"]

    for index, item in enumerate(raw_steps):
        if len(accepted_steps) >= _MAX_ADVISORY_STEPS:
            rejected += len(raw_steps) - index
            notes.append("max_advisory_steps_reached")
            break
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        objective = _clip(str(item.get("objective") or ""))
        acceptance = _clip(str(item.get("acceptance_condition") or item.get("acceptance") or ""))
        if not objective or not acceptance:
            rejected += 1
            continue
        raw_id = str(item.get("step_id") or f"a{index + 1}").strip()
        # Advisory ids must not collide with template ids or inject odd paths.
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", raw_id):
            raw_id = f"a{index + 1}"
        if raw_id in known_ids:
            raw_id = f"a_{raw_id}_{index + 1}"
        deps_raw = item.get("dependencies") or ()
        if not isinstance(deps_raw, (list, tuple)):
            deps_raw = ()
        deps: list[str] = []
        for dep in deps_raw:
            dep_s = str(dep).strip()
            if dep_s in known_ids or dep_s in {s.step_id for s in accepted_steps}:
                deps.append(dep_s)
            # Unknown dependency → drop dep, keep step (bounded).
        caps_raw = item.get("likely_capabilities") or ()
        if not isinstance(caps_raw, (list, tuple)):
            caps_raw = ()
        caps = tuple(
            str(c).strip()
            for c in caps_raw
            if isinstance(c, str) and str(c).strip() in _ALLOWED_CAPABILITIES
        )[:6]
        risk = _parse_risk(item.get("risk_class"), floor=risk_floor)
        expected = _clip(str(item.get("expected_observation") or "advisory observation")) or None
        step = PlanStep(
            step_id=raw_id,
            objective=objective,
            dependencies=tuple(deps),
            expected_observation=expected,
            acceptance_condition=acceptance,
            likely_capabilities=caps,
            risk_class=risk,
            completion_criteria=(acceptance,),
            resource_estimate={"advisory": True},
        )
        accepted_steps.append(step)
        known_ids.add(raw_id)

    return PlanAdvice(
        steps=tuple(accepted_steps),
        notes=tuple(notes),
        rejected_count=rejected,
        accepted=bool(accepted_steps),
        source=source,
    )


def merge_plan_advice(plan: CognitivePlan, advice: PlanAdvice) -> CognitivePlan:
    """Append validated advisory steps; template steps stay first."""
    assumptions = list(plan.assumptions)
    assumptions.append(f"plan_advice_source:{advice.source}")
    assumptions.append(f"plan_advice_accepted:{advice.accepted}")
    if advice.rejected_count:
        assumptions.append(f"plan_advice_rejected_steps:{advice.rejected_count}")
    if not advice.accepted:
        plan.assumptions = assumptions
        return plan
    steps = list(plan.steps) + list(advice.steps)
    assumptions.append(f"advisory_steps_appended:{len(advice.steps)}")
    return CognitivePlan(
        plan_id=plan.plan_id,
        strategy=plan.strategy,
        steps=steps,
        assumptions=assumptions,
        stale=plan.stale,
        revision=plan.revision,
    )


class TaskAdvisor(Protocol):
    def advise_task(self, raw_request: str, base: TaskModel) -> Mapping[str, Any] | None: ...


class PlanAdvisor(Protocol):
    def advise_plan(
        self,
        task: TaskModel,
        *,
        strategy: ReasoningStrategy,
        base_steps: Sequence[PlanStep],
    ) -> Sequence[Mapping[str, Any]] | None: ...


@dataclass
class HeuristicTaskAdvisor:
    """Cheap semantic hints without inventing authority (no LLM required)."""

    source: str = "heuristic"

    def advise_task(self, raw_request: str, base: TaskModel) -> Mapping[str, Any] | None:
        text = (raw_request or "").strip()
        if not text:
            return None
        lowered = text.lower()
        advice: dict[str, Any] = {}
        # Quoted phrases → entity candidates
        entities = re.findall(r"\"([^\"]{2,64})\"|'([^']{2,64})'", text)
        flat = [a or b for a, b in entities]
        if flat:
            advice["entities"] = flat[:_MAX_LIST_ITEMS]
        if "?" in text and not base.unknowns:
            advice["unknowns"] = ["clarification may be needed for ambiguous ask"]
        if any(t in lowered for t in ("vs", "versus", "vergelijk", "compare")):
            advice["success_criteria"] = ["compare alternatives with explicit criteria"]
            advice["ambiguities"] = advice.get("ambiguities", []) + ["comparison dimensions may be underspecified"]
        if any(t in lowered for t in ("today", "latest", "current", "actueel")):
            advice["requires_current_information"] = True
            advice["requires_research"] = True
            advice["research_mode"] = "assisted" if base.research_mode == "none" else base.research_mode
        return advice or None


@dataclass
class HeuristicPlanAdvisor:
    """Propose bounded advisory steps from task signals (validated later)."""

    source: str = "heuristic"

    def advise_plan(
        self,
        task: TaskModel,
        *,
        strategy: ReasoningStrategy,
        base_steps: Sequence[PlanStep],
    ) -> Sequence[Mapping[str, Any]] | None:
        proposals: list[dict[str, Any]] = []
        base_ids = [s.step_id for s in base_steps]
        dep = base_ids[-1] if base_ids else None
        if task.requires_current_information or task.research_mode in {"assisted", "deep"}:
            proposals.append(
                {
                    "step_id": "a_freshness",
                    "objective": "Check freshness of sources before final answer",
                    "acceptance_condition": "freshness status recorded or UNMEASURED honest",
                    "expected_observation": "freshness note",
                    "dependencies": [dep] if dep else [],
                    "likely_capabilities": ["knowledge.search", "research.run"],
                    "risk_class": task.risk_class.value,
                }
            )
        if task.ambiguities:
            proposals.append(
                {
                    "step_id": "a_disambiguate",
                    "objective": "Record unresolved ambiguities explicitly",
                    "acceptance_condition": "ambiguities listed in public state",
                    "expected_observation": "ambiguity ledger",
                    "dependencies": [base_ids[0]] if base_ids else [],
                    "risk_class": "LOW",
                }
            )
        if strategy == ReasoningStrategy.COMPARE_ALTERNATIVES and len(proposals) < _MAX_ADVISORY_STEPS:
            proposals.append(
                {
                    "step_id": "a_compare_matrix",
                    "objective": "Build a short comparison matrix of candidates",
                    "acceptance_condition": "matrix with at least two options or honest shortage",
                    "expected_observation": "comparison matrix",
                    "dependencies": [dep] if dep else [],
                    "risk_class": task.risk_class.value,
                }
            )
        return proposals or None


@dataclass
class CallableTaskAdvisor:
    """Optional model-backed advisor: expects JSON object in public text."""

    model_caller: Any
    source: str = "model"

    def advise_task(self, raw_request: str, base: TaskModel) -> Mapping[str, Any] | None:
        if self.model_caller is None:
            return None
        prompt = (
            "Return ONLY a JSON object with optional keys: unknowns, ambiguities, "
            "entities, success_criteria, assumptions, preferences, research_mode, "
            "requires_research, requires_current_information. "
            "Do not include chain-of-thought. Do not set risk_class or hard_constraints."
        )
        try:
            result = self.model_caller(
                system_prompt=prompt,
                messages=[{"role": "user", "content": raw_request[:4000]}],
                role="planner",
                max_tokens=400,
            )
        except Exception:  # noqa: BLE001
            return None
        text = result[0] if isinstance(result, tuple) else (
            result.get("text") if isinstance(result, dict) else result
        )
        return _extract_json_object(str(text or ""))


@dataclass
class CallablePlanAdvisor:
    model_caller: Any
    source: str = "model"

    def advise_plan(
        self,
        task: TaskModel,
        *,
        strategy: ReasoningStrategy,
        base_steps: Sequence[PlanStep],
    ) -> Sequence[Mapping[str, Any]] | None:
        if self.model_caller is None:
            return None
        prompt = (
            "Return ONLY a JSON array of plan steps with keys objective, "
            "acceptance_condition, optional step_id, dependencies, "
            "likely_capabilities, risk_class, expected_observation. "
            "No chain-of-thought. Capabilities must be from a small allowlist."
        )
        payload = {
            "goal": task.goal,
            "strategy": strategy.value,
            "base_steps": [s.public_dict() for s in base_steps],
        }
        try:
            result = self.model_caller(
                system_prompt=prompt,
                messages=[{"role": "user", "content": json.dumps(payload)[:6000]}],
                role="planner",
                max_tokens=600,
            )
        except Exception:  # noqa: BLE001
            return None
        text = result[0] if isinstance(result, tuple) else (
            result.get("text") if isinstance(result, dict) else result
        )
        parsed = _extract_json_array(str(text or ""))
        return parsed


def _extract_json_object(text: str) -> Mapping[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _extract_json_array(text: str) -> list[Mapping[str, Any]] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, Mapping)]
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            return [x for x in data["steps"] if isinstance(x, Mapping)]
        return None
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, Mapping)]
        except json.JSONDecodeError:
            return None
    return None


@dataclass
class CompositeTaskAdvisor:
    advisors: tuple[Any, ...] = ()

    def advise_task(self, raw_request: str, base: TaskModel) -> Mapping[str, Any] | None:
        merged: dict[str, Any] = {}
        for advisor in self.advisors:
            if advisor is None:
                continue
            try:
                piece = advisor.advise_task(raw_request, base)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(piece, Mapping):
                continue
            for key, value in piece.items():
                if key in {
                    "unknowns",
                    "ambiguities",
                    "entities",
                    "success_criteria",
                    "assumptions",
                    "preferences",
                } and isinstance(value, list):
                    merged.setdefault(key, [])
                    merged[key] = list(merged[key]) + list(value)
                else:
                    merged[key] = value
        return merged or None


@dataclass
class CompositePlanAdvisor:
    advisors: tuple[Any, ...] = ()

    def advise_plan(
        self,
        task: TaskModel,
        *,
        strategy: ReasoningStrategy,
        base_steps: Sequence[PlanStep],
    ) -> Sequence[Mapping[str, Any]] | None:
        out: list[Mapping[str, Any]] = []
        for advisor in self.advisors:
            if advisor is None:
                continue
            try:
                piece = advisor.advise_plan(task, strategy=strategy, base_steps=base_steps)
            except Exception:  # noqa: BLE001
                continue
            if not piece:
                continue
            out.extend(list(piece))
        return out or None
