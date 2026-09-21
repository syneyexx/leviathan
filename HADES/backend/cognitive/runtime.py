"""Cognitive Runtime façade — One Brain integration of all ten pillars.

Does not create a second Brain. Domain runtimes keep proof ownership.
Adaptive influence defaults conservatively (OFF/SHADOW).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import credit as credit_mod
from . import epistemic as epistemic_mod
from . import homeostasis as homeostasis_mod
from . import immune as immune_mod
from . import mental_models as mental_mod
from . import ontology as ontology_mod
from . import perception as perception_mod
from . import scientific_method as science_mod
from . import self_model as self_model_mod
from . import self_repair as repair_mod
from .contracts import CONTROLLER_VERSION, AdaptiveDecision, utc_now
from .modes import (
    DEFAULT_MODE,
    PILLAR_DEFAULT_MODES,
    CognitiveMode,
    mode_allows_influence,
    parse_mode,
)
from .store import CognitiveStore


class CognitiveRuntime:
    """Process-local cognitive runtime coordinating the ten pillars."""

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        store: CognitiveStore | None = None,
        modes: dict[str, CognitiveMode] | None = None,
    ) -> None:
        self.store = store
        if self.store is None and db_path is not None:
            self.store = CognitiveStore(db_path)
        self.modes: dict[str, CognitiveMode] = dict(PILLAR_DEFAULT_MODES)
        if modes:
            for key, value in modes.items():
                self.modes[key] = parse_mode(value, default=self.modes.get(key, DEFAULT_MODE))
        self._last_self_model: dict[str, Any] | None = None

    def set_mode(self, pillar: str, mode: CognitiveMode | str) -> None:
        self.modes[pillar] = parse_mode(mode, default=self.modes.get(pillar, DEFAULT_MODE))

    def mode_for(self, pillar: str) -> CognitiveMode:
        return self.modes.get(pillar, DEFAULT_MODE)

    # --- Wave A --------------------------------------------------------------------

    def self_model(self, **kwargs: Any) -> dict[str, Any]:
        snap = self_model_mod.build_self_model(**kwargs)
        self._last_self_model = snap
        if self.store is not None:
            self.store.append_decision(snap["decision"])
        return snap

    def epistemic(self, signals: dict[str, Any]) -> dict[str, Any]:
        result = epistemic_mod.epistemic_step(signals, mode=self.mode_for("epistemic"))
        if self.store is not None:
            self.store.append_decision(result["decision"])
        return result

    def homeostasis(self, metrics: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        result = homeostasis_mod.assess_homeostasis(
            metrics,
            mode=self.mode_for("homeostasis"),
            store=self.store,
            **kwargs,
        )
        if self.store is not None:
            self.store.append_decision(result["decision"])
        return result

    # --- Wave B --------------------------------------------------------------------

    def perceive(self, **kwargs: Any) -> dict[str, Any]:
        result = perception_mod.select_observation(mode=self.mode_for("perception"), **kwargs)
        if self.store is not None:
            self.store.append_decision(result["decision"])
        return result

    def immune_scan(self, **kwargs: Any) -> dict[str, Any]:
        result = immune_mod.admit_or_quarantine(self.store, **kwargs)
        if self.store is not None:
            self.store.append_decision(result["decision"])
        return result

    # --- Wave C --------------------------------------------------------------------

    def form_concept(self, **kwargs: Any) -> dict[str, Any]:
        result = ontology_mod.propose_concept(self.store, mode=self.mode_for("ontology"), **kwargs)
        if self.store is not None and result.get("decision"):
            self.store.append_decision(result["decision"])
        return result

    def promote_concept(self, **kwargs: Any) -> dict[str, Any]:
        return ontology_mod.evaluate_and_promote(self.store, mode=self.mode_for("ontology"), **kwargs)

    def update_agent_model(self, **kwargs: Any) -> dict[str, Any]:
        result = mental_mod.update_agent_model(self.store, mode=self.mode_for("mental_models"), **kwargs)
        if self.store is not None:
            self.store.append_decision(result["decision"])
        return result

    def rank_agents(self, **kwargs: Any) -> dict[str, Any]:
        return mental_mod.rank_agents_for_task(self.store, **kwargs)

    def user_model(self, **kwargs: Any) -> dict[str, Any]:
        return mental_mod.build_user_model(**kwargs)

    def assign_credit(self, **kwargs: Any) -> dict[str, Any]:
        result = credit_mod.assign_credit(self.store, mode=self.mode_for("credit"), **kwargs)
        if self.store is not None:
            self.store.append_decision(result["decision"])
        return result

    # --- Wave D --------------------------------------------------------------------

    def create_hypothesis(self, **kwargs: Any) -> dict[str, Any]:
        return science_mod.create_hypothesis(self.store, mode=self.mode_for("scientific_method"), **kwargs)

    def run_ab(self, **kwargs: Any) -> dict[str, Any]:
        return science_mod.run_controlled_ab(self.store, mode=self.mode_for("scientific_method"), **kwargs)

    def diagnose(self, **kwargs: Any) -> dict[str, Any]:
        return repair_mod.diagnose(self_model=self._last_self_model, **kwargs)

    def propose_repair(self, **kwargs: Any) -> dict[str, Any]:
        return repair_mod.propose_repair(self.store, mode=self.mode_for("self_repair"), **kwargs)

    def repair_fixture(self) -> dict[str, Any]:
        # Fixture may run in SHADOW for observability even when default is OFF
        mode = self.mode_for("self_repair")
        if mode is CognitiveMode.OFF:
            mode = CognitiveMode.SHADOW
        return repair_mod.run_controlled_repair_fixture(self.store, mode=mode)

    # --- Integration loop ----------------------------------------------------------

    def tick(
        self,
        *,
        metrics: dict[str, Any] | None = None,
        epistemic_signals: dict[str, Any] | None = None,
        perception_candidates: list[dict[str, Any]] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One coherent observe→know→act cognitive cycle (bounded, policy-safe)."""
        snap = self.self_model(**(extras or {}))
        homeo = self.homeostasis(metrics or {})
        epist = self.epistemic(epistemic_signals or {"unknown_runtime_state": False})
        perception = None
        if perception_candidates:
            # If homeostasis says bound retrieval, shrink candidates
            cands = list(perception_candidates)
            if any(a.get("action") == "bound_retrieval" for a in homeo.get("applied_actions") or []):
                cands = cands[:1]
            perception = self.perceive(
                candidates=cands,
                uncertainties=epist.get("states") or [],
                budget_pool=(metrics or {}).get("budget_pool"),
            )
        loop = {
            "version": CONTROLLER_VERSION,
            "generated_at": utc_now(),
            "self_model": {
                "counts_by_status": snap.get("counts_by_status"),
                "routing_hints": snap.get("routing_hints"),
            },
            "homeostasis": {
                "healthy": homeo.get("healthy"),
                "applied_actions": homeo.get("applied_actions"),
                "decision": homeo.get("decision"),
            },
            "epistemic": {
                "primary_action": epist.get("primary_action"),
                "ask_user": epist.get("ask_user"),
                "decision": epist.get("decision"),
            },
            "perception": perception,
            "modes": {k: v.value for k, v in self.modes.items()},
            "decision": AdaptiveDecision(
                controller="cognitive.runtime",
                decision="tick",
                reason_code="INTEGRATED_CYCLE",
                mode="active",
            ).to_dict(),
        }
        return loop

    def overview(self) -> dict[str, Any]:
        return {
            "brain": "hades.one",
            "cognitive_runtime": CONTROLLER_VERSION,
            "monolith": False,
            "pillars": {
                "self_model": "present",
                "perception": "present",
                "epistemic": "present",
                "ontology": "present",
                "immune": "present",
                "mental_models": "present",
                "homeostasis": "present",
                "self_repair": "present",
                "scientific_method": "present",
                "credit": "present",
            },
            "modes": {k: v.value for k, v in self.modes.items()},
            "store": str(self.store.path) if self.store else None,
            "authority": "recommend_only — policy/permissions remain deterministic",
        }


_RUNTIME: CognitiveRuntime | None = None


def get_cognitive_runtime(
    db_path: str | Path | None = None,
    **kwargs: Any,
) -> CognitiveRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = CognitiveRuntime(db_path=db_path, **kwargs)
    elif db_path is not None and _RUNTIME.store is None:
        _RUNTIME.store = CognitiveStore(db_path)
    return _RUNTIME


def reset_cognitive_runtime() -> None:
    global _RUNTIME
    _RUNTIME = None
