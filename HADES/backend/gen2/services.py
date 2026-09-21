"""Gen2 service layer — working implementations for the ten strategic systems."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gen2 import agent_factory as agent_factory_mod
from gen2 import committee as committee_mod
from gen2 import compute_fabric as compute_fabric_mod
from gen2 import context_compiler as context_compiler_mod
from gen2 import dashboard as dashboard_mod
from gen2 import eval_lab as eval_lab_mod
from gen2 import finance_fusion as finance_fusion_mod
from gen2 import flight_recorder as flight_recorder_mod
from gen2 import mission_control as mission_control_mod
from gen2 import temporal_graph as temporal_graph_mod
from gen2 import workflows as workflows_mod
from gen2.mission_budget import MissionBudgetLedger
from gen2.mission_control import MISSION_TRANSITIONS, _VERIFICATION_NON_PASS
from gen2.sandbox import (
    SANDBOX_ACTIONS,
    available_sandbox_tiers,
    build_default_envelope,
    detect_host_sandbox_capabilities,
    enforce_envelope_policy,
    path_is_within,
    try_assign_job_object,
)
from gen2.store import Gen2Store
from gen2.workflow_adapters import WorkflowServices

# Back-compat alias — resolved dynamically from host probes.
AVAILABLE_SANDBOX_TIERS = available_sandbox_tiers()

# Re-export for callers that import from services.
COMPUTE_JOB_TYPES = compute_fabric_mod.COMPUTE_JOB_TYPES
# MISSION_TRANSITIONS / _VERIFICATION_NON_PASS re-exported from mission_control above.


def _path_is_within(candidate: Path, root: Path) -> bool:
    return path_is_within(candidate, root)


class Gen2Services:
    def __init__(
        self,
        store: Gen2Store,
        *,
        data_root: Path | None = None,
        artifact_service: Any | None = None,
    ) -> None:
        self.store = store
        self.data_root = Path(data_root or Path.home() / ".hades").expanduser()
        self.artifact_service = artifact_service
        self.coding_agent: Any | None = None
        self.research_runner: Any | None = None
        self.plugin_manager: Any | None = None
        self.platform_db: Any | None = None
        self.chat_fn: Any | None = None
        self.approval_service: Any | None = None
        self._budget = MissionBudgetLedger(
            get_mission=self.store.get_mission,
            update_mission=self.store.update_mission,
            record=self.record,
        )
        self.ensure_local_node()

    def set_artifact_service(self, artifact_service: Any | None) -> None:
        self.artifact_service = artifact_service

    def set_workflow_runtime(
        self,
        *,
        coding_agent: Any | None = None,
        research_runner: Any | None = None,
        plugin_manager: Any | None = None,
        platform_db: Any | None = None,
        chat_fn: Any | None = None,
        approval_service: Any | None = None,
        artifact_service: Any | None = None,
        data_root: Path | None = None,
    ) -> None:
        """Bind real product services for workflow product execution (A06)."""
        if coding_agent is not None:
            self.coding_agent = coding_agent
        if research_runner is not None:
            self.research_runner = research_runner
        if plugin_manager is not None:
            self.plugin_manager = plugin_manager
        if platform_db is not None:
            self.platform_db = platform_db
        if chat_fn is not None:
            self.chat_fn = chat_fn
        if approval_service is not None:
            self.approval_service = approval_service
        if artifact_service is not None:
            self.artifact_service = artifact_service
        if data_root is not None:
            self.data_root = Path(data_root)

    def workflow_services(self) -> WorkflowServices:
        return WorkflowServices(
            coding_agent=self.coding_agent,
            research_runner=self.research_runner,
            plugin_manager=self.plugin_manager,
            artifact_service=self.artifact_service,
            platform_db=self.platform_db,
            chat_fn=self.chat_fn,
            data_root=self.data_root,
            approval_service=self.approval_service,
        )

    @staticmethod
    def validate_mission_ir(ir: dict[str, Any]) -> list[str]:
        """Return human-readable IR validation errors (empty = valid)."""
        return mission_control_mod.validate_mission_ir(ir)

    def pending_gates_for_wave(self, mission: dict[str, Any], before_wave: int) -> list[dict[str, Any]]:
        return mission_control_mod.pending_gates_for_wave(mission, before_wave)

    def sync_mission_from_task(
        self,
        task_id: str,
        *,
        status: str,
        error: str | None = None,
        verification: dict[str, Any] | None = None,
        step_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Map Work Runtime terminal/blocked outcomes onto the linked mission.

        Completion is evidence-based: failed steps or failed verification cannot become
        ``completed`` even if the Work Runtime status string says completed.
        """
        return mission_control_mod.sync_mission_from_task(
            self.store,
            self.record,
            task_id,
            status=status,
            error=error,
            verification=verification,
            step_summary=step_summary,
            artifact_service=self.artifact_service,
        )

    def mission_budget_ledger(self, mission_id: str) -> dict[str, Any]:
        """Return shared mission budget reservation ledger (honest partial accounting)."""
        return self._budget.snapshot(mission_id)

    def reserve_mission_budget(
        self,
        mission_id: str,
        *,
        key: str,
        amount: float,
        step_id: str | None = None,
        reason: str = "reserve",
        idempotency_key: str | None = None,
        reservation_id: str | None = None,
    ) -> dict[str, Any]:
        """Reserve against the shared mission budget; fails when remaining is insufficient."""
        return self._budget.reserve(
            mission_id,
            key=key,
            amount=amount,
            step_id=step_id,
            reason=reason,
            idempotency_key=idempotency_key,
            reservation_id=reservation_id,
        )

    def consume_mission_budget(
        self,
        mission_id: str,
        *,
        key: str,
        amount: float,
        step_id: str | None = None,
        from_reservation: bool = True,
        reservation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._budget.consume(
            mission_id,
            key=key,
            amount=amount,
            step_id=step_id,
            from_reservation=from_reservation,
            reservation_id=reservation_id,
            idempotency_key=idempotency_key,
        )

    def release_mission_budget(
        self,
        mission_id: str,
        *,
        reservation_id: str,
        reason: str = "release",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._budget.release(
            mission_id,
            reservation_id=reservation_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def select_promoted_skill(self, prompt: str) -> dict[str, Any] | None:
        """Return a promoted skill whose name/workflow keywords match the prompt."""
        return agent_factory_mod.select_promoted_skill(self.store, prompt)

    async def run_model_eval(
        self,
        *,
        model_id: str,
        suite: str = "reasoning",
        chat_fn: Any | None = None,
        prompts: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Live-model evaluation via existing LM client. No invented scores."""
        return await eval_lab_mod.run_model_eval(
            self.store,
            model_id=model_id,
            suite=suite,
            chat_fn=chat_fn,
            prompts=prompts,
        )
    # ------------------------------------------------------------------ #
    # 2. Intelligence Evaluation Lab
    # ------------------------------------------------------------------ #
    def run_eval_lab(
        self,
        *,
        model_id: str | None = None,
        suite: str = "reasoning",
        mode: str = "deterministic_software",
        holdout_limit: int | None = None,
        seed: int | None = None,
        holdout_split: str | None = None,
    ) -> dict[str, Any]:
        """Run deterministic local software scenarios (not live model quality).

        ``model_id`` is an optional label only — no LM Studio call is made in this mode.
        Use ``suite=quality`` / ``mode=quality_suite`` for the ≥30 executable quality scenarios.
        """
        chat_fn = None
        # Optional: caller may attach chat_fn via instance attribute in tests.
        if callable(getattr(self, "_eval_chat_fn", None)):
            chat_fn = self._eval_chat_fn
        return eval_lab_mod.run_eval_lab(
            self.store,
            model_id=model_id,
            suite=suite,
            mode=mode,
            chat_fn=chat_fn,
            holdout_limit=holdout_limit,
            seed=seed,
            holdout_split=holdout_split,
        )

    @staticmethod
    def _task_type_for_scenario(scenario_id: str, title: str) -> str:
        return eval_lab_mod.task_type_for_scenario(scenario_id, title)

    def eval_reports(self, limit: int = 50) -> list[dict[str, Any]]:
        return eval_lab_mod.eval_reports(self.store, limit=limit)

    def eval_catalog(self) -> dict[str, Any]:
        return eval_lab_mod.list_eval_catalog()

    def eval_metrics_catalog(self) -> dict[str, Any]:
        return eval_lab_mod.metrics_catalog()

    def detect_flaky_cases(
        self, *, suite: str, mode: str | None = None, last_n: int = 5
    ) -> dict[str, Any]:
        return eval_lab_mod.detect_flaky_cases(self.store, suite=suite, mode=mode, last_n=last_n)

    def run_ab_experiment(
        self,
        *,
        strategy_a: str,
        strategy_b: str,
        suite: str = "reasoning",
        n: int = 3,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        return eval_lab_mod.run_ab_experiment(
            self.store,
            strategy_a=strategy_a,
            strategy_b=strategy_b,
            suite=suite,
            n=n,
            model_id=model_id,
        )

    def pr_help_summary(self, run_a: str, run_b: str) -> dict[str, Any]:
        return eval_lab_mod.pr_help_summary(self.store, run_a, run_b)

    def ingest_flight_recorder_run(self, run_id: str) -> dict[str, Any]:
        return eval_lab_mod.ingest_flight_recorder_run(self.store, run_id)

    def propose_regression_candidate_from_flight(
        self,
        run_id: str,
        *,
        expected_end_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from gen2.regression_candidates import build_regression_candidate_from_flight

        return build_regression_candidate_from_flight(
            self.store,
            run_id,
            expected_end_state=expected_end_state,
        )

    def run_effect_ledger_regression_case(self) -> dict[str, Any]:
        from gen2.regression_candidates import run_effect_ledger_contradiction_case

        return run_effect_ledger_contradiction_case()

    def capability_matrix(self) -> dict[str, Any]:
        return eval_lab_mod.capability_matrix(self.store)

    def recommend_model(self, task_type: str, metric: str = "pass") -> dict[str, Any]:
        return eval_lab_mod.recommend_model(self.store, task_type, metric=metric)

    # ------------------------------------------------------------------ #
    # 6. Context Compiler 2.0
    # ------------------------------------------------------------------ #
    def compile_context(
        self,
        *,
        goal: str,
        items: list[dict[str, Any]],
        max_tokens: int = 2048,
        model_context_size: int | None = None,
        run_id: str | None = None,
        persist: bool = True,
        response_reserve_tokens: int | None = None,
        system_reserve_tokens: int | None = None,
        request_budget_tokens: int | None = None,
        tokenizer_mode: str = "approx_chars_4",
        max_age_hours: float | None = None,
        hierarchical_summarization: bool = True,
        pin_overflow: str = "keep_with_note",
    ) -> dict[str, Any]:
        """Compile ranked context with approx tokenizer, dedupe, contradiction grouping, diversity."""
        return context_compiler_mod.compile_context(
            self.store,
            goal=goal,
            items=items,
            max_tokens=max_tokens,
            model_context_size=model_context_size,
            run_id=run_id,
            persist=persist,
            response_reserve_tokens=response_reserve_tokens,
            system_reserve_tokens=system_reserve_tokens,
            request_budget_tokens=request_budget_tokens,
            tokenizer_mode=tokenizer_mode,
            max_age_hours=max_age_hours,
            hierarchical_summarization=hierarchical_summarization,
            pin_overflow=pin_overflow,
        )

    def compile_context_for_chat(
        self,
        *,
        goal: str,
        items: list[dict[str, Any]],
        max_tokens: int = 2048,
        opt_in: bool | None = None,
        persist: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Opt-in Context Compiler for chat path — default path unchanged when disabled."""
        return context_compiler_mod.compile_for_chat_path(
            self.store,
            goal=goal,
            items=items,
            max_tokens=max_tokens,
            opt_in=opt_in,
            persist=persist,
            **kwargs,
        )

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return context_compiler_mod.estimate_tokens(text)

    @staticmethod
    def _entity_key(text: str) -> str:
        return context_compiler_mod.entity_key(text)

    # ------------------------------------------------------------------ #
    # 8. Flight Recorder
    # ------------------------------------------------------------------ #
    def record(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        model_id: str | None = None,
        component: str | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        parent_event_id: str | None = None,
        severity: str | None = None,
        duration_ms: float | None = None,
        correlation_id: str | None = None,
        config_fingerprint: str | None = None,
        model_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return flight_recorder_mod.record(
            self.store,
            run_id,
            event_type,
            payload,
            model_id=model_id,
            component=component,
            input_text=input_text,
            output_text=output_text,
            parent_event_id=parent_event_id,
            severity=severity,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            config_fingerprint=config_fingerprint,
            model_snapshot=model_snapshot,
        )

    def emit_run_lifecycle(
        self,
        run_id: str,
        phase: str,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return flight_recorder_mod.emit_run_lifecycle(self.store, run_id, phase, payload, **kwargs)

    def flight_log(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return flight_recorder_mod.flight_log(self.store, run_id, after_sequence=after_sequence)

    def compare_runs(self, run_a: str, run_b: str) -> dict[str, Any]:
        return flight_recorder_mod.compare_runs(self.store, run_a, run_b)

    def export_audit_bundle(self, run_id: str) -> dict[str, Any]:
        return flight_recorder_mod.export_audit_bundle(self.store, run_id)

    def export_reproducible_bundle(
        self,
        run_id: str,
        *,
        experiment: dict[str, Any] | None = None,
        include_events: bool = True,
    ) -> dict[str, Any]:
        from gen2 import correlation_telemetry as corr_mod

        return corr_mod.export_reproducible_bundle(
            self.store,
            run_id,
            experiment=experiment,
            include_events=include_events,
        )

    def human_run_summary(self, run_id: str) -> dict[str, Any]:
        from gen2 import correlation_telemetry as corr_mod

        return corr_mod.human_run_summary(self.store, run_id)

    def record_correlated(self, run_id: str, event_type: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        from gen2 import correlation_telemetry as corr_mod

        return corr_mod.record_correlated(
            self.store,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
            **kwargs,
        )

    def register_experiment_relation(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        experiment: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        from gen2 import correlation_telemetry as corr_mod

        return corr_mod.register_experiment_relation(
            self.store,
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            experiment=experiment,
            correlation_id=correlation_id,
        )

    def replay_plan(
        self,
        run_id: str,
        *,
        from_sequence: int = 1,
        alternate_model: str | None = None,
        alternate_plugin_version: str | None = None,
        permit_side_effects: bool = False,
    ) -> dict[str, Any]:
        return flight_recorder_mod.replay_plan(
            self.store,
            run_id,
            from_sequence=from_sequence,
            alternate_model=alternate_model,
            alternate_plugin_version=alternate_plugin_version,
            permit_side_effects=permit_side_effects,
            record_fn=self.record,
        )

    # ------------------------------------------------------------------ #
    # 1. Mission Control / Mission Compiler
    # ------------------------------------------------------------------ #
    def compile_mission(self, goal: str, *, title: str | None = None, domain: str | None = None) -> dict[str, Any]:
        return mission_control_mod.compile_mission(
            self.store, self.record, goal, title=title, domain=domain
        )

    def start_mission(
        self,
        mission_id: str,
        *,
        create_task: Any | None = None,
        schedule_task: Any | None = None,
        force_retry: bool = False,
    ) -> dict[str, Any]:
        return mission_control_mod.start_mission(
            self.store,
            self.record,
            mission_id,
            create_task=create_task,
            schedule_task=schedule_task,
            force_retry=force_retry,
        )

    def decide_mission_gate(
        self, mission_id: str, gate_id: str, *, approve: bool, note: str = ""
    ) -> dict[str, Any]:
        return mission_control_mod.decide_mission_gate(
            self.store, self.record, mission_id, gate_id, approve=approve, note=note
        )

    def revoke_mission_gate(self, mission_id: str, gate_id: str, *, reason: str = "") -> dict[str, Any]:
        return mission_control_mod.revoke_mission_gate(
            self.store, self.record, mission_id, gate_id, reason=reason
        )

    def evaluate_mission_acceptance(
        self,
        mission_id: str,
        *,
        status: str | None = None,
        verification: dict[str, Any] | None = None,
        step_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate executable acceptance checks for a mission (evidence-based)."""
        mission = self.store.get_mission(mission_id)
        if not mission:
            raise ValueError("mission not found")
        ir = dict(mission.get("ir") or {})
        checks = list(ir.get("acceptance_checks") or [])
        for item in mission.get("acceptance_criteria") or []:
            if isinstance(item, dict) and item.get("type") in mission_control_mod.ACCEPTANCE_CHECK_TYPES:
                if item not in checks:
                    checks.append(item)
        ver = {**(mission.get("verification") or {}), **(verification or {})}
        summary = dict(step_summary or (ver.get("step_summary") or {}))
        eval_status = status or str(mission.get("status") or "")
        result = mission_control_mod.evaluate_acceptance_checks(
            checks,
            status=eval_status,
            verification=ver,
            step_summary=summary,
            mission=mission,
            artifact_service=self.artifact_service,
        )
        return {
            "mission_id": mission_id,
            "status": eval_status,
            "checks": checks,
            **result,
        }

    def replan_mission(
        self,
        mission_id: str,
        cause: str,
        *,
        note: str = "",
        failed_step_id: str | None = None,
    ) -> dict[str, Any]:
        return mission_control_mod.replan_mission(
            self.store,
            self.record,
            mission_id,
            cause,
            note=note,
            failed_step_id=failed_step_id,
        )

    def portfolio_missions(
        self, *, status: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        return mission_control_mod.portfolio_view(self.store, status=status, limit=limit)

    def list_mission_revisions(self, mission_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return mission_control_mod.list_mission_revisions(self.store, mission_id, limit=limit)

    def diff_mission_revisions(
        self, mission_id: str, from_version: int, to_version: int
    ) -> dict[str, Any]:
        return mission_control_mod.diff_mission_revision_versions(
            self.store, mission_id, from_version, to_version
        )

    def mission_identity_links(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.get_mission(mission_id)
        if not mission:
            raise ValueError("mission not found")
        return mission_control_mod.mission_identity_links(mission)

    # ------------------------------------------------------------------ #
    # 9. Multi-Agent Intelligence Committee
    # ------------------------------------------------------------------ #
    def run_committee(
        self,
        topic: str,
        *,
        domain: str = "research",
        evidence: list[str] | None = None,
        chat_fn: Any | None = None,
        model_id: str | None = None,
        model_slots: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Heuristic committee (default). For live specialists use ``run_committee_live``."""
        return committee_mod.run_committee(
            self.store,
            self.record,
            topic,
            domain=domain,
            evidence=evidence,
            chat_fn=chat_fn,
            model_id=model_id,
            model_slots=model_slots,
        )

    def _committee_roles(self, domain: str, *, topic: str = "", complexity: str | None = None) -> list[dict[str, Any]]:
        return committee_mod.committee_roles(domain, topic=topic, complexity=complexity)

    def _role_stance_live(
        self,
        role_id: str,
        topic: str,
        evidence: list[str],
        *,
        chat_fn: Any,
        model_id: str | None,
        focus: str,
    ) -> dict[str, Any]:
        """Sync wrapper — prefer async live path from ``run_committee_live``."""
        return committee_mod.role_stance_live_sync(
            role_id,
            topic,
            evidence,
            chat_fn=chat_fn,
            model_id=model_id,
            focus=focus,
        )

    async def _role_stance_live_async(
        self,
        role_id: str,
        topic: str,
        evidence: list[str],
        *,
        chat_fn: Any,
        model_id: str | None,
        focus: str,
    ) -> dict[str, Any]:
        return await committee_mod.role_stance_live_async(
            role_id,
            topic,
            evidence,
            chat_fn=chat_fn,
            model_id=model_id,
            focus=focus,
        )

    async def run_committee_live(
        self,
        topic: str,
        *,
        domain: str = "research",
        evidence: list[str] | None = None,
        chat_fn: Any | None = None,
        model_id: str | None = None,
        model_slots: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Committee with live specialist calls when ``chat_fn`` is available."""
        return await committee_mod.run_committee_live(
            self.store,
            self.record,
            topic,
            domain=domain,
            evidence=evidence,
            chat_fn=chat_fn,
            model_id=model_id,
            model_slots=model_slots,
        )

    def _finalize_committee(
        self,
        topic_clean: str,
        domain: str,
        evidence: list[str],
        positions: list[dict[str, Any]],
        *,
        live_requested: bool,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        return committee_mod.finalize_committee(
            self.store,
            self.record,
            topic_clean,
            domain,
            evidence,
            positions,
            live_requested=live_requested,
            model_id=model_id,
        )

    def _role_stance(self, role_id: str, topic: str, evidence: list[str]) -> dict[str, Any]:
        return committee_mod.role_stance(role_id, topic, evidence)

    # ------------------------------------------------------------------ #
    # 4. Self-Evolving Agent Factory
    # ------------------------------------------------------------------ #
    def extract_skill_candidate(
        self,
        *,
        name: str,
        workflow: list[Any],
        pattern_source: str,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        return agent_factory_mod.extract_skill_candidate(
            self.store,
            self.record,
            name=name,
            workflow=workflow,
            pattern_source=pattern_source,
            tools=tools,
        )

    def extract_patterns_from_run(self, run_id: str) -> dict[str, Any]:
        return agent_factory_mod.extract_patterns_from_run(self.store, run_id)

    def extract_and_create_candidate(
        self,
        run_id: str,
        *,
        name: str | None = None,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        return agent_factory_mod.extract_and_create_candidate(
            self.store, self.record, run_id, name=name, tools=tools
        )

    def benchmark_skill(self, skill_id: str) -> dict[str, Any]:
        return agent_factory_mod.benchmark_skill(
            self.store,
            self.record,
            skill_id,
            run_eval_lab=self.run_eval_lab,
        )

    def promote_skill(self, skill_id: str, *, human_approved: bool) -> dict[str, Any]:
        return agent_factory_mod.promote_skill(
            self.store, self.record, skill_id, human_approved=human_approved
        )

    def deactivate_skill(self, skill_id: str, *, reason: str = "deactivated") -> dict[str, Any]:
        return agent_factory_mod.deactivate_skill(self.store, self.record, skill_id, reason=reason)

    def rollback_skill(self, skill_id: str, *, to_status: str = "benchmarked") -> dict[str, Any]:
        return agent_factory_mod.rollback_skill(self.store, self.record, skill_id, to_status=to_status)

    def execute_promoted_skill(self, skill_id: str, *, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the promoted skill's validated workflow handlers (same version as benchmark/promote)."""
        return agent_factory_mod.execute_promoted_skill(
            self.store, self.record, skill_id, inputs=inputs
        )

    # ------------------------------------------------------------------ #
    # Workflows (Gen2 product surface above Work Runtime / skills)
    # ------------------------------------------------------------------ #
    def validate_workflow(self, ir: dict[str, Any]) -> list[str]:
        return workflows_mod.validate_workflow(ir)

    def list_workflows(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_workflows(status=status, limit=limit)

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return self.store.get_workflow(workflow_id)

    def create_workflow(self, definition: dict[str, Any], *, note: str = "create") -> dict[str, Any]:
        return workflows_mod.create_workflow(self.store, self.record, definition, note=note)

    def update_workflow(
        self,
        workflow_id: str,
        definition: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        bump_version: bool = True,
        note: str = "update",
    ) -> dict[str, Any]:
        return workflows_mod.update_workflow(
            self.store,
            self.record,
            workflow_id,
            definition,
            name=name,
            bump_version=bump_version,
            note=note,
        )

    def archive_workflow(self, workflow_id: str) -> dict[str, Any]:
        return workflows_mod.soft_archive(self.store, self.record, workflow_id)

    def draft_workflow(self, goal: str, *, chat_fn: Any | None = None) -> dict[str, Any]:
        return workflows_mod.draft_from_nl(goal, chat_fn=chat_fn)

    def dry_run_workflow(self, workflow_id: str) -> dict[str, Any]:
        return workflows_mod.dry_run(self.store, self.record, workflow_id)

    def sandbox_run_workflow(
        self, workflow_id: str, *, run_inputs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return workflows_mod.sandbox_run(self.store, self.record, workflow_id, run_inputs=run_inputs)

    def product_run_workflow(
        self,
        workflow_id: str,
        *,
        run_inputs: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        async_mode: bool = True,
        blocking: bool = False,
    ) -> dict[str, Any]:
        return workflows_mod.product_run(
            self.store,
            self.record,
            workflow_id,
            services=self.workflow_services(),
            run_inputs=run_inputs,
            timeout_seconds=timeout_seconds,
            async_mode=async_mode,
            blocking=blocking,
        )

    def get_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get_workflow_run(run_id)

    def list_workflow_runs(self, workflow_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_workflow_runs(workflow_id, limit=limit)

    def cancel_workflow_run(self, run_id: str) -> dict[str, Any]:
        row = self.store.get_workflow_run(run_id)
        ctl = workflows_mod.cancel_workflow_run(run_id)
        if row and str(row.get("status")) in {"queued", "running", "paused", "awaiting_human"}:
            result = dict(row.get("result") or {})
            result["status"] = "cancel_requested"
            self.store.update_workflow_run(run_id, result=result)
        return {**(row or {}), **ctl}

    def pause_workflow_run(self, run_id: str) -> dict[str, Any]:
        return workflows_mod.pause_workflow_run(run_id)

    def resume_workflow_run(self, run_id: str) -> dict[str, Any]:
        row = self.store.get_workflow_run(run_id)
        ctl = workflows_mod.resume_workflow_run(run_id)
        if row and str(row.get("status")) == "paused":
            self.store.update_workflow_run(run_id, status="running")
        return {**(row or {}), **ctl}

    def promote_workflow(
        self,
        workflow_id: str,
        *,
        human_approved: bool = False,
        target: str | None = None,
    ) -> dict[str, Any]:
        return workflows_mod.promote_workflow(
            self.store, self.record, workflow_id, human_approved=human_approved, target=target
        )

    def rollback_workflow(
        self,
        workflow_id: str,
        *,
        to_status: str = "tested",
        to_version: int | None = None,
    ) -> dict[str, Any]:
        return workflows_mod.rollback_workflow(
            self.store, self.record, workflow_id, to_status=to_status, to_version=to_version
        )

    def list_workflow_revisions(self, workflow_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return workflows_mod.list_revisions(self.store, workflow_id, limit=limit)

    def diff_workflow_revisions(
        self, workflow_id: str, from_version: int, to_version: int
    ) -> dict[str, Any]:
        return workflows_mod.diff_revisions(self.store, workflow_id, from_version, to_version)

    def list_workflow_templates(self) -> list[dict[str, Any]]:
        return workflows_mod.list_templates()

    def create_workflow_from_template(
        self, template_id: str, *, name: str | None = None
    ) -> dict[str, Any]:
        return workflows_mod.create_from_template(
            self.store, self.record, template_id, name=name
        )

    def export_workflow(self, workflow_id: str, *, as_zip: bool = False) -> dict[str, Any] | bytes:
        return workflows_mod.export_workflow(self.store, workflow_id, as_zip=as_zip)

    def import_workflow(self, package: dict[str, Any] | bytes | str) -> dict[str, Any]:
        return workflows_mod.import_workflow(self.store, self.record, package)

    def workflow_to_skill(self, workflow_id: str) -> dict[str, Any]:
        return workflows_mod.workflow_to_skill_candidate(self.store, self.record, workflow_id)

    def decide_workflow_human_step(
        self,
        workflow_id: str,
        step_id: str,
        *,
        decision: str,
        value: Any = None,
        resume: bool = True,
    ) -> dict[str, Any]:
        return workflows_mod.decide_human_step(
            self.store,
            self.record,
            workflow_id,
            step_id,
            decision=decision,
            value=value,
            resume=resume,
            services=self.workflow_services(),
        )

    def workflow_metrics(self, workflow_id: str) -> dict[str, Any]:
        return workflows_mod.workflow_metrics(self.store, workflow_id)

    # ------------------------------------------------------------------ #
    # 5. Plugin Sandbox (tiers 0/1 always; 2/3 host-detected, fail-closed)
    # ------------------------------------------------------------------ #
    def default_envelope(self, plugin_id: str, *, permissions: list[str] | None = None) -> dict[str, Any]:
        tier, envelope = build_default_envelope(plugin_id, permissions=permissions)
        return self.store.upsert_envelope(plugin_id, tier, envelope)

    def enforce_envelope(
        self,
        plugin_id: str,
        *,
        action: str,
        path: str | None = None,
        network_host: str | None = None,
        autonomous: bool = False,
        approved: bool = False,
        check_approval: bool = True,
    ) -> dict[str, Any]:
        env = self.store.get_envelope(plugin_id)
        if not env:
            env = self.default_envelope(plugin_id, permissions=["subprocess"])
        envelope = env["envelope"]
        requested_tier = int(env["tier"])
        result = enforce_envelope_policy(
            plugin_id=plugin_id,
            envelope=envelope,
            requested_tier=requested_tier,
            action=action,
            path=path,
            network_host=network_host,
            autonomous=autonomous,
            approved=approved,
            check_approval=check_approval,
            expand_path=self._expand_path,
            available_tiers=available_sandbox_tiers(),
        )
        self.record(
            plugin_id,
            "TOOL_SELECTED" if result["ok"] else "TOOL_RESULT",
            result,
            component="sandbox",
        )
        return result

    def sandbox_host_capabilities(self) -> dict[str, Any]:
        caps = detect_host_sandbox_capabilities()
        from gen2.sandbox import sandbox_honesty_labels

        return {**caps, "honesty": sandbox_honesty_labels(caps)}

    def sandbox_tier2_selftest(self) -> dict[str, Any]:
        from gen2.sandbox_job import run_tier2_selftest

        return run_tier2_selftest()

    def list_policy_profiles(self) -> list[dict[str, Any]]:
        from gen2.policy_profiles import list_policy_profiles

        return list_policy_profiles()

    def envelope_for_policy_profile(self, plugin_id: str, profile_id: str) -> dict[str, Any]:
        from gen2.policy_profiles import envelope_for_profile

        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            raise ValueError("plugin_id required")
        if self.platform_db is not None:
            known = {
                str(item.get("id") or "")
                for item in (self.platform_db.list_plugins() or [])
                if isinstance(item, dict)
            }
            if plugin_id not in known:
                raise ValueError(f"unknown_plugin:{plugin_id}")
        built = envelope_for_profile(plugin_id, profile_id)
        stored = self.store.upsert_envelope(plugin_id, int(built["tier"]), built["envelope"])
        return {**stored, "ok": True, "profile_id": profile_id, "profile": built.get("profile")}

    def jit_ux_panel(self, profile_id: str | None = None) -> dict[str, Any]:
        from gen2.policy_profiles import jit_ux_panel_model

        return jit_ux_panel_model(profile_id)

    def list_jit_grants(
        self,
        *,
        plugin_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.store.list_jit_grants(plugin_id=plugin_id, status=status, limit=limit)

    def request_jit_grant(
        self,
        *,
        plugin_id: str,
        profile_id: str,
        capability: str,
        reason: str = "",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        from gen2.policy_profiles import jit_grant
        from gen2.store import utc_now

        issued = jit_grant(
            plugin_id=plugin_id,
            profile_id=profile_id,
            capability=capability,
            reason=reason,
            now_iso=utc_now(),
            expires_iso=expires_at,
        )
        if not issued.get("ok"):
            return issued
        row = self.store.create_jit_grant(
            {
                "plugin_id": plugin_id,
                "profile_id": profile_id,
                "capability": issued["capability"],
                "status": "active",
                "reason": reason,
                "granted_at": issued["granted_at"],
                "expires_at": issued.get("expires_at"),
                "payload": issued,
            }
        )
        return {**issued, "grant": row, "id": row["id"]}

    def revoke_jit_grant(self, grant_id: str, *, reason: str = "") -> dict[str, Any]:
        existing = self.store.get_jit_grant(grant_id)
        if not existing:
            raise ValueError("jit_grant_not_found")
        if existing.get("status") == "revoked":
            return {**existing, "ok": True, "already_revoked": True}
        updated = self.store.revoke_jit_grant(grant_id, reason=reason)
        return {"ok": True, "grant": updated, "status": "revoked"}

    def scan_plugin_security(
        self,
        *,
        path: str | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from gen2.plugin_security import scan_plugin_manifest, scan_plugin_path

        if path:
            result = scan_plugin_path(path)
            plugin_id = result.get("plugin_id")
            content_hash = result.get("content_hash")
            if plugin_id and content_hash:
                self.store.upsert_plugin_integrity(
                    str(plugin_id),
                    content_hash=str(content_hash),
                    source_path=path,
                    scan=result,
                )
            return result
        if manifest is not None:
            result = scan_plugin_manifest(manifest)
            plugin_id = result.get("plugin_id")
            if plugin_id:
                from gen2.plugin_security import compute_content_hash
                import json

                content_hash = compute_content_hash(json.dumps(manifest, sort_keys=True))
                result["content_hash"] = content_hash
                self.store.upsert_plugin_integrity(
                    str(plugin_id),
                    content_hash=content_hash,
                    scan=result,
                )
            return result
        return {
            "ok": False,
            "findings": [
                {
                    "code": "path_or_manifest_required",
                    "severity": "error",
                    "message": "Provide path or manifest",
                    "blocking": True,
                }
            ],
            "finding_count": 1,
            "blocking_count": 1,
        }

    def verify_plugin_integrity(
        self,
        *,
        plugin_id: str | None = None,
        path: str | None = None,
        expected_hash: str,
    ) -> dict[str, Any]:
        from gen2.plugin_security import verify_plugin_integrity
        from gen2.store import utc_now

        stored = self.store.get_plugin_integrity(plugin_id) if plugin_id else None
        expected = expected_hash or (stored or {}).get("content_hash") or ""
        result = verify_plugin_integrity(
            expected_hash=str(expected),
            path=path,
            actual_hash=None if path else (stored or {}).get("content_hash"),
        )
        if plugin_id and result.get("verified"):
            self.store.upsert_plugin_integrity(
                plugin_id,
                content_hash=str(result.get("actual_hash") or expected),
                source_path=path,
                verified_at=utc_now(),
                scan={"verify": result},
            )
        return {**result, "plugin_id": plugin_id, "stored": stored}

    def validate_mcp_allowlist(self, config: dict[str, Any] | None) -> dict[str, Any]:
        from gen2.mcp_harden import validate_mcp_allowlist_config

        return validate_mcp_allowlist_config(config)

    def enforce_tool_boundary(self, args: Any, *, mode: str = "reject") -> dict[str, Any]:
        from gen2.tool_boundary import enforce_tool_args

        return enforce_tool_args(args, mode=mode)

    def network_optional_matrix(self) -> dict[str, Any]:
        from gen2.network_optional import network_optional_feature_matrix, probe_unreachable_host

        matrix = network_optional_feature_matrix()
        probe = probe_unreachable_host()
        return {**matrix, "probe": probe}

    def skill_catalog_hygiene(self, *, stale_days: int = 30) -> dict[str, Any]:
        return agent_factory_mod.catalog_hygiene_report(self.store, stale_days=stale_days)

    def validate_dod_claim(self, claim: dict[str, Any] | None) -> dict[str, Any]:
        from gen2.dod import refuse_full_without_evidence

        return refuse_full_without_evidence(claim)

    def sandbox_assign_job_object(self, pid: int) -> dict[str, Any]:
        return try_assign_job_object(pid)

    def _expand_path(self, template: str) -> str:
        return str(Path(template.replace("{data_root}", str(self.data_root))).expanduser().resolve())

    # ------------------------------------------------------------------ #
    # 3. Temporal Intelligence Graph
    # ------------------------------------------------------------------ #
    def assert_edge(self, values: dict[str, Any], *, require_provenance: bool = False) -> dict[str, Any]:
        return temporal_graph_mod.assert_edge(
            self.store, self.record, values, require_provenance=require_provenance
        )

    def as_of_beliefs(
        self,
        entity_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Beliefs about entity valid at ``as_of`` (valid-time)."""
        return temporal_graph_mod.as_of_beliefs(
            self.store,
            entity_id,
            as_of,
            known_as_of=known_as_of,
            limit=limit,
        )

    def find_contradictions(self, entity_id: str | None = None) -> list[dict[str, Any]]:
        return temporal_graph_mod.find_contradictions(self.store, entity_id)

    def find_analogues(
        self,
        *,
        entity_id: str | None = None,
        relation_kind: str | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return temporal_graph_mod.find_analogues(
            self.store,
            entity_id=entity_id,
            relation_kind=relation_kind,
            text=text,
            limit=limit,
        )

    def assert_edge_strict(self, values: dict[str, Any]) -> dict[str, Any]:
        return temporal_graph_mod.assert_edge(
            self.store, self.record, values, require_provenance=True
        )

    # ------------------------------------------------------------------ #
    # 7. Financial Intelligence Fusion
    # ------------------------------------------------------------------ #
    def fuse_market_intelligence(
        self,
        *,
        articles: list[dict[str, Any]] | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        return finance_fusion_mod.fuse_market_intelligence(
            self.store, articles=articles, symbol=symbol
        )

    def run_event_study(
        self,
        event: dict[str, Any],
        *,
        bars: list[dict[str, Any]] | None = None,
        window_days: int = 5,
    ) -> dict[str, Any]:
        return finance_fusion_mod.run_event_study(event, bars=bars, window_days=window_days)

    def persist_finance_thesis(
        self, thesis: dict[str, Any], *, symbol: str | None = None
    ) -> dict[str, Any]:
        return finance_fusion_mod.persist_thesis(self.store, thesis, symbol=symbol)

    def _classify_catalyst(self, text: str) -> str:
        return finance_fusion_mod.classify_catalyst(text)

    def _horizon_for(self, event_type: str) -> str:
        return finance_fusion_mod.horizon_for(event_type)

    def _guess_company(self, title: str) -> str | None:
        return finance_fusion_mod.guess_company(title)

    # ------------------------------------------------------------------ #
    # 10. Local-first compute fabric (not an operational distributed cluster)
    # ------------------------------------------------------------------ #
    def ensure_local_node(self) -> dict[str, Any]:
        return compute_fabric_mod.ensure_local_node(self.store, self.data_root)

    def heartbeat(self, node_id: str = "node_local") -> dict[str, Any]:
        return compute_fabric_mod.heartbeat(self.store, self.data_root, node_id)

    def discover_nodes(self) -> list[dict[str, Any]]:
        return compute_fabric_mod.discover_nodes(self.store, self.data_root)

    def dispatch_job(
        self,
        *,
        payload: dict[str, Any],
        mission_id: str | None = None,
        node_id: str | None = None,
        network_allowed: bool | None = None,
        prefer_local_fallback: bool = True,
    ) -> dict[str, Any]:
        return compute_fabric_mod.dispatch_job(
            self.store,
            self.data_root,
            payload=payload,
            mission_id=mission_id,
            node_id=node_id,
            record_fn=self.record,
            network_allowed=network_allowed,
            prefer_local_fallback=prefer_local_fallback,
        )

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return compute_fabric_mod.cancel_job(
            self.store, job_id, record_fn=self.record, data_root=self.data_root
        )

    def pair_worker(
        self,
        *,
        node_id: str | None = None,
        name: str | None = None,
        base_url: str | None = None,
        shared_secret: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return compute_fabric_mod.pair_remote_node(
            self.store,
            self.data_root,
            node_id=node_id,
            name=name,
            base_url=base_url,
            shared_secret=shared_secret,
            capabilities=capabilities,
        )

    def worker_status(self) -> dict[str, Any]:
        return compute_fabric_mod.worker_status(self.store, self.data_root)

    def distributed_status(self) -> dict[str, Any]:
        return compute_fabric_mod.distributed_fabric_status(self.data_root)

    def process_local_compute_queue(self, *, limit: int = 20) -> dict[str, Any]:
        return compute_fabric_mod.process_local_queue(
            self.store, self.data_root, limit=limit, record_fn=self.record
        )

    def single_node_compute_gate(self) -> dict[str, Any]:
        return compute_fabric_mod.single_node_solidity_gate(self.store, self.data_root)

    def comparative_replay(
        self,
        run_id: str,
        *,
        alternate_model: str | None = None,
        implementation_id: str | None = None,
        chat_fn: Any | None = None,
        tool_adapter: Any | None = None,
        reuse_recorded_tools: bool = True,
        reexecute_side_effects: bool = False,
        from_sequence: int = 1,
        source_versions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return flight_recorder_mod.comparative_replay(
            self.store,
            run_id,
            alternate_model=alternate_model,
            implementation_id=implementation_id,
            chat_fn=chat_fn,
            tool_adapter=tool_adapter,
            reuse_recorded_tools=reuse_recorded_tools,
            reexecute_side_effects=reexecute_side_effects,
            from_sequence=from_sequence,
            record_fn=self.record,
            source_versions=source_versions,
        )

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #
    def dashboard(self) -> dict[str, Any]:
        self.ensure_local_node()
        return dashboard_mod.build_dashboard(self.store, data_root=self.data_root)
