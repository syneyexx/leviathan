"""Bounded learning-cycle state machine.

Stages are durable. A crash resumes from the last completed stage and does not replay
irreversible operations (holdout consumption is never automatic). The cycle is a scientific
research loop, not a profit-seeking bot: budgets stop it, sealed data stays sealed, and
development winners cannot install themselves as Champion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from trading_lab.champions import evaluate_challenger, scope_key
from trading_lab.contracts import StrategySpec, utc_iso
from trading_lab.evolution import (
    DEFAULT_BUDGETS,
    candidate_fingerprint,
    generation_of,
    materialize_candidate,
    mutate_from_findings,
)
from trading_lab.experience import ingest_resolved_decisions
from trading_lab.learning import (
    LEARNING_SPLITS,
    MIN_SAMPLES_FOR_FINDING,
    aggregate_experiences,
    apply_curator_output,
    compact_findings,
    finding_to_belief_proposal,
    retrieve_beliefs,
)

AUTONOMY_LEVELS = ("off", "learn_only", "propose", "research", "auto_research")
AUTONOMY_RANK = {name: index for index, name in enumerate(AUTONOMY_LEVELS)}

STAGES = (
    "queued",
    "collecting",
    "aggregating",
    "curating",
    "generating",
    "experimenting",
    "validating",
    "comparing",
    "completed",
    "cancelled",
    "failed",
)

IRREVERSIBLE_STAGES = {"validating"}  # holdout is still never auto-consumed


def normalize_autonomy(value: Any, *, default: str = "off") -> str:
    text = str(value or default).strip().lower().replace("-", "_")
    return text if text in AUTONOMY_RANK else default


def autonomy_at_least(current: str, required: str) -> bool:
    return AUTONOMY_RANK.get(normalize_autonomy(current), 0) >= AUTONOMY_RANK.get(required, 99)


class LearningCycleEngine:
    def __init__(
        self,
        store: Any,
        *,
        runner: Any | None = None,
        registry: Any | None = None,
        chat: Callable[..., Any] | None = None,
        model_id: str = "",
    ) -> None:
        self.store = store
        self.runner = runner
        self.registry = registry
        self.chat = chat
        self.model_id = model_id

    def start(
        self,
        *,
        objective: str = "",
        autonomy_level: str = "off",
        parent_strategy_ids: list[str] | None = None,
        budget: dict[str, Any] | None = None,
        allow_sealed_holdout: bool = False,
    ) -> dict[str, Any]:
        level = normalize_autonomy(autonomy_level)
        if level == "off":
            # Explicit start is allowed even when the default setting is OFF: the operator
            # asked for this cycle. The *setting* stays OFF; this cycle records its own level.
            level = "learn_only"
        return self.store.create_learning_cycle(
            {
                "objective": objective or "Iterate on completed simulation evidence",
                "autonomy_level": level,
                "parent_strategy_ids": parent_strategy_ids or [],
                "budget": {**DEFAULT_BUDGETS, **(budget or {}), "allow_sealed_holdout": bool(allow_sealed_holdout)},
                "status": "queued",
                "stage": "queued",
            }
        )

    def run(self, cycle_id: str, *, cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
        cycle = self.store.get_learning_cycle(cycle_id)
        if cycle is None:
            raise ValueError(f"unknown_learning_cycle:{cycle_id}")
        if cycle.get("status") in {"completed", "cancelled"}:
            return cycle
        checkpoint = dict(cycle.get("checkpoint") or {})
        done = set(checkpoint.get("stages_done") or [])
        try:
            self._set(cycle_id, status="collecting", stage="collecting", started_at=cycle.get("started_at") or utc_iso(datetime.now(tz=UTC)))
            if "collecting" not in done:
                if cancelled and cancelled():
                    return self._cancel(cycle_id)
                collect = self._collect(cycle)
                checkpoint["collect"] = collect
                done.add("collecting")
                self._checkpoint(cycle_id, checkpoint, done)
            self._set(cycle_id, status="aggregating", stage="aggregating")
            if "aggregating" not in done:
                findings = self._aggregate(cycle)
                checkpoint["finding_ids"] = [item["finding_id"] for item in findings]
                done.add("aggregating")
                self._checkpoint(cycle_id, checkpoint, done)
            else:
                findings = self.store.list_learning_findings(cycle_id=cycle_id, limit=200)
            self._set(cycle_id, status="curating", stage="curating")
            if "curating" not in done:
                curated = self._curate(cycle, findings)
                checkpoint["curation"] = {key: curated.get(key) for key in ("accepted_count", "rejected_count", "token_usage", "used_llm")}
                done.add("curating")
                self._checkpoint(cycle_id, checkpoint, done)
            level = normalize_autonomy(cycle.get("autonomy_level"))
            if not autonomy_at_least(level, "propose"):
                report = self._report(cycle_id, checkpoint, stopped_at="learn_only")
                return self._finish(cycle_id, report)
            self._set(cycle_id, status="generating", stage="generating")
            if "generating" not in done:
                generated = self._generate(cycle, findings, checkpoint)
                checkpoint["generated"] = generated
                done.add("generating")
                self._checkpoint(cycle_id, checkpoint, done)
            if not autonomy_at_least(level, "research"):
                report = self._report(cycle_id, checkpoint, stopped_at="propose")
                return self._finish(cycle_id, report)
            self._set(cycle_id, status="experimenting", stage="experimenting")
            if "experimenting" not in done:
                if cancelled and cancelled():
                    return self._cancel(cycle_id)
                experimented = self._experiment(cycle, checkpoint)
                checkpoint["experimented"] = experimented
                done.add("experimenting")
                self._checkpoint(cycle_id, checkpoint, done)
            if autonomy_at_least(level, "auto_research"):
                self._set(cycle_id, status="validating", stage="validating")
                if "validating" not in done:
                    validated = self._validate(cycle, checkpoint)
                    checkpoint["validated"] = validated
                    done.add("validating")
                    self._checkpoint(cycle_id, checkpoint, done)
            self._set(cycle_id, status="comparing", stage="comparing")
            if "comparing" not in done:
                compared = self._compare(cycle, checkpoint)
                checkpoint["compared"] = compared
                done.add("comparing")
                self._checkpoint(cycle_id, checkpoint, done)
            report = self._report(cycle_id, checkpoint, stopped_at="completed")
            return self._finish(cycle_id, report)
        except Exception as exc:  # noqa: BLE001 - cycles fail honestly
            self.store.update_learning_cycle(
                cycle_id,
                status="failed",
                stage="failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
                finished_at=utc_iso(datetime.now(tz=UTC)),
                checkpoint={**checkpoint, "stages_done": sorted(done)},
            )
            return self.store.get_learning_cycle(cycle_id) or {"cycle_id": cycle_id, "status": "failed"}

    # --- stages -------------------------------------------------------------------

    def _collect(self, cycle: dict[str, Any]) -> dict[str, Any]:
        ingest = ingest_resolved_decisions(self.store, engine_version="trading-lab-engine-1")
        parents = list(cycle.get("parent_strategy_ids") or [])
        snapshot = {
            "experiences": self.store.count_experiences(split="development"),
            "ingested": ingest,
            "parent_strategy_ids": parents,
        }
        self.store.update_learning_cycle(cycle["cycle_id"], evidence_snapshot=snapshot)
        return snapshot

    def _aggregate(self, cycle: dict[str, Any]) -> list[dict[str, Any]]:
        parents = list(cycle.get("parent_strategy_ids") or [])
        rows: list[dict[str, Any]] = []
        if parents:
            for strategy_id in parents:
                rows.extend(self.store.list_experiences(strategy_id=strategy_id, split="development", limit=20000))
        else:
            rows = self.store.list_experiences(split="development", limit=20000)
        # Holdout / validation rows are never mixed into the mutation set.
        rows = [row for row in rows if row.get("split") in LEARNING_SPLITS]
        findings = aggregate_experiences(rows, include_version=True, min_samples=MIN_SAMPLES_FOR_FINDING)
        family_findings = aggregate_experiences(rows, include_version=False, min_samples=MIN_SAMPLES_FOR_FINDING)
        all_findings = findings + family_findings
        saved = []
        for finding in all_findings:
            finding["cycle_id"] = cycle["cycle_id"]
            self.store.save_learning_finding(finding)
            saved.append(finding)
        accepted = [item["finding_id"] for item in saved if item.get("evidence_status") == "sufficient"]
        rejected = [item["finding_id"] for item in saved if item.get("evidence_status") != "sufficient"]
        self.store.update_learning_cycle(cycle["cycle_id"], accepted_findings=accepted, rejected_findings=rejected)
        return saved

    def _curate(self, cycle: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        now = utc_iso(datetime.now(tz=UTC))
        proposals = []
        for finding in findings:
            proposal = finding_to_belief_proposal(finding, now=now)
            if proposal:
                proposal["source_cycle_id"] = cycle["cycle_id"]
                stored = self.store.upsert_trading_belief(proposal)
                proposals.append(stored)
        used_llm = False
        token_usage = {}
        accepted_count = len(proposals)
        rejected_count = 0
        if self.chat and self.model_id:
            curated = self._run_curator(cycle, findings, proposals)
            used_llm = bool(curated.get("used_llm"))
            token_usage = curated.get("token_usage") or {}
            accepted_count += int(curated.get("accepted_count") or 0)
            rejected_count += int(curated.get("rejected_count") or 0)
        return {
            "beliefs_written": len(proposals),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "used_llm": used_llm,
            "token_usage": token_usage,
        }

    def _run_curator(self, cycle: dict[str, Any], findings: list[dict[str, Any]], beliefs: list[dict[str, Any]]) -> dict[str, Any]:
        from trading_lab.agents import AgentContext, AgentTeam

        compact = compact_findings(findings, limit=12)
        prior = retrieve_beliefs(beliefs, limit=8)
        allowed_refs: set[str] = set()
        for item in compact:
            allowed_refs.add(f"finding:{item.get('finding_id')}")
            for ref in item.get("evidence_refs") or []:
                allowed_refs.add(str(ref))
        facts = {
            "mode": "SIMULATION / PAPER — no real money",
            "cycle_id": cycle["cycle_id"],
            "objective": cycle.get("objective"),
            "findings": compact,
            "prior_beliefs": prior,
            "limitations": [
                "You may not invent evidence references.",
                "Sealed holdout contents are not in this context and must not be assumed.",
                "Insufficient-evidence findings are not durable knowledge.",
                "Do not collapse regime-conditional results into a global 'strategy is good'.",
            ],
        }
        team = AgentTeam(self.chat, default_model=self.model_id, max_concurrency=1)
        context = AgentContext(
            question=(
                "Interpret the aggregated findings. Confirm, weaken, contradict or retire prior beliefs "
                "only with cited evidence. Suggest bounded candidate mutations, not arbitrary code."
            ),
            facts=facts,
            constraints=[
                "Every claim needs at least one evidence_ref from FACTS.",
                "Do not compute new metrics; use the numbers given.",
                "Negative evidence is first-class.",
            ],
            max_fact_chars=8000,
        )
        import asyncio

        try:
            result = asyncio.run(team.run_role("learning_curator", context, run_id=cycle["cycle_id"]))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(team.run_role("learning_curator", context, run_id=cycle["cycle_id"]))
            finally:
                loop.close()
        if result.status not in {"completed", "incomplete"} or not result.output:
            return {"used_llm": True, "accepted_count": 0, "rejected_count": 1, "token_usage": {"prompt_hash": result.prompt_hash}, "error": result.error}
        verdict = apply_curator_output(result.output, allowed_refs=allowed_refs, findings=findings, prior_beliefs=beliefs)
        applied = 0
        for item in verdict["accepted"]:
            if item.get("open_question"):
                self.store.add_open_question(cycle["cycle_id"], item["claim"], item.get("evidence_refs") or [])
                continue
            if item.get("bucket") == "candidate_suggestions":
                self.store.save_cycle_suggestion(cycle["cycle_id"], item)
                continue
            if item.get("belief_id"):
                self.store.update_trading_belief_status(
                    item["belief_id"],
                    status=item.get("suggested_status") or "supported",
                    actor="learning_curator",
                    reason=item.get("claim") or "",
                    evidence_refs=item.get("evidence_refs") or [],
                )
                applied += 1
            elif item.get("bucket") == "new_findings" and item.get("evidence_refs"):
                self.store.upsert_trading_belief(
                    {
                        "claim": item["claim"],
                        "scope": item.get("applies_to") or {},
                        "evidence_refs": item["evidence_refs"],
                        "status": "proposed",
                        "confidence": 0.2,
                        "confidence_cap": 0.45,
                        "source_cycle_id": cycle["cycle_id"],
                        "supporting_count": 0,
                        "contradicting_count": 0,
                    }
                )
                applied += 1
        return {
            "used_llm": True,
            "accepted_count": applied,
            "rejected_count": len(verdict["rejected"]),
            "token_usage": {"prompt_hash": result.prompt_hash, "model_id": result.model_id},
            "rejected": verdict["rejected"][:20],
        }

    def _generate(self, cycle: dict[str, Any], findings: list[dict[str, Any]], checkpoint: dict[str, Any]) -> dict[str, Any]:
        budget = dict(cycle.get("budget") or DEFAULT_BUDGETS)
        parents = list(cycle.get("parent_strategy_ids") or [])
        if not parents:
            parents = sorted(
                {
                    str((item.get("group") or {}).get("strategy_id"))
                    for item in findings
                    if (item.get("group") or {}).get("strategy_id")
                }
            )
        known = {row["fingerprint"] for row in self.store.list_candidate_fingerprints()}
        failed = {row["fingerprint"] for row in self.store.list_candidate_fingerprints(status="rejected")}
        lineage = self.store.list_strategy_lineage(limit=2000)
        created = []
        rejected = []
        for strategy_id in parents[:8]:
            record = self.store.get_strategy(strategy_id)
            version = self.store.get_strategy_version(strategy_id)
            if record is None or version is None:
                rejected.append({"reason": "unknown_strategy", "strategy_id": strategy_id})
                continue
            spec = StrategySpec.model_validate(version["spec"])
            generation = generation_of(lineage, strategy_id, int(version.get("version") or spec.version))
            relevant = [
                item
                for item in findings
                if (item.get("group") or {}).get("strategy_id") in {None, strategy_id}
                or (item.get("group") or {}).get("strategy_family") == spec.family
            ]
            beliefs = self.store.list_trading_beliefs(strategy_family=spec.family, limit=40)
            result = mutate_from_findings(
                spec,
                relevant,
                beliefs=beliefs,
                budget=budget,
                known_fingerprints=known,
                failed_fingerprints=failed,
                dataset_checksum=(relevant[0].get("group") or {}).get("dataset_checksum", "") if relevant else "",
                generation=generation,
            )
            rejected.extend(result["rejected"])
            for proposal in result["candidates"]:
                child = materialize_candidate(spec, proposal)
                if self.registry is None:
                    rejected.append({"reason": "registry_unavailable", "fingerprint": proposal["fingerprint"]})
                    continue
                version_no = self.registry.add_version(strategy_id, child, created_by="evolution_engine")
                known.add(proposal["fingerprint"])
                candidate = self.store.save_strategy_candidate(
                    {
                        **proposal,
                        "cycle_id": cycle["cycle_id"],
                        "strategy_id": strategy_id,
                        "strategy_version": version_no,
                        "spec": child.as_json(),
                        "status": "proposed",
                    }
                )
                self.store.save_strategy_lineage(
                    {
                        "parent_strategy_id": strategy_id,
                        "parent_version": spec.version,
                        "child_strategy_id": strategy_id,
                        "child_version": version_no,
                        "mutation_kind": proposal["mutation_kind"],
                        "mutation_reason": proposal["mutation_reason"],
                        "changed_fields": proposal["changed_fields"],
                        "belief_refs": proposal.get("belief_refs") or [],
                        "evidence_refs": proposal.get("evidence_refs") or [],
                        "created_by": "evolution_engine",
                        "generation": generation,
                        "fingerprint": proposal["fingerprint"],
                    }
                )
                created.append(candidate)
        ids = [item.get("candidate_id") for item in created if item.get("candidate_id")]
        self.store.update_learning_cycle(cycle["cycle_id"], generated_candidates=ids)
        return {"created": len(created), "rejected": rejected[:30], "candidate_ids": ids}

    def _experiment(self, cycle: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
        if self.runner is None:
            return {"status": "skipped", "reason": "experiment_runner_unavailable"}
        budget = dict(cycle.get("budget") or DEFAULT_BUDGETS)
        max_experiments = int(budget.get("max_experiments_per_cycle") or 2)
        max_combos = int(budget.get("max_parameter_combinations") or 8)
        already = set(checkpoint.get("experimented", {}).get("experiment_ids") or cycle.get("experiment_ids") or [])
        candidates = [
            item
            for item in self.store.list_strategy_candidates(cycle_id=cycle["cycle_id"], limit=50)
            if item.get("status") == "proposed"
        ]
        ran = []
        for candidate in candidates[:max_experiments]:
            spec_payload = candidate.get("spec") or {}
            try:
                spec = StrategySpec.model_validate(spec_payload)
            except Exception as exc:  # noqa: BLE001
                self.store.update_strategy_candidate(candidate["candidate_id"], status="rejected", rejection_reason=f"invalid_spec:{exc}")
                continue
            fingerprint = candidate.get("fingerprint") or candidate_fingerprint(
                family=spec.family,
                params=spec.params,
                instruments=spec.instruments,
                timeframe=spec.timeframe,
            )
            existing = self.store.find_candidate_by_fingerprint(fingerprint)
            if existing and existing.get("candidate_id") != candidate.get("candidate_id") and existing.get("experiment_id"):
                self.store.update_strategy_candidate(
                    candidate["candidate_id"],
                    status="reused",
                    reuse_of=existing["candidate_id"],
                    rejection_reason="identical fingerprint already evaluated; evidence reused",
                )
                continue
            from trading_lab.research import experiment_defaults
            from trading_lab.contracts import ExperimentSpec

            payload = experiment_defaults(spec.family)
            dataset_ids: list[str] = []
            for instrument_id in spec.instruments:
                datasets = self.store.list_datasets(instrument_id=instrument_id, limit=3)
                usable = [item for item in datasets if not item.get("is_synthetic")] or datasets
                if usable:
                    dataset_ids.append(usable[0]["dataset_id"])
            if not dataset_ids:
                self.store.update_strategy_candidate(
                    candidate["candidate_id"],
                    status="rejected",
                    rejection_reason="no_dataset_for_candidate_instruments",
                )
                continue
            payload.update(
                {
                    "title": f"learning cycle {cycle['cycle_id']} · {spec.name}",
                    "strategy_family": spec.family,
                    "instruments": list(spec.instruments),
                    "timeframe": spec.timeframe,
                    "dataset_ids": dataset_ids,
                    "split": "development",
                    "search_method": "single",
                    "search_budget": min(1, max_combos) or 1,
                    "param_space": {},
                    "fixed_params": spec.params,
                    "requested_by": "learning_cycle",
                }
            )

            experiment_spec = ExperimentSpec.model_validate(payload)
            experiment_id = self.store.create_experiment(experiment_spec, strategy_id=candidate["strategy_id"])
            already.add(experiment_id)
            outcome = self.runner.run_experiment(
                experiment_spec,
                experiment_id=experiment_id,
                base_strategy=spec,
            )
            self.store.update_experiment(experiment_id, status=outcome.get("status", "completed"), result=outcome)
            ingest_resolved_decisions(self.store, experiment_id=experiment_id, engine_version="trading-lab-engine-1")
            metrics = ((outcome.get("best") or {}).get("metrics") or {}) if isinstance(outcome, dict) else {}
            expectancy = metrics.get("net_return")
            status = "tested"
            rejection = ""
            if outcome.get("status") != "completed":
                status = "rejected"
                rejection = str(outcome.get("error") or "experiment_failed")
            elif metrics.get("insufficient_evidence"):
                status = "rejected"
                rejection = "insufficient_evidence_on_development"
            elif expectancy is not None and float(expectancy) < 0:
                status = "rejected"
                rejection = f"negative_development_net_return:{expectancy}"
            self.store.update_strategy_candidate(
                candidate["candidate_id"],
                status=status,
                experiment_id=experiment_id,
                rejection_reason=rejection,
            )
            ran.append({"candidate_id": candidate["candidate_id"], "experiment_id": experiment_id, "status": status, "rejection": rejection})
        ids = sorted(already)
        self.store.update_learning_cycle(cycle["cycle_id"], experiment_ids=ids)
        return {"experiment_ids": ids, "ran": ran}

    def _validate(self, cycle: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
        budget = dict(cycle.get("budget") or {})
        if budget.get("allow_sealed_holdout"):
            # Still refuse automatic sealed consumption. The flag is recorded so an operator
            # can later run sealed confirmation through the existing registry gate.
            pass
        if self.runner is None:
            return {"status": "skipped", "reason": "runner_unavailable"}
        tested = [
            item
            for item in self.store.list_strategy_candidates(cycle_id=cycle["cycle_id"], limit=50)
            if item.get("status") == "tested"
        ]
        reports = []
        for candidate in tested[: int(budget.get("max_experiments_per_cycle") or 2)]:
            version = self.store.get_strategy_version(candidate["strategy_id"], candidate.get("strategy_version"))
            if version is None:
                continue
            spec = StrategySpec.model_validate(version["spec"])
            report_id = f"ev_learn_{candidate['candidate_id'][:12]}"
            outcome = self.runner.evaluate(
                spec,
                report_id=report_id,
                split="validation",
                folds=3,
                search_trials_considered=max(1, self.store.count_trials(strategy_id=candidate["strategy_id"]) or 1),
                evaluated_by="learning_cycle_auto_research",
                include_stress=False,
            )
            if outcome.get("status") != "completed":
                self.store.update_strategy_candidate(
                    candidate["candidate_id"],
                    status="rejected",
                    rejection_reason=str(outcome.get("error") or "validation_failed"),
                )
                continue
            report = outcome["report"]
            # automatic_gate is not independent_validator; champion policy still requires
            # independent validation for replacement. AUTO_RESEARCH may *request* it.
            report.evaluated_by = "learning_cycle_auto_research"
            report.evaluator_role = "automatic_gate"
            self.store.save_evaluation(report)
            verdict = report.verdict
            status = "validated" if verdict == "pass" else "rejected"
            self.store.update_strategy_candidate(
                candidate["candidate_id"],
                status=status,
                evaluation_id=report.report_id,
                rejection_reason="" if verdict == "pass" else f"validation_{verdict}",
            )
            reports.append({"candidate_id": candidate["candidate_id"], "report_id": report.report_id, "verdict": verdict})
        ids = [item["report_id"] for item in reports]
        self.store.update_learning_cycle(cycle["cycle_id"], evaluation_ids=ids)
        return {"reports": reports, "note": "sealed_test was not consumed"}

    def _compare(self, cycle: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
        changes = []
        candidates = self.store.list_strategy_candidates(cycle_id=cycle["cycle_id"], limit=50)
        for candidate in candidates:
            strategy = self.store.get_strategy(candidate["strategy_id"])
            if strategy is None:
                continue
            version = self.store.get_strategy_version(candidate["strategy_id"], candidate.get("strategy_version"))
            spec = (version or {}).get("spec") or {}
            instrument = (spec.get("instruments") or [None])[0]
            key = scope_key(instrument_id=instrument, timeframe=spec.get("timeframe"), objective="net_after_costs")
            champion = self.store.get_active_champion(key)
            challenger_evals = self.store.list_evaluations(strategy_id=candidate["strategy_id"], limit=20)
            champion_evals = []
            if champion:
                champion_evals = self.store.list_evaluations(strategy_id=champion["strategy_id"], limit=20)
            decision = evaluate_challenger(
                challenger={
                    "status": strategy.get("status"),
                    "family": spec.get("family"),
                    "params": spec.get("params") or {},
                    "strategy_id": candidate["strategy_id"],
                    "strategy_version": candidate.get("strategy_version"),
                },
                champion=champion,
                challenger_evaluations=challenger_evals,
                champion_evaluations=champion_evals,
            )
            if decision["decision"] == "install" or decision["decision"] == "replace":
                record = self.store.install_champion(
                    {
                        "scope_key": key,
                        "scope": {
                            "instrument_id": instrument,
                            "timeframe": spec.get("timeframe"),
                            "objective": "net_after_costs",
                        },
                        "strategy_id": candidate["strategy_id"],
                        "strategy_version": candidate.get("strategy_version"),
                        "admission": decision,
                        "replaced_champion_id": (champion or {}).get("champion_id"),
                        "replaced_reason": decision.get("reason") or "",
                    }
                )
                changes.append({"decision": decision["decision"], "champion": record, "reasons": decision.get("reasons")})
            else:
                changes.append(
                    {
                        "decision": "reject",
                        "candidate_id": candidate.get("candidate_id"),
                        "reason": decision.get("reason"),
                        "reasons": decision.get("reasons"),
                    }
                )
                if candidate.get("status") not in {"rejected", "validated"}:
                    self.store.update_strategy_candidate(
                        candidate["candidate_id"],
                        rejection_reason=str(decision.get("reason") or "champion_policy_rejected"),
                    )
        self.store.update_learning_cycle(cycle["cycle_id"], champion_changes=changes)
        return {"changes": changes}

    def _report(self, cycle_id: str, checkpoint: dict[str, Any], *, stopped_at: str) -> dict[str, Any]:
        cycle = self.store.get_learning_cycle(cycle_id) or {}
        beliefs = self.store.list_trading_beliefs(limit=20)
        return {
            "cycle_id": cycle_id,
            "stopped_at": stopped_at,
            "autonomy_level": cycle.get("autonomy_level"),
            "experiences": (cycle.get("evidence_snapshot") or {}).get("experiences"),
            "findings_accepted": cycle.get("accepted_findings") or [],
            "findings_rejected": cycle.get("rejected_findings") or [],
            "candidates": cycle.get("generated_candidates") or [],
            "experiments": cycle.get("experiment_ids") or [],
            "evaluations": cycle.get("evaluation_ids") or [],
            "champion_changes": cycle.get("champion_changes") or [],
            "beliefs_preview": retrieve_beliefs(beliefs, limit=8),
            "checkpoint_stages": (checkpoint.get("stages_done") or []),
            "note": (
                "A later cycle starts with these beliefs already in the store. "
                "Sealed holdout was not consumed. This is simulation/paper only."
            ),
        }

    def _finish(self, cycle_id: str, report: dict[str, Any]) -> dict[str, Any]:
        return self.store.update_learning_cycle(
            cycle_id,
            status="completed",
            stage="completed",
            report=report,
            finished_at=utc_iso(datetime.now(tz=UTC)),
        ) or {"cycle_id": cycle_id, "status": "completed", "report": report}

    def _cancel(self, cycle_id: str) -> dict[str, Any]:
        return self.store.update_learning_cycle(
            cycle_id,
            status="cancelled",
            stage="cancelled",
            finished_at=utc_iso(datetime.now(tz=UTC)),
            failure_reason="cancelled_by_operator",
        ) or {"cycle_id": cycle_id, "status": "cancelled"}

    def _set(self, cycle_id: str, **fields: Any) -> None:
        self.store.update_learning_cycle(cycle_id, **fields)

    def _checkpoint(self, cycle_id: str, checkpoint: dict[str, Any], done: set[str]) -> None:
        checkpoint["stages_done"] = sorted(done)
        self.store.update_learning_cycle(cycle_id, checkpoint=checkpoint)


__all__ = [
    "AUTONOMY_LEVELS",
    "IRREVERSIBLE_STAGES",
    "LearningCycleEngine",
    "STAGES",
    "autonomy_at_least",
    "normalize_autonomy",
]
