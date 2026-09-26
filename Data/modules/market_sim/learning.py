"""Adaptive Evolutionary Strategy Search — durable, resumable Strategy Learning Loop."""

from __future__ import annotations

import json
import random
import uuid
from typing import Any, Callable

from Data.modules.common.hashing import sha256_text

from .learning_candidates import (
    FAMILY_TEMPLATES,
    generate_population,
    proposal_from_spec,
    restore_rng,
    update_learner_from_outcomes,
)
from .learning_fitness import (
    classify_failures,
    compute_fitness,
    measure_strategy_complexity,
    parent_deltas,
)
from .learning_types import (
    LEARNING_ALGORITHM,
    LEARNING_ALGORITHM_VERSION,
    CandidateProposal,
    FailureCategory,
    LearnerState,
    LearningObjectiveSpec,
    LearningRunStatus,
    LearningStage,
    StrategyLearningRun,
    learning_input_fingerprint,
    new_learning_objective,
)
from .strategy_lineage import attach_lineage_metadata
from .types import MarketSimError, StrategyVersion


def init_learner_priors(
    *,
    parent_family: str | None = None,
    trial_history: list[dict[str, Any]] | None = None,
    lessons: list[dict[str, Any]] | None = None,
    exploration_rate: float = 0.15,
    crossover_rate: float = 0.25,
) -> LearnerState:
    """Initialize proposal priors from lineage / trial history / validated lessons — never SEALED."""
    state = LearnerState(exploration_rate=exploration_rate, crossover_rate=crossover_rate)
    # Mild bump for parent family
    if parent_family and parent_family in state.family_probabilities:
        bump = 0.1
        state.family_probabilities[parent_family] = state.family_probabilities[parent_family] + bump
        total = sum(state.family_probabilities.values()) or 1.0
        state.family_probabilities = {k: v / total for k, v in state.family_probabilities.items()}

    # Trial history (TRAIN/VAL only — caller must exclude SEALED)
    fam_wins: dict[str, float] = {}
    for trial in trial_history or []:
        split = str((trial.get("split") or {}).get("role") or trial.get("split_role") or "").upper()
        if split == "SEALED":
            continue
        results = dict(trial.get("results") or {})
        fam = str(
            results.get("family")
            or (trial.get("config") or {}).get("family")
            or trial.get("family")
            or ""
        )
        if not fam:
            continue
        score = results.get("fitness_score")
        if score is None and results.get("accepted"):
            score = 0.5
        if score is None:
            continue
        try:
            fam_wins[fam] = fam_wins.get(fam, 0.0) + float(score)
        except (TypeError, ValueError):
            continue
    if fam_wins:
        for fam, sc in fam_wins.items():
            if fam in state.family_probabilities:
                state.family_probabilities[fam] += max(0.0, sc) * 0.05
        total = sum(state.family_probabilities.values()) or 1.0
        state.family_probabilities = {k: v / total for k, v in state.family_probabilities.items()}

    for lesson in lessons or []:
        trust = str(lesson.get("trust") or "")
        if trust not in {"VALIDATED", "AGENT_PROPOSED"}:
            continue
        conf = float(lesson.get("confidence") or 0.0)
        if trust == "AGENT_PROPOSED":
            conf *= 0.25  # not authoritative
        applies = list(lesson.get("applies_to") or [])
        claim = str(lesson.get("claim") or "").lower()
        weight = conf if "underperform" not in claim and "fail" not in claim else -conf
        for fam in applies:
            if fam in state.family_probabilities:
                state.lesson_priors[fam] = state.lesson_priors.get(fam, 0.0) + weight
    return state


def create_learning_run(
    *,
    lab_id: str | None,
    campaign_id: str | None,
    strategy_id: str,
    parent_strategy_version: int,
    source_id: str,
    objective: LearningObjectiveSpec | dict[str, Any] | None = None,
    seed: int = 42,
    parent_family: str | None = None,
    trial_history: list[dict[str, Any]] | None = None,
    lessons: list[dict[str, Any]] | None = None,
    feature_pipeline_version: str = "",
    split_refs: dict[str, dict[str, Any]] | None = None,
    now: str = "",
) -> StrategyLearningRun:
    obj = (
        objective
        if isinstance(objective, LearningObjectiveSpec)
        else new_learning_objective(**dict(objective or {}), seed=seed)
    )
    # Bind seed into objective immutably via reconstruction if needed
    if obj.seed != seed:
        d = obj.content_dict()
        d["seed"] = seed
        obj = LearningObjectiveSpec.from_dict(d)

    learner = init_learner_priors(
        parent_family=parent_family,
        trial_history=trial_history,
        lessons=lessons,
        exploration_rate=obj.exploration_rate,
        crossover_rate=obj.crossover_rate,
    )
    rng = random.Random(seed)
    try:
        learner.rng_state = list(rng.getstate()[1])
    except Exception:  # noqa: BLE001
        pass

    splits = dict(split_refs or {})
    fp = learning_input_fingerprint(
        objective_hash=obj.objective_hash(),
        strategy_id=strategy_id,
        parent_version=parent_strategy_version,
        source_id=source_id,
        seed=seed,
        algorithm=LEARNING_ALGORITHM,
        algorithm_version=LEARNING_ALGORITHM_VERSION,
        split_hashes={k: str(v.get("hash") or v.get("split_hash") or "") for k, v in splits.items()},
        feature_pipeline_version=feature_pipeline_version,
    )
    return StrategyLearningRun(
        learning_run_id=str(uuid.uuid4()),
        lab_id=lab_id,
        campaign_id=campaign_id,
        status=LearningRunStatus.CREATED.value,
        stage=LearningStage.CREATED.value,
        objective_spec=obj,
        objective_hash=obj.objective_hash(),
        seed=seed,
        rng_state=learner.rng_state,
        current_generation=0,
        generation_budget=obj.generation_budget,
        trial_budget=obj.trial_budget,
        population_size=obj.population_size,
        strategy_id=strategy_id,
        parent_strategy_version=parent_strategy_version,
        source_id=source_id,
        train_split_ref=dict(splits.get("train") or splits.get("TRAIN") or {}),
        validation_split_ref=dict(splits.get("val") or splits.get("VAL") or {}),
        robustness_split_ref=dict(splits.get("robustness") or splits.get("ROBUSTNESS") or {}),
        sealed_split_ref=dict(splits.get("sealed") or splits.get("SEALED") or {}),
        learner_state=learner,
        input_fingerprint=fp,
        created_at=now,
        updated_at=now,
        metadata={"algorithm": LEARNING_ALGORITHM, "algorithm_version": LEARNING_ALGORITHM_VERSION},
    )


def should_early_stop(run: StrategyLearningRun) -> tuple[bool, str]:
    obj = run.objective_spec
    if obj is None:
        return False, ""
    rules = dict(obj.early_stop_rules or {})
    if run.qualified_candidate and rules.get("stop_on_qualified", True):
        return True, "qualified_candidate"
    if run.trials_used >= run.trial_budget:
        return True, "trial_budget_exhausted"
    if run.current_generation >= run.generation_budget:
        return True, "generation_budget_exhausted"
    no_imp = int(rules.get("no_improvement_generations") or 3)
    if run.learner_state.generations_without_improvement >= no_imp and run.current_generation > 0:
        return True, "no_elite_improvement"
    collapse = float(rules.get("diversity_collapse_min") or 0.05)
    if (
        run.learner_state.diversity_score < collapse
        and run.learner_state.generations_without_improvement >= max(1, no_imp - 1)
        and run.current_generation > 1
    ):
        return True, "diversity_collapse_no_improvement"
    return False, ""


def _parent_spec_from_version(ver: Any) -> dict[str, Any]:
    entry = dict(getattr(ver, "entry_rules", None) or ver.get("entry_rules") or {})
    family = str(entry.get("kind") or "ma_cross")
    return {
        "family": family,
        "entry_rules": entry,
        "exit_rules": dict(getattr(ver, "exit_rules", None) or ver.get("exit_rules") or {}),
        "parameters": dict(getattr(ver, "parameters", None) or ver.get("parameters") or {}),
        "risk_rules": dict(getattr(ver, "risk_rules", None) or ver.get("risk_rules") or {}),
    }


class AdaptiveEvolutionaryLearner:
    """Production algorithm v1 — population evolution with adaptive distributions."""

    def __init__(self, run: StrategyLearningRun) -> None:
        self.run = run

    def restore_rng(self) -> random.Random:
        return restore_rng(self.run.seed, self.run.learner_state.rng_state or self.run.rng_state)

    def propose_generation(
        self,
        *,
        parent_version: Any,
        elite_specs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        run = self.run
        if run.objective_spec is None:
            raise MarketSimError("LEARNING_OBJECTIVE_MISSING", run.learning_run_id, http_status=409)
        if run.trials_used >= run.trial_budget:
            raise MarketSimError("LEARNING_TRIAL_BUDGET", "trial budget exhausted", http_status=409)
        generation = run.current_generation + 1
        if generation > run.generation_budget:
            raise MarketSimError("LEARNING_GENERATION_BUDGET", "generation budget exhausted", http_status=409)
        rng = self.restore_rng()
        remaining = run.trial_budget - run.trials_used
        # Bound population by remaining trial budget
        obj = run.objective_spec
        pop_size = min(obj.population_size, remaining)
        # Temporary objective with bounded population
        bounded = LearningObjectiveSpec.from_dict({**obj.content_dict(), "population_size": pop_size})
        parent_spec = _parent_spec_from_version(parent_version)
        elites = list(elite_specs or [])
        if not elites and generation == 1:
            elites = [parent_spec]
        raw = generate_population(
            state=run.learner_state,
            objective=bounded,
            generation=generation,
            parent_strategy_id=run.strategy_id,
            rng=rng,
            elite_specs=elites,
            prior_candidates=run.candidates,
        )
        # Persist RNG after proposal
        try:
            run.learner_state.rng_state = list(rng.getstate()[1])
            run.rng_state = run.learner_state.rng_state
        except Exception:  # noqa: BLE001
            pass
        return raw

    def materialize_candidates(
        self,
        raw_population: list[dict[str, Any]],
        *,
        version_factory: Callable[..., StrategyVersion],
        generation: int,
    ) -> list[CandidateProposal]:
        """Create immutable StrategyVersions + CandidateProposals (idempotent by content+generation key)."""
        run = self.run
        obj_hash = run.objective_hash or (run.objective_spec.objective_hash() if run.objective_spec else "")
        state_hash = run.learner_state.state_hash()
        existing_keys = {
            (
                c.generation,
                c.content_hash,
                c.proposal_method,
            )
            for c in run.candidates
            if c.generation == generation
        }
        out: list[CandidateProposal] = []
        for item in raw_population:
            spec = item["spec"]
            # Pre-hash to check idempotency before versioning
            tmp = proposal_from_spec(
                spec,
                generation=generation,
                strategy_id=run.strategy_id,
                strategy_version=0,
                method=item["method"],
                parent_refs=item.get("parent_refs"),
                mutations=item.get("mutations"),
                crossover_metadata=item.get("crossover_metadata"),
                learner_state_hash=state_hash,
                objective_hash=obj_hash,
                hypothesis=item.get("hypothesis") or "",
            )
            key = (generation, tmp.content_hash, item["method"])
            if key in existing_keys:
                # Reuse existing candidate with same identity
                for c in run.candidates:
                    if c.generation == generation and c.content_hash == tmp.content_hash and c.proposal_method == item["method"]:
                        out.append(c)
                        break
                continue
            ver = version_factory(
                strategy_id=run.strategy_id,
                parameters=spec.get("parameters"),
                entry_rules=spec.get("entry_rules"),
                exit_rules=spec.get("exit_rules"),
                risk_rules=spec.get("risk_rules"),
                changelog=f"learning gen={generation} method={item['method']}",
                lineage_extra={
                    "generation": generation,
                    "proposal_method": item["method"],
                    "mutation_operations": list(item.get("mutations") or []),
                    "crossover_metadata": dict(item.get("crossover_metadata") or {}),
                    "learner_state_hash": state_hash,
                    "objective_hash": obj_hash,
                    "learning_run_id": run.learning_run_id,
                    "parent_refs": list(item.get("parent_refs") or []),
                },
            )
            cand = proposal_from_spec(
                spec,
                generation=generation,
                strategy_id=run.strategy_id,
                strategy_version=int(ver.version),
                method=item["method"],
                parent_refs=item.get("parent_refs"),
                mutations=item.get("mutations"),
                crossover_metadata=item.get("crossover_metadata"),
                learner_state_hash=state_hash,
                objective_hash=obj_hash,
                hypothesis=item.get("hypothesis") or "",
            )
            cand.content_hash = ver.content_hash
            cand.status = "VERSIONED"
            cand.metadata["version_id"] = ver.version_id
            out.append(cand)
            existing_keys.add(key)
        return out

    def apply_train_outcomes(
        self,
        outcomes: list[dict[str, Any]],
        *,
        generation: int,
    ) -> LearnerState:
        run = self.run
        if run.objective_spec is None:
            raise MarketSimError("LEARNING_OBJECTIVE_MISSING", run.learning_run_id)
        rng = self.restore_rng()
        new_state = update_learner_from_outcomes(
            run.learner_state,
            outcomes=outcomes,
            objective=run.objective_spec,
            rng=rng,
            split_role="TRAIN",
        )
        # generation_number already incremented inside update
        run.learner_state = new_state
        run.current_generation = generation
        run.rng_state = new_state.rng_state
        return new_state


def evaluate_candidate_metrics(
    *,
    candidate: CandidateProposal,
    metrics: dict[str, Any],
    objective: LearningObjectiveSpec,
    split_role: str,
    parent_metrics: dict[str, Any] | None = None,
    parent_fitness: float | None = None,
) -> dict[str, Any]:
    complexity = candidate.complexity or measure_strategy_complexity(
        candidate.entry_rules, candidate.exit_rules, candidate.parameters
    )
    fitness = compute_fitness(
        candidate_id=candidate.candidate_id,
        split_role=split_role,
        metrics=metrics,
        objective=objective,
        complexity=complexity,
    )
    cats = classify_failures(metrics, objective=objective, fitness=fitness)
    for c in cats:
        if c not in fitness.failure_categories:
            fitness.failure_categories.append(c)
    fitness.parent_deltas = parent_deltas(
        metrics,
        parent_metrics,
        child_complexity=complexity,
        parent_complexity=None,
        child_fitness=fitness.scalar_score,
        parent_fitness=parent_fitness,
    )
    return {
        "candidate_id": candidate.candidate_id,
        "family": candidate.family,
        "fitness_score": fitness.scalar_score,
        "fitness": fitness.public_dict(),
        "failure_categories": list(fitness.failure_categories),
        "parameters": dict(candidate.parameters),
        "complexity": complexity,
        "content_hash": candidate.content_hash,
        "metrics": metrics,
        "measurement_status": fitness.measurement_status,
    }


def build_generation_summary(
    *,
    generation: int,
    candidates: list[CandidateProposal],
    outcomes: list[dict[str, Any]],
    learner_state: LearnerState,
) -> dict[str, Any]:
    scores = [o.get("fitness_score") for o in outcomes if o.get("fitness_score") is not None]
    return {
        "generation": generation,
        "population_size": len(candidates),
        "trials_completed": sum(1 for o in outcomes if o.get("measurement_status") == "MEASURED"),
        "trials_failed": sum(1 for o in outcomes if o.get("failure_categories")),
        "best_train_fitness": max(scores) if scores else None,
        "median_train_fitness": sorted(scores)[len(scores) // 2] if scores else None,
        "diversity_score": learner_state.diversity_score,
        "family_entropy": None,
        "exploration_rate": learner_state.exploration_rate,
        "family_probabilities": dict(learner_state.family_probabilities),
        "elite_refs": list(learner_state.elite_refs),
        "best_candidate_ref": learner_state.best_candidate_ref,
        "learner_state_hash": learner_state.state_hash(),
    }


def reject_sealed_learner_update() -> None:
    raise MarketSimError(
        "SEALED_LEARNER_UPDATE_FORBIDDEN",
        "SEALED outcomes must not update learner proposal state",
        http_status=409,
    )


def assert_objective_immutable(stored_hash: str, objective: LearningObjectiveSpec) -> None:
    current = objective.objective_hash()
    if stored_hash and stored_hash != current:
        raise MarketSimError(
            "OBJECTIVE_MUTATION_FORBIDDEN",
            "learning objective is immutable for a run; create a new run to change criteria",
            http_status=409,
        )


def learning_idempotency_key(
    *,
    learning_run_id: str,
    generation: int,
    candidate_id: str,
    stage: str,
    input_fingerprint: str,
) -> str:
    raw = f"{learning_run_id}:{generation}:{candidate_id}:{stage}:{input_fingerprint}"
    return sha256_text(raw)


def attach_learning_lineage(
    base_meta: dict[str, Any],
    *,
    parent_version: int | None,
    parent_content_hash: str | None,
    changelog: str,
    lineage_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = attach_lineage_metadata(
        parent_version=parent_version,
        parent_content_hash=parent_content_hash,
        changelog=changelog,
    )
    meta.update(dict(lineage_extra or {}))
    meta.update(dict(base_meta or {}))
    return meta


# Re-export templates for tests / UI summaries
STRATEGY_FAMILY_TEMPLATES = FAMILY_TEMPLATES
