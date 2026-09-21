"""FastAPI routes for HADES Gen2 systems."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

router = APIRouter(tags=["gen2"])


class EvalRunInput(BaseModel):
    model_id: str | None = None
    suite: str = Field(default="reasoning", max_length=80)
    mode: str = Field(default="deterministic_software", max_length=40)
    holdout_limit: int | None = Field(default=None, ge=1, le=200)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    holdout_split: str | None = Field(default=None, max_length=80)


class JitGrantRequestInput(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=80)
    capability: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=500)
    expires_at: str | None = Field(default=None, max_length=64)


class JitGrantRevokeInput(BaseModel):
    reason: str = Field(default="", max_length=500)


class PluginScanInput(BaseModel):
    path: str | None = Field(default=None, max_length=2000)
    manifest: dict[str, Any] | None = None


class PluginVerifyInput(BaseModel):
    plugin_id: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=2000)
    expected_hash: str = Field(min_length=8, max_length=128)


class McpAllowlistInput(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class ToolBoundaryInput(BaseModel):
    args: Any = None
    mode: str = Field(default="reject", max_length=20)


class EvalAbInput(BaseModel):
    strategy_a: str = Field(min_length=1, max_length=120)
    strategy_b: str = Field(min_length=1, max_length=120)
    suite: str = Field(default="reasoning", max_length=80)
    n: int = Field(default=3, ge=1, le=30)
    model_id: str | None = None


class EvalPrHelpInput(BaseModel):
    run_a: str = Field(min_length=1, max_length=120)
    run_b: str = Field(min_length=1, max_length=120)


class EvalIngestFlightInput(BaseModel):
    run_id: str = Field(min_length=1, max_length=120)


class HumanUsabilityRatingInput(BaseModel):
    """Human usability rating payload.

    Pydantic v2 reserves the name ``model_config`` for ConfigDict, so the wire
    key ``model_config`` is mapped onto ``llm_model_config`` before validation.
    """

    model_config = ConfigDict(extra="ignore")

    rating: str = Field(min_length=1, max_length=64)
    eval_run_id: str | None = Field(default=None, max_length=120)
    task_id: str | None = Field(default=None, max_length=120)
    coding_job_id: str | None = Field(default=None, max_length=120)
    artifact_version: str = Field(default="", max_length=120)
    llm_model_config: dict[str, Any] = Field(default_factory=dict)
    correction_notes: str = Field(default="", max_length=4000)
    correction_seconds: float | None = Field(default=None, ge=0, le=86400)
    primary_error: str = Field(default="", max_length=500)
    original_result: dict[str, Any] = Field(default_factory=dict)
    timer_opt_in: bool = False

    @model_validator(mode="before")
    @classmethod
    def _map_reserved_model_config_key(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "model_config" in data and "llm_model_config" not in data:
            mapped = dict(data)
            mapped["llm_model_config"] = mapped.pop("model_config")
            return mapped
        return data


class EvalRegressionCandidateInput(BaseModel):
    run_id: str = Field(min_length=1, max_length=120)
    expected_end_state: dict[str, Any] | None = None


class ContextCompileInput(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    max_tokens: int = Field(default=2048, ge=64, le=128_000)
    model_context_size: int | None = Field(default=None, ge=256, le=1_000_000)
    run_id: str | None = None
    persist: bool = True
    response_reserve_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    system_reserve_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    request_budget_tokens: int | None = Field(default=None, ge=64, le=1_000_000)
    tokenizer_mode: str = Field(default="approx_chars_4", max_length=64)
    max_age_hours: float | None = Field(default=None, ge=0, le=876000)
    hierarchical_summarization: bool = True
    pin_overflow: str = Field(default="keep_with_note", max_length=40)


class MissionCompileInput(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=200)
    domain: str | None = Field(default=None, max_length=40)


class MissionGateInput(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=2000)


class MissionAcceptanceEvalInput(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    verification: dict[str, Any] = Field(default_factory=dict)
    step_summary: dict[str, Any] = Field(default_factory=dict)


class MissionReplanInput(BaseModel):
    cause: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=2000)
    failed_step_id: str | None = Field(default=None, max_length=120)


class CommitteeInput(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    domain: str = Field(default="research", max_length=40)
    evidence: list[str] = Field(default_factory=list, max_length=40)
    mode: str = Field(default="heuristic", max_length=40)
    model_id: str | None = None
    # Optional per-role dynamic LM Studio model ids — never hardcoded production models.
    model_slots: dict[str, str] = Field(default_factory=dict)


class SkillExtractInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workflow: list[Any] = Field(default_factory=list, max_length=40)
    pattern_source: str = Field(default="manual", max_length=200)
    tools: list[str] = Field(default_factory=list, max_length=40)


class SkillExtractFromRunInput(BaseModel):
    run_id: str = Field(min_length=1, max_length=120)
    name: str | None = Field(default=None, max_length=120)
    tools: list[str] = Field(default_factory=list, max_length=40)
    create: bool = True


class SkillPromoteInput(BaseModel):
    human_approved: bool


class EnvelopeInput(BaseModel):
    permissions: list[str] = Field(default_factory=list, max_length=20)
    tier: int | None = Field(default=None, ge=0, le=3)
    envelope: dict[str, Any] | None = None


class EnvelopeCheckInput(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    path: str | None = None
    network_host: str | None = None
    autonomous: bool = False
    approved: bool = False


class GraphEdgeInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    relation: str = Field(default="related_to", max_length=80)
    relation_kind: str = Field(default="related_to", max_length=80)
    valid_from: str | None = None
    valid_until: str | None = None
    observed_at: str | None = None
    source_ref: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    provenance: str = ""
    supersedes: str | None = None
    contradicts: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    require_provenance: bool = False


class FinanceFuseInput(BaseModel):
    articles: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    symbol: str | None = Field(default=None, max_length=40)


class FinanceEventStudyInput(BaseModel):
    event: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = Field(default=None, max_length=120)
    bars: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    window_days: int = Field(default=5, ge=1, le=60)


class ContextChatCompileInput(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    max_tokens: int = Field(default=2048, ge=64, le=128_000)
    opt_in: bool = False
    persist: bool = False
    tokenizer_mode: str = Field(default="approx_chars_4", max_length=64)


class RecordEventInput(BaseModel):
    run_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    model_id: str | None = None
    component: str | None = None
    input_text: str | None = None
    output_text: str | None = None
    config_fingerprint: str | None = None
    correlation_id: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None
    mission_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    toolcall_id: str | None = None
    approval_id: str | None = None
    plan_revision: int | None = None
    artifact_version: str | None = None
    token_usage: dict[str, Any] | None = None
    effective_model_config: dict[str, Any] | None = None
    use_correlation: bool = False


class ExperimentRelationInput(BaseModel):
    parent_run_id: str = Field(min_length=1, max_length=120)
    child_run_id: str = Field(min_length=1, max_length=120)
    experiment: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class ReproducibleExportInput(BaseModel):
    experiment: dict[str, Any] = Field(default_factory=dict)
    include_events: bool = True


class LifecycleEmitInput(BaseModel):
    run_id: str = Field(min_length=1, max_length=120)
    phase: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    model_id: str | None = None
    component: str | None = None
    input_text: str | None = None
    output_text: str | None = None
    config_fingerprint: str | None = None
    severity: str | None = None
    duration_ms: float | None = None
    correlation_id: str | None = None


class ReplayInput(BaseModel):
    from_sequence: int = Field(default=1, ge=1)
    alternate_model: str | None = None
    alternate_plugin_version: str | None = None
    permit_side_effects: bool = False


class ComparativeReplayInput(BaseModel):
    alternate_model: str | None = None
    implementation_id: str | None = None
    reuse_recorded_tools: bool = True
    reexecute_side_effects: bool = False
    from_sequence: int = Field(default=1, ge=1)
    source_versions: dict[str, Any] = Field(default_factory=dict)
    # Optional stub response for sandboxed model execution without live LM Studio.
    stub_model_output: str | None = None
    stub_tokens: int = 0


class DispatchJobInput(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    mission_id: str | None = None
    node_id: str | None = None
    network_allowed: bool | None = None
    prefer_local_fallback: bool = True


class PairWorkerInput(BaseModel):
    node_id: str | None = None
    name: str | None = None
    base_url: str | None = None
    shared_secret: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreateInput(BaseModel):
    definition: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=200)
    note: str = Field(default="create", max_length=200)


class WorkflowUpdateInput(BaseModel):
    definition: dict[str, Any] | None = None
    name: str | None = Field(default=None, max_length=200)
    bump_version: bool = True
    note: str = Field(default="update", max_length=200)


class WorkflowDraftInput(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class WorkflowPromoteInput(BaseModel):
    human_approved: bool = False
    target: str | None = Field(default=None, max_length=40)


class WorkflowRollbackInput(BaseModel):
    to_status: str = Field(default="tested", max_length=40)
    to_version: int | None = Field(default=None, ge=1)


class WorkflowTemplateCreateInput(BaseModel):
    template_id: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=200)


class WorkflowImportInput(BaseModel):
    package: dict[str, Any] | None = None
    # Optional raw JSON string for single-file .HadesWorkflow packages.
    raw: str | None = Field(default=None, max_length=2_000_000)


class WorkflowHumanDecideInput(BaseModel):
    decision: str = Field(min_length=1, max_length=200)
    value: Any = None
    resume: bool = True


class WorkflowExecuteInput(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, ge=1, le=86_400)
    async_mode: bool = True
    blocking: bool = False


class WorkflowSandboxInput(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


def mount_gen2_routes(ctx: dict[str, Any]) -> APIRouter:
    class _Svc:
        def __getattr__(self, name: str) -> Any:
            return ctx[name]

        def get(self, name: str, default: Any = None) -> Any:
            return ctx.get(name, default)

    s = _Svc()

    def gen2():
        svc = s.get("gen2")
        if svc is None:
            raise HTTPException(status_code=503, detail="Gen2 services unavailable")
        return svc

    @router.get("/gen2/sandbox/profiles")
    async def sandbox_profiles() -> list[dict[str, Any]]:
        return gen2().list_policy_profiles()

    @router.get("/gen2/sandbox/host-capabilities")
    async def sandbox_host_capabilities() -> dict[str, Any]:
        return gen2().sandbox_host_capabilities()

    @router.post("/gen2/sandbox/tier2-selftest")
    async def sandbox_tier2_selftest() -> dict[str, Any]:
        """Honest Tier-2 probe. On Linux returns UNVERIFIED_ON_HOST — never fake PASS."""
        return gen2().sandbox_tier2_selftest()

    @router.post("/gen2/sandbox/profiles/{profile_id}/apply")
    async def apply_sandbox_profile(profile_id: str, values: dict[str, Any]) -> dict[str, Any]:
        plugin_id = str(values.get("plugin_id") or "").strip()
        if not plugin_id:
            raise HTTPException(status_code=400, detail="plugin_id required")
        try:
            return gen2().envelope_for_policy_profile(plugin_id, profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/sandbox/jit/ux")
    async def sandbox_jit_ux(profile_id: str | None = None) -> dict[str, Any]:
        return gen2().jit_ux_panel(profile_id)

    @router.get("/gen2/sandbox/jit/grants")
    async def list_jit_grants(
        plugin_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return gen2().list_jit_grants(plugin_id=plugin_id, status=status, limit=limit)

    @router.post("/gen2/sandbox/jit/grants")
    async def request_jit_grant(values: JitGrantRequestInput) -> dict[str, Any]:
        try:
            return gen2().request_jit_grant(
                plugin_id=values.plugin_id,
                profile_id=values.profile_id,
                capability=values.capability,
                reason=values.reason,
                expires_at=values.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/sandbox/jit/grants/{grant_id}/revoke")
    async def revoke_jit_grant(grant_id: str, values: JitGrantRevokeInput | None = None) -> dict[str, Any]:
        values = values or JitGrantRevokeInput()
        try:
            return gen2().revoke_jit_grant(grant_id, reason=values.reason)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/plugins/security/scan")
    async def plugin_security_scan(values: PluginScanInput) -> dict[str, Any]:
        return gen2().scan_plugin_security(path=values.path, manifest=values.manifest)

    @router.post("/gen2/plugins/security/verify")
    async def plugin_security_verify(values: PluginVerifyInput) -> dict[str, Any]:
        return gen2().verify_plugin_integrity(
            plugin_id=values.plugin_id,
            path=values.path,
            expected_hash=values.expected_hash,
        )

    @router.post("/gen2/mcp/allowlist/validate")
    async def mcp_allowlist_validate(values: McpAllowlistInput) -> dict[str, Any]:
        return gen2().validate_mcp_allowlist(values.config)

    @router.post("/gen2/tools/boundary/enforce")
    async def tool_boundary_enforce(values: ToolBoundaryInput) -> dict[str, Any]:
        return gen2().enforce_tool_boundary(values.args, mode=values.mode)

    @router.get("/gen2/network/optional")
    async def network_optional_matrix() -> dict[str, Any]:
        return gen2().network_optional_matrix()

    @router.get("/gen2/skills/catalog/hygiene")
    async def skill_catalog_hygiene(stale_days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
        return gen2().skill_catalog_hygiene(stale_days=stale_days)

    @router.get("/gen2/dod/validate")
    async def dod_validate_get() -> dict[str, Any]:
        """Explain DoD helper — POST body for real validation."""
        return {
            "required_evidence_fields": ["tests", "verification_status", "notes"],
            "forbidden_full_without_evidence": True,
        }

    @router.post("/gen2/dod/validate")
    async def dod_validate(values: dict[str, Any]) -> dict[str, Any]:
        return gen2().validate_dod_claim(values)

    @router.get("/gen2/dashboard")
    async def dashboard() -> dict[str, Any]:
        return gen2().dashboard()

    # Eval Lab
    @router.post("/gen2/evals/run")
    async def run_evals(values: EvalRunInput) -> dict[str, Any]:
        mode = (values.mode or "deterministic_software").strip().lower()
        if mode in {"live_model", "live", "model"}:
            if not values.model_id:
                raise HTTPException(status_code=400, detail="model_id required for live_model eval")
            chat_fn = None
            try:
                gateway = s.get("gateway_chat")
                factory = s.get("lm_client")
                if callable(gateway):
                    async def chat_fn(payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
                        return await gateway(payload, surface="eval", model_id=values.model_id)
                elif callable(factory):
                    client = factory()
                    chat_fn = client.chat
            except Exception:
                chat_fn = None
            return await gen2().run_model_eval(model_id=values.model_id, suite=values.suite, chat_fn=chat_fn)
        return gen2().run_eval_lab(
            model_id=values.model_id,
            suite=values.suite,
            mode=mode,
            holdout_limit=values.holdout_limit,
            seed=values.seed,
            holdout_split=values.holdout_split,
        )

    @router.get("/gen2/evals/metrics-catalog")
    async def eval_metrics_catalog() -> dict[str, Any]:
        return gen2().eval_metrics_catalog()

    @router.get("/gen2/evals/catalog")
    async def eval_catalog() -> dict[str, Any]:
        return gen2().eval_catalog()

    @router.get("/gen2/evals/reports")
    async def eval_reports(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
        return gen2().eval_reports(limit=limit)

    @router.get("/gen2/evals/matrix")
    async def eval_matrix() -> dict[str, Any]:
        return gen2().capability_matrix()

    @router.get("/gen2/evals/recommend")
    async def eval_recommend(task_type: str, metric: str = "pass") -> dict[str, Any]:
        return gen2().recommend_model(task_type, metric=metric)

    @router.get("/gen2/evals/flaky")
    async def eval_flaky(
        suite: str,
        mode: str | None = None,
        last_n: int = Query(default=5, ge=2, le=50),
    ) -> dict[str, Any]:
        return gen2().detect_flaky_cases(suite=suite, mode=mode, last_n=last_n)

    @router.post("/gen2/evals/ab")
    async def eval_ab(values: EvalAbInput) -> dict[str, Any]:
        return gen2().run_ab_experiment(
            strategy_a=values.strategy_a,
            strategy_b=values.strategy_b,
            suite=values.suite,
            n=values.n,
            model_id=values.model_id,
        )

    @router.post("/gen2/evals/pr-help")
    async def eval_pr_help(values: EvalPrHelpInput) -> dict[str, Any]:
        return gen2().pr_help_summary(values.run_a, values.run_b)

    @router.post("/gen2/evals/ingest-flight")
    async def eval_ingest_flight(values: EvalIngestFlightInput) -> dict[str, Any]:
        return gen2().ingest_flight_recorder_run(values.run_id)

    @router.post("/gen2/evals/human-rating")
    async def eval_human_rating(values: HumanUsabilityRatingInput) -> dict[str, Any]:
        """Compact human usability rating; original results are preserved."""
        try:
            return gen2().store.save_human_usability_rating(
                rating=values.rating,
                eval_run_id=values.eval_run_id,
                task_id=values.task_id,
                coding_job_id=values.coding_job_id,
                artifact_version=values.artifact_version,
                model_config=values.llm_model_config,
                correction_notes=values.correction_notes,
                correction_seconds=values.correction_seconds,
                primary_error=values.primary_error,
                original_result=values.original_result,
                timer_opt_in=values.timer_opt_in,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/evals/human-ratings")
    async def eval_human_ratings(
        eval_run_id: str | None = None,
        task_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        rows = gen2().store.list_human_usability_ratings(
            eval_run_id=eval_run_id, task_id=task_id, limit=limit
        )
        return {
            "ratings": rows,
            "trends": gen2().store.human_usability_trends(limit=limit),
        }

    @router.post("/gen2/evals/regression-candidate")
    async def eval_regression_candidate(values: EvalRegressionCandidateInput) -> dict[str, Any]:
        """Propose a development regression candidate from a failed flight run (review required)."""
        return gen2().propose_regression_candidate_from_flight(
            values.run_id,
            expected_end_state=values.expected_end_state,
        )

    @router.post("/gen2/evals/regression-case/effect-ledger")
    async def eval_effect_ledger_regression_case() -> dict[str, Any]:
        """Deterministic software regression case (no model call)."""
        return gen2().run_effect_ledger_regression_case()

    # Context compiler
    @router.post("/gen2/context/compile")
    async def compile_context(values: ContextCompileInput) -> dict[str, Any]:
        try:
            return gen2().compile_context(
                goal=values.goal,
                items=values.items,
                max_tokens=values.max_tokens,
                model_context_size=values.model_context_size,
                run_id=values.run_id,
                persist=values.persist,
                response_reserve_tokens=values.response_reserve_tokens,
                system_reserve_tokens=values.system_reserve_tokens,
                request_budget_tokens=values.request_budget_tokens,
                tokenizer_mode=values.tokenizer_mode,
                max_age_hours=values.max_age_hours,
                hierarchical_summarization=values.hierarchical_summarization,
                pin_overflow=values.pin_overflow,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/context/compile-for-chat")
    async def compile_context_for_chat(values: ContextChatCompileInput) -> dict[str, Any]:
        """Opt-in only — default retrieval path unchanged unless opt_in or env flag."""
        return gen2().compile_context_for_chat(
            goal=values.goal,
            items=values.items,
            max_tokens=values.max_tokens,
            opt_in=values.opt_in,
            persist=values.persist,
            tokenizer_mode=values.tokenizer_mode,
        )

    @router.get("/gen2/context/packs/{pack_id}")
    async def get_context_pack(pack_id: str) -> dict[str, Any]:
        pack = gen2().store.get_context_pack(pack_id)
        if not pack:
            raise HTTPException(status_code=404, detail="context pack not found")
        return pack

    # Flight recorder
    @router.post("/gen2/flight/events", status_code=status.HTTP_201_CREATED)
    async def record_event(values: RecordEventInput) -> dict[str, Any]:
        use_corr = bool(
            values.use_correlation
            or values.correlation_id
            or values.conversation_id
            or values.task_id
            or values.mission_id
            or values.workflow_id
            or values.step_id
            or values.toolcall_id
            or values.approval_id
            or values.plan_revision is not None
            or values.artifact_version
            or values.token_usage is not None
            or values.effective_model_config is not None
        )
        if use_corr:
            return gen2().record_correlated(
                values.run_id,
                values.event_type,
                values.payload,
                correlation={
                    "correlation_id": values.correlation_id,
                    "conversation_id": values.conversation_id,
                    "task_id": values.task_id,
                    "mission_id": values.mission_id,
                    "workflow_id": values.workflow_id,
                    "run_id": values.run_id,
                    "step_id": values.step_id,
                    "toolcall_id": values.toolcall_id,
                    "approval_id": values.approval_id,
                    "plan_revision": values.plan_revision,
                    "artifact_version": values.artifact_version,
                },
                model_id=values.model_id,
                component=values.component,
                input_text=values.input_text,
                output_text=values.output_text,
                config_fingerprint=values.config_fingerprint,
                token_usage=values.token_usage,
                effective_model_config=values.effective_model_config,
            )
        return gen2().record(
            values.run_id,
            values.event_type,
            values.payload,
            model_id=values.model_id,
            component=values.component,
            input_text=values.input_text,
            output_text=values.output_text,
            config_fingerprint=values.config_fingerprint,
            correlation_id=values.correlation_id,
        )

    @router.post("/gen2/flight/lifecycle", status_code=status.HTTP_201_CREATED)
    async def emit_lifecycle(values: LifecycleEmitInput) -> dict[str, Any]:
        return gen2().emit_run_lifecycle(
            values.run_id,
            values.phase,
            values.payload,
            model_id=values.model_id,
            component=values.component,
            input_text=values.input_text,
            output_text=values.output_text,
            config_fingerprint=values.config_fingerprint,
            severity=values.severity,
            duration_ms=values.duration_ms,
            correlation_id=values.correlation_id,
        )

    @router.get("/gen2/flight/runs/{run_id}/events")
    async def flight_events(run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return gen2().flight_log(run_id, after_sequence=after_sequence)

    @router.get("/gen2/flight/runs/{run_id}/audit-bundle")
    async def flight_audit_bundle(run_id: str) -> dict[str, Any]:
        return gen2().export_audit_bundle(run_id)

    @router.get("/gen2/flight/runs/{run_id}/summary")
    async def flight_human_summary(run_id: str) -> dict[str, Any]:
        return gen2().human_run_summary(run_id)

    @router.post("/gen2/flight/runs/{run_id}/export")
    async def flight_reproducible_export(run_id: str, values: ReproducibleExportInput) -> dict[str, Any]:
        return gen2().export_reproducible_bundle(
            run_id,
            experiment=values.experiment or None,
            include_events=values.include_events,
        )

    @router.post("/gen2/flight/experiments/relate", status_code=status.HTTP_201_CREATED)
    async def flight_experiment_relate(values: ExperimentRelationInput) -> dict[str, Any]:
        return gen2().register_experiment_relation(
            parent_run_id=values.parent_run_id,
            child_run_id=values.child_run_id,
            experiment=values.experiment,
            correlation_id=values.correlation_id,
        )

    @router.get("/gen2/flight/modes")
    async def flight_inspect_vs_replay_modes() -> dict[str, Any]:
        from gen2.correlation_telemetry import inspect_vs_replay_modes

        return inspect_vs_replay_modes()

    @router.get("/gen2/flight/compare")
    async def flight_compare(run_a: str, run_b: str) -> dict[str, Any]:
        return gen2().compare_runs(run_a, run_b)

    @router.post("/gen2/flight/runs/{run_id}/replay")
    async def flight_replay(run_id: str, values: ReplayInput) -> dict[str, Any]:
        result = gen2().replay_plan(
            run_id,
            from_sequence=values.from_sequence,
            alternate_model=values.alternate_model,
            alternate_plugin_version=values.alternate_plugin_version,
            permit_side_effects=values.permit_side_effects,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error") or "replay failed")
        result.setdefault("inspection_not_replay", True)
        return result

    @router.post("/gen2/flight/runs/{run_id}/comparative-replay")
    async def flight_comparative_replay(run_id: str, values: ComparativeReplayInput) -> dict[str, Any]:
        chat_fn = None
        if values.stub_model_output is not None or values.alternate_model:
            stub_output = values.stub_model_output if values.stub_model_output is not None else ""
            stub_tokens = int(values.stub_tokens or 0)

            def chat_fn(req: dict[str, Any]) -> dict[str, Any]:
                # Honest labeling: zero stub tokens => missing, not a fabricated exact total.
                if stub_tokens > 0:
                    usage = {"total_tokens": stub_tokens, "kind": "estimate", "estimated": True, "source": "software-test"}
                    tokens = stub_tokens
                else:
                    usage = {"missing": True, "kind": "missing", "source": "software-test"}
                    tokens = None
                out = {
                    "output": stub_output or f"[comparative stub for {req.get('model_id')}]",
                    "content": stub_output or f"[comparative stub for {req.get('model_id')}]",
                    "usage": usage,
                    "token_kind": usage.get("kind"),
                    "model_id": req.get("model_id"),
                    "label": "software-test",
                }
                if tokens is not None:
                    out["tokens"] = tokens
                    out["estimated"] = True
                else:
                    out["tokens_missing"] = True
                return out

        result = gen2().comparative_replay(
            run_id,
            alternate_model=values.alternate_model,
            implementation_id=values.implementation_id,
            chat_fn=chat_fn,
            reuse_recorded_tools=values.reuse_recorded_tools,
            reexecute_side_effects=values.reexecute_side_effects,
            from_sequence=values.from_sequence,
            source_versions=values.source_versions,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "comparative replay failed")
        return result

    # Mission Control
    @router.get("/gen2/missions")
    async def list_missions(
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None, max_length=64),
    ) -> list[dict[str, Any]]:
        return gen2().store.list_missions(limit=limit, status=status)

    @router.get("/gen2/missions/portfolio")
    async def mission_portfolio(
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None, max_length=64),
    ) -> dict[str, Any]:
        return gen2().portfolio_missions(status=status, limit=limit)

    @router.post("/gen2/missions/compile", status_code=status.HTTP_201_CREATED)
    async def compile_mission(values: MissionCompileInput) -> dict[str, Any]:
        try:
            return gen2().compile_mission(values.goal, title=values.title, domain=values.domain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/missions/{mission_id}")
    async def get_mission(mission_id: str) -> dict[str, Any]:
        mission = gen2().store.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        from gen2.mission_control import attach_identity_links

        return attach_identity_links(mission) or mission

    @router.get("/gen2/missions/{mission_id}/links")
    async def mission_links(mission_id: str) -> dict[str, Any]:
        try:
            return gen2().mission_identity_links(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/gen2/missions/{mission_id}/revisions")
    async def list_mission_revisions(
        mission_id: str, limit: int = Query(default=50, ge=1, le=200)
    ) -> list[dict[str, Any]]:
        try:
            return gen2().list_mission_revisions(mission_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/gen2/missions/{mission_id}/revisions/diff")
    async def diff_mission_revisions(
        mission_id: str,
        from_version: int = Query(..., ge=1),
        to_version: int = Query(..., ge=1),
    ) -> dict[str, Any]:
        try:
            return gen2().diff_mission_revisions(mission_id, from_version, to_version)
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.post("/gen2/missions/{mission_id}/start")
    async def start_mission(mission_id: str, force_retry: bool = Query(default=False)) -> dict[str, Any]:
        def _create_task(mission: dict[str, Any]) -> dict[str, Any]:
            create = s.get("create_mission_task")
            if not callable(create):
                raise RuntimeError("task_bridge_unavailable")
            task = create(mission)
            if not isinstance(task, dict) or not task.get("id"):
                raise RuntimeError("task_bridge_unavailable")
            return task

        def _schedule_task(task_id: str) -> None:
            schedule = s.get("schedule_mission_task")
            if callable(schedule):
                schedule(task_id)

        try:
            # F-05: start_mission may briefly poll/sleep while another claim attaches
            # task_id — keep that off the request event loop.
            return await asyncio.to_thread(
                gen2().start_mission,
                mission_id,
                create_task=_create_task,
                schedule_task=_schedule_task,
                force_retry=force_retry,
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/gates/{gate_id}")
    async def decide_gate(mission_id: str, gate_id: str, values: MissionGateInput) -> dict[str, Any]:
        try:
            mission = gen2().decide_mission_gate(mission_id, gate_id, approve=values.approve, note=values.note)
            # Resume Work Runtime when a mid-wave gate clears.
            if values.approve and mission.get("task_id") and mission.get("status") in {"ready", "running"}:
                resume = s.get("resume_mission_task")
                if callable(resume):
                    try:
                        resume(str(mission["task_id"]))
                    except Exception as exc:
                        # Do not present gate approval as fully resumed when Work Runtime resume failed.
                        mission = {
                            **mission,
                            "resume_attempted": True,
                            "resume_ok": False,
                            "resume_error": str(exc)[:500],
                        }
                    else:
                        mission = {**mission, "resume_attempted": True, "resume_ok": True}
            return mission
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/gates/{gate_id}/revoke")
    async def revoke_gate(mission_id: str, gate_id: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        values = values or {}
        try:
            return gen2().revoke_mission_gate(mission_id, gate_id, reason=str(values.get("reason") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/missions/{mission_id}/budgets")
    async def mission_budgets(mission_id: str) -> dict[str, Any]:
        try:
            return gen2().mission_budget_ledger(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/budgets/reserve")
    async def mission_budget_reserve(mission_id: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            return gen2().reserve_mission_budget(
                mission_id,
                key=str(values.get("key") or "max_tool_calls"),
                amount=float(values.get("amount") if values.get("amount") is not None else 1),
                step_id=values.get("step_id"),
                reason=str(values.get("reason") or "reserve"),
                idempotency_key=values.get("idempotency_key"),
                reservation_id=values.get("reservation_id"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/budgets/consume")
    async def mission_budget_consume(mission_id: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            return gen2().consume_mission_budget(
                mission_id,
                key=str(values.get("key") or "max_tool_calls"),
                amount=float(values.get("amount") if values.get("amount") is not None else 1),
                step_id=values.get("step_id"),
                reservation_id=values.get("reservation_id"),
                from_reservation=bool(values.get("from_reservation", True)),
                idempotency_key=values.get("idempotency_key"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/budgets/release")
    async def mission_budget_release(mission_id: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            return gen2().release_mission_budget(
                mission_id,
                reservation_id=str(values.get("reservation_id") or ""),
                reason=str(values.get("reason") or "release"),
                idempotency_key=values.get("idempotency_key"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/acceptance/evaluate")
    async def evaluate_mission_acceptance(
        mission_id: str, values: MissionAcceptanceEvalInput | None = None
    ) -> dict[str, Any]:
        body = values or MissionAcceptanceEvalInput()
        try:
            return gen2().evaluate_mission_acceptance(
                mission_id,
                status=body.status,
                verification=dict(body.verification or {}),
                step_summary=dict(body.step_summary or {}),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/replan")
    async def replan_mission(mission_id: str, values: MissionReplanInput) -> dict[str, Any]:
        try:
            return gen2().replan_mission(
                mission_id,
                values.cause,
                note=values.note,
                failed_step_id=values.failed_step_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc

    @router.post("/gen2/missions/{mission_id}/pause")
    async def pause_mission(mission_id: str) -> dict[str, Any]:
        mission = gen2().store.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        if mission.get("status") not in {"running", "queued", "ready", "awaiting_approval", "dispatched"}:
            raise HTTPException(status_code=400, detail=f"cannot pause from {mission.get('status')}")
        pause = s.get("pause_mission_task")
        if mission.get("task_id") and callable(pause):
            try:
                pause(str(mission["task_id"]))
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = gen2().store.update_mission(mission_id, status="paused") or mission
        gen2().record(mission_id, "RUN_PAUSED", {"task_id": mission.get("task_id")}, component="mission_control")
        return updated

    @router.post("/gen2/missions/{mission_id}/resume")
    async def resume_mission(mission_id: str) -> dict[str, Any]:
        mission = gen2().store.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="mission not found")
        if mission.get("status") not in {"paused", "blocked", "awaiting_approval", "ready"}:
            raise HTTPException(status_code=400, detail=f"cannot resume from {mission.get('status')}")
        # Do not resume past required start gates.
        pending = gen2().pending_gates_for_wave(mission, before_wave=1)
        # pending_gates_for_wave only includes before_wave>0; include wave0/1 start gates manually.
        start_blocked = [
            g
            for g in (mission.get("gates") or [])
            if g.get("required")
            and g.get("status") != "approved"
            and int(g.get("before_wave", 0) or 0) <= 1
        ]
        if start_blocked or pending:
            raise HTTPException(status_code=400, detail="gates still require approval")
        resume = s.get("resume_mission_task")
        if mission.get("task_id") and callable(resume):
            try:
                resume(str(mission["task_id"]))
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = gen2().store.update_mission(mission_id, status="running") or mission
        gen2().record(mission_id, "RUN_RESUMED", {"task_id": mission.get("task_id")}, component="mission_control")
        return updated

    # Committee
    @router.post("/gen2/committees", status_code=status.HTTP_201_CREATED)
    async def run_committee(values: CommitteeInput) -> dict[str, Any]:
        mode = (values.mode or "heuristic").strip().lower()
        try:
            if mode in {"live", "live_specialist", "model"}:
                chat_fn = None
                try:
                    gateway = s.get("gateway_chat")
                    factory = s.get("lm_client")
                    if callable(gateway):
                        async def chat_fn(payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
                            return await gateway(payload, surface="committee", model_id=values.model_id)
                    elif callable(factory):
                        client = factory()
                        chat_fn = client.chat
                except Exception:
                    chat_fn = None
                return await gen2().run_committee_live(
                    values.topic,
                    domain=values.domain,
                    evidence=values.evidence,
                    chat_fn=chat_fn,
                    model_id=values.model_id,
                    model_slots=values.model_slots or None,
                )
            return gen2().run_committee(
                values.topic,
                domain=values.domain,
                evidence=values.evidence,
                model_id=values.model_id,
                model_slots=values.model_slots or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/committees")
    async def list_committees(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
        return gen2().store.list_committees(limit=limit)

    @router.get("/gen2/committees/{session_id}")
    async def get_committee(session_id: str) -> dict[str, Any]:
        item = gen2().store.get_committee(session_id)
        if not item:
            raise HTTPException(status_code=404, detail="committee not found")
        return item

    # Agent factory
    @router.get("/gen2/skills")
    async def list_skills(status_filter: str | None = None) -> list[dict[str, Any]]:
        return gen2().store.list_skills(status=status_filter)

    @router.post("/gen2/skills/candidates", status_code=status.HTTP_201_CREATED)
    async def extract_skill(values: SkillExtractInput) -> dict[str, Any]:
        return gen2().extract_skill_candidate(
            name=values.name,
            workflow=values.workflow,
            pattern_source=values.pattern_source,
            tools=values.tools,
        )

    @router.post("/gen2/skills/extract-from-run")
    async def extract_skill_from_run(values: SkillExtractFromRunInput) -> dict[str, Any]:
        """Auto-extract skill patterns from a Flight Recorder run (known handlers only)."""
        if not values.create:
            extraction = gen2().extract_patterns_from_run(values.run_id)
            return {
                "created": False,
                "skill": None,
                "extraction": extraction,
                "reason": extraction.get("reason"),
                "promoted": False,
            }
        result = gen2().extract_and_create_candidate(
            values.run_id, name=values.name, tools=values.tools or None
        )
        # Never auto-promote; created candidates stay status=candidate.
        if result.get("created") and (result.get("skill") or {}).get("status") == "promoted":
            raise HTTPException(status_code=500, detail="extract_must_not_promote")
        return result

    @router.post("/gen2/skills/{skill_id}/benchmark")
    async def benchmark_skill(skill_id: str) -> dict[str, Any]:
        try:
            return gen2().benchmark_skill(skill_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/skills/{skill_id}/promote")
    async def promote_skill(skill_id: str, values: SkillPromoteInput) -> dict[str, Any]:
        try:
            return gen2().promote_skill(skill_id, human_approved=values.human_approved)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/skills/{skill_id}/execute")
    async def execute_skill(skill_id: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return gen2().execute_promoted_skill(skill_id, inputs=dict((values or {}).get("inputs") or {}))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/skills/{skill_id}/deactivate")
    async def deactivate_skill(skill_id: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return gen2().deactivate_skill(skill_id, reason=str((values or {}).get("reason") or "deactivated"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/skills/{skill_id}/rollback")
    async def rollback_skill(skill_id: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return gen2().rollback_skill(skill_id, to_status=str((values or {}).get("to_status") or "benchmarked"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Sandbox
    @router.get("/gen2/sandbox/envelopes")
    async def list_envelopes() -> list[dict[str, Any]]:
        return gen2().store.list_envelopes()

    @router.put("/gen2/sandbox/envelopes/{plugin_id}")
    async def upsert_envelope(plugin_id: str, values: EnvelopeInput) -> dict[str, Any]:
        if values.envelope is not None:
            tier = int(values.tier if values.tier is not None else values.envelope.get("tier") or 1)
            return gen2().store.upsert_envelope(plugin_id, tier, values.envelope)
        return gen2().default_envelope(plugin_id, permissions=values.permissions)

    @router.get("/gen2/sandbox/envelopes/{plugin_id}")
    async def get_envelope(plugin_id: str) -> dict[str, Any]:
        env = gen2().store.get_envelope(plugin_id)
        if not env:
            env = gen2().default_envelope(plugin_id)
        return env

    @router.post("/gen2/sandbox/envelopes/{plugin_id}/check")
    async def check_envelope(plugin_id: str, values: EnvelopeCheckInput) -> dict[str, Any]:
        return gen2().enforce_envelope(
            plugin_id,
            action=values.action,
            path=values.path,
            network_host=values.network_host,
            autonomous=values.autonomous,
            approved=values.approved,
        )

    # Temporal graph
    @router.post("/gen2/graph/edges", status_code=status.HTTP_201_CREATED)
    async def add_edge(values: GraphEdgeInput) -> dict[str, Any]:
        try:
            payload = values.model_dump()
            require = bool(payload.pop("require_provenance", False))
            return gen2().assert_edge(payload, require_provenance=require)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/graph/edges")
    async def list_edges(
        as_of: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> list[dict[str, Any]]:
        return gen2().store.list_graph_edges(as_of=as_of, source_id=source_id, target_id=target_id, limit=limit)

    @router.get("/gen2/graph/as-of")
    async def graph_as_of(
        entity_id: str,
        as_of: str,
        known_as_of: str | None = None,
    ) -> dict[str, Any]:
        return gen2().as_of_beliefs(entity_id, as_of, known_as_of=known_as_of)

    @router.get("/gen2/graph/contradictions")
    async def graph_contradictions(entity_id: str | None = None) -> list[dict[str, Any]]:
        return gen2().find_contradictions(entity_id)

    # Finance fusion
    @router.get("/gen2/graph/analogues")
    async def graph_analogues(
        entity_id: str | None = None,
        relation_kind: str | None = None,
        text: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return gen2().find_analogues(
            entity_id=entity_id, relation_kind=relation_kind, text=text, limit=limit
        )

    @router.post("/gen2/finance/fuse")
    async def finance_fuse(values: FinanceFuseInput) -> dict[str, Any]:
        return gen2().fuse_market_intelligence(articles=values.articles, symbol=values.symbol)

    @router.post("/gen2/finance/event-study")
    async def finance_event_study(values: FinanceEventStudyInput) -> dict[str, Any]:
        event = dict(values.event or {})
        if values.event_id and not event.get("id"):
            stored = gen2().store.get_market_event(values.event_id)
            if not stored:
                raise HTTPException(status_code=404, detail="event not found")
            event = stored
        if not event:
            raise HTTPException(status_code=400, detail="event or event_id required")
        return gen2().run_event_study(event, bars=values.bars or None, window_days=values.window_days)

    @router.get("/gen2/finance/events")
    async def finance_events(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
        return gen2().store.list_market_events(limit=limit)

    # Compute fabric
    @router.get("/gen2/compute/nodes")
    async def compute_nodes() -> list[dict[str, Any]]:
        return gen2().discover_nodes()

    @router.get("/gen2/compute/status")
    async def compute_status() -> dict[str, Any]:
        return {
            "workers": gen2().worker_status(),
            "fabric": gen2().distributed_status(),
        }

    @router.post("/gen2/compute/nodes/heartbeat")
    async def compute_heartbeat(node_id: str = "node_local") -> dict[str, Any]:
        return gen2().heartbeat(node_id)

    @router.post("/gen2/compute/workers/pair", status_code=status.HTTP_201_CREATED)
    async def pair_worker(values: PairWorkerInput) -> dict[str, Any]:
        return gen2().pair_worker(
            node_id=values.node_id,
            name=values.name,
            base_url=values.base_url,
            shared_secret=values.shared_secret,
            capabilities=values.capabilities or None,
        )

    @router.post("/gen2/compute/jobs", status_code=status.HTTP_201_CREATED)
    async def dispatch_job(values: DispatchJobInput) -> dict[str, Any]:
        try:
            return gen2().dispatch_job(
                payload=values.payload,
                mission_id=values.mission_id,
                node_id=values.node_id,
                network_allowed=values.network_allowed,
                prefer_local_fallback=values.prefer_local_fallback,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/compute/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return gen2().cancel_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/gen2/compute/jobs")
    async def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
        return gen2().store.list_remote_jobs(limit=limit)

    @router.post("/gen2/compute/queue/drain")
    async def drain_local_queue(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return gen2().process_local_compute_queue(limit=limit)

    @router.get("/gen2/compute/gates/single-node")
    async def compute_single_node_gate() -> dict[str, Any]:
        return gen2().single_node_compute_gate()

    # ------------------------------------------------------------------ #
    # Workflows
    # ------------------------------------------------------------------ #
    @router.get("/gen2/workflows")
    async def list_workflows(
        status_filter: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return gen2().list_workflows(status=status_filter, limit=limit)

    @router.post("/gen2/workflows", status_code=status.HTTP_201_CREATED)
    async def create_workflow(values: WorkflowCreateInput) -> dict[str, Any]:
        definition = dict(values.definition or {})
        if values.name:
            definition["name"] = values.name
        try:
            return gen2().create_workflow(definition, note=values.note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/workflows/draft")
    async def draft_workflow(values: WorkflowDraftInput) -> dict[str, Any]:
        try:
            return gen2().draft_workflow(values.goal)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/workflows/templates")
    async def list_workflow_templates() -> list[dict[str, Any]]:
        return gen2().list_workflow_templates()

    @router.post("/gen2/workflows/templates", status_code=status.HTTP_201_CREATED)
    async def create_workflow_from_template(values: WorkflowTemplateCreateInput) -> dict[str, Any]:
        try:
            return gen2().create_workflow_from_template(values.template_id, name=values.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/gen2/workflows/import", status_code=status.HTTP_201_CREATED)
    async def import_workflow(values: WorkflowImportInput) -> dict[str, Any]:
        package: Any = values.package if values.package is not None else values.raw
        if package is None:
            raise HTTPException(status_code=400, detail="package or raw required")
        try:
            return gen2().import_workflow(package)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/gen2/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str) -> dict[str, Any]:
        row = gen2().get_workflow(workflow_id)
        if not row:
            raise HTTPException(status_code=404, detail="workflow not found")
        return row

    @router.put("/gen2/workflows/{workflow_id}")
    async def update_workflow(workflow_id: str, values: WorkflowUpdateInput) -> dict[str, Any]:
        try:
            return gen2().update_workflow(
                workflow_id,
                values.definition,
                name=values.name,
                bump_version=values.bump_version,
                note=values.note,
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.post("/gen2/workflows/{workflow_id}/validate")
    async def validate_workflow(workflow_id: str) -> dict[str, Any]:
        row = gen2().get_workflow(workflow_id)
        if not row:
            raise HTTPException(status_code=404, detail="workflow not found")
        errors = gen2().validate_workflow(row.get("definition") or {})
        return {"workflow_id": workflow_id, "valid": not errors, "errors": errors}

    @router.post("/gen2/workflows/{workflow_id}/dry-run")
    async def dry_run_workflow(workflow_id: str) -> dict[str, Any]:
        try:
            return gen2().dry_run_workflow(workflow_id)
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.post("/gen2/workflows/{workflow_id}/sandbox-run")
    async def sandbox_run_workflow(
        workflow_id: str, values: WorkflowSandboxInput | None = None
    ) -> dict[str, Any]:
        try:
            return gen2().sandbox_run_workflow(
                workflow_id, run_inputs=dict((values or WorkflowSandboxInput()).inputs or {})
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.post("/gen2/workflows/{workflow_id}/execute")
    async def execute_workflow(
        workflow_id: str, values: WorkflowExecuteInput | None = None
    ) -> dict[str, Any]:
        """Product execution via real CodingAgent/ResearchRunner/adapters (non-blocking by default)."""
        payload = values or WorkflowExecuteInput()
        try:
            return gen2().product_run_workflow(
                workflow_id,
                run_inputs=dict(payload.inputs or {}),
                timeout_seconds=payload.timeout_seconds,
                async_mode=payload.async_mode,
                blocking=payload.blocking,
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.get("/gen2/workflows/{workflow_id}/runs")
    async def list_workflow_runs(
        workflow_id: str, limit: int = Query(default=50, ge=1, le=200)
    ) -> list[dict[str, Any]]:
        if not gen2().get_workflow(workflow_id):
            raise HTTPException(status_code=404, detail="workflow not found")
        return gen2().list_workflow_runs(workflow_id, limit=limit)

    @router.get("/gen2/workflows/{workflow_id}/runs/{run_id}")
    async def get_workflow_run(workflow_id: str, run_id: str) -> dict[str, Any]:
        row = gen2().get_workflow_run(run_id)
        if not row or str(row.get("workflow_id")) != workflow_id:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return row

    @router.post("/gen2/workflows/{workflow_id}/runs/{run_id}/cancel")
    async def cancel_workflow_run(workflow_id: str, run_id: str) -> dict[str, Any]:
        row = gen2().get_workflow_run(run_id)
        if not row or str(row.get("workflow_id")) != workflow_id:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return gen2().cancel_workflow_run(run_id)

    @router.post("/gen2/workflows/{workflow_id}/runs/{run_id}/pause")
    async def pause_workflow_run(workflow_id: str, run_id: str) -> dict[str, Any]:
        row = gen2().get_workflow_run(run_id)
        if not row or str(row.get("workflow_id")) != workflow_id:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return gen2().pause_workflow_run(run_id)

    @router.post("/gen2/workflows/{workflow_id}/runs/{run_id}/resume")
    async def resume_workflow_run(workflow_id: str, run_id: str) -> dict[str, Any]:
        row = gen2().get_workflow_run(run_id)
        if not row or str(row.get("workflow_id")) != workflow_id:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return gen2().resume_workflow_run(run_id)

    @router.post("/gen2/workflows/{workflow_id}/promote")
    async def promote_workflow(workflow_id: str, values: WorkflowPromoteInput) -> dict[str, Any]:
        try:
            return gen2().promote_workflow(
                workflow_id, human_approved=values.human_approved, target=values.target
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.post("/gen2/workflows/{workflow_id}/rollback")
    async def rollback_workflow(workflow_id: str, values: WorkflowRollbackInput) -> dict[str, Any]:
        try:
            return gen2().rollback_workflow(
                workflow_id, to_status=values.to_status, to_version=values.to_version
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.get("/gen2/workflows/{workflow_id}/revisions")
    async def list_workflow_revisions(
        workflow_id: str, limit: int = Query(default=50, ge=1, le=200)
    ) -> list[dict[str, Any]]:
        try:
            return gen2().list_workflow_revisions(workflow_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/gen2/workflows/{workflow_id}/diff")
    async def diff_workflow_revisions(
        workflow_id: str,
        from_version: int = Query(alias="from", ge=1),
        to_version: int = Query(alias="to", ge=1),
    ) -> dict[str, Any]:
        try:
            return gen2().diff_workflow_revisions(workflow_id, from_version, to_version)
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.get("/gen2/workflows/{workflow_id}/export")
    async def export_workflow(
        workflow_id: str, as_zip: bool = Query(default=False)
    ) -> dict[str, Any]:
        try:
            package = gen2().export_workflow(workflow_id, as_zip=as_zip)
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc
        if isinstance(package, (bytes, bytearray)):
            import base64

            return {
                "format": "HadesWorkflow",
                "encoding": "zip_base64",
                "data": base64.b64encode(bytes(package)).decode("ascii"),
            }
        return package

    @router.post("/gen2/workflows/{workflow_id}/to-skill", status_code=status.HTTP_201_CREATED)
    async def workflow_to_skill(workflow_id: str) -> dict[str, Any]:
        try:
            return gen2().workflow_to_skill(workflow_id)
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.post("/gen2/workflows/{workflow_id}/human/{step_id}/decide")
    async def decide_workflow_human_step(
        workflow_id: str, step_id: str, values: WorkflowHumanDecideInput
    ) -> dict[str, Any]:
        try:
            return gen2().decide_workflow_human_step(
                workflow_id,
                step_id,
                decision=values.decision,
                value=values.value,
                resume=values.resume,
            )
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    @router.get("/gen2/workflows/{workflow_id}/metrics")
    async def workflow_metrics(workflow_id: str) -> dict[str, Any]:
        try:
            return gen2().workflow_metrics(workflow_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/gen2/workflows/{workflow_id}/archive")
    async def archive_workflow(workflow_id: str) -> dict[str, Any]:
        try:
            return gen2().archive_workflow(workflow_id)
        except ValueError as exc:
            detail = str(exc)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from exc

    return router
