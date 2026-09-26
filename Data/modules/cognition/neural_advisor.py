"""Neural task understanding advisor (W5).

Produces structured TaskAdvice. Heuristics remain as labeled fallback —
never silently pretend to be neural when the model path is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .task_model import TaskModel, TaskModelBuilder
from .types import RiskClass


@dataclass(frozen=True)
class TaskAdvice:
    task_type: str
    domain: str
    freshness: str  # none | preferred | required
    required_tools: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    risk: str = "LOW"
    ambiguity: float = 0.0
    language: str = "auto"
    research_need: str = "none"  # none | light | deep
    verification_need: str = "none"  # none | light | required
    source: str = "heuristic_fallback"  # neural | heuristic_fallback
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "domain": self.domain,
            "freshness": self.freshness,
            "required_tools": list(self.required_tools),
            "required_evidence": list(self.required_evidence),
            "risk": self.risk,
            "ambiguity": self.ambiguity,
            "language": self.language,
            "research_need": self.research_need,
            "verification_need": self.verification_need,
            "source": self.source,
            "notes": list(self.notes),
            "truth": {
                "fallback_is_labeled": self.source == "heuristic_fallback",
                "advice_is_not_authority": True,
            },
        }


ModelAdvisorCaller = Callable[..., Any]


class NeuralTaskModelAdvisor:
    """Prefer schema-constrained neural advice; fall back to TaskModelBuilder heuristics."""

    def __init__(
        self,
        *,
        model_caller: ModelAdvisorCaller | None = None,
        builder: TaskModelBuilder | None = None,
    ) -> None:
        self.model_caller = model_caller
        self.builder = builder or TaskModelBuilder()

    def advise(self, message: str, *, metadata: dict[str, Any] | None = None) -> TaskAdvice:
        if self.model_caller is not None:
            try:
                neural = self._neural_advise(message, metadata=metadata)
                if neural is not None:
                    return neural
            except Exception:  # noqa: BLE001 — fall through to labeled heuristic
                pass
        return self._heuristic_advise(message, metadata=metadata)

    def apply_to_task(self, task: TaskModel, advice: TaskAdvice) -> TaskModel:
        """Merge advice into task metadata without inventing authority."""
        meta = dict(task.metadata or {})
        meta["task_advice"] = advice.public_dict()
        if advice.source == "neural":
            # Neural may refine labels when heuristic was uncertain.
            if advice.ambiguity >= 0.4 or meta.get("allow_neural_task_override"):
                task.task_type = advice.task_type or task.task_type
                task.domain = advice.domain or task.domain
                if advice.research_need != "none":
                    task.requires_research = True
                    task.research_mode = advice.research_need
                if advice.freshness == "required":
                    task.requires_current_information = True
                if advice.verification_need == "required":
                    task.verification_mode = "REQUIRED"
                try:
                    task.risk_class = RiskClass(advice.risk)
                except ValueError:
                    pass
        task.metadata = meta
        return task

    def _heuristic_advise(
        self, message: str, *, metadata: dict[str, Any] | None
    ) -> TaskAdvice:
        task = self.builder.build(message, metadata=metadata)
        freshness = "none"
        if getattr(task, "requires_current_information", False):
            freshness = "required"
        research = getattr(task, "research_mode", "none") or "none"
        verification = "none"
        if getattr(task, "verification_mode", None) in {"REQUIRED", "CORROBORATED"}:
            verification = "required"
        elif task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}:
            verification = "light"
        tools: list[str] = []
        if getattr(task, "requires_tools", False) or getattr(task, "needs_calculation", False):
            tools.append("tools")
        if task.domain == "coding":
            tools.append("coding")
        if research != "none":
            tools.append("research")
        return TaskAdvice(
            task_type=task.task_type,
            domain=task.domain,
            freshness=freshness,
            required_tools=tuple(tools),
            required_evidence=("sources",) if research != "none" else (),
            risk=task.risk_class.value,
            ambiguity=float(task.initial_uncertainty),
            language=str((metadata or {}).get("response_language") or "auto"),
            research_need=str(research),
            verification_need=verification,
            source="heuristic_fallback",
            notes=("labeled heuristic fallback — neural advisor unavailable or failed",),
        )

    def _neural_advise(
        self, message: str, *, metadata: dict[str, Any] | None
    ) -> TaskAdvice | None:
        schema = {
            "type": "object",
            "required": [
                "task_type",
                "domain",
                "freshness",
                "risk",
                "ambiguity",
                "research_need",
                "verification_need",
            ],
        }
        prompt = (
            "Classify the user task. Reply with ONLY JSON matching keys: "
            "task_type, domain, freshness (none|preferred|required), "
            "required_tools (array), required_evidence (array), risk (LOW|MEDIUM|HIGH|CRITICAL), "
            "ambiguity (0..1), language, research_need (none|light|deep), "
            "verification_need (none|light|required).\n\n"
            f"USER:\n{message}"
        )
        raw = self.model_caller(
            system_prompt="You are a task classifier. Output JSON only.",
            messages=[{"role": "user", "content": prompt}],
            role="task_advisor",
            response_format={"type": "json_object"},
            max_tokens=256,
        )
        text = raw.get("text") if isinstance(raw, dict) else raw
        if not text:
            return None
        try:
            data = json.loads(str(text)[str(text).find("{") : str(text).rfind("}") + 1])
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(data, dict) or "task_type" not in data:
            return None
        _ = schema  # documented contract
        return TaskAdvice(
            task_type=str(data.get("task_type") or "general"),
            domain=str(data.get("domain") or "general"),
            freshness=str(data.get("freshness") or "none"),
            required_tools=tuple(str(t) for t in (data.get("required_tools") or [])),
            required_evidence=tuple(str(t) for t in (data.get("required_evidence") or [])),
            risk=str(data.get("risk") or "LOW"),
            ambiguity=float(data.get("ambiguity") or 0.0),
            language=str(data.get("language") or (metadata or {}).get("response_language") or "auto"),
            research_need=str(data.get("research_need") or "none"),
            verification_need=str(data.get("verification_need") or "none"),
            source="neural",
            notes=("schema-constrained neural task advice",),
        )
