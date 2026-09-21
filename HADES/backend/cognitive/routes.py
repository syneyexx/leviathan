"""HTTP surface for Cognitive Runtime observability (One Brain)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .modes import CognitiveMode, parse_mode
from .runtime import get_cognitive_runtime


class ModeUpdate(BaseModel):
    pillar: str = Field(min_length=1, max_length=64)
    mode: str = Field(min_length=2, max_length=16)


class EpistemicInput(BaseModel):
    signals: dict[str, Any] = Field(default_factory=dict)


class HomeostasisInput(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict)


class PerceptionInput(BaseModel):
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    belief_state: dict[str, Any] | None = None
    uncertainties: list[dict[str, Any]] | None = None
    known_evidence_text: str = ""
    acceptance_satisfied: bool = False


class ImmuneInput(BaseModel):
    text: str = Field(default="", max_length=100_000)
    artifact_kind: str = "memory"
    trust_category: str = "untrusted_source"
    provenance: dict[str, Any] | None = None
    allow_memory: bool = False
    allow_training: bool = False
    allow_neural_slow: bool = False
    allow_skill_promotion: bool = False


class ConceptInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=2000)
    supporting_examples: list[Any] = Field(default_factory=list)
    counterexamples: list[Any] | None = None
    relations: list[dict[str, Any]] | None = None
    scope: str = "general"


class CreditInput(BaseModel):
    outcome_ref: str = Field(min_length=1, max_length=200)
    attributions: list[dict[str, Any]] = Field(default_factory=list)


class HypothesisInput(BaseModel):
    claim: str = Field(min_length=1, max_length=2000)
    scope: str = "general"
    predicted_outcome: str = ""
    falsification_criterion: str = Field(min_length=1, max_length=2000)
    required_evidence: list[str] | None = None
    experiment: dict[str, Any] | None = None
    confounders: list[str] | None = None


class ABInput(BaseModel):
    claim: str = Field(min_length=1, max_length=2000)
    scope: str = "general"
    falsification_criterion: str = Field(min_length=1, max_length=2000)
    control_metrics: dict[str, float]
    treatment_metrics: dict[str, float]
    primary_metric: str = "score"
    higher_is_better: bool = True


class TickInput(BaseModel):
    metrics: dict[str, Any] | None = None
    epistemic_signals: dict[str, Any] | None = None
    perception_candidates: list[dict[str, Any]] | None = None


def mount_cognitive_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/cognitive", tags=["cognitive"])

    def runtime():
        db_path = ctx.get("db_path")
        if db_path is None:
            database = ctx.get("database")
            if database is not None and hasattr(database, "path"):
                db_path = database.path
        return get_cognitive_runtime(db_path)

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        return runtime().overview()

    @router.get("/self-model")
    def self_model() -> dict[str, Any]:
        return runtime().self_model()

    @router.post("/modes")
    def set_mode(payload: ModeUpdate) -> dict[str, Any]:
        rt = runtime()
        rt.set_mode(payload.pillar, payload.mode)
        return {"pillar": payload.pillar, "mode": rt.mode_for(payload.pillar).value}

    @router.post("/epistemic")
    def epistemic(payload: EpistemicInput) -> dict[str, Any]:
        return runtime().epistemic(payload.signals)

    @router.post("/homeostasis")
    def homeostasis(payload: HomeostasisInput) -> dict[str, Any]:
        return runtime().homeostasis(payload.metrics)

    @router.post("/perception")
    def perception(payload: PerceptionInput) -> dict[str, Any]:
        return runtime().perceive(
            candidates=payload.candidates,
            belief_state=payload.belief_state,
            uncertainties=payload.uncertainties,
            known_evidence_text=payload.known_evidence_text,
            acceptance_satisfied=payload.acceptance_satisfied,
        )

    @router.post("/immune/scan")
    def immune_scan(payload: ImmuneInput) -> dict[str, Any]:
        return runtime().immune_scan(
            text=payload.text,
            artifact_kind=payload.artifact_kind,
            trust_category=payload.trust_category,
            provenance=payload.provenance,
            allow_memory=payload.allow_memory,
            allow_training=payload.allow_training,
            allow_neural_slow=payload.allow_neural_slow,
            allow_skill_promotion=payload.allow_skill_promotion,
        )

    @router.get("/immune/quarantine")
    def quarantine_list(limit: int = 50) -> dict[str, Any]:
        rt = runtime()
        items = rt.store.list_quarantine(limit=limit) if rt.store else []
        return {"items": items}

    @router.post("/ontology/concepts")
    def form_concept(payload: ConceptInput) -> dict[str, Any]:
        return runtime().form_concept(
            name=payload.name,
            definition=payload.definition,
            supporting_examples=payload.supporting_examples,
            counterexamples=payload.counterexamples,
            relations=payload.relations,
            scope=payload.scope,
        )

    @router.get("/ontology/concepts")
    def list_concepts(status: str | None = None, limit: int = 50) -> dict[str, Any]:
        rt = runtime()
        items = rt.store.list_concepts(status=status, limit=limit) if rt.store else []
        return {"items": items}

    @router.post("/credit")
    def credit(payload: CreditInput) -> dict[str, Any]:
        return runtime().assign_credit(outcome_ref=payload.outcome_ref, attributions=payload.attributions)

    @router.post("/science/hypotheses")
    def create_hypothesis(payload: HypothesisInput) -> dict[str, Any]:
        return runtime().create_hypothesis(
            claim=payload.claim,
            scope=payload.scope,
            predicted_outcome=payload.predicted_outcome,
            falsification_criterion=payload.falsification_criterion,
            required_evidence=payload.required_evidence,
            experiment=payload.experiment,
            confounders=payload.confounders,
        )

    @router.post("/science/ab")
    def run_ab(payload: ABInput) -> dict[str, Any]:
        return runtime().run_ab(
            claim=payload.claim,
            scope=payload.scope,
            falsification_criterion=payload.falsification_criterion,
            control_metrics=payload.control_metrics,
            treatment_metrics=payload.treatment_metrics,
            primary_metric=payload.primary_metric,
            higher_is_better=payload.higher_is_better,
        )

    @router.post("/repair/fixture")
    def repair_fixture() -> dict[str, Any]:
        return runtime().repair_fixture()

    @router.post("/tick")
    def tick(payload: TickInput) -> dict[str, Any]:
        return runtime().tick(
            metrics=payload.metrics,
            epistemic_signals=payload.epistemic_signals,
            perception_candidates=payload.perception_candidates,
        )

    return router
