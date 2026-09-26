"""Strategy learning domain types — immutable objectives, run state, candidates."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.common.hashing import sha256_text


LEARNING_ALGORITHM = "adaptive_evolutionary_strategy_search"
LEARNING_ALGORITHM_VERSION = "1.0.0"


class LearningStage(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    TRAIN = "TRAIN"
    VALIDATING = "VALIDATING"
    ROBUSTNESS = "ROBUSTNESS"
    SEALED_EVALUATION = "SEALED_EVALUATION"
    QUALIFIED_STRATEGY_FOUND = "QUALIFIED_STRATEGY_FOUND"
    NO_STRATEGY_QUALIFIED = "NO_STRATEGY_QUALIFIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LearningRunStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProposalMethod(str, Enum):
    SEED = "SEED"
    ELITE = "ELITE"
    MUTATION = "MUTATION"
    CROSSOVER = "CROSSOVER"
    EXPLORATION = "EXPLORATION"
    AGENT_PROPOSED = "AGENT_PROPOSED"


class FailureCategory(str, Enum):
    INVALID_SPEC = "INVALID_SPEC"
    INSUFFICIENT_TRADES = "INSUFFICIENT_TRADES"
    EXCESSIVE_DRAWDOWN = "EXCESSIVE_DRAWDOWN"
    NEGATIVE_RETURN = "NEGATIVE_RETURN"
    HIGH_COST_SENSITIVITY = "HIGH_COST_SENSITIVITY"
    VALIDATION_COLLAPSE = "VALIDATION_COLLAPSE"
    REGIME_BRITTLE = "REGIME_BRITTLE"
    HIGH_COMPLEXITY = "HIGH_COMPLEXITY"
    INCOMPATIBLE_RUNTIME = "INCOMPATIBLE_RUNTIME"
    MISSING_FEATURE = "MISSING_FEATURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    POLICY_LOAD_FAILED = "POLICY_LOAD_FAILED"
    UNKNOWN = "UNKNOWN"


class MeasurementStatus(str, Enum):
    MEASURED = "MEASURED"
    UNMEASURED = "UNMEASURED"
    INVALID = "INVALID"


SUPPORTED_STRATEGY_FAMILIES = (
    "ma_cross",
    "mean_reversion",
    "breakout",
    "rsi",
    "feature_compare",
    "composite",
)


@dataclass(frozen=True)
class LearningObjectiveSpec:
    """Immutable pre-registered learning objective — never mutated after binding."""

    objective_id: str
    version: str = "1"
    primary_objectives: tuple[str, ...] = ("risk_adjusted_return", "drawdown_quality")
    secondary_objectives: tuple[str, ...] = ("trade_sufficiency", "stability")
    constraints: dict[str, Any] = field(default_factory=dict)
    min_trades: int = 5
    max_drawdown_pct: float = 25.0
    min_validation_coverage: float = 0.0
    fitness_components: tuple[str, ...] = (
        "return_quality",
        "risk_adjusted_return",
        "drawdown_quality",
        "stability",
        "regime_robustness",
        "validation_stability",
        "trade_sufficiency",
        "execution_cost_quality",
        "turnover_quality",
        "concentration_quality",
        "complexity_quality",
    )
    fitness_weights: dict[str, float] = field(
        default_factory=lambda: {
            "return_quality": 0.20,
            "risk_adjusted_return": 0.20,
            "drawdown_quality": 0.20,
            "stability": 0.10,
            "trade_sufficiency": 0.10,
            "execution_cost_quality": 0.05,
            "turnover_quality": 0.05,
            "complexity_quality": 0.10,
        }
    )
    turnover_penalty: float = 0.05
    cost_penalty: float = 0.05
    instability_penalty: float = 0.1
    concentration_penalty: float = 0.05
    complexity_penalty: float = 0.1
    selection_method: str = "rank_weighted_elitism"
    early_stop_rules: dict[str, Any] = field(
        default_factory=lambda: {
            "no_improvement_generations": 3,
            "diversity_collapse_min": 0.05,
            "stop_on_qualified": True,
        }
    )
    generation_budget: int = 8
    trial_budget: int = 96
    population_size: int = 12
    elite_count: int = 3
    exploration_rate: float = 0.15
    mutation_rate: float = 0.35
    crossover_rate: float = 0.25
    seed: int = 42
    require_val_pass: bool = True
    require_robustness_pass: bool = True
    require_sealed_pass: bool = True
    max_episode_bars: int | None = None
    universe: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "version": self.version,
            "primary_objectives": list(self.primary_objectives),
            "secondary_objectives": list(self.secondary_objectives),
            "constraints": dict(self.constraints),
            "min_trades": self.min_trades,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_validation_coverage": self.min_validation_coverage,
            "fitness_components": list(self.fitness_components),
            "fitness_weights": dict(self.fitness_weights),
            "turnover_penalty": self.turnover_penalty,
            "cost_penalty": self.cost_penalty,
            "instability_penalty": self.instability_penalty,
            "concentration_penalty": self.concentration_penalty,
            "complexity_penalty": self.complexity_penalty,
            "selection_method": self.selection_method,
            "early_stop_rules": dict(self.early_stop_rules),
            "generation_budget": self.generation_budget,
            "trial_budget": self.trial_budget,
            "population_size": self.population_size,
            "elite_count": self.elite_count,
            "exploration_rate": self.exploration_rate,
            "mutation_rate": self.mutation_rate,
            "crossover_rate": self.crossover_rate,
            "seed": self.seed,
            "require_val_pass": self.require_val_pass,
            "require_robustness_pass": self.require_robustness_pass,
            "require_sealed_pass": self.require_sealed_pass,
            "max_episode_bars": self.max_episode_bars,
            "universe": list(self.universe),
            "metadata": dict(self.metadata),
        }

    def objective_hash(self) -> str:
        return sha256_text(json.dumps(self.content_dict(), sort_keys=True, separators=(",", ":")))

    def public_dict(self) -> dict[str, Any]:
        d = self.content_dict()
        d["objective_hash"] = self.objective_hash()
        d["truth"] = {
            "immutable_pre_registered": True,
            "must_not_relax_thresholds": True,
            "missing_metric_is_not_pass": True,
        }
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "LearningObjectiveSpec":
        raw = dict(raw or {})
        weights = dict(raw.get("fitness_weights") or {})
        return cls(
            objective_id=str(raw.get("objective_id") or uuid.uuid4()),
            version=str(raw.get("version") or "1"),
            primary_objectives=tuple(raw.get("primary_objectives") or ("risk_adjusted_return", "drawdown_quality")),
            secondary_objectives=tuple(raw.get("secondary_objectives") or ("trade_sufficiency", "stability")),
            constraints=dict(raw.get("constraints") or {}),
            min_trades=int(raw.get("min_trades", 5)),
            max_drawdown_pct=float(raw.get("max_drawdown_pct", 25.0)),
            min_validation_coverage=float(raw.get("min_validation_coverage", 0.0)),
            fitness_components=tuple(
                raw.get("fitness_components")
                or (
                    "return_quality",
                    "risk_adjusted_return",
                    "drawdown_quality",
                    "stability",
                    "regime_robustness",
                    "validation_stability",
                    "trade_sufficiency",
                    "execution_cost_quality",
                    "turnover_quality",
                    "concentration_quality",
                    "complexity_quality",
                )
            ),
            fitness_weights=weights
            or {
                "return_quality": 0.20,
                "risk_adjusted_return": 0.20,
                "drawdown_quality": 0.20,
                "stability": 0.10,
                "trade_sufficiency": 0.10,
                "execution_cost_quality": 0.05,
                "turnover_quality": 0.05,
                "complexity_quality": 0.10,
            },
            turnover_penalty=float(raw.get("turnover_penalty", 0.05)),
            cost_penalty=float(raw.get("cost_penalty", 0.05)),
            instability_penalty=float(raw.get("instability_penalty", 0.1)),
            concentration_penalty=float(raw.get("concentration_penalty", 0.05)),
            complexity_penalty=float(raw.get("complexity_penalty", 0.1)),
            selection_method=str(raw.get("selection_method") or "rank_weighted_elitism"),
            early_stop_rules=dict(
                raw.get("early_stop_rules")
                or {
                    "no_improvement_generations": 3,
                    "diversity_collapse_min": 0.05,
                    "stop_on_qualified": True,
                }
            ),
            generation_budget=int(raw.get("generation_budget", raw.get("max_generations", 8))),
            trial_budget=int(raw.get("trial_budget", raw.get("max_trials", 96))),
            population_size=int(raw.get("population_size", 12)),
            elite_count=int(raw.get("elite_count", 3)),
            exploration_rate=float(raw.get("exploration_rate", 0.15)),
            mutation_rate=float(raw.get("mutation_rate", 0.35)),
            crossover_rate=float(raw.get("crossover_rate", 0.25)),
            seed=int(raw.get("seed", 42)),
            require_val_pass=bool(raw.get("require_val_pass", True)),
            require_robustness_pass=bool(raw.get("require_robustness_pass", True)),
            require_sealed_pass=bool(raw.get("require_sealed_pass", True)),
            max_episode_bars=raw.get("max_episode_bars"),
            universe=tuple(raw.get("universe") or ()),
            metadata=dict(raw.get("metadata") or {}),
        )


@dataclass
class LearnerState:
    """Stateful adaptive proposal distributions — must change after generation updates."""

    generation_number: int = 0
    population_refs: list[str] = field(default_factory=list)
    elite_refs: list[str] = field(default_factory=list)
    family_probabilities: dict[str, float] = field(
        default_factory=lambda: {f: 1.0 / len(SUPPORTED_STRATEGY_FAMILIES) for f in SUPPORTED_STRATEGY_FAMILIES}
    )
    parameter_distributions: dict[str, dict[str, float]] = field(default_factory=dict)
    categorical_distributions: dict[str, dict[str, float]] = field(default_factory=dict)
    mutation_rates: dict[str, float] = field(
        default_factory=lambda: {
            "numeric": 0.35,
            "categorical": 0.2,
            "structure": 0.15,
            "feature": 0.15,
            "risk": 0.2,
        }
    )
    crossover_rate: float = 0.25
    exploration_rate: float = 0.15
    fitness_history: list[dict[str, Any]] = field(default_factory=list)
    regime_performance: dict[str, dict[str, float]] = field(default_factory=dict)
    failure_statistics: dict[str, int] = field(default_factory=dict)
    lesson_priors: dict[str, float] = field(default_factory=dict)
    rng_state: list[Any] | None = None
    best_candidate_ref: str | None = None
    diversity_score: float = 1.0
    generations_without_improvement: int = 0
    validation_exposure_count: int = 0
    sealed_attempt_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def state_hash(self) -> str:
        payload = {
            "generation_number": self.generation_number,
            "population_refs": self.population_refs,
            "elite_refs": self.elite_refs,
            "family_probabilities": self.family_probabilities,
            "parameter_distributions": self.parameter_distributions,
            "categorical_distributions": self.categorical_distributions,
            "mutation_rates": self.mutation_rates,
            "crossover_rate": self.crossover_rate,
            "exploration_rate": self.exploration_rate,
            "fitness_history": self.fitness_history,
            "failure_statistics": self.failure_statistics,
            "lesson_priors": self.lesson_priors,
            "rng_state": self.rng_state,
            "best_candidate_ref": self.best_candidate_ref,
            "diversity_score": self.diversity_score,
            "generations_without_improvement": self.generations_without_improvement,
            "validation_exposure_count": self.validation_exposure_count,
        }
        return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))

    def public_dict(self) -> dict[str, Any]:
        return {
            "generation_number": self.generation_number,
            "population_refs": list(self.population_refs),
            "elite_refs": list(self.elite_refs),
            "family_probabilities": dict(self.family_probabilities),
            "parameter_distributions": dict(self.parameter_distributions),
            "categorical_distributions": dict(self.categorical_distributions),
            "mutation_rates": dict(self.mutation_rates),
            "crossover_rate": self.crossover_rate,
            "exploration_rate": self.exploration_rate,
            "fitness_history": list(self.fitness_history),
            "regime_performance": dict(self.regime_performance),
            "failure_statistics": dict(self.failure_statistics),
            "lesson_priors": dict(self.lesson_priors),
            "rng_state": self.rng_state,
            "best_candidate_ref": self.best_candidate_ref,
            "diversity_score": self.diversity_score,
            "generations_without_improvement": self.generations_without_improvement,
            "validation_exposure_count": self.validation_exposure_count,
            "sealed_attempt_ref": self.sealed_attempt_ref,
            "learner_state_hash": self.state_hash(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "LearnerState":
        raw = dict(raw or {})
        fam = dict(raw.get("family_probabilities") or {})
        if not fam:
            fam = {f: 1.0 / len(SUPPORTED_STRATEGY_FAMILIES) for f in SUPPORTED_STRATEGY_FAMILIES}
        return cls(
            generation_number=int(raw.get("generation_number") or 0),
            population_refs=list(raw.get("population_refs") or []),
            elite_refs=list(raw.get("elite_refs") or []),
            family_probabilities=fam,
            parameter_distributions=dict(raw.get("parameter_distributions") or {}),
            categorical_distributions=dict(raw.get("categorical_distributions") or {}),
            mutation_rates=dict(
                raw.get("mutation_rates")
                or {
                    "numeric": 0.35,
                    "categorical": 0.2,
                    "structure": 0.15,
                    "feature": 0.15,
                    "risk": 0.2,
                }
            ),
            crossover_rate=float(raw.get("crossover_rate", 0.25)),
            exploration_rate=float(raw.get("exploration_rate", 0.15)),
            fitness_history=list(raw.get("fitness_history") or []),
            regime_performance=dict(raw.get("regime_performance") or {}),
            failure_statistics={str(k): int(v) for k, v in dict(raw.get("failure_statistics") or {}).items()},
            lesson_priors={str(k): float(v) for k, v in dict(raw.get("lesson_priors") or {}).items()},
            rng_state=list(raw["rng_state"]) if raw.get("rng_state") is not None else None,
            best_candidate_ref=raw.get("best_candidate_ref"),
            diversity_score=float(raw.get("diversity_score", 1.0)),
            generations_without_improvement=int(raw.get("generations_without_improvement") or 0),
            validation_exposure_count=int(raw.get("validation_exposure_count") or 0),
            sealed_attempt_ref=raw.get("sealed_attempt_ref"),
            metadata=dict(raw.get("metadata") or {}),
        )


@dataclass
class CandidateProposal:
    candidate_id: str
    generation: int
    strategy_id: str
    strategy_version: int
    parent_refs: list[dict[str, Any]] = field(default_factory=list)
    proposal_method: str = ProposalMethod.SEED.value
    mutations: list[str] = field(default_factory=list)
    crossover_metadata: dict[str, Any] = field(default_factory=dict)
    hypothesis: str = ""
    content_hash: str = ""
    family: str = ""
    entry_rules: dict[str, Any] = field(default_factory=dict)
    exit_rules: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_rules: dict[str, Any] = field(default_factory=dict)
    complexity: dict[str, int] = field(default_factory=dict)
    status: str = "PROPOSED"
    learner_state_hash: str = ""
    objective_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "generation": self.generation,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "parent_refs": list(self.parent_refs),
            "proposal_method": self.proposal_method,
            "mutations": list(self.mutations),
            "crossover_metadata": dict(self.crossover_metadata),
            "hypothesis": self.hypothesis,
            "content_hash": self.content_hash,
            "family": self.family,
            "entry_rules": dict(self.entry_rules),
            "exit_rules": dict(self.exit_rules),
            "parameters": dict(self.parameters),
            "risk_rules": dict(self.risk_rules),
            "complexity": dict(self.complexity),
            "status": self.status,
            "learner_state_hash": self.learner_state_hash,
            "objective_hash": self.objective_hash,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "CandidateProposal":
        raw = dict(raw or {})
        return cls(
            candidate_id=str(raw.get("candidate_id") or uuid.uuid4()),
            generation=int(raw.get("generation") or 0),
            strategy_id=str(raw.get("strategy_id") or ""),
            strategy_version=int(raw.get("strategy_version") or 0),
            parent_refs=list(raw.get("parent_refs") or []),
            proposal_method=str(raw.get("proposal_method") or ProposalMethod.SEED.value),
            mutations=list(raw.get("mutations") or []),
            crossover_metadata=dict(raw.get("crossover_metadata") or {}),
            hypothesis=str(raw.get("hypothesis") or ""),
            content_hash=str(raw.get("content_hash") or ""),
            family=str(raw.get("family") or ""),
            entry_rules=dict(raw.get("entry_rules") or {}),
            exit_rules=dict(raw.get("exit_rules") or {}),
            parameters=dict(raw.get("parameters") or {}),
            risk_rules=dict(raw.get("risk_rules") or {}),
            complexity=dict(raw.get("complexity") or {}),
            status=str(raw.get("status") or "PROPOSED"),
            learner_state_hash=str(raw.get("learner_state_hash") or ""),
            objective_hash=str(raw.get("objective_hash") or ""),
            metadata=dict(raw.get("metadata") or {}),
        )


@dataclass
class FitnessComponent:
    name: str
    value: float | None
    status: str = MeasurementStatus.UNMEASURED.value
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class FitnessResult:
    candidate_id: str
    split_role: str
    components: dict[str, FitnessComponent] = field(default_factory=dict)
    scalar_score: float | None = None
    measurement_status: str = MeasurementStatus.UNMEASURED.value
    failure_reasons: list[str] = field(default_factory=list)
    failure_categories: list[str] = field(default_factory=list)
    metric_refs: dict[str, Any] = field(default_factory=dict)
    parent_deltas: dict[str, float | None] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "split_role": self.split_role,
            "components": {k: v.public_dict() for k, v in self.components.items()},
            "scalar_score": self.scalar_score,
            "measurement_status": self.measurement_status,
            "failure_reasons": list(self.failure_reasons),
            "failure_categories": list(self.failure_categories),
            "metric_refs": dict(self.metric_refs),
            "parent_deltas": dict(self.parent_deltas),
            "truth": {
                "unmeasured_is_not_zero": True,
                "nan_is_not_pass": True,
                "server_side_only": True,
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "FitnessResult":
        raw = dict(raw or {})
        comps: dict[str, FitnessComponent] = {}
        for k, v in dict(raw.get("components") or {}).items():
            if isinstance(v, FitnessComponent):
                comps[k] = v
            else:
                comps[k] = FitnessComponent(
                    name=str(v.get("name") or k),
                    value=v.get("value"),
                    status=str(v.get("status") or MeasurementStatus.UNMEASURED.value),
                    detail=str(v.get("detail") or ""),
                )
        return cls(
            candidate_id=str(raw.get("candidate_id") or ""),
            split_role=str(raw.get("split_role") or "TRAIN"),
            components=comps,
            scalar_score=raw.get("scalar_score"),
            measurement_status=str(raw.get("measurement_status") or MeasurementStatus.UNMEASURED.value),
            failure_reasons=list(raw.get("failure_reasons") or []),
            failure_categories=list(raw.get("failure_categories") or []),
            metric_refs=dict(raw.get("metric_refs") or {}),
            parent_deltas=dict(raw.get("parent_deltas") or {}),
        )


@dataclass
class StrategyLearningRun:
    learning_run_id: str
    lab_id: str | None = None
    campaign_id: str | None = None
    status: str = LearningRunStatus.CREATED.value
    stage: str = LearningStage.CREATED.value
    objective_spec: LearningObjectiveSpec | None = None
    objective_hash: str = ""
    algorithm: str = LEARNING_ALGORITHM
    algorithm_version: str = LEARNING_ALGORITHM_VERSION
    seed: int = 42
    rng_state: list[Any] | None = None
    current_generation: int = 0
    generation_budget: int = 8
    trial_budget: int = 96
    trials_used: int = 0
    population_size: int = 12
    strategy_id: str = ""
    parent_strategy_version: int = 1
    source_id: str = ""
    train_split_ref: dict[str, Any] = field(default_factory=dict)
    validation_split_ref: dict[str, Any] = field(default_factory=dict)
    robustness_split_ref: dict[str, Any] = field(default_factory=dict)
    sealed_split_ref: dict[str, Any] = field(default_factory=dict)
    learner_state: LearnerState = field(default_factory=LearnerState)
    candidates: list[CandidateProposal] = field(default_factory=list)
    generation_summaries: list[dict[str, Any]] = field(default_factory=list)
    best_train_candidate: str | None = None
    best_validation_candidate: str | None = None
    qualified_candidate: str | None = None
    input_fingerprint: str = ""
    job_id: str | None = None
    error: str = ""
    pause_requested: bool = False
    cancel_requested: bool = False
    created_at: str = ""
    updated_at: str = ""
    last_checkpoint_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        obj = self.objective_spec.public_dict() if self.objective_spec else {}
        return {
            "learning_run_id": self.learning_run_id,
            "lab_id": self.lab_id,
            "campaign_id": self.campaign_id,
            "status": self.status,
            "stage": self.stage,
            "objective_spec": obj,
            "objective_hash": self.objective_hash or (self.objective_spec.objective_hash() if self.objective_spec else ""),
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "seed": self.seed,
            "rng_state": self.rng_state,
            "current_generation": self.current_generation,
            "generation_budget": self.generation_budget,
            "trial_budget": self.trial_budget,
            "trials_used": self.trials_used,
            "population_size": self.population_size,
            "strategy_id": self.strategy_id,
            "parent_strategy_version": self.parent_strategy_version,
            "source_id": self.source_id,
            "train_split_ref": dict(self.train_split_ref),
            "validation_split_ref": dict(self.validation_split_ref),
            "robustness_split_ref": dict(self.robustness_split_ref),
            "sealed_split_ref": dict(self.sealed_split_ref),
            "learner_state": self.learner_state.public_dict(),
            "candidates": [c.public_dict() for c in self.candidates],
            "generation_summaries": list(self.generation_summaries),
            "best_train_candidate": self.best_train_candidate,
            "best_validation_candidate": self.best_validation_candidate,
            "qualified_candidate": self.qualified_candidate,
            "input_fingerprint": self.input_fingerprint,
            "job_id": self.job_id,
            "error": self.error,
            "pause_requested": self.pause_requested,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_checkpoint_at": self.last_checkpoint_at,
            "metadata": dict(self.metadata),
            "truth": {
                "adaptive_dsl_learning": True,
                "neural_rl_not_required": True,
                "sealed_never_trains_learner": True,
                "live_trading_blocked": True,
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "StrategyLearningRun":
        raw = dict(raw or {})
        obj_raw = raw.get("objective_spec")
        objective = LearningObjectiveSpec.from_dict(obj_raw) if obj_raw else None
        return cls(
            learning_run_id=str(raw.get("learning_run_id") or uuid.uuid4()),
            lab_id=raw.get("lab_id"),
            campaign_id=raw.get("campaign_id"),
            status=str(raw.get("status") or LearningRunStatus.CREATED.value),
            stage=str(raw.get("stage") or LearningStage.CREATED.value),
            objective_spec=objective,
            objective_hash=str(raw.get("objective_hash") or ""),
            algorithm=str(raw.get("algorithm") or LEARNING_ALGORITHM),
            algorithm_version=str(raw.get("algorithm_version") or LEARNING_ALGORITHM_VERSION),
            seed=int(raw.get("seed") or 42),
            rng_state=list(raw["rng_state"]) if raw.get("rng_state") is not None else None,
            current_generation=int(raw.get("current_generation") or 0),
            generation_budget=int(raw.get("generation_budget") or 8),
            trial_budget=int(raw.get("trial_budget") or 96),
            trials_used=int(raw.get("trials_used") or 0),
            population_size=int(raw.get("population_size") or 12),
            strategy_id=str(raw.get("strategy_id") or ""),
            parent_strategy_version=int(raw.get("parent_strategy_version") or 1),
            source_id=str(raw.get("source_id") or ""),
            train_split_ref=dict(raw.get("train_split_ref") or {}),
            validation_split_ref=dict(raw.get("validation_split_ref") or {}),
            robustness_split_ref=dict(raw.get("robustness_split_ref") or {}),
            sealed_split_ref=dict(raw.get("sealed_split_ref") or {}),
            learner_state=LearnerState.from_dict(raw.get("learner_state")),
            candidates=[CandidateProposal.from_dict(c) for c in (raw.get("candidates") or [])],
            generation_summaries=list(raw.get("generation_summaries") or []),
            best_train_candidate=raw.get("best_train_candidate"),
            best_validation_candidate=raw.get("best_validation_candidate"),
            qualified_candidate=raw.get("qualified_candidate"),
            input_fingerprint=str(raw.get("input_fingerprint") or ""),
            job_id=raw.get("job_id"),
            error=str(raw.get("error") or ""),
            pause_requested=bool(raw.get("pause_requested")),
            cancel_requested=bool(raw.get("cancel_requested")),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            last_checkpoint_at=str(raw.get("last_checkpoint_at") or ""),
            metadata=dict(raw.get("metadata") or {}),
        )


def new_learning_objective(**kwargs: Any) -> LearningObjectiveSpec:
    raw = dict(kwargs)
    raw.setdefault("objective_id", str(uuid.uuid4()))
    return LearningObjectiveSpec.from_dict(raw)


def learning_input_fingerprint(
    *,
    objective_hash: str,
    strategy_id: str,
    parent_version: int,
    source_id: str,
    seed: int,
    algorithm: str,
    algorithm_version: str,
    split_hashes: dict[str, str] | None = None,
    feature_pipeline_version: str = "",
    cost_model_ref: str = "",
) -> str:
    payload = {
        "objective_hash": objective_hash,
        "strategy_id": strategy_id,
        "parent_version": parent_version,
        "source_id": source_id,
        "seed": seed,
        "algorithm": algorithm,
        "algorithm_version": algorithm_version,
        "split_hashes": dict(split_hashes or {}),
        "feature_pipeline_version": feature_pipeline_version,
        "cost_model_ref": cost_model_ref,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
