"""Strategy lifecycle and the sealed-holdout gate.

A strategy moves through fixed states and can only move forward on evidence produced by
someone other than its author:

    draft -> researched -> validated -> paper -> retired
                    \\-> rejected

The rules that are enforced rather than suggested:

- promotion to ``validated`` requires an :class:`EvaluationReport` with verdict ``pass`` that
  was written by an independent evaluator role, not by the researcher agent;
- the sealed test split may be touched **once** per strategy version. The second attempt is
  refused, because a holdout you can retry is just another validation set;
- a strategy that changes in any way that alters its content hash starts a new version and
  loses the evidence attached to the old one;
- promotion to ``paper`` records that everything before it was historical simulation; the
  paper track then collects prospective evidence, which is a different, stronger class.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from trading_lab.contracts import EvaluationReport, StrategySpec, utc_iso

LIFECYCLE_STATES = ("draft", "researched", "validated", "paper", "retired", "rejected")

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("researched", "rejected"),
    "researched": ("validated", "rejected", "draft"),
    "validated": ("paper", "rejected", "retired"),
    "paper": ("retired", "rejected"),
    "retired": ("draft",),
    "rejected": ("draft",),
}


class PromotionRefused(RuntimeError):
    pass


class HoldoutExhausted(RuntimeError):
    pass


@dataclass
class PromotionRequest:
    strategy_id: str
    version: int
    target_state: str
    requested_by: str
    evaluation_report_id: str | None = None
    justification: str = ""


class StrategyRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store

    # --- lifecycle ---------------------------------------------------------------

    def create(self, spec: StrategySpec, *, created_by: str = "operator") -> dict[str, Any]:
        if spec.hypothesis is None:
            raise ValueError(
                "strategy_requires_hypothesis: economic rationale, regimes, benchmarks and at least one "
                "falsification criterion must exist before any result can be interpreted"
            )
        strategy_id = self.store.create_strategy(
            name=spec.name,
            family=spec.family,
            hypothesis=spec.hypothesis,
            created_by=created_by,
            scope_note=spec.scope_note,
            status="draft",
        )
        self.store.add_strategy_version(
            strategy_id,
            spec.model_copy(update={"strategy_id": strategy_id}),
            created_by=created_by,
        )
        return self.store.get_strategy(strategy_id) or {"strategy_id": strategy_id}

    def add_version(self, strategy_id: str, spec: StrategySpec, *, created_by: str = "operator") -> int:
        current = self.store.get_strategy(strategy_id)
        if current is None:
            raise ValueError(f"unknown_strategy:{strategy_id}")
        version = self.store.add_strategy_version(strategy_id, spec, created_by=created_by)
        if current.get("status") in {"validated", "paper"}:
            self.store.set_strategy_status(
                strategy_id,
                "draft",
                actor=created_by,
                reason=(
                    f"version {version} changed the strategy definition; evidence for the previous version "
                    "does not transfer"
                ),
            )
        return version

    def transition(self, request: PromotionRequest) -> dict[str, Any]:
        strategy = self.store.get_strategy(request.strategy_id)
        if strategy is None:
            raise ValueError(f"unknown_strategy:{request.strategy_id}")
        current = str(strategy.get("status", "draft"))
        target = request.target_state
        if target not in LIFECYCLE_STATES:
            raise ValueError(f"unknown_state:{target}")
        if target not in ALLOWED_TRANSITIONS.get(current, ()):
            raise PromotionRefused(f"transition_not_allowed:{current}->{target}")

        if target == "validated":
            self._require_independent_pass(request, strategy)
        if target == "paper":
            if current != "validated":
                raise PromotionRefused("paper_requires_validated_state")

        return self.store.set_strategy_status(
            request.strategy_id,
            target,
            actor=request.requested_by,
            actor_role="independent_validator" if target == "validated" else "operator",
            report_id=request.evaluation_report_id,
            reason=request.justification or f"promoted to {target}",
        ) or {}

    def _require_independent_pass(self, request: PromotionRequest, strategy: dict[str, Any]) -> None:
        if not request.evaluation_report_id:
            raise PromotionRefused("validated_requires_evaluation_report")
        report = self.store.get_evaluation(request.evaluation_report_id)
        if report is None:
            raise PromotionRefused(f"unknown_evaluation_report:{request.evaluation_report_id}")
        if report.get("strategy_id") != request.strategy_id:
            raise PromotionRefused("evaluation_report_belongs_to_a_different_strategy")
        if int(report.get("strategy_version", 0)) != int(request.version):
            raise PromotionRefused(
                f"evaluation covers version {report.get('strategy_version')}, promotion asks for version {request.version}"
            )
        if report.get("verdict") != "pass":
            raise PromotionRefused(f"evaluation_verdict_is_{report.get('verdict')}")
        if report.get("evaluator_role") != "independent_validator":
            raise PromotionRefused("evaluation_was_not_produced_by_an_independent_validator")
        if report.get("evaluated_by") == strategy.get("created_by"):
            raise PromotionRefused(
                "the evaluator is the same actor that authored the strategy; independence is a hard requirement"
            )

    # --- holdout gate ------------------------------------------------------------

    def holdout_available(self, strategy_id: str, version: int) -> tuple[bool, str]:
        usages = self.store.holdout_usage(strategy_id, "sealed_test")
        for usage in usages:
            if int(usage.get("strategy_version", -1)) == int(version):
                return False, (
                    f"sealed_test already used for version {version} on {usage.get('created_at')} by "
                    f"{usage.get('actor')}. A holdout is single-use by construction; create a new version "
                    "or accept the recorded result."
                )
        return True, "sealed test available for this version"

    def consume_holdout(
        self,
        *,
        strategy_id: str,
        version: int,
        used_by: str,
        report_id: str,
        purpose: str = "final_confirmation",
    ) -> dict[str, Any]:
        available, reason = self.holdout_available(strategy_id, version)
        if not available:
            raise HoldoutExhausted(reason)
        return self.store.record_holdout_usage(
            strategy_id=strategy_id,
            strategy_version=version,
            split="sealed_test",
            actor=used_by,
            report_id=report_id,
            reason=purpose,
        )

    # --- reporting ---------------------------------------------------------------

    def evidence(self, strategy_id: str) -> dict[str, Any]:
        strategy = self.store.get_strategy(strategy_id)
        if strategy is None:
            raise ValueError(f"unknown_strategy:{strategy_id}")
        evaluations = self.store.list_evaluations(strategy_id=strategy_id, limit=50)
        holdouts = self.store.holdout_usage(strategy_id)
        classes = {report.get("evidence_class") for report in evaluations}
        return {
            "strategy": strategy,
            "evaluations": evaluations,
            "holdout_usage": holdouts,
            "evidence_classes_present": sorted(item for item in classes if item),
            "strongest_evidence": self._strongest(evaluations),
            "next_step": self._next_step(strategy, evaluations),
        }

    @staticmethod
    def _strongest(evaluations: Sequence[dict[str, Any]]) -> str:
        order = [
            "code_present",
            "static_review",
            "executed_test",
            "historical_evaluation",
            "prospective_paper_evaluation",
        ]
        best = "code_present"
        for report in evaluations:
            candidate = str(report.get("evidence_class", "code_present"))
            if candidate in order and order.index(candidate) > order.index(best):
                best = candidate
        return best

    @staticmethod
    def _next_step(strategy: dict[str, Any], evaluations: Sequence[dict[str, Any]]) -> str:
        status = str(strategy.get("status", "draft"))
        if status == "draft":
            return "run a bounded search on the development split, then request validation"
        if status == "researched":
            passing = [report for report in evaluations if report.get("verdict") == "pass"]
            if not passing:
                return "an independent walk-forward evaluation on the validation split is required"
            return "request promotion to validated, citing the passing report"
        if status == "validated":
            return "optionally consume the single sealed-test run, then start prospective paper evaluation"
        if status == "paper":
            return "collect prospective paper evidence; historical results alone do not upgrade the evidence class"
        return "no action"

    def summary(self) -> dict[str, Any]:
        strategies = self.store.list_strategies(limit=500)
        counts: dict[str, int] = {state: 0 for state in LIFECYCLE_STATES}
        for strategy in strategies:
            counts[str(strategy.get("status", "draft"))] = counts.get(str(strategy.get("status", "draft")), 0) + 1
        return {"counts": counts, "total": len(strategies), "states": list(LIFECYCLE_STATES)}


def evidence_class_for(report: EvaluationReport, *, mode: str) -> str:
    """Paper runs produce prospective evidence; everything else is historical simulation."""
    if mode == "paper":
        return "prospective_paper_evaluation"
    return report.evidence_class


def promotion_audit_entry(request: PromotionRequest, outcome: str, detail: str = "") -> dict[str, Any]:
    return {
        "at": utc_iso(datetime.now(tz=UTC)),
        "strategy_id": request.strategy_id,
        "version": request.version,
        "target_state": request.target_state,
        "requested_by": request.requested_by,
        "evaluation_report_id": request.evaluation_report_id,
        "outcome": outcome,
        "detail": detail,
    }


__all__ = [
    "ALLOWED_TRANSITIONS",
    "HoldoutExhausted",
    "LIFECYCLE_STATES",
    "PromotionRefused",
    "PromotionRequest",
    "StrategyRegistry",
    "evidence_class_for",
    "promotion_audit_entry",
]
