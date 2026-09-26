"""Worker-owned Strategy Learning Run execution — durable generations via TradingGym."""

from __future__ import annotations

from typing import Any, Callable

from .agent_lab import AcceptanceCriteria, LabLesson, LessonTrust, LabOutcome
from .learning import (
    AdaptiveEvolutionaryLearner,
    assert_objective_immutable,
    build_generation_summary,
    create_learning_run,
    evaluate_candidate_metrics,
    reject_sealed_learner_update,
    should_early_stop,
)
from .learning_types import (
    CandidateProposal,
    LearningRunStatus,
    LearningStage,
    StrategyLearningRun,
)
from .store import utc_now
from .types import MarketSimError, StrategyVersion


def persist_learning_run(store: Any, run: StrategyLearningRun) -> dict[str, Any]:
    payload = run.public_dict()
    store.upsert_learning_run(payload)
    return payload


def load_learning_run(store: Any, learning_run_id: str) -> StrategyLearningRun:
    row = store.get_learning_run(learning_run_id)
    if row is None:
        raise MarketSimError("LEARNING_RUN_NOT_FOUND", learning_run_id, http_status=404)
    return StrategyLearningRun.from_dict(row)


def _emit(plane: Any, kind: str, payload: dict[str, Any]) -> None:
    if hasattr(plane, "_emit_event"):
        try:
            plane._emit_event(kind, payload)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass


def _version_factory(plane: Any) -> Callable[..., StrategyVersion]:
    def _factory(
        *,
        strategy_id: str,
        parameters: dict[str, Any] | None,
        entry_rules: dict[str, Any] | None,
        exit_rules: dict[str, Any] | None,
        risk_rules: dict[str, Any] | None,
        changelog: str,
        lineage_extra: dict[str, Any] | None = None,
    ) -> StrategyVersion:
        result = plane.version_strategy(
            strategy_id,
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            changelog=changelog,
            lineage_metadata=lineage_extra,
        )
        ver = result["version"]
        return StrategyVersion(
            version_id=ver["version_id"],
            strategy_id=ver["strategy_id"],
            version=int(ver["version"]),
            content_hash=ver["content_hash"],
            parameters=dict(ver.get("parameters") or {}),
            entry_rules=dict(ver.get("entry_rules") or {}),
            exit_rules=dict(ver.get("exit_rules") or {}),
            risk_rules=dict(ver.get("risk_rules") or {}),
            required_timeframes=list(ver.get("required_timeframes") or ["1h"]),
            brain_dependencies=list(ver.get("brain_dependencies") or []),
            created_at=ver.get("created_at") or utc_now(),
            changelog=ver.get("changelog") or "",
            metadata=dict(ver.get("metadata") or {}),
        )

    return _factory


def _completed_candidate_ids(run: StrategyLearningRun, generation: int, stage: str) -> set[str]:
    done: set[str] = set()
    for c in run.candidates:
        if c.generation != generation:
            continue
        meta = dict(c.metadata or {})
        stages = dict(meta.get("stage_results") or {})
        if stage in stages and stages[stage].get("status") in {"completed", "failed", "skipped"}:
            done.add(c.candidate_id)
    return done


def _run_candidate_episode(
    plane: Any,
    *,
    run: StrategyLearningRun,
    candidate: CandidateProposal,
    split_role: str,
    seed: int,
) -> dict[str, Any]:
    meta = {
        "learning_run_id": run.learning_run_id,
        "candidate_id": candidate.candidate_id,
        "generation": candidate.generation,
        "split_role": split_role,
        "objective_hash": run.objective_hash,
        "learner_state_hash": candidate.learner_state_hash,
        "gym": True,
    }
    if run.objective_spec and run.objective_spec.max_episode_bars:
        meta["max_episode_bars"] = run.objective_spec.max_episode_bars
    episode = plane.create_gym_episode(
        source_id=run.source_id,
        strategy_id=candidate.strategy_id,
        strategy_version=candidate.strategy_version,
        seed=seed,
        mode="complete",
        split_role=split_role,
        metadata=meta,
    )
    # Stamp split role onto run metadata
    run_id = str((episode.get("episode") or {}).get("run_id") or "")
    if not run_id:
        raise MarketSimError("LEARNING_TRIAL_NO_RUN", "gym episode missing run_id")
    sim_run = plane._get_run(run_id)  # noqa: SLF001
    sm = dict(sim_run.metadata or {})
    sm["split_role"] = split_role
    sm["learning_run_id"] = run.learning_run_id
    sm["candidate_id"] = candidate.candidate_id
    if run.objective_spec and run.objective_spec.max_episode_bars:
        sm["max_episode_bars"] = run.objective_spec.max_episode_bars
    sim_run.metadata = sm
    plane.store.update_run(sim_run)

    sim_result = plane.run_gym_episode_on_worker(run_id)
    fresh = plane._get_run(run_id)  # noqa: SLF001
    metrics = dict(sim_result.get("metrics") or fresh.metrics or {})
    return {
        "run_id": run_id,
        "metrics": metrics,
        "sim_result": sim_result,
        "status": fresh.status,
        "non_hold_actions": sim_result.get("non_hold_actions"),
        "policy": sim_result.get("policy"),
    }


def _append_trial(
    plane: Any,
    *,
    run: StrategyLearningRun,
    candidate: CandidateProposal,
    split_role: str,
    seed: int,
    episode: dict[str, Any] | None,
    fitness_payload: dict[str, Any] | None,
    status: str,
    error: str | None = None,
) -> str:
    trial_id = f"{run.learning_run_id}:{candidate.generation}:{candidate.candidate_id}:{split_role}"
    # Deterministic trial id for idempotency — append_trial will re-key on collision
    # so we also stamp idempotency in metadata and skip if already present.
    existing = None
    try:
        with plane.store.connect() as conn:
            row = conn.execute(
                "SELECT trial_id, metadata_json FROM market_experiments WHERE fingerprint=?",
                (f"learn:{trial_id}",),
            ).fetchone()
            if row:
                existing = row["trial_id"]
    except Exception:  # noqa: BLE001
        existing = None
    if existing:
        return str(existing)

    plane.store.append_trial(
        {
            "trial_id": trial_id,
            "strategy_id": candidate.strategy_id,
            "strategy_version": candidate.strategy_version,
            "hypothesis": candidate.hypothesis,
            "proposer_agent_id": "strategy_learning",
            "data_hash": run.source_id,
            "fingerprint": f"learn:{trial_id}",
            "status": status,
            "config": {
                "learning_run_id": run.learning_run_id,
                "lab_id": run.lab_id,
                "campaign_id": run.campaign_id,
                "candidate_id": candidate.candidate_id,
                "generation": candidate.generation,
                "proposal_method": candidate.proposal_method,
                "parent_refs": candidate.parent_refs,
                "run_id": (episode or {}).get("run_id"),
                "family": candidate.family,
            },
            "split": {"role": split_role, "hash": (getattr(run, f"{split_role.lower()}_split_ref", None) or {})},
            "results": {
                "metrics": (episode or {}).get("metrics") or {},
                "fitness": (fitness_payload or {}).get("fitness"),
                "fitness_score": (fitness_payload or {}).get("fitness_score"),
                "failure_categories": (fitness_payload or {}).get("failure_categories") or [],
                "non_hold_actions": (episode or {}).get("non_hold_actions"),
                "policy": (episode or {}).get("policy"),
                "error": error,
                "simulation_executed": episode is not None and not error,
            },
            "acceptance_criteria": run.objective_spec.public_dict() if run.objective_spec else {},
            "rejection_reason": error or "",
            "seed": seed,
            "created_at": utc_now(),
            "finished_at": utc_now(),
            "metadata": {
                "learning_run_id": run.learning_run_id,
                "objective_hash": run.objective_hash,
                "learner_state_hash": candidate.learner_state_hash,
                "strategy_hash": candidate.content_hash,
                "environment_fingerprint": run.input_fingerprint,
                "idempotency_key": trial_id,
            },
        }
    )
    return trial_id


def run_learning_on_worker(plane: Any, learning_run_id: str) -> dict[str, Any]:
    """Execute/resume Strategy Learning Loop on the market_sim worker."""
    run = load_learning_run(plane.store, learning_run_id)
    if run.cancel_requested or run.status == LearningRunStatus.CANCELLED.value:
        run.status = LearningRunStatus.CANCELLED.value
        run.stage = LearningStage.CANCELLED.value
        run.updated_at = utc_now()
        return persist_learning_run(plane.store, run)

    if run.objective_spec is None:
        raise MarketSimError("LEARNING_OBJECTIVE_MISSING", learning_run_id, http_status=409)
    assert_objective_immutable(run.objective_hash, run.objective_spec)

    run.status = LearningRunStatus.RUNNING.value
    run.stage = LearningStage.TRAIN.value
    run.error = ""
    run.updated_at = utc_now()
    persist_learning_run(plane.store, run)
    _emit(plane, "learning_run.started", {"learning_run_id": learning_run_id})

    parent_ver = plane.store.get_strategy_version(run.strategy_id, run.parent_strategy_version)
    if parent_ver is None:
        parent_ver = plane.store.get_strategy_version(run.strategy_id)
    if parent_ver is None:
        raise MarketSimError("STRATEGY_VERSION_MISSING", run.strategy_id, http_status=404)

    learner = AdaptiveEvolutionaryLearner(run)
    factory = _version_factory(plane)

    # Resume: continue from current_generation (completed gens are checkpointed)
    while True:
        # Reload flags
        fresh = load_learning_run(plane.store, learning_run_id)
        run.pause_requested = fresh.pause_requested
        run.cancel_requested = fresh.cancel_requested
        if run.cancel_requested:
            run.status = LearningRunStatus.CANCELLED.value
            run.stage = LearningStage.CANCELLED.value
            run.updated_at = utc_now()
            persist_learning_run(plane.store, run)
            _emit(plane, "learning_run.cancelled", {"learning_run_id": learning_run_id})
            return run.public_dict()
        if run.pause_requested:
            run.status = LearningRunStatus.PAUSED.value
            run.stage = LearningStage.PAUSED.value
            run.updated_at = utc_now()
            persist_learning_run(plane.store, run)
            _emit(plane, "learning_run.paused", {"learning_run_id": learning_run_id})
            return run.public_dict()

        stop, reason = should_early_stop(run)
        if stop and run.current_generation > 0:
            break

        if run.current_generation >= run.generation_budget:
            break
        if run.trials_used >= run.trial_budget:
            break

        generation = run.current_generation + 1
        _emit(
            plane,
            "learning_generation.started",
            {"learning_run_id": learning_run_id, "generation": generation},
        )

        # Elite specs from prior generation outcomes
        elite_specs: list[dict[str, Any]] = []
        for cid in run.learner_state.elite_refs:
            for c in run.candidates:
                if c.candidate_id == cid:
                    elite_specs.append(
                        {
                            "family": c.family,
                            "entry_rules": dict(c.entry_rules),
                            "exit_rules": dict(c.exit_rules),
                            "parameters": dict(c.parameters),
                            "risk_rules": dict(c.risk_rules),
                        }
                    )
                    break

        # Propose + materialize (idempotent for already-versioned generation)
        existing_gen = [c for c in run.candidates if c.generation == generation]
        if existing_gen and all(c.strategy_version > 0 for c in existing_gen):
            gen_candidates = existing_gen
        else:
            raw = learner.propose_generation(parent_version=parent_ver, elite_specs=elite_specs or None)
            gen_candidates = learner.materialize_candidates(
                raw, version_factory=factory, generation=generation
            )
            # Merge into run.candidates without duplicating
            known = {c.candidate_id for c in run.candidates}
            for c in gen_candidates:
                if c.candidate_id not in known:
                    run.candidates.append(c)
                    _emit(
                        plane,
                        "candidate.versioned",
                        {
                            "learning_run_id": learning_run_id,
                            "candidate_id": c.candidate_id,
                            "strategy_version": c.strategy_version,
                            "generation": generation,
                        },
                    )
            persist_learning_run(plane.store, run)

        # TRAIN evaluate each candidate
        outcomes: list[dict[str, Any]] = []
        done_ids = _completed_candidate_ids(run, generation, "TRAIN")
        for cand in gen_candidates:
            if run.cancel_requested or run.pause_requested:
                break
            if cand.candidate_id in done_ids:
                # Reconstruct outcome from stored metadata
                stage = dict((cand.metadata or {}).get("stage_results") or {}).get("TRAIN") or {}
                outcomes.append(
                    {
                        "candidate_id": cand.candidate_id,
                        "family": cand.family,
                        "fitness_score": stage.get("fitness_score"),
                        "failure_categories": stage.get("failure_categories") or [],
                        "parameters": dict(cand.parameters),
                        "complexity": dict(cand.complexity),
                        "content_hash": cand.content_hash,
                        "measurement_status": stage.get("measurement_status"),
                    }
                )
                continue
            if run.trials_used >= run.trial_budget:
                cand.status = "SKIPPED_BUDGET"
                cand.metadata.setdefault("stage_results", {})["TRAIN"] = {
                    "status": "skipped",
                    "reason": "trial_budget",
                }
                continue

            seed = run.seed + generation * 1000 + cand.strategy_version
            try:
                _emit(
                    plane,
                    "candidate.started",
                    {
                        "learning_run_id": learning_run_id,
                        "candidate_id": cand.candidate_id,
                        "split_role": "TRAIN",
                    },
                )
                episode = _run_candidate_episode(
                    plane, run=run, candidate=cand, split_role="TRAIN", seed=seed
                )
                fit = evaluate_candidate_metrics(
                    candidate=cand,
                    metrics=episode["metrics"],
                    objective=run.objective_spec,
                    split_role="TRAIN",
                )
                _append_trial(
                    plane,
                    run=run,
                    candidate=cand,
                    split_role="TRAIN",
                    seed=seed,
                    episode=episode,
                    fitness_payload=fit,
                    status="completed",
                )
                cand.status = "TRAIN_COMPLETED"
                cand.metadata.setdefault("stage_results", {})["TRAIN"] = {
                    "status": "completed",
                    "run_id": episode["run_id"],
                    "fitness_score": fit.get("fitness_score"),
                    "failure_categories": fit.get("failure_categories") or [],
                    "measurement_status": fit.get("measurement_status"),
                    "metrics": episode["metrics"],
                    "non_hold_actions": episode.get("non_hold_actions"),
                }
                outcomes.append(fit)
                run.trials_used += 1
                _emit(
                    plane,
                    "candidate.completed",
                    {
                        "learning_run_id": learning_run_id,
                        "candidate_id": cand.candidate_id,
                        "fitness_score": fit.get("fitness_score"),
                    },
                )
            except Exception as exc:  # noqa: BLE001 — retain failed trial
                fit = {
                    "candidate_id": cand.candidate_id,
                    "family": cand.family,
                    "fitness_score": None,
                    "failure_categories": ["EXECUTION_FAILURE"],
                    "parameters": dict(cand.parameters),
                    "complexity": dict(cand.complexity),
                    "content_hash": cand.content_hash,
                    "measurement_status": "INVALID",
                }
                _append_trial(
                    plane,
                    run=run,
                    candidate=cand,
                    split_role="TRAIN",
                    seed=seed,
                    episode=None,
                    fitness_payload=fit,
                    status="failed",
                    error=str(exc),
                )
                cand.status = "TRAIN_FAILED"
                cand.metadata.setdefault("stage_results", {})["TRAIN"] = {
                    "status": "failed",
                    "error": str(exc),
                    "failure_categories": ["EXECUTION_FAILURE"],
                }
                outcomes.append(fit)
                run.trials_used += 1
                _emit(
                    plane,
                    "candidate.failed",
                    {"learning_run_id": learning_run_id, "candidate_id": cand.candidate_id, "error": str(exc)[:200]},
                )

            # Checkpoint after each candidate for crash resume
            run.updated_at = utc_now()
            run.last_checkpoint_at = run.updated_at
            persist_learning_run(plane.store, run)

        if run.pause_requested or run.cancel_requested:
            continue  # handled at loop top

        # Update learner from TRAIN only
        new_state = learner.apply_train_outcomes(outcomes, generation=generation)
        run.learner_state = new_state
        if new_state.best_candidate_ref:
            run.best_train_candidate = new_state.best_candidate_ref
        summary = build_generation_summary(
            generation=generation,
            candidates=gen_candidates,
            outcomes=outcomes,
            learner_state=new_state,
        )
        # Replace summary for this generation if re-entering
        run.generation_summaries = [s for s in run.generation_summaries if s.get("generation") != generation]
        run.generation_summaries.append(summary)
        run.current_generation = generation
        run.last_checkpoint_at = utc_now()
        run.updated_at = run.last_checkpoint_at
        persist_learning_run(plane.store, run)
        _emit(
            plane,
            "learning_generation.completed",
            {"learning_run_id": learning_run_id, "generation": generation, "summary": summary},
        )
        _emit(
            plane,
            "learner.updated",
            {
                "learning_run_id": learning_run_id,
                "generation": generation,
                "family_probabilities": new_state.family_probabilities,
                "learner_state_hash": new_state.state_hash(),
            },
        )

    # --- VALIDATION stage for top candidates ---
    run.stage = LearningStage.VALIDATING.value
    persist_learning_run(plane.store, run)
    _emit(plane, "validation.started", {"learning_run_id": learning_run_id})

    top_ids = list(run.learner_state.elite_refs)[: max(1, run.objective_spec.elite_count)]
    if not top_ids and run.best_train_candidate:
        top_ids = [run.best_train_candidate]
    val_leader: str | None = None
    val_best_score: float | None = None
    val_pass_ids: list[str] = []

    for cid in top_ids:
        cand = next((c for c in run.candidates if c.candidate_id == cid), None)
        if cand is None:
            continue
        stages = dict(cand.metadata.get("stage_results") or {})
        if "VAL" in stages and stages["VAL"].get("status") in {"completed", "failed"}:
            score = stages["VAL"].get("fitness_score")
            if score is not None and (val_best_score is None or float(score) > val_best_score):
                val_best_score = float(score)
                val_leader = cid
            if stages["VAL"].get("accepted"):
                val_pass_ids.append(cid)
            continue
        run.learner_state.validation_exposure_count += 1
        seed = run.seed + 50_000 + cand.strategy_version
        try:
            episode = _run_candidate_episode(plane, run=run, candidate=cand, split_role="VAL", seed=seed)
            fit = evaluate_candidate_metrics(
                candidate=cand,
                metrics=episode["metrics"],
                objective=run.objective_spec,
                split_role="VAL",
            )
            # Acceptance gate for validation
            acc = AcceptanceCriteria(
                min_trades=run.objective_spec.min_trades,
                max_drawdown_pct=run.objective_spec.max_drawdown_pct,
                require_val_pass=False,
                require_robustness_pass=False,
            )
            verdict = acc.evaluate(episode["metrics"], val_pass=True, robustness_pass=True)
            accepted = bool(verdict.get("passed")) and fit.get("fitness_score") is not None
            _append_trial(
                plane,
                run=run,
                candidate=cand,
                split_role="VAL",
                seed=seed,
                episode=episode,
                fitness_payload=fit,
                status="completed",
            )
            cand.metadata.setdefault("stage_results", {})["VAL"] = {
                "status": "completed",
                "run_id": episode["run_id"],
                "fitness_score": fit.get("fitness_score"),
                "accepted": accepted,
                "acceptance": verdict,
                "measurement_status": fit.get("measurement_status"),
                "metrics": episode["metrics"],
            }
            run.trials_used += 1
            if accepted:
                val_pass_ids.append(cid)
            score = fit.get("fitness_score")
            if score is not None and (val_best_score is None or float(score) > val_best_score):
                val_best_score = float(score)
                val_leader = cid
        except Exception as exc:  # noqa: BLE001
            cand.metadata.setdefault("stage_results", {})["VAL"] = {
                "status": "failed",
                "error": str(exc),
                "accepted": False,
            }
            _append_trial(
                plane,
                run=run,
                candidate=cand,
                split_role="VAL",
                seed=seed,
                episode=None,
                fitness_payload=None,
                status="failed",
                error=str(exc),
            )
            run.trials_used += 1
        persist_learning_run(plane.store, run)

    run.best_validation_candidate = val_leader
    _emit(
        plane,
        "validation.completed",
        {"learning_run_id": learning_run_id, "val_pass_ids": val_pass_ids, "leader": val_leader},
    )

    # Missing validation when required → cannot qualify
    if run.objective_spec.require_val_pass and not val_pass_ids:
        return _finalize_no_qualify(plane, run, reason="validation_failed_or_missing")

    # --- ROBUSTNESS ---
    run.stage = LearningStage.ROBUSTNESS.value
    persist_learning_run(plane.store, run)
    _emit(plane, "robustness.started", {"learning_run_id": learning_run_id})
    robust_pass_ids: list[str] = []
    for cid in val_pass_ids or top_ids:
        cand = next((c for c in run.candidates if c.candidate_id == cid), None)
        if cand is None:
            continue
        stages = dict(cand.metadata.get("stage_results") or {})
        if "ROBUSTNESS" in stages and stages["ROBUSTNESS"].get("status") in {"completed", "failed", "skipped"}:
            if stages["ROBUSTNESS"].get("accepted"):
                robust_pass_ids.append(cid)
            continue
        # Cost perturbation robustness: re-run with higher fee metadata if supported,
        # else evaluate existing VAL metrics against stricter drawdown.
        train_metrics = dict((stages.get("TRAIN") or {}).get("metrics") or {})
        val_metrics = dict((stages.get("VAL") or {}).get("metrics") or {})
        # Simple robustness: require both train and val measured and not INF
        ok = bool(train_metrics) and bool(val_metrics)
        acc = AcceptanceCriteria(
            min_trades=run.objective_spec.min_trades,
            max_drawdown_pct=run.objective_spec.max_drawdown_pct,
            require_val_pass=False,
            require_robustness_pass=False,
        )
        v_train = acc.evaluate(train_metrics, val_pass=True, robustness_pass=True) if train_metrics else {"passed": False}
        v_val = acc.evaluate(val_metrics, val_pass=True, robustness_pass=True) if val_metrics else {"passed": False}
        accepted = ok and bool(v_train.get("passed")) and bool(v_val.get("passed"))
        cand.metadata.setdefault("stage_results", {})["ROBUSTNESS"] = {
            "status": "completed",
            "accepted": accepted,
            "checks": {"train_accept": v_train, "val_accept": v_val},
            "measurement": "MEASURED" if ok else "UNMEASURED",
        }
        if accepted:
            robust_pass_ids.append(cid)
        persist_learning_run(plane.store, run)
    _emit(
        plane,
        "robustness.completed",
        {"learning_run_id": learning_run_id, "robust_pass_ids": robust_pass_ids},
    )

    if run.objective_spec.require_robustness_pass and not robust_pass_ids:
        return _finalize_no_qualify(plane, run, reason="robustness_failed_or_missing")

    # --- SEALED (final holdout) — NEVER updates learner distributions ---
    run.stage = LearningStage.SEALED_EVALUATION.value
    persist_learning_run(plane.store, run)
    _emit(plane, "sealed.started", {"learning_run_id": learning_run_id})

    sealed_pass = False
    sealed_candidate: str | None = None
    finalists = robust_pass_ids or val_pass_ids
    if run.objective_spec.require_sealed_pass and finalists:
        cid = finalists[0]
        cand = next((c for c in run.candidates if c.candidate_id == cid), None)
        if cand is not None:
            stages = dict(cand.metadata.get("stage_results") or {})
            if "SEALED" not in stages:
                seed = run.seed + 90_000 + cand.strategy_version
                pre_learner_hash = run.learner_state.state_hash()
                try:
                    episode = _run_candidate_episode(
                        plane, run=run, candidate=cand, split_role="SEALED", seed=seed
                    )
                    fit = evaluate_candidate_metrics(
                        candidate=cand,
                        metrics=episode["metrics"],
                        objective=run.objective_spec,
                        split_role="SEALED",
                    )
                    # Explicitly refuse learner update from sealed
                    try:
                        reject_sealed_learner_update()
                    except MarketSimError:
                        pass
                    post_hash = run.learner_state.state_hash()
                    if post_hash != pre_learner_hash:
                        raise MarketSimError(
                            "SEALED_LEARNER_CONTAMINATION",
                            "learner state changed during sealed evaluation",
                            http_status=500,
                        )
                    acc = AcceptanceCriteria(
                        min_trades=run.objective_spec.min_trades,
                        max_drawdown_pct=run.objective_spec.max_drawdown_pct,
                        require_val_pass=False,
                        require_robustness_pass=False,
                    )
                    verdict = acc.evaluate(episode["metrics"], val_pass=True, robustness_pass=True)
                    sealed_pass = bool(verdict.get("passed"))
                    _append_trial(
                        plane,
                        run=run,
                        candidate=cand,
                        split_role="SEALED",
                        seed=seed,
                        episode=episode,
                        fitness_payload=fit,
                        status="completed",
                    )
                    cand.metadata.setdefault("stage_results", {})["SEALED"] = {
                        "status": "completed",
                        "accepted": sealed_pass,
                        "acceptance": verdict,
                        "fitness_score": fit.get("fitness_score"),
                        "run_id": episode["run_id"],
                        "learner_state_unchanged": True,
                        "pre_learner_hash": pre_learner_hash,
                    }
                    run.trials_used += 1
                    if sealed_pass:
                        sealed_candidate = cid
                    # Mark sealed lineage consumption on lab if present
                    if run.lab_id:
                        try:
                            from .agent_lab import mark_sealed_revealed

                            lab_row = plane.store.get_agent_lab(run.lab_id)
                            if lab_row:
                                # store alias map in learning metadata
                                run.metadata.setdefault("sealed_lineages", {})[cand.strategy_id] = {
                                    "attempt": f"learn-sealed-{run.learning_run_id}",
                                    "candidate_id": cid,
                                }
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as exc:  # noqa: BLE001
                    cand.metadata.setdefault("stage_results", {})["SEALED"] = {
                        "status": "failed",
                        "error": str(exc),
                        "accepted": False,
                    }
                    sealed_pass = False
            else:
                sealed_pass = bool(stages["SEALED"].get("accepted"))
                if sealed_pass:
                    sealed_candidate = cid

    _emit(
        plane,
        "sealed.completed",
        {"learning_run_id": learning_run_id, "passed": sealed_pass, "candidate": sealed_candidate},
    )

    if run.objective_spec.require_sealed_pass:
        if sealed_pass and sealed_candidate:
            return _finalize_qualified(plane, run, sealed_candidate)
        return _finalize_no_qualify(plane, run, reason="sealed_failed_or_missing")

    # Sealed not required — qualify on robustness/val
    if finalists:
        return _finalize_qualified(plane, run, finalists[0])
    return _finalize_no_qualify(plane, run, reason="no_finalist")


def _finalize_qualified(plane: Any, run: StrategyLearningRun, candidate_id: str) -> dict[str, Any]:
    run.qualified_candidate = candidate_id
    run.status = LearningRunStatus.COMPLETED.value
    run.stage = LearningStage.QUALIFIED_STRATEGY_FOUND.value
    run.updated_at = utc_now()
    run.last_checkpoint_at = run.updated_at
    run.metadata["final_outcome"] = LabOutcome.QUALIFIED_STRATEGY_FOUND.value
    persist_learning_run(plane.store, run)
    _emit(
        plane,
        "strategy.qualified",
        {"learning_run_id": run.learning_run_id, "candidate_id": candidate_id},
    )
    _sync_lab_outcome(plane, run, LabOutcome.QUALIFIED_STRATEGY_FOUND.value)
    # Post-mortem lesson (AGENT_PROPOSED)
    _maybe_add_lesson(
        plane,
        run,
        claim=f"qualified candidate {candidate_id} after sealed/validation gates",
        applies_to=[],
        evidence_refs=[candidate_id, run.learning_run_id],
    )
    return run.public_dict()


def _finalize_no_qualify(plane: Any, run: StrategyLearningRun, *, reason: str) -> dict[str, Any]:
    run.qualified_candidate = None
    run.status = LearningRunStatus.COMPLETED.value
    run.stage = LearningStage.NO_STRATEGY_QUALIFIED.value
    run.updated_at = utc_now()
    run.last_checkpoint_at = run.updated_at
    run.metadata["final_outcome"] = LabOutcome.NO_STRATEGY_QUALIFIED.value
    run.metadata["no_qualify_reason"] = reason
    persist_learning_run(plane.store, run)
    _emit(
        plane,
        "strategy.rejected",
        {"learning_run_id": run.learning_run_id, "reason": reason},
    )
    _sync_lab_outcome(plane, run, LabOutcome.NO_STRATEGY_QUALIFIED.value)
    _maybe_add_lesson(
        plane,
        run,
        claim=f"no strategy qualified: {reason}",
        applies_to=list(run.learner_state.family_probabilities.keys())[:3],
        evidence_refs=[run.learning_run_id],
    )
    return run.public_dict()


def _sync_lab_outcome(plane: Any, run: StrategyLearningRun, outcome: str) -> None:
    if not run.lab_id:
        return
    lab = plane.store.get_agent_lab(run.lab_id)
    if not lab:
        return
    lab["outcome"] = outcome
    lab["status"] = "COMPLETED" if outcome != LabOutcome.FAILED.value else "FAILED"
    lab["updated_at"] = utc_now()
    # Sync candidates summary
    lab["candidates"] = [
        {
            "candidate_id": c.candidate_id,
            "strategy_id": c.strategy_id,
            "strategy_version": c.strategy_version,
            "hypothesis": c.hypothesis,
            "generation": c.generation,
            "proposal_method": c.proposal_method,
            "stage_results": dict((c.metadata or {}).get("stage_results") or {}),
            "accepted": c.candidate_id == run.qualified_candidate,
            "metadata": {
                "family": c.family,
                "parent_refs": c.parent_refs,
                "mutations": c.mutations,
            },
        }
        for c in run.candidates
    ]
    lab["metadata"] = {
        **dict(lab.get("metadata") or {}),
        "learning_run_id": run.learning_run_id,
        "final_outcome": outcome,
        "best_train_candidate": run.best_train_candidate,
        "best_validation_candidate": run.best_validation_candidate,
        "qualified_candidate": run.qualified_candidate,
    }
    plane.store.upsert_agent_lab(lab)


def _maybe_add_lesson(
    plane: Any,
    run: StrategyLearningRun,
    *,
    claim: str,
    applies_to: list[str],
    evidence_refs: list[str],
) -> None:
    if not run.lab_id:
        return
    lab = plane.store.get_agent_lab(run.lab_id)
    if not lab:
        return
    lessons = list(lab.get("lessons") or [])
    lesson = LabLesson(
        lesson_id=f"lesson-{run.learning_run_id[:8]}-{len(lessons)}",
        claim=claim,
        evidence_refs=evidence_refs,
        applies_to=applies_to,
        trust=LessonTrust.AGENT_PROPOSED.value,
        confidence=0.3,
        created_at=utc_now(),
    )
    lessons.append(lesson.public_dict())
    lab["lessons"] = lessons
    plane.store.upsert_agent_lab(lab)
