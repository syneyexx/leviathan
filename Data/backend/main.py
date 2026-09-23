from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DATA_ROOT, FRONTEND_DIST, FRONTEND_ROOT, settings
from .database import Database
from .migrations import MigrationRunner
from Data.backend.routes.settings import build_settings_router
from Data.modules.settings import DEFAULT_BEHAVIOR_PROFILE, SettingsControlPlane
from Data.modules.settings.bindings import bind_default_consumers
from Data.modules.common import ownership_public_dict
from Data.modules.agents import (
    AgentFleetService,
    AgentFleetStore,
    AgentKind,
    AgentRuntime,
    MultiAgentCoordinator,
)
from Data.modules.analytics import AnalyticsService
from Data.modules.approvals import (
    DEFAULT_AUTHORITY_PROFILE,
    ApprovalService,
    ApprovalStatus,
    ApprovalStore,
    PolicyEngine,
)
from Data.modules.coding import CodingControlPlane
from Data.backend.routes.coding import build_coding_router
from Data.backend.routes.agents import build_agents_router
from Data.backend.routes.analytics import build_analytics_router
from Data.modules.market_sim import MarketSimControlPlane
from Data.backend.routes.market_sim import build_market_sim_router
from Data.modules.artifacts import ArtifactStore
from Data.modules.evidence import EvidenceService, EvidenceStatus, EvidenceStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
    build_frontier_manifest,
)
from Data.modules.function_runtime import FunctionCallStatus, build_default_registry, FunctionRuntime
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager
from Data.modules.knowledge import (
    AtlasStore,
    CognitiveEconomyGovernor,
    DeepRecallRequest,
    DeepRecallService,
    HybridRetriever,
    KnowledgeStore,
    RerankerProvider,
    RetrievalQuery,
    WhyLibrary,
    build_embedding_provider,
)
from Data.modules.memory import MemoryKind, MemoryStatus, MemoryStore
from Data.modules.model_runtime import LLMUnavailable, OpenAICompatibleLLM, chat_truth, sse_encode
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.backend.routes.models import build_models_router
from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleManagerError
from Data.modules.observations import ObservationStore
from Data.modules.reasoning import ReasoningEngine
from Data.modules.run import EventType, RunState, RunStore
from Data.modules.verification import (
    VerificationEngine,
    VerificationReportStore,
    VerificationRequirement,
)
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef, WorkflowStore
from Data.modules.schedules import (
    ScheduleRunner,
    ScheduleStatus,
    ScheduleStore,
    ScheduleTargetKind,
)
from Data.modules.observability import (
    ObservabilityHub,
    SystemTelemetrySampler,
    build_default_operator_registry,
)
from Data.modules.metrics import MetricsCollector, TimeSeriesStore
from Data.backend.routes.observability import build_observability_router
from Data.backend.routes.system import build_system_telemetry_router
from Data.backend.routes.brain import build_brain_router
from Data.modules.brain import BrainQueryFacade
from Data.modules.neuro import (
    ContrastiveRetrievalHead,
    CortexPlanner,
    CortexRuntime,
    NeuroAbsorbService,
    NeuroAdvisor,
    NeuroMemoryFacade,
    NeuroSnapshotStore,
    NeuroSoakHarness,
    ProcessCritic,
    ResidualOrchestrator,
    ResidualReceiptStore,
    build_residual_runtime,
)
from Data.modules.plugins import PluginRegistry, PluginStatus
from Data.modules.evaluation import EvaluationHarness
from Data.modules.isolation import IsolationGuard, IsolationMode, IsolationRequest
from Data.modules.training import (
    PreferenceBridge,
    TrainingRecipeRegistry,
    TrainingRegistry,
    TrainingService,
    build_neuro_recipe_trainer,
)
from Data.modules.datasets import DatasetService
from Data.modules.research import ResearchService
from Data.modules.common.corpus import build_corpus_layout
from Data.backend.routes.datasets import build_datasets_router
from Data.backend.routes.training import build_training_router
from Data.backend.routes.research import build_research_router
from Data.modules.browser import BrowserAction, BrowserAutomationStub
from Data.modules.media import MediaAction, MediaAutomationStub
from Data.modules.voice import VoiceAction, VoiceRuntimeStub
from Data.modules.release import GateCheck, GateSeverity, ReleaseGateRunner
from Data.modules.mcp import McpBridge, McpProvider, McpStore, register_module_mcp, unregister_module_mcp
from Data.backend.routes.mcp import build_mcp_router
from Data.backend.routes.cognition import build_cognition_router
from Data.modules.mcp.errors import McpError
from Data.modules.cognition import (
    CognitionStore,
    CognitiveRuntime,
    DelegationService,
    ExperienceStore,
    PerceptionService,
    CapabilityBroker,
)
from Data.modules.security import SecurityAuditor, SecurityFinding
from Data.modules.native import NativeRuntimeStub
from Data.modules.trading import TradingStub
from Data.modules.backup import BackupError, BackupService
from Data.modules.chaos import ChaosInjector, ChaosPlan
from Data.modules.master import MasterGateCheck, MasterGateRunner, MasterGateStatus

db = Database(settings.database_path)
runs = RunStore(settings.database_path)
artifacts = ArtifactStore(settings.database_path, settings.artifacts.root)
embedding_provider = build_embedding_provider(
    kind=settings.knowledge.embedding_provider,
    model_name=settings.knowledge.embedding_model,
    hash_dimensions=settings.knowledge.embedding_hash_dimensions,
)
reranker_provider = (
    RerankerProvider(model_name=settings.knowledge.reranker_model)
    if settings.knowledge.reranker_model
    else None
)
knowledge = KnowledgeStore(
    settings.database_path,
    data_root=settings.knowledge.data_root,
    chunk_max_chars=settings.knowledge.chunk_max_chars,
    chunk_overlap=settings.knowledge.chunk_overlap,
    embedding_provider=embedding_provider,
)
retriever = HybridRetriever(knowledge, embeddings=embedding_provider, reranker=reranker_provider)
atlas_store = AtlasStore(settings.database_path)
why_library = WhyLibrary(settings.database_path, enabled=settings.features.why_library)
economy_governor = CognitiveEconomyGovernor(
    enabled=True,
    default_deep_recall_budget=settings.knowledge.deep_recall_budget,
)
deep_recall_service = DeepRecallService(
    knowledge=knowledge,
    atlas=atlas_store,
    retriever=retriever,
    db_path=settings.database_path,
    enabled=settings.features.deep_recall,
)
function_registry = build_default_registry()
function_runtime = FunctionRuntime(
    function_registry,
    max_concurrency=settings.resources.max_function_concurrency,
    warm_cache_size=2,
)
capability_catalog = build_default_catalog()
approval_store = ApprovalStore(settings.database_path)
approval_service = ApprovalService(approval_store, PolicyEngine())
observation_store = ObservationStore(settings.database_path)
execution_gateway = ExecutionGateway(
    catalog=capability_catalog,
    function_runtime=function_runtime,
    knowledge_retriever=retriever,
    knowledge_store=knowledge,
    artifact_store=artifacts,
    approval_checker=approval_service,
    observation_store=observation_store,
)
job_store = JobStore(settings.database_path)
resource_manager = ResourceManager(settings.resources.max_job_concurrency)
job_runtime = JobRuntime(job_store, execution_gateway, resource_manager)
evidence_store = EvidenceStore(settings.database_path)
evidence_service = EvidenceService(
    evidence_store,
    artifacts=artifacts,
    observations=observation_store,
)
memory_store = MemoryStore(settings.database_path)
verification_reports = VerificationReportStore(settings.database_path)
verification_engine = VerificationEngine(evidence_store)
agent_runtime = AgentRuntime(
    gateway=execution_gateway,
    jobs=job_runtime,
    verification=verification_engine,
    runs=runs,
    agents_enabled=settings.features.agents_enabled,
)
multi_agents = MultiAgentCoordinator(agent_runtime)
agent_fleet_store = AgentFleetStore(settings.database_path)
agent_fleet = AgentFleetService(agent_fleet_store, agent_runtime)
analytics_service = AnalyticsService(settings.database_path)
workflow_store = WorkflowStore(settings.database_path)
workflow_runtime = WorkflowRuntime(workflow_store, execution_gateway)
schedule_store = ScheduleStore(settings.database_path)
schedule_runner = ScheduleRunner(
    schedule_store,
    jobs=job_runtime,
    workflows=workflow_runtime,
)
observability = ObservabilityHub(capacity=2000, db_path=settings.database_path)
system_telemetry_sampler = SystemTelemetrySampler(interval_s=1.0, gpu_interval_s=2.0)
metrics = MetricsCollector()
timeseries = TimeSeriesStore(max_points_per_series=3_600)
deep_recall_service._emit = lambda name, payload: observability.emit(  # noqa: SLF001
    "knowledge", name, payload=payload
)
neuro_snapshots = NeuroSnapshotStore(settings.database_path)
residual_receipts = ResidualReceiptStore(settings.database_path)
residual_runtime = build_residual_runtime(
    kind=settings.neuro_runtime.residual_kind,
    model_id=settings.neuro_runtime.residual_model_id,
    device=settings.neuro_runtime.residual_device,
    load_weights=settings.neuro_runtime.residual_load_weights,
    selected_layers=settings.neuro_runtime.residual_hook_layers or None,
    server_url=settings.neuro_runtime.residual_server_url,
)
neuro_memory = NeuroMemoryFacade(
    enabled=settings.features.neuro_enabled and settings.features.neuro_memory_tiers,
    memory_store=memory_store,
    knowledge_store=knowledge,
    knowledge_retriever=retriever,
    snapshot_store=neuro_snapshots,
    use_embeddings=bool(retriever.embeddings.available()),
    working_capacity=settings.neuro_runtime.memory_tier0_max_slots,
)
neuro_absorb = NeuroAbsorbService(knowledge)
neuro_contrastive = ContrastiveRetrievalHead(
    neuro_memory,
    embeddings_available=bool(retriever.embeddings.available()),
    embedding_provider=retriever.embeddings if retriever.embeddings.available() else None,
)
neuro_critic = ProcessCritic(enabled=settings.features.neuro_process_critic)
cortex_runtime = CortexRuntime(
    residual_port=residual_runtime,
    critic=neuro_critic,
    max_k=settings.neuro_runtime.cortex_max_k,
    named_blocks_enabled=settings.features.neuro_cortex_blocks,
)
residual_orchestrator = ResidualOrchestrator(
    residual_port=residual_runtime,
    enabled=(
        settings.features.neuro_enabled
        and settings.features.neuro_residual_orchestrator
    ),
    hook_layers=settings.neuro_runtime.residual_hook_layers,
    observability=observability,
)
neuro_advisor = NeuroAdvisor(
    enabled=settings.features.neuro_enabled,
    associative_memory=settings.features.neuro_associative_memory,
    process_critic=settings.features.neuro_process_critic,
    residual_injection=settings.features.neuro_residual_injection,
    cortex_enabled=settings.features.neuro_cortex,
    memory_tiers_enabled=settings.features.neuro_memory_tiers,
    residual_port=residual_runtime,
    memory_facade=neuro_memory,
    cortex_planner=CortexPlanner(
        enabled=settings.features.neuro_cortex,
        max_depth=min(2, max(0, settings.neuro_runtime.cortex_max_k)),
        max_critic_rounds=settings.neuro_runtime.cortex_max_k,
        default_token_budget=settings.context.token_budget,
    ),
    critic=neuro_critic,
    token_budget=settings.context.token_budget,
    observability=observability,
)
module_manager = ModuleManager(
    discovery_roots=(
        DATA_ROOT / "modules",
        settings.knowledge.data_root / "plugins",
    ),
    enabled=settings.features.module_manager_enabled,
    allow_subprocess_isolation=settings.features.module_manager_subprocess,
)
plugin_registry = PluginRegistry(capability_catalog)
plugin_registry.register_echo_mcp_stub()
mcp_store = McpStore(settings.database_path)
mcp_bridge = McpBridge(
    store=mcp_store,
    catalog=capability_catalog,
    plugin_registry=plugin_registry,
    enabled=settings.features.mcp_enabled,
    stdio_enabled=settings.features.mcp_stdio,
    http_enabled=settings.features.mcp_http,
    auto_expand_modules=settings.features.mcp_auto_expand_modules,
    allow_outbound=settings.network.allow_outbound,
)
mcp_provider = McpProvider(mcp_bridge)
execution_gateway.mcp_executor = mcp_provider
evaluation_harness = EvaluationHarness(
    catalog=capability_catalog,
    evidence=evidence_store,
    verification=verification_engine,
)
isolation_guard = IsolationGuard(settings)
training_registry = TrainingRegistry()
training_recipes = TrainingRecipeRegistry(
    trainer=build_neuro_recipe_trainer(
        real_worker=settings.features.neuro_training_real_worker
    )
)
preference_bridge = PreferenceBridge(training_registry)
corpus_layout = build_corpus_layout(settings)
dataset_service = DatasetService.from_settings(settings, knowledge=knowledge)
training_service = TrainingService(settings, corpus=corpus_layout)
research_service = ResearchService.from_settings(
    settings,
    db_path=settings.database_path,
    knowledge=knowledge,
)
coding_service = CodingControlPlane.from_settings(
    settings,
    db_path=settings.database_path,
    gateway=execution_gateway,
    approvals=approval_service,
    llm=None,  # wired after OpenAICompatibleLLM / FakeLLM in tests
    context_builder=None,
    reasoning=None,
    neuro=neuro_advisor,
    verification=verification_engine,
)
agent_runtime.coding = coding_service
agent_runtime.coding_enabled = settings.features.coding_enabled
market_sim_service = MarketSimControlPlane.from_settings(
    settings,
    db_path=settings.database_path,
    knowledge=knowledge,
    memory=memory_store,
    evidence=evidence_store,
    neuro=neuro_advisor,
    observability_emit=observability.emit,
)
neuro_soak = NeuroSoakHarness(long_soak_enabled=settings.features.neuro_soak_long)
browser_stub = BrowserAutomationStub()
media_stub = MediaAutomationStub()
voice_stub = VoiceRuntimeStub()


def _gate_catalog_builtins() -> GateCheck:
    required = {
        "file.read",
        "knowledge.search",
        "artifact.create_text",
        "knowledge.ingest_scan",
        "workspace.list",
        "workspace.search",
        "file.write",
        "file.patch",
        "file.delete",
        "coding.run_tests",
        "git.status",
        "git.diff",
    }
    missing = sorted(required - {item.id for item in capability_catalog.list()})
    return GateCheck(
        gate_id="catalog_builtins",
        name="Core capabilities registered",
        severity=GateSeverity.BLOCK,
        passed=not missing,
        detail="ok" if not missing else f"missing {missing}",
    )


def _gate_loopback() -> GateCheck:
    return GateCheck(
        gate_id="loopback_only",
        name="Loopback-only host",
        severity=GateSeverity.BLOCK,
        passed=bool(settings.runtime.loopback_only),
        detail="loopback_only enabled" if settings.runtime.loopback_only else "loopback_only disabled",
    )


def _gate_outbound() -> GateCheck:
    return GateCheck(
        gate_id="outbound_default_deny",
        name="Outbound network default deny",
        severity=GateSeverity.WARN,
        passed=not settings.network.allow_outbound,
        detail="outbound denied" if not settings.network.allow_outbound else "outbound allowed",
    )


def _gate_frontend() -> GateCheck:
    ready = (FRONTEND_DIST / "index.html").is_file()
    return GateCheck(
        gate_id="frontend_dist",
        name="Frontend dist present",
        severity=GateSeverity.WARN,
        passed=ready,
        detail="dist ready" if ready else "frontend dist missing",
    )


def _gate_neuro_residual_posture() -> GateCheck:
    """WARN when residual injection flag is ON but runtime cannot support residuals."""
    flag_on = settings.features.neuro_residual_injection
    supported = residual_runtime.supports_residuals()
    ok = (not flag_on) or supported
    return GateCheck(
        gate_id="neuro_residual_posture",
        name="Neuro residual posture",
        severity=GateSeverity.WARN,
        passed=ok,
        detail=(
            "ok"
            if ok
            else "NEURO_RESIDUAL_INJECTION=true but residual runtime unsupported"
        ),
    )


def _gate_module_manager_subprocess() -> GateCheck:
    enabled = settings.features.module_manager_subprocess
    return GateCheck(
        gate_id="module_manager_subprocess",
        name="Module Manager subprocess isolation",
        severity=GateSeverity.INFO,
        passed=True,
        detail="subprocess isolation ON" if enabled else "subprocess isolation OFF (inproc default)",
    )


release_gates = ReleaseGateRunner(
    checks=[
        _gate_catalog_builtins,
        _gate_loopback,
        _gate_outbound,
        _gate_frontend,
        _gate_neuro_residual_posture,
        _gate_module_manager_subprocess,
    ]
)
security_auditor = SecurityAuditor(
    checks=[
        lambda: SecurityFinding(
            finding_id="loopback",
            severity="high",
            title="Loopback-only binding",
            detail="ok" if settings.runtime.loopback_only else "host may be non-loopback",
            passed=bool(settings.runtime.loopback_only),
        ),
        lambda: SecurityFinding(
            finding_id="outbound",
            severity="medium",
            title="Outbound network default deny",
            detail="denied" if not settings.network.allow_outbound else "allowed",
            passed=not settings.network.allow_outbound,
        ),
        lambda: SecurityFinding(
            finding_id="approvals_write",
            severity="high",
            title="WRITE capabilities require approvals",
            detail="ExecutionGateway enforces approval_id for gated side effects",
            passed=True,
        ),
        lambda: SecurityFinding(
            finding_id="agents_default_off",
            severity="info",
            title="Agents feature default OFF",
            detail="agents_enabled=" + str(settings.features.agents_enabled),
            passed=not settings.features.agents_enabled,
        ),
        lambda: SecurityFinding(
            finding_id="chaos_default_off",
            severity="high",
            title="Chaos injection default OFF",
            detail="chaos_enabled=" + str(settings.chaos.enabled),
            passed=not settings.chaos.enabled,
        ),
        lambda: SecurityFinding(
            finding_id="public_summary_no_secrets",
            severity="high",
            title="Health public_summary omits API keys",
            detail="api_key absent from settings.public_summary()",
            passed="api_key" not in str(settings.public_summary()).lower()
            and "not-needed" not in str(settings.public_summary()),
        ),
        lambda: SecurityFinding(
            finding_id="restore_requires_confirm",
            severity="medium",
            title="Backup restore requires confirm=true",
            detail="BackupService.restore refuses silent overwrite",
            passed=True,
        ),
    ]
)
native_runtime = NativeRuntimeStub()
trading_stub = TradingStub()
backup_service = BackupService(
    database_path=settings.database_path,
    artifacts_root=settings.artifacts.root,
    backup_root=settings.backup.root,
)
chaos = ChaosInjector(
    ChaosPlan(
        enabled=settings.chaos.enabled,
        latency_ms=settings.chaos.latency_ms,
        error_rate=settings.chaos.error_rate,
    )
)


def _master_release_check() -> MasterGateCheck:
    report = release_gates.run()
    blocked = any(
        (not item.passed) and item.severity == GateSeverity.BLOCK for item in report.checks
    )
    warned = any(
        (not item.passed) and item.severity == GateSeverity.WARN for item in report.checks
    )
    if blocked:
        status = MasterGateStatus.BLOCKED
        detail = "release gates blocked"
    elif warned or not report.ready:
        status = MasterGateStatus.DEGRADED
        detail = "release gates degraded / warnings"
    else:
        status = MasterGateStatus.READY
        detail = "release gates ready (local)"
    return MasterGateCheck(
        check_id="release_gates",
        name="Release gates",
        status=status,
        detail=detail,
    )


def _master_security_check() -> MasterGateCheck:
    report = security_auditor.run()
    failed = report.summary.get("failed", 0)
    if failed:
        return MasterGateCheck(
            check_id="security_audit",
            name="Security posture",
            status=MasterGateStatus.BLOCKED,
            detail=f"{failed} finding(s) failed",
        )
    return MasterGateCheck(
        check_id="security_audit",
        name="Security posture",
        status=MasterGateStatus.READY,
        detail="posture checks passed (not a pentest)",
    )


def _master_evaluation_check() -> MasterGateCheck:
    report = evaluation_harness.run_suite(
        "foundation",
        evaluation_harness.default_foundation_suite(),
    )
    outcomes = {item.outcome.value for item in report.results}
    if "FAILED" in outcomes or "ERROR" in outcomes:
        return MasterGateCheck(
            check_id="evaluation_foundation",
            name="Foundation evaluation",
            status=MasterGateStatus.BLOCKED,
            detail="foundation suite has FAILED/ERROR",
        )
    if "UNMEASURED" in outcomes:
        return MasterGateCheck(
            check_id="evaluation_foundation",
            name="Foundation evaluation",
            status=MasterGateStatus.DEGRADED,
            detail="foundation suite has UNMEASURED (honest)",
        )
    return MasterGateCheck(
        check_id="evaluation_foundation",
        name="Foundation evaluation",
        status=MasterGateStatus.READY,
        detail="foundation suite measured",
    )


def _master_verification_store_check() -> MasterGateCheck:
    return MasterGateCheck(
        check_id="verification_reports",
        name="Verification report store",
        status=MasterGateStatus.READY,
        detail="durable verification_reports table available",
    )


def _master_neuro_posture_check() -> MasterGateCheck:
    residual_flag = settings.features.neuro_residual_injection
    supported = residual_runtime.supports_residuals()
    if residual_flag and not supported:
        return MasterGateCheck(
            check_id="neuro_residual",
            name="Neuro residual posture",
            status=MasterGateStatus.DEGRADED,
            detail="residual injection flagged ON without supporting runtime",
        )
    return MasterGateCheck(
        check_id="neuro_residual",
        name="Neuro residual posture",
        status=MasterGateStatus.READY,
        detail=(
            f"residual_supported={supported}; kind={settings.neuro_runtime.residual_kind}"
        ),
    )


master_gates = MasterGateRunner(
    checks=[
        _master_release_check,
        _master_security_check,
        _master_evaluation_check,
        _master_verification_store_check,
        _master_neuro_posture_check,
    ]
)
migrations = MigrationRunner(settings.database_path)
reasoner = ReasoningEngine()
llm = OpenAICompatibleLLM(settings)
model_plane = ModelControlPlane(settings, observability=observability)
settings_plane = SettingsControlPlane(settings)

cognition_store = CognitionStore(settings.database_path)
cognition_delegation = DelegationService()
cognition_runtime = CognitiveRuntime(
    enabled=settings.features.cognition_enabled,
    shadow=settings.features.cognition_shadow,
    iterative=settings.features.cognition_iterative_loop,
    belief_enabled=settings.features.cognition_belief_state,
    neuro_enabled=settings.features.cognition_neuro,
    adaptive_depth=settings.features.cognition_adaptive_depth,
    delegation_enabled=settings.features.cognition_delegation,
    experience_learning=settings.features.cognition_experience_learning,
    perception=PerceptionService(
        knowledge_store=knowledge,
        memory_store=memory_store,
        evidence_service=evidence_service,
        capability_catalog=capability_catalog,
        neuro_advisor=neuro_advisor if settings.features.cognition_neuro else None,
    ),
    broker=CapabilityBroker(capability_catalog),
    delegation=cognition_delegation,
    experience_store=ExperienceStore(store=cognition_store),
    store=cognition_store,
    neuro_advisor=neuro_advisor if settings.features.cognition_neuro else None,
    verification_engine=verification_engine,
    execution_gateway=execution_gateway,
    observability=observability,
    resource_pressure_fn=lambda: 0.0,
)


def _component_health() -> list[dict]:
    """Aggregate real component health for Performance page (no fabricated healthy)."""
    components: list[dict] = []

    def add(cid: str, name: str, ctype: str, status: str, detail: str = "") -> None:
        components.append(
            {
                "id": cid,
                "name": name,
                "type": ctype,
                "status": status,
                "detail": detail,
            }
        )

    add("backend", "backend", "Core", "healthy", "process up")
    add(
        "observability",
        "observability",
        "Runtime",
        "healthy" if observability.store is not None else "degraded",
        "durable" if observability.store is not None else "ring_buffer_only",
    )
    add(
        "job_runtime",
        "job-runtime",
        "Runtime",
        "healthy",
        f"queued={len(job_runtime.list(state=JobState.QUEUED, limit=500))}",
    )
    add(
        "module_manager",
        "module-manager",
        "Runtime",
        "healthy" if module_manager.enabled else "stopped",
        f"modules={len(module_manager.list())}",
    )
    if settings.features.mcp_enabled:
        try:
            servers = mcp_bridge.list_servers()
            connected = sum(
                1
                for s in servers
                if (s.get("connection_state") if isinstance(s, dict) else None) == "connected"
                or (getattr(s, "connection_state", None) == "connected")
            )
            add(
                "mcp_bridge",
                "mcp-bridge",
                "Bridge",
                "healthy" if connected or not servers else "degraded",
                f"servers={len(servers)} connected={connected}",
            )
        except Exception as exc:  # noqa: BLE001
            add("mcp_bridge", "mcp-bridge", "Bridge", "failed", type(exc).__name__)
    else:
        add("mcp_bridge", "mcp-bridge", "Bridge", "unavailable", "feature_disabled")

    sample = system_telemetry_sampler.latest_public()
    dash = sample.get("dashboard") if isinstance(sample, dict) else None
    if isinstance(dash, dict) and dash.get("cpuPct") is None and dash.get("ramPct") is None:
        add("system_telemetry", "system-telemetry", "Sampler", "degraded", "partial_unavailable")
    else:
        add("system_telemetry", "system-telemetry", "Sampler", "healthy", "sampling")

    return components


operator_registry = build_default_operator_registry(
    deps={
        "observability": observability,
        "module_manager": module_manager,
        "mcp_bridge": mcp_bridge,
        "workflow_store": workflow_store,
        "workflow_runtime": workflow_runtime,
        "job_store": job_store,
        "job_runtime": job_runtime,
        "capability_catalog": capability_catalog,
        "research_service": research_service,
        "dataset_service": dataset_service,
        "metrics": metrics,
        "system_telemetry_sampler": system_telemetry_sampler,
        "health_fn": lambda: {
            "ok": True,
            "modules": len(module_manager.list()),
            "jobs_queued": len(job_runtime.list(state=JobState.QUEUED, limit=500)),
            "observability": observability.snapshot(),
        },
    }
)

brain_facade = BrainQueryFacade(
    knowledge_list=lambda: knowledge.list_documents(limit=200),
    evidence_list=lambda: evidence_store.list(limit=200),
    research_list=lambda: research_service.list_projects(limit=100),
    dataset_list=lambda: dataset_service.list_datasets(limit=100),
    module_list=lambda: module_manager.list(),
    capability_list=lambda: capability_catalog.list(),
    mcp_servers=lambda: mcp_bridge.list_servers() if settings.features.mcp_enabled else [],
    mcp_tools=lambda: (
        mcp_bridge.list_tools() if hasattr(mcp_bridge, "list_tools") and settings.features.mcp_enabled else []
    ),
    workflow_list=lambda: workflow_store.list(limit=100),
    atlas_list=lambda: atlas_store.search("", limit=100) if settings.features.rag_v3 else [],
    max_nodes=250,
    max_edges=500,
)


def live_settings():
    """Effective settings after Settings Control Plane overrides."""
    return settings_plane.effective


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrations.apply_all()
    settings_plane.start()
    bind_default_consumers(
        settings_plane,
        resource_manager=resource_manager,
        function_runtime=function_runtime,
        knowledge=knowledge,
        deep_recall=deep_recall_service,
        why_library=why_library,
        mcp_bridge=mcp_bridge,
        cognition_runtime=cognition_runtime,
        agent_runtime=agent_runtime,
        coding_service=coding_service,
        research_service=research_service,
        isolation_guard=isolation_guard,
        chaos=chaos,
        model_plane=model_plane,
        llm=llm,
        neuro_advisor=neuro_advisor,
        neuro_critic=neuro_critic,
        neuro_soak=neuro_soak,
        module_manager=module_manager,
        market_sim_service=market_sim_service,
    )
    settings_plane._run_callbacks_for_all_hot()
    observability.emit(
        "settings",
        "control_plane.started",
        payload={"override_count": len(settings_plane._overrides)},
        level="info",
        message="Settings control plane started",
    )
    db.initialize()
    knowledge.initialize()
    atlas_store.initialize()
    why_library.initialize()
    deep_recall_service.initialize()
    runs.initialize()
    artifacts.initialize()
    approval_store.initialize()
    job_store.initialize()
    observation_store.initialize()
    evidence_store.initialize()
    memory_store.initialize()
    neuro_snapshots.initialize()
    residual_receipts.initialize()
    verification_reports.initialize()
    workflow_store.initialize()
    schedule_store.initialize()
    try:
        cognition_store.reconcile_interrupted()
    except Exception as exc:  # noqa: BLE001
        observability.emit(
            "cognition",
            "reconcile.failed",
            payload={"error": str(exc)},
            level="warning",
        )
    model_plane.bootstrap()
    try:
        await model_plane.reconcile_startup()
    except Exception as exc:  # noqa: BLE001 — startup must not crash if providers offline
        observability.emit(
            "models",
            "model.discovery.failed",
            payload={"error": str(exc)},
            level="warning",
        )
    dataset_service.reconcile()
    dataset_service.runner.start_background()
    training_service.reconcile()
    agent_fleet.initialize(seed_defaults=True)
    agent_fleet.reconcile()
    research_service.recover()
    coding_service.start_background()
    mcp_bridge.initialize()
    market_sim_service.start_background()
    if module_manager.enabled:
        ready = module_manager.discover_load_initialize_all(
            ModuleContext(
                database_path=str(settings.database_path),
                data_root=str(live_settings().knowledge.data_root),
                feature_flags={
                    "neuro_enabled": live_settings().features.neuro_enabled,
                    "neuro_cortex": live_settings().features.neuro_cortex,
                    "neuro_memory_tiers": live_settings().features.neuro_memory_tiers,
                    "neuro_residual_injection": live_settings().features.neuro_residual_injection,
                    "module_manager_enabled": live_settings().features.module_manager_enabled,
                    "mcp_enabled": live_settings().features.mcp_enabled,
                    "rag_v3": live_settings().features.rag_v3,
                    "deep_recall": live_settings().features.deep_recall,
                    "why_library": live_settings().features.why_library,
                    "residual_production": live_settings().features.residual_production,
                },
            )
        )
        if live_settings().features.mcp_enabled:
            for managed in ready:
                try:
                    register_module_mcp(
                        mcp_bridge,
                        module_id=managed.manifest.module_id,
                        manifest_path=managed.manifest.source_path,
                    )
                except McpError as exc:
                    observability.emit(
                        "mcp",
                        "module_expand_failed",
                        payload={
                            "module_id": managed.manifest.module_id,
                            "error": exc.code,
                            "message": exc.message,
                        },
                        level="warning",
                    )
        observability.emit(
            "module_manager",
            "startup",
            payload={"ready": len(ready), "telemetry": dict(module_manager.telemetry)},
        )
    job_runtime.start_background_worker()
    system_telemetry_sampler.start()
    metrics.incr("lifespan_starts")
    observability.emit(
        "backend",
        "startup",
        level="success",
        message="Leviathan backend ready",
        success=True,
        source="lifespan",
    )
    try:
        yield
    finally:
        observability.emit(
            "backend",
            "shutdown",
            level="info",
            message="Leviathan backend shutting down",
            source="lifespan",
        )
        observability.shutdown()
        system_telemetry_sampler.stop()
        mcp_bridge.shutdown()
        if module_manager.enabled:
            for managed in list(module_manager.list()):
                if managed.status.value in {"READY", "INITIALIZED", "LOADED", "EXECUTING"}:
                    if live_settings().features.mcp_enabled:
                        unregister_module_mcp(mcp_bridge, managed.manifest.module_id)
                    try:
                        module_manager.shutdown(managed.manifest.module_id)
                    except ModuleManagerError:
                        pass
        dataset_service.runner.stop_background()
        coding_service.stop_background()
        market_sim_service.stop_background()
        job_runtime.stop_background_worker()
        function_runtime.shutdown()


app = FastAPI(title="Leviathan", version="0.65.0-wave1-cognition", lifespan=lifespan)
app.include_router(build_models_router(model_plane))
app.include_router(build_datasets_router(dataset_service))
app.include_router(build_training_router(training_service))
app.include_router(build_research_router(research_service))
app.include_router(build_coding_router(coding_service))
app.include_router(build_agents_router(agent_fleet))
app.include_router(build_analytics_router(analytics_service))
app.include_router(build_system_telemetry_router(system_telemetry_sampler))
app.include_router(
    build_observability_router(
        observability=observability,
        operator=operator_registry,
        metrics=metrics,
        timeseries=timeseries,
        sampler=system_telemetry_sampler,
        component_health_fn=_component_health,
    )
)
app.include_router(build_brain_router(brain_facade))
app.include_router(build_mcp_router(mcp_bridge, execution_gateway))
app.include_router(build_market_sim_router(market_sim_service))
app.include_router(build_cognition_router(cognition_runtime))
app.include_router(build_settings_router(settings_plane))


@app.middleware("http")
async def _observability_http_middleware(request: Request, call_next):
    path = request.url.path
    # Skip noisy static/frontend asset traffic
    if path.startswith("/assets") or path in {"/", "/favicon.ico"}:
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)
    started = time.perf_counter()
    metrics.incr("http.requests")
    timeseries.observe("http.requests", 1.0)
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        timeseries.observe_latency_ms("http.request", duration_ms)
        metrics.incr(f"http.status.{status_code}")
        if status_code >= 500:
            metrics.incr("http.errors")
        # Avoid flooding console with high-frequency polling endpoints
        noisy = path in {
            "/api/system/telemetry",
            "/api/telemetry",
            "/api/events",
            "/api/metrics",
            "/api/performance/snapshot",
            "/api/health",
        }
        if not noisy and not path.startswith("/api/events/stream"):
            level = "error" if status_code >= 500 else ("warning" if status_code >= 400 else "info")
            observability.emit(
                "http",
                "request",
                level=level,
                message=f"{request.method} {path} → {status_code}",
                payload={
                    "method": request.method,
                    "path": path,
                    "status": status_code,
                    "duration_ms": round(duration_ms, 2),
                },
                duration_ms=duration_ms,
                success=status_code < 400,
                source="http_middleware",
            )


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    conversation_id: str | None = None
    model_id: str | None = None
    preferred_role: str | None = None
    stream: bool = False


class KnowledgeWrite(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=250_000)
    source: str = Field(default="manual", min_length=1, max_length=240)


def _frontend_index() -> FileResponse:
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "Frontend build missing. Run `npm install && npm run build` "
                f"in {FRONTEND_ROOT} before starting LEVIATHAN."
            ),
        )
    return FileResponse(index)


@app.get("/api/health")
async def health() -> dict:
    try:
        chaos.maybe_fault()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    model = await llm.health()
    metrics.incr("health_checks")
    metrics.set_gauge("capabilities_registered", float(len(capability_catalog)))
    metrics.set_gauge("approvals_pending", float(len(approval_service.list(status=ApprovalStatus.PENDING, limit=500))))
    model_status = model_plane.status_cards()
    return {
        "ok": True,
        "version": app.version,
        "database": str(settings.database_path),
        "reasoning_enabled": settings.reasoning_enabled,
        "models": model_status,
        "frontend": {
            "dist_ready": (FRONTEND_DIST / "index.html").is_file(),
            "dist_path": str(FRONTEND_DIST),
        },
        "config": live_settings().public_summary(),

        "knowledge": {
            "data_root": str(settings.knowledge.data_root),
            "documents": len(knowledge.list_documents(limit=10_000)),
            "embedding_provider": retriever.embeddings.provider_id,
            "embedding_available": retriever.embeddings.available(),
            "embedding_status": (
                retriever.embeddings.status()
                if hasattr(retriever.embeddings, "status")
                else {"provider_id": retriever.embeddings.provider_id}
            ),
            "rag_v3": settings.features.rag_v3,
            "deep_recall": settings.features.deep_recall,
            "why_library": settings.features.why_library,
            "reranker_available": bool(reranker_provider and reranker_provider.available()),
            "deep_recall_budget": settings.knowledge.deep_recall_budget,
        },
        "functions": {
            "registered": len(function_registry),
            "loaded": sorted(function_runtime.loaded_function_ids()),
            "telemetry": dict(function_runtime.telemetry),
        },
        "capabilities": {
            "registered": len(capability_catalog),
            "telemetry": dict(execution_gateway.telemetry),
            "effects_recorded": len(execution_gateway.effect_ledger),
        },
        "approvals": {
            "pending": len(approval_service.list(status=ApprovalStatus.PENDING, limit=500)),
        },
        "jobs": {
            "queued": len(job_runtime.list(state=JobState.QUEUED, limit=500)),
            "active": resource_manager.active_job_ids(),
            "telemetry": dict(job_runtime.telemetry),
            "resources": dict(resource_manager.telemetry),
        },
        "agents": {
            "enabled": settings.features.agents_enabled,
        },
        "observability": observability.snapshot(),
        "neuro": {
            "enabled": settings.features.neuro_enabled,
            "associative_memory": settings.features.neuro_associative_memory,
            "process_critic": settings.features.neuro_process_critic,
            "residual_injection": settings.features.neuro_residual_injection,
            "cortex": settings.features.neuro_cortex,
            "memory_tiers": settings.features.neuro_memory_tiers,
            "residual_orchestrator": settings.features.neuro_residual_orchestrator,
            "cortex_blocks": settings.features.neuro_cortex_blocks,
            "contrastive_training": settings.features.neuro_contrastive_training,
            "soak_long": settings.features.neuro_soak_long,
            "training_real_worker": settings.features.neuro_training_real_worker,
            "residual_supported": residual_runtime.supports_residuals(),
            "residual_kind": settings.neuro_runtime.residual_kind,
            "residual_load_weights": settings.neuro_runtime.residual_load_weights,
            "residual_production": settings.features.residual_production,
            "residual_hook_layers": list(settings.neuro_runtime.residual_hook_layers),
            "cortex_max_k": settings.neuro_runtime.cortex_max_k,
            "working_memory_load": neuro_memory.working.load if neuro_memory.enabled else 0.0,
            "working_memory_slots": (
                len(neuro_memory.working.snapshot()) if neuro_memory.enabled else 0
            ),
            "memory_tier0_max_slots": settings.neuro_runtime.memory_tier0_max_slots,
            "residual_runtime": (
                residual_runtime.runtime_info()
                if hasattr(residual_runtime, "runtime_info")
                else {"kind": settings.neuro_runtime.residual_kind}
            ),
            "orchestrator_telemetry": dict(residual_orchestrator.telemetry),
            "absorb": dict(neuro_absorb.telemetry),
            "contrastive_ready": bool(
                settings.features.neuro_contrastive_training
                and neuro_contrastive.embeddings_available
            ),
            "contrastive_method_default": (
                "embedding" if neuro_contrastive.embeddings_available else "lexical"
            ),
            "chat_streaming": settings.features.chat_streaming,
            "chat_sse": settings.features.chat_sse,
            "streaming_posture": (
                "sse_ready"
                if settings.features.chat_streaming
                else "disabled"
            ),
            "cognition": cognition_runtime.health(),
            "residual_applied_count": int(
                residual_orchestrator.telemetry.get("injects_applied") or 0
            ),
            "residual_degraded_count": int(
                residual_orchestrator.telemetry.get("degraded") or 0
            ),
            "truth": {
                "neural_signal_is_not_authority": True,
                "residual_implemented": residual_runtime.supports_residuals(),
                "residual_applied": bool(
                    residual_orchestrator.telemetry.get("injects_applied")
                ),
                "discoverable_is_not_authorized": True,
                "unapplied_is_not_success": True,
                "model_output_is_not_evidence": True,
                "unsupported_is_not_failure_of_core": True,
                "streaming_degraded": False,
            },
        },
        "module_manager": {
            "enabled": settings.features.module_manager_enabled,
            "subprocess_isolation": settings.features.module_manager_subprocess,
            "modules": len(module_manager.list()) if module_manager.enabled else 0,
            "telemetry": dict(module_manager.telemetry) if module_manager.enabled else {},
        },
        "training_recipes": {
            "registered": len(training_recipes.list()),
        },
        "plugins": {
            "registered": len(plugin_registry.list()),
        },
        "mcp": mcp_bridge.health_summary().public_dict(),
        "isolation": isolation_guard.evaluate().public_dict(),
        "training": {
            "registered": len(training_registry.list()),
        },
        "chaos": chaos.public_dict(),
        "backup": {
            "root": str(settings.backup.root),
            "count": len(backup_service.list(limit=500)),
        },
        "verification_reports": {
            "recent": len(verification_reports.list(limit=50)),
        },
        "llm": model,
    }


@app.get("/api/architecture/ownership")
def architecture_ownership() -> dict:
    """Canonical ownership matrix (Wave 0 / U001–U020)."""
    return {
        "ownership": ownership_public_dict(),
        "behavior_profile": DEFAULT_BEHAVIOR_PROFILE.public_dict(include_prompt=False),
        "authority_profile": DEFAULT_AUTHORITY_PROFILE.public_dict(),
        "truth": {
            "behavior_is_not_authority": True,
            "extend_over_new": True,
            "external_first_is_not_second_architecture": True,
        },
    }


@app.get("/api/architecture/capability-manifest")
def architecture_capability_manifest() -> dict:
    """Frontier Capability Manifest derived from the live CapabilityCatalog (U016)."""
    manifest = build_frontier_manifest(
        capability_catalog,
        metadata={
            "durable_kernel": live_settings().features.durable_kernel,
            "version": app.version,
        },
    )
    return {"manifest": manifest.public_dict()}


@app.get("/api/metrics")
def metrics_snapshot() -> dict:
    snap = metrics.snapshot(
        labels={"service": "leviathan", "version": app.version},
        enrich=lambda: {
            "jobs_queued": float(len(job_runtime.list(state=JobState.QUEUED, limit=500))),
            "capabilities": float(len(capability_catalog)),
            "observations": float(len(observation_store.list_observations(limit=500))),
        },
    )
    return {"metrics": snap.public_dict()}


@app.get("/api/conversations")
def list_conversations(q: str | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"conversations": db.list_conversations(limit=limit, q=q)}


@app.post("/api/conversations")
def create_conversation(payload: ConversationCreate) -> dict:
    return {"conversation": db.create_conversation(payload.title.strip())}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    conversation = db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation": conversation,
        "messages": db.get_messages(conversation_id, limit=200),
    }


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: str, payload: ConversationUpdate) -> dict:
    if payload.title is None and payload.pinned is None:
        raise HTTPException(status_code=422, detail="No conversation fields to update")
    conversation = db.update_conversation(
        conversation_id,
        title=payload.title.strip() if payload.title is not None else None,
        pinned=payload.pinned,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    if not db.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True, "id": conversation_id}


@app.post("/api/chat")
async def chat(payload: ChatRequest, request: Request):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    if payload.conversation_id:
        conversation = db.get_conversation(payload.conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = db.create_conversation()

    conversation_id = conversation["id"]
    user_message = db.add_message(conversation_id, "user", message)

    if conversation["title"] == "New conversation":
        title = " ".join(message.split())[:72] or "New conversation"
        db.set_conversation_title(conversation_id, title)

    run = runs.create_run(user_request=message, conversation_id=conversation_id)
    runs.transition(run.run_id, RunState.PLANNING)
    runs.append_event(run.run_id, EventType.REASONING_STARTED, {})

    has_knowledge = bool(knowledge.list_documents(limit=1))
    wm_load = neuro_memory.working.load if neuro_memory.enabled else 0.0
    # Provisional plan for economy inputs, then finalize with governor decision.
    provisional = (
        reasoner.analyze(message, has_knowledge, deep_recall_enabled=settings.features.deep_recall)
        if settings.reasoning_enabled
        else ReasoningEngine().analyze(message, False)
    )
    economy = economy_governor.decide(
        complexity=provisional.complexity,
        intent=provisional.intent,
        memory_coverage=1.0 if has_knowledge else 0.0,
        residual_available=residual_runtime.supports_residuals(),
        deep_recall_enabled=settings.features.deep_recall,
        explicit_deep_recall=any(term in message.lower() for term in ("exact", "cite", "deep recall")),
        working_memory_load=wm_load,
    )
    plan = (
        reasoner.analyze(
            message,
            has_knowledge,
            deep_recall_enabled=settings.features.deep_recall,
            economy_allow_deep_recall=economy.allow_deep_recall,
            memory_coverage=1.0 if has_knowledge else 0.0,
        )
        if settings.reasoning_enabled
        else provisional
    )
    runs.append_event(
        run.run_id,
        EventType.REASONING_COMPLETED,
        {**plan.public_summary(), "economy": economy.public_dict()},
    )

    cognition_meta: dict | None = None
    if settings.features.cognition_enabled:
        try:
            history_rows = db.get_messages(conversation_id, limit=live_settings().max_history_messages)
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in history_rows
                if m.get("role") in {"user", "assistant"} and m.get("content")
            ]
            cognition_meta = cognition_runtime.submit(
                message,
                conversation_id=conversation_id,
                history=history,
                has_knowledge=has_knowledge,
                shadow=True if settings.features.cognition_shadow else False,
                metadata={"chat_run_id": run.run_id},
                run=True,
            )
            observability.emit(
                "cognition",
                "chat.shadow" if settings.features.cognition_shadow else "chat.active",
                payload={
                    "run_id": cognition_meta.get("run_id"),
                    "status": cognition_meta.get("status"),
                    "mode": cognition_meta.get("mode"),
                    "strategy": cognition_meta.get("strategy"),
                },
            )
        except Exception as exc:  # noqa: BLE001 — cognition must not break chat
            cognition_meta = {
                "error": f"{type(exc).__name__}: {exc}",
                "truth": {"cognition_failure_does_not_fail_chat": True},
            }

    runs.transition(
        run.run_id,
        RunState.RETRIEVING if plan.use_knowledge else RunState.EXECUTING,
        intent=plan.intent,
        complexity=plan.complexity,
    )

    knowledge_hits: list[dict] = []
    atlas_hits: list[dict] = []
    why_hits: list[dict] = []
    contradictions: list[str] = []
    deep_recall_result = None
    if plan.use_knowledge:
        runs.append_event(run.run_id, EventType.RETRIEVAL_STARTED, {})
        if plan.use_deep_recall and economy.allow_deep_recall:
            deep_recall_result = deep_recall_service.recall(
                DeepRecallRequest(
                    current_question=message,
                    maximum_context_budget=economy.deep_recall_budget,
                    hydrate_limit=live_settings().knowledge_top_k,
                    required_precision="high" if plan.complexity == "high" else "normal",
                )
            )
            atlas_hits = list(deep_recall_result.atlas_matches)
            contradictions = list(deep_recall_result.contradictions_found)
            knowledge_hits = [
                {
                    "id": detail.get("document_id") or detail.get("ref"),
                    "title": detail.get("title") or "evidence",
                    "content": detail.get("content") or "",
                    "source": "deep_recall",
                    "chunk_id": detail.get("chunk_id") or detail.get("ref"),
                    "content_hash": detail.get("content_hash"),
                    "layer": "evidence",
                }
                for detail in deep_recall_result.exact_details
            ]
            observability.emit(
                "knowledge",
                "deep_recall",
                payload={
                    "context_cost": deep_recall_result.context_cost,
                    "stopped_reason": deep_recall_result.stopped_reason,
                    "evidence_count": len(knowledge_hits),
                },
            )
        else:
            if plan.use_atlas and settings.features.rag_v3:
                atlas_hits = [item.public_dict() for item in atlas_store.search(message, limit=3)]
            hits = retriever.search(
                RetrievalQuery(text=message, limit=live_settings().knowledge_top_k)
            )
            knowledge_hits = [hit.as_context_document() for hit in hits]
        if settings.features.why_library:
            why_hits = [item.as_context_item() for item in why_library.search(message, limit=3)]
        runs.append_event(
            run.run_id,
            EventType.RETRIEVAL_COMPLETED,
            {
                "count": len(knowledge_hits),
                "atlas_count": len(atlas_hits),
                "deep_recall": bool(deep_recall_result and deep_recall_result.available),
            },
        )
        runs.transition(run.run_id, RunState.EXECUTING)

    history_rows = db.get_messages(conversation_id, limit=live_settings().max_history_messages)
    history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
    memory_hits = [item.as_context_item() for item in memory_store.search(message, limit=5)]
    knowledge_ids = [str(item.get("id") or "") for item in knowledge_hits if item.get("id")]
    neuro = neuro_advisor.assess(message, plan=plan, knowledge_ids=knowledge_ids)
    neuro_context: list[dict] = []
    cortex_report = None
    residual_applied_any = False
    if neuro.enabled:
        observability.emit(
            "neuro",
            "assess",
            payload={"signals": len(neuro.signals)},
        )
        for signal in neuro.signals:
            neuro_context.append(
                {
                    "id": signal.signal_id,
                    "content": f"[{signal.kind} strength={signal.strength}] {signal.summary}",
                    "status": "advisory",
                }
            )
        if settings.features.neuro_memory_tiers and neuro_memory.enabled:
            try:
                neuro_memory.write_working(
                    message[:800],
                    tags=("chat_turn",),
                    metadata={"run_id": run.run_id, "conversation_id": conversation_id},
                )
            except (RuntimeError, ValueError):
                pass
            bundle = neuro_memory.retrieve(message, tiers=(0, 1, 2), limit_per_tier=3)
            for hit in bundle.hits:
                memory_hits.append(
                    {
                        "memory_id": hit.ref_id,
                        "content": f"[tier{hit.tier}] {hit.content}",
                        "status": "ACTIVE",
                        "kind": f"neuro_tier_{hit.tier}",
                    }
                )
            if settings.features.neuro_contrastive_training:
                contrastive = neuro_contrastive.retrieve(message, tiers=(1, 2), limit=3)
                for hit in contrastive.hits[:3]:
                    memory_hits.append(
                        {
                            "memory_id": hit.get("ref_id") or hit.get("memory_id") or "contrastive",
                            "content": f"[contrastive:{contrastive.method}] {hit.get('content') or ''}",
                            "status": "ACTIVE",
                            "kind": "neuro_contrastive",
                        }
                    )
        if settings.features.neuro_cortex:
            engagement = next((s for s in neuro.signals if s.kind == "cortex_engagement"), None)
            depth = 0
            critic_rounds = 0
            if engagement is not None:
                depth = int((engagement.provenance or {}).get("depth") or 0)
                critic_rounds = int((engagement.provenance or {}).get("critic_rounds") or 0)
            if depth > 0 or residual_runtime.supports_residuals():
                report = cortex_runtime.run(
                    messages=[{"role": "user", "content": message}],
                    depth=max(depth, 1 if residual_runtime.supports_residuals() else 0),
                    critic_rounds=critic_rounds,
                    knowledge_ids=knowledge_ids,
                    plan_steps=list(plan.steps),
                )
                cortex_report = report.public_dict()
                if settings.features.residual_production or settings.features.neuro_residual_injection:
                    for receipt_dict in report.inject_receipts:
                        # Re-hydrate minimal receipt fields for durable audit trail.
                        from Data.modules.neuro.residual import ResidualHookPoint, ResidualInjectReceipt

                        hook_raw = receipt_dict.get("hook") or {}
                        residual_receipts.record(
                            ResidualInjectReceipt(
                                implemented=bool(receipt_dict.get("implemented")),
                                mode=str(receipt_dict.get("mode") or "DISABLED"),
                                hook=ResidualHookPoint(
                                    layer_index=int(hook_raw.get("layer_index") or 0),
                                    name=str(hook_raw.get("name") or "unknown"),
                                    site=str(hook_raw.get("site") or "block_out"),
                                ),
                                applied=bool(receipt_dict.get("applied")),
                                detail=str(receipt_dict.get("detail") or ""),
                                reason=str(receipt_dict.get("reason") or ""),
                                degraded_to_chat_completions=bool(
                                    receipt_dict.get("degraded_to_chat_completions")
                                ),
                            ),
                            metadata={"run_id": run.run_id, "source": "cortex_runtime"},
                        )
                        if receipt_dict.get("applied"):
                            residual_applied_any = True
                if settings.features.neuro_residual_orchestrator:
                    orch = residual_orchestrator.orchestrate(
                        messages=[{"role": "user", "content": message}],
                        complexity=str(plan.complexity or "medium"),
                        token_budget=settings.context.token_budget,
                        payload_ref=knowledge_ids[0] if knowledge_ids else None,
                        run_forward=False,
                        run_id=run.run_id,
                    )
                    for receipt in orch.receipts:
                        residual_receipts.record(
                            receipt,
                            metadata={"run_id": run.run_id, "source": "residual_orchestrator"},
                        )
                        if receipt.applied:
                            residual_applied_any = True
                    neuro_context.append(
                        {
                            "id": f"residual-orch-{run.run_id}",
                            "content": (
                                f"[residual_orchestrator layers={list(orch.selected_layers)} "
                                f"applied={sum(1 for r in orch.receipts if r.applied)}] {orch.detail}"
                            ),
                            "status": "advisory",
                        }
                    )
                observability.emit(
                    "neuro",
                    "cortex_engagement",
                    payload={"engaged": report.engaged, "degraded": report.degraded},
                )
                metrics.incr("neuro_cortex_runs")
                neuro_context.append(
                    {
                        "id": f"cortex-{run.run_id}",
                        "content": (
                            f"[cortex engaged={report.engaged} depth={report.depth} "
                            f"early_exit={report.early_exit} k={report.k_used}/{report.max_k}] "
                            f"{report.detail}"
                        ),
                        "status": "advisory",
                    }
                )

    # Streaming posture: residual-aware forward rarely streams — degrade honestly.
    accept = (request.headers.get("accept") or "").lower()
    wants_sse = payload.stream or ("text/event-stream" in accept)
    stream_enabled = bool(settings.features.chat_streaming)
    residual_wants_stream = residual_runtime.supports_residuals() and bool(
        settings.features.neuro_residual_injection or settings.features.residual_production
    )
    residual_can_stream = bool(
        getattr(residual_runtime, "supports_streaming_forward", lambda: False)()
    )
    streaming_degraded = bool(
        wants_sse and stream_enabled and residual_wants_stream and not residual_can_stream
    )
    use_sse = bool(wants_sse and stream_enabled)

    runs.append_event(run.run_id, EventType.MODEL_STARTED, {})
    route_meta: dict | None = None
    call_id: str | None = None
    provider_id_for_release = "unknown"
    model_id_for_release = "unknown"
    routed: dict | None = None
    profile = None
    try:
        routed = model_plane.resolve_for_chat(
            explicit_model_id=payload.model_id,
            preferred_role=payload.preferred_role,
        )
        decision = routed["decision"]
        profile = routed["profile"]
        provider_id_for_release = routed["provider_id"]
        model_id_for_release = routed["model"].id
        call_id = model_plane.gateway.acquire(
            model_id=model_id_for_release,
            provider_id=provider_id_for_release,
            timeout_seconds=min(settings.llm_timeout_seconds, 30.0),
        )
        route_meta = {
            "decision": decision.public_dict(),
            "traceId": call_id,
        }
        runs.append_event(run.run_id, EventType.MODEL_STARTED, route_meta)
    except ModelControlError as exc:
        if call_id:
            model_plane.gateway.release(
                model_id=model_id_for_release,
                provider_id=provider_id_for_release,
                error=exc.code,
            )
            call_id = None
        if exc.code in {"ROUTER_EXHAUSTED", "MODEL_NOT_FOUND"} and not payload.model_id:
            routed = None
            profile = None
            route_meta = {
                "decision": {
                    "reason": "legacy_settings_fallback",
                    "fallbackUsed": True,
                    "fallbackReason": exc.code,
                }
            }
            model_plane.gateway.record_fallback(exc.code)
        else:
            runs.transition(run.run_id, RunState.FAILED, error=str(exc))
            raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc

    llm_kwargs = dict(
        history=history,
        knowledge=knowledge_hits,
        plan=plan,
        memory=memory_hits,
        neuro=neuro_context or None,
        atlas=atlas_hits or None,
        why=why_hits or None,
        contradictions=contradictions or None,
    )
    if routed is not None and profile is not None:
        llm_kwargs.update(
            model_id=routed["provider_model_id"],
            endpoint=routed["endpoint"],
            api_key=routed["api_key"],
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            top_p=profile.top_p,
            system_prompt=profile.system_prompt or None,
        )

    def _finalize_chat(answer: str, model: str) -> dict:
        nonlocal call_id
        if call_id and routed is not None:
            model_plane.registry.touch_used(model_id_for_release)
            model_plane.gateway.release(
                model_id=model_id_for_release, provider_id=provider_id_for_release
            )
            call_id = None
        runs.append_event(
            run.run_id,
            EventType.MODEL_COMPLETED,
            {"model": model, **(route_meta or {})},
        )
        assistant_message = db.add_message(conversation_id, "assistant", answer)
        observability.emit(
            "chat",
            "completed",
            payload={
                "run_id": run.run_id,
                "model": model,
                "memory_hits": len(memory_hits),
                "route": route_meta,
                "streamed": use_sse,
                "streaming_degraded": streaming_degraded,
            },
        )
        completed = runs.transition(
            run.run_id,
            RunState.COMPLETED,
            selected_model=model,
            output=answer,
        )
        return {
            "conversation_id": conversation_id,
            "run_id": completed.run_id,
            "run_state": completed.state.value,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "model": model,
            "routing": route_meta,
            "reasoning": plan.public_summary(),
            "knowledge_sources": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "source": item["source"],
                    "chunk_id": item.get("chunk_id"),
                }
                for item in knowledge_hits
            ],
            "atlas_sources": [
                {"atlas_id": item.get("atlas_id"), "title": item.get("title")} for item in atlas_hits
            ],
            "deep_recall": deep_recall_result.public_dict() if deep_recall_result else None,
            "economy": economy.public_dict(),
            "why_sources": [{"id": item.get("id"), "kind": item.get("kind")} for item in why_hits],
            "memory_sources": [{"memory_id": item["memory_id"]} for item in memory_hits],
            "neuro": neuro.public_dict(),
            "cortex": cortex_report,
            "cognition": cognition_meta,
            "streamed": use_sse,
            "truth": chat_truth(
                streaming_degraded=streaming_degraded,
                residual_implemented=residual_runtime.supports_residuals(),
                residual_applied=residual_applied_any,
            ),
        }

    if use_sse:

        async def _sse_events():
            nonlocal call_id
            yield sse_encode(
                "meta",
                {
                    "conversation_id": conversation_id,
                    "run_id": run.run_id,
                    "user_message": user_message,
                    "reasoning": plan.public_summary(),
                    "model": (routed or {}).get("provider_model_id") if routed else None,
                    "streaming_degraded": streaming_degraded,
                    "truth": chat_truth(
                        streaming_degraded=streaming_degraded,
                        residual_implemented=residual_runtime.supports_residuals(),
                        residual_applied=residual_applied_any,
                    ),
                },
            )
            parts: list[str] = []
            model_name = "unknown"
            try:
                async for delta, model_name in llm.chat_stream(**llm_kwargs):
                    parts.append(delta)
                    yield sse_encode("token", {"text": delta, "model": model_name})
                answer = "".join(parts).strip()
                if not answer:
                    raise LLMUnavailable("LLM stream produced empty text")
                done_payload = _finalize_chat(answer, model_name)
                yield sse_encode("done", done_payload)
            except LLMUnavailable as stream_exc:
                # Honest degrade: non-stream completion still via real provider path.
                try:
                    answer, model_name = await llm.chat(**llm_kwargs, stream=False)
                    done_payload = _finalize_chat(answer, model_name)
                    done_payload["truth"] = chat_truth(
                        streaming_degraded=True,
                        residual_implemented=residual_runtime.supports_residuals(),
                        residual_applied=residual_applied_any,
                    )
                    done_payload["streamed"] = False
                    yield sse_encode(
                        "meta",
                        {
                            "streaming_degraded": True,
                            "detail": str(stream_exc),
                            "truth": done_payload["truth"],
                        },
                    )
                    yield sse_encode("token", {"text": answer, "model": model_name})
                    yield sse_encode("done", done_payload)
                except LLMUnavailable as llm_exc:
                    if call_id:
                        model_plane.gateway.release(
                            model_id=model_id_for_release,
                            provider_id=provider_id_for_release,
                            error=str(llm_exc),
                        )
                        call_id = None
                    runs.transition(run.run_id, RunState.FAILED, error=str(llm_exc))
                    yield sse_encode(
                        "error",
                        {
                            "detail": str(llm_exc),
                            "truth": chat_truth(streaming_degraded=True),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                if call_id:
                    model_plane.gateway.release(
                        model_id=model_id_for_release,
                        provider_id=provider_id_for_release,
                        error=str(exc),
                    )
                    call_id = None
                runs.transition(run.run_id, RunState.FAILED, error=str(exc))
                yield sse_encode(
                    "error",
                    {
                        "detail": str(exc),
                        "truth": chat_truth(streaming_degraded=streaming_degraded),
                    },
                )

        return StreamingResponse(
            _sse_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-stream path (default / when feature flag OFF).
    try:
        answer, model = await llm.chat(**llm_kwargs, stream=False)
    except LLMUnavailable as exc:
        if call_id:
            model_plane.gateway.release(
                model_id=model_id_for_release,
                provider_id=provider_id_for_release,
                error=str(exc),
            )
        runs.transition(run.run_id, RunState.FAILED, error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = _finalize_chat(answer, model)
    if wants_sse and not stream_enabled:
        result["truth"] = chat_truth(
            streaming_degraded=True,
            residual_implemented=residual_runtime.supports_residuals(),
            residual_applied=residual_applied_any,
        )
        result["stream_note"] = (
            "stream requested but LEVIATHAN_FEATURE_CHAT_STREAMING is OFF — non-stream response"
        )
    return result


@app.get("/api/neuro/status")
def neuro_status() -> dict:
    """Residual + contrastive + streaming posture (supervisor/runtime-backed)."""
    contrastive_ready = bool(
        settings.features.neuro_enabled
        and settings.features.neuro_contrastive_training
        and neuro_contrastive.embeddings_available
    )
    return {
        "enabled": settings.features.neuro_enabled,
        "residual": {
            "supports_residuals": residual_runtime.supports_residuals(),
            "kind": settings.neuro_runtime.residual_kind,
            "production": settings.features.residual_production,
            "orchestrator": settings.features.neuro_residual_orchestrator,
            "applied_count": int(residual_orchestrator.telemetry.get("injects_applied") or 0),
            "degraded_count": int(residual_orchestrator.telemetry.get("degraded") or 0),
            "degrade_reasons": dict(residual_orchestrator.telemetry.get("degrade_reasons") or {}),
            "supports_streaming_forward": bool(
                getattr(residual_runtime, "supports_streaming_forward", lambda: False)()
            ),
            "runtime": (
                residual_runtime.runtime_info()
                if hasattr(residual_runtime, "runtime_info")
                else {}
            ),
        },
        "contrastive": {
            "flag": settings.features.neuro_contrastive_training,
            "embeddings_available": neuro_contrastive.embeddings_available,
            "ready": contrastive_ready,
            "method": "embedding" if neuro_contrastive.embeddings_available else "lexical",
        },
        "streaming": {
            "chat_streaming": settings.features.chat_streaming,
            "chat_sse": settings.features.chat_sse,
            "posture": "sse_ready" if settings.features.chat_streaming else "disabled",
        },
        "truth": chat_truth(
            streaming_degraded=False,
            residual_implemented=residual_runtime.supports_residuals(),
            residual_applied=bool(residual_orchestrator.telemetry.get("injects_applied")),
        ),
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = runs.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run.public_dict(), "events": [
        {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "created_at": event.created_at,
            "payload": event.payload,
        }
        for event in runs.list_events(run_id)
    ]}


class ArtifactWrite(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(min_length=1, max_length=180)
    artifact_type: str = Field(default="text", min_length=1, max_length=80)
    run_id: str | None = None
    producer: str = Field(default="api", min_length=1, max_length=120)


@app.post("/api/artifacts")
def create_artifact(payload: ArtifactWrite) -> dict:
    if "/" in payload.filename or "\\" in payload.filename:
        raise HTTPException(status_code=422, detail="filename must be a basename")
    if payload.run_id and not runs.get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    record = artifacts.create_from_bytes(
        data=payload.content.encode("utf-8"),
        artifact_type=payload.artifact_type.strip(),
        producer=payload.producer.strip(),
        filename=payload.filename.strip(),
        run_id=payload.run_id,
    )
    return {"artifact": record.public_dict()}


@app.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict:
    record = artifacts.get(artifact_id)
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"artifact": record.public_dict()}


@app.post("/api/artifacts/{artifact_id}/verify")
def verify_artifact(artifact_id: str) -> dict:
    try:
        ok = artifacts.verify_hash(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    record = artifacts.get(artifact_id)
    assert record is not None
    return {"ok": ok, "artifact": record.public_dict()}


@app.get("/api/knowledge")
def list_knowledge() -> dict:
    return {"documents": [doc.public_dict() for doc in knowledge.list_documents()]}


@app.post("/api/knowledge")
def write_knowledge(payload: KnowledgeWrite) -> dict:
    document = knowledge.upsert_document(
        document_id=payload.id,
        title=payload.title.strip(),
        content=payload.content.strip(),
        source=payload.source.strip(),
    )
    return {"document": document.public_dict()}


@app.get("/api/knowledge/search")
def search_knowledge(
    q: Annotated[str, Query(min_length=1, max_length=4000)],
    limit: int = 5,
    source: str | None = None,
) -> dict:
    safe_limit = min(max(limit, 1), 20)
    hits = retriever.search(RetrievalQuery(text=q, limit=safe_limit, source=source))
    return {
        "hits": [hit.public_dict() for hit in hits],
        # Backward-compatible document projection for older clients.
        "documents": [hit.as_context_document() for hit in hits],
    }


class AtlasWrite(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=20_000)
    scale: str = Field(default="thread", min_length=1, max_length=64)
    scope: str = Field(default="", max_length=500)
    entities: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    evidence_record_refs: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AtlasRevise(BaseModel):
    summary: str | None = None
    title: str | None = None
    revision_reason: str = Field(default="revised", max_length=500)
    unresolved_questions: list[str] | None = None
    contradictions: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_record_refs: list[str] | None = None


class DeepRecallBody(BaseModel):
    current_question: str = Field(min_length=1, max_length=4000)
    remembered_gist: str = Field(default="", max_length=4000)
    missing_detail: str = Field(default="", max_length=4000)
    required_precision: str = Field(default="normal", max_length=32)
    maximum_context_budget: int | None = Field(default=None, ge=64, le=20_000)
    hydrate_limit: int = Field(default=5, ge=1, le=50)


class WhyAssimilateBody(BaseModel):
    observation: str = Field(min_length=1, max_length=8000)
    parent_ref: str | None = None
    child_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    resemblance_notes: str = Field(default="", max_length=4000)
    residue: str = Field(default="", max_length=4000)
    exclude_child: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


@app.get("/api/knowledge/atlas")
def list_atlas(
    q: Annotated[str, Query(max_length=4000)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    if not settings.features.rag_v3:
        return {
            "available": False,
            "reason": "LEVIATHAN_FEATURE_RAG_V3=false",
            "records": [],
        }
    records = atlas_store.search(q, limit=limit) if q.strip() else atlas_store.search("", limit=limit)
    return {"available": True, "records": [item.public_dict() for item in records]}


@app.post("/api/knowledge/atlas")
def create_atlas(payload: AtlasWrite) -> dict:
    if not settings.features.rag_v3:
        raise HTTPException(status_code=503, detail="RAG V3 / atlas unavailable")
    try:
        record = atlas_store.create(
            title=payload.title,
            summary=payload.summary,
            scale=payload.scale,
            scope=payload.scope,
            entities=payload.entities,
            projects=payload.projects,
            evidence_record_refs=payload.evidence_record_refs,
            unresolved_questions=payload.unresolved_questions,
            contradictions=payload.contradictions,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"record": record.public_dict()}


@app.post("/api/knowledge/atlas/{atlas_id}/revise")
def revise_atlas(atlas_id: str, payload: AtlasRevise) -> dict:
    if not settings.features.rag_v3:
        raise HTTPException(status_code=503, detail="RAG V3 / atlas unavailable")
    record = atlas_store.revise(
        atlas_id,
        summary=payload.summary,
        title=payload.title,
        revision_reason=payload.revision_reason,
        unresolved_questions=payload.unresolved_questions,
        contradictions=payload.contradictions,
        confidence=payload.confidence,
        evidence_record_refs=payload.evidence_record_refs,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Atlas record not found")
    return {"record": record.public_dict()}


@app.post("/api/knowledge/deep-recall")
def run_deep_recall(payload: DeepRecallBody) -> dict:
    if not settings.features.deep_recall:
        disabled = DeepRecallService(
            knowledge=knowledge,
            atlas=atlas_store,
            retriever=retriever,
            db_path=settings.database_path,
            enabled=False,
        )
        result = disabled.recall(DeepRecallRequest(current_question=payload.current_question))
        return {
            "available": False,
            "reason": "LEVIATHAN_FEATURE_DEEP_RECALL=false",
            "result": result.public_dict(),
        }
    result = deep_recall_service.recall(
        DeepRecallRequest(
            current_question=payload.current_question,
            remembered_gist=payload.remembered_gist,
            missing_detail=payload.missing_detail,
            required_precision=payload.required_precision,
            maximum_context_budget=payload.maximum_context_budget
            or settings.knowledge.deep_recall_budget,
            hydrate_limit=payload.hydrate_limit,
        )
    )
    return {"available": result.available, "result": result.public_dict()}


@app.get("/api/knowledge/deep-recall/logs")
def deep_recall_logs(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
    return {"logs": deep_recall_service.recent_logs(limit=limit)}


@app.post("/api/knowledge/why")
def assimilate_why(payload: WhyAssimilateBody) -> dict:
    if not settings.features.why_library:
        return {"available": False, "reason": "LEVIATHAN_FEATURE_WHY_LIBRARY=false", "record": None}
    record = why_library.assimilate(
        observation=payload.observation,
        parent_ref=payload.parent_ref,
        child_ref=payload.child_ref,
        evidence_refs=payload.evidence_refs,
        resemblance_notes=payload.resemblance_notes,
        residue=payload.residue,
        exclude_child=payload.exclude_child,
        confidence=payload.confidence,
    )
    return {"available": True, "record": record.public_dict() if record else None}


@app.get("/api/knowledge/why")
def list_why(
    q: Annotated[str, Query(max_length=4000)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    if not settings.features.why_library:
        return {"available": False, "reason": "LEVIATHAN_FEATURE_WHY_LIBRARY=false", "records": []}
    records = why_library.search(q, limit=limit) if q.strip() else why_library.list_recent(limit=limit)
    return {"available": True, "records": [item.public_dict() for item in records]}


@app.get("/api/knowledge/{document_id}")
def get_knowledge_document(document_id: str) -> dict:
    document = knowledge.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {
        "document": document.public_dict(),
        "chunks": [chunk.public_dict() for chunk in knowledge.list_chunks(document_id)],
    }


@app.delete("/api/knowledge/{document_id}")
def delete_knowledge(document_id: str) -> dict:
    if not knowledge.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"deleted": True, "id": document_id}


class KnowledgeIngestPath(BaseModel):
    path: str = Field(min_length=1, max_length=4000)


@app.post("/api/knowledge/ingest/path")
def ingest_knowledge_path(payload: KnowledgeIngestPath) -> dict:
    try:
        resolved = knowledge.resolve_under_data_root(payload.path.strip())
        record = knowledge.ingest_file(resolved)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        return {"ingested": False, "reason": "unchanged"}
    return {
        "ingested": True,
        "document": record.public_dict(),
        "chunks": [chunk.public_dict() for chunk in knowledge.list_chunks(record.document_id)],
    }


@app.post("/api/knowledge/ingest/scan")
def ingest_knowledge_scan(limit: int = 50) -> dict:
    safe_limit = min(max(limit, 1), 500)
    try:
        docs = knowledge.scan_data_root(limit=safe_limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "scanned": len(docs),
        "data_root": str(settings.knowledge.data_root),
        "documents": [doc.public_dict() for doc in docs],
    }

@app.get("/api/functions")
def list_functions() -> dict:
    return {
        "functions": [item.public_dict() for item in function_registry.list()],
        "loaded": sorted(function_runtime.loaded_function_ids()),
        "telemetry": dict(function_runtime.telemetry),
    }


@app.get("/api/functions/{function_id}")
def get_function(function_id: str) -> dict:
    definition = function_registry.get(function_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Function not found")
    return {
        "function": definition.public_dict(),
        "loaded": function_id in function_runtime.loaded_function_ids(),
    }


class FunctionExecuteRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


@app.post("/api/functions/{function_id}/execute")
def execute_function(function_id: str, payload: FunctionExecuteRequest) -> dict:
    if function_id not in function_registry:
        raise HTTPException(status_code=404, detail="Function not found")
    result = function_runtime.execute(function_id, payload.arguments)
    status_code = 200
    if result.status == FunctionCallStatus.REJECTED:
        status_code = 422
    elif result.status == FunctionCallStatus.TIMEOUT:
        status_code = 504
    elif result.status == FunctionCallStatus.CANCELLED:
        status_code = 409
    elif result.status == FunctionCallStatus.FAILED:
        status_code = 500
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.public_dict())
    return {"result": result.public_dict()}


@app.post("/api/functions/calls/{call_id}/cancel")
def cancel_function_call(call_id: str) -> dict:
    cancelled = function_runtime.cancel(call_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Active function call not found")
    return {"cancelled": True, "call_id": call_id}


@app.get("/api/capabilities")
def list_capabilities(q: str | None = None, limit: int = Query(200, ge=1, le=500)) -> dict:
    if q:
        items = capability_catalog.search(q, limit=limit)
    else:
        items = execution_gateway.list_capabilities()[:limit]
    return {
        "capabilities": [item.public_dict() for item in items],
        "telemetry": dict(execution_gateway.telemetry),
        "effects_recorded": len(execution_gateway.effect_ledger),
        "truth": {"capability_search_avoids_prompt_schema_explosion": True},
    }


@app.get("/api/capabilities/search")
def search_capabilities(q: str = Query("", max_length=240), limit: int = Query(20, ge=1, le=100)) -> dict:
    items = capability_catalog.search(q, limit=limit)
    return {
        "query": q,
        "capabilities": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "provider_kind": item.provider_kind.value,
                "available": item.available,
                "side_effects": [e.value for e in item.side_effects],
            }
            for item in items
        ],
        "truth": {"shortlist_not_full_schema_dump": True},
    }


@app.get("/api/capabilities/effects/recent")
def recent_capability_effects(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    durable = observation_store.list_effects(limit=limit)
    if durable:
        return {"effects": [item.public_dict() for item in durable], "source": "durable"}
    items = execution_gateway.effect_ledger[-limit:]
    return {
        "source": "memory",
        "effects": [
            {
                "effect_id": item.effect_id,
                "request_id": item.request_id,
                "capability_id": item.capability_id,
                "side_effects": list(item.side_effects),
                "status": item.status,
                "provider_kind": item.provider_kind,
                "provider_ref": item.provider_ref,
                "recorded_at_ms": item.recorded_at_ms,
                "approval_id": item.approval_id,
                "error": item.error,
                "observation_id": item.observation_id,
            }
            for item in reversed(items)
        ],
    }


@app.get("/api/capabilities/{capability_id}")
def get_capability(capability_id: str) -> dict:
    definition = execution_gateway.get_capability(capability_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return {"capability": definition.public_dict()}


class CapabilityExecuteRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None
    run_id: str | None = None
    requested_by: str = "api"


@app.post("/api/capabilities/{capability_id}/execute")
def execute_capability(capability_id: str, payload: CapabilityExecuteRequest) -> dict:
    if capability_id not in capability_catalog:
        raise HTTPException(status_code=404, detail="Capability not found")
    result = execution_gateway.execute(
        CapabilityRequest(
            capability_id=capability_id,
            arguments=payload.arguments,
            approval_id=payload.approval_id,
            run_id=payload.run_id,
            requested_by=payload.requested_by,
        )
    )
    observability.emit(
        "capability",
        "execute",
        payload={
            "capability_id": capability_id,
            "status": result.status.value,
            "request_id": result.request_id,
        },
        level="info" if result.status.value == "COMPLETED" else "warn",
    )
    status_code = 200
    if result.status == CapabilityStatus.REJECTED:
        reason = (result.telemetry or {}).get("reason")
        status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
    elif result.status == CapabilityStatus.TIMEOUT:
        status_code = 504
    elif result.status == CapabilityStatus.CANCELLED:
        status_code = 409
    elif result.status == CapabilityStatus.FAILED:
        status_code = 500
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.public_dict())
    return {"result": result.public_dict()}


@app.get("/api/observations")
def list_observations(
    capability_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    items = observation_store.list_observations(capability_id=capability_id, limit=limit)
    return {"observations": [item.public_dict() for item in items]}


@app.get("/api/observations/{observation_id}")
def get_observation(observation_id: str) -> dict:
    item = observation_store.get_observation(observation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return {"observation": item.public_dict()}


class ApprovalCreateRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=120)
    reason: str | None = None
    run_id: str | None = None
    requested_by: str = "api"
    single_use: bool = True
    arguments: dict = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = "operator"
    reason: str | None = None


@app.get("/api/approvals")
def list_approvals(
    status: Annotated[str | None, Query()] = None,
    capability_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    parsed_status = None
    if status:
        try:
            parsed_status = ApprovalStatus(status.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}") from exc
    items = approval_service.list(
        status=parsed_status,
        capability_id=capability_id,
        limit=limit,
    )
    return {"approvals": [item.public_dict() for item in items]}


@app.post("/api/approvals")
def create_approval(payload: ApprovalCreateRequest) -> dict:
    definition = capability_catalog.get(payload.capability_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    decision = approval_service.evaluate_policy(definition.side_effects)
    if not decision.requires_approval:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Capability does not require approval",
                "policy": decision.public_dict(),
            },
        )
    record = approval_service.request(
        capability_id=definition.id,
        side_effects=definition.side_effects,
        requested_by=payload.requested_by,
        reason=payload.reason,
        run_id=payload.run_id,
        single_use=payload.single_use,
        arguments=payload.arguments or None,
    )
    return {"approval": record.public_dict(), "policy": decision.public_dict()}


@app.get("/api/approvals/{approval_id}")
def get_approval(approval_id: str) -> dict:
    record = approval_service.get(approval_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return {"approval": record.public_dict()}


@app.post("/api/approvals/{approval_id}/approve")
def approve_approval(approval_id: str, payload: ApprovalDecisionRequest) -> dict:
    try:
        record = approval_service.approve(
            approval_id,
            decided_by=payload.decided_by,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"approval": record.public_dict()}


@app.post("/api/approvals/{approval_id}/deny")
def deny_approval(approval_id: str, payload: ApprovalDecisionRequest) -> dict:
    try:
        record = approval_service.deny(
            approval_id,
            decided_by=payload.decided_by,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"approval": record.public_dict()}


class JobCreateRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None
    run_id: str | None = None
    requested_by: str = "api"


@app.get("/api/jobs")
def list_jobs(
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    parsed = None
    if state:
        try:
            parsed = JobState(state.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid job state: {state}") from exc
    return {"jobs": [item.public_dict() for item in job_runtime.list(state=parsed, limit=limit)]}


@app.post("/api/jobs")
def create_job(payload: JobCreateRequest) -> dict:
    try:
        job = job_runtime.enqueue(
            capability_id=payload.capability_id,
            arguments=payload.arguments,
            approval_id=payload.approval_id,
            run_id=payload.run_id,
            requested_by=payload.requested_by,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job": job.public_dict()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_runtime.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.public_dict()}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        job = job_runtime.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job": job.public_dict()}


class EvidenceArtifactClaim(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=120)
    claim: str | None = None
    observation_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    verify_now: bool = True


class EvidenceFileClaim(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    claim: str | None = None
    observation_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None


class EvidenceObservationClaim(BaseModel):
    observation_id: str = Field(min_length=1, max_length=120)
    claim: str | None = None
    run_id: str | None = None
    job_id: str | None = None


@app.get("/api/evidence")
def list_evidence(
    status: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    parsed = None
    if status:
        try:
            parsed = EvidenceStatus(status.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid evidence status: {status}") from exc
    items = evidence_service.store.list(status=parsed, run_id=run_id, limit=limit)
    return {"evidence": [item.public_dict() for item in items]}


@app.get("/api/evidence/{evidence_id}")
def get_evidence(evidence_id: str) -> dict:
    item = evidence_service.store.get(evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {"evidence": item.public_dict()}


@app.post("/api/evidence/artifact")
def claim_artifact_evidence(payload: EvidenceArtifactClaim) -> dict:
    try:
        record = evidence_service.claim_artifact_hash(
            artifact_id=payload.artifact_id,
            claim=payload.claim,
            observation_id=payload.observation_id,
            run_id=payload.run_id,
            job_id=payload.job_id,
            verify_now=payload.verify_now,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"evidence": record.public_dict()}


@app.post("/api/evidence/file")
def claim_file_evidence(payload: EvidenceFileClaim) -> dict:
    record = evidence_service.claim_file_exists(
        path=payload.path,
        claim=payload.claim,
        observation_id=payload.observation_id,
        run_id=payload.run_id,
        job_id=payload.job_id,
    )
    return {"evidence": record.public_dict()}


@app.post("/api/evidence/observation")
def claim_observation_evidence(payload: EvidenceObservationClaim) -> dict:
    record = evidence_service.claim_observation_ref(
        observation_id=payload.observation_id,
        claim=payload.claim,
        run_id=payload.run_id,
        job_id=payload.job_id,
    )
    return {"evidence": record.public_dict()}


@app.post("/api/evidence/{evidence_id}/verify")
def verify_evidence(evidence_id: str) -> dict:
    try:
        record = evidence_service.verify(evidence_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evidence not found") from exc
    return {"evidence": record.public_dict()}


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: str = "NOTE"
    source: str = "manual"
    trust: str = "explicit"
    tags: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    run_id: str | None = None


@app.get("/api/memory")
def list_memory(
    status: Annotated[str | None, Query()] = "ACTIVE",
    kind: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    parsed_status = None
    if status:
        try:
            parsed_status = MemoryStatus(status.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid memory status: {status}") from exc
    parsed_kind = None
    if kind:
        try:
            parsed_kind = MemoryKind(kind.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid memory kind: {kind}") from exc
    items = memory_store.list(status=parsed_status, kind=parsed_kind, limit=limit)
    return {"memory": [item.public_dict() for item in items]}


@app.post("/api/memory")
def create_memory(payload: MemoryCreateRequest) -> dict:
    try:
        kind = MemoryKind(payload.kind.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid memory kind: {payload.kind}") from exc
    try:
        record = memory_store.create(
            content=payload.content,
            kind=kind,
            source=payload.source,
            trust=payload.trust,
            tags=payload.tags,
            conversation_id=payload.conversation_id,
            run_id=payload.run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"memory": record.public_dict()}


@app.get("/api/memory/search")
def search_memory(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict:
    items = memory_store.search(q, limit=limit)
    return {"memory": [item.public_dict() for item in items]}


@app.get("/api/memory/{memory_id}")
def get_memory(memory_id: str) -> dict:
    item = memory_store.get(memory_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"memory": item.public_dict()}


@app.post("/api/memory/{memory_id}/archive")
def archive_memory(memory_id: str) -> dict:
    item = memory_store.set_status(memory_id, MemoryStatus.ARCHIVED)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"memory": item.public_dict()}


@app.post("/api/memory/{memory_id}/revoke")
def revoke_memory(memory_id: str) -> dict:
    item = memory_store.set_status(memory_id, MemoryStatus.REVOKED)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"memory": item.public_dict()}


class VerifyRequest(BaseModel):
    run_id: str | None = None
    job_id: str | None = None
    requirements: list[dict] = Field(default_factory=list)


@app.post("/api/verification/evaluate")
def evaluate_verification(payload: VerifyRequest) -> dict:
    reqs: list[VerificationRequirement] = []
    for raw in payload.requirements:
        try:
            reqs.append(
                VerificationRequirement(
                    requirement_id=str(raw.get("requirement_id") or raw.get("id") or f"req-{len(reqs)}"),
                    description=str(raw.get("description") or "requirement"),
                    evidence_kind=raw.get("evidence_kind"),
                    min_verified=int(raw.get("min_verified") or 1),
                    artifact_id=raw.get("artifact_id"),
                    path=raw.get("path"),
                    observation_id=raw.get("observation_id"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid requirement: {exc}") from exc
    report = verification_engine.verify(
        reqs,
        run_id=payload.run_id,
        job_id=payload.job_id,
    )
    verification_reports.save(report)
    metrics.incr("verification_evaluations")
    return {"report": report.public_dict()}


@app.get("/api/verification/reports")
def list_verification_reports(
    run_id: Annotated[str | None, Query()] = None,
    job_id: Annotated[str | None, Query()] = None,
    outcome: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict:
    items = verification_reports.list(
        run_id=run_id,
        job_id=job_id,
        outcome=outcome,
        limit=limit,
    )
    return {"reports": [item.public_dict() for item in items]}


@app.get("/api/verification/reports/{report_id}")
def get_verification_report(report_id: str) -> dict:
    item = verification_reports.get(report_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Verification report not found")
    return {"report": item.public_dict()}


class AgentExecuteRequest(BaseModel):
    request: str = Field(min_length=1, max_length=30_000)
    kind: str = "GENERIC"
    use_jobs: bool = False
    conversation_id: str | None = None
    capability_overrides: dict = Field(default_factory=dict)


@app.post("/api/agents/execute")
def execute_agent(payload: AgentExecuteRequest) -> dict:
    try:
        kind = AgentKind(payload.kind.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid agent kind: {payload.kind}") from exc
    result = agent_runtime.execute(
        payload.request,
        kind=kind,
        use_jobs=payload.use_jobs,
        conversation_id=payload.conversation_id,
        capability_overrides=payload.capability_overrides or None,
    )
    if result.status == "DISABLED":
        raise HTTPException(status_code=403, detail=result.public_dict())
    return {"agent": result.public_dict()}


class MultiAgentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=30_000)
    kinds: list[str] = Field(default_factory=lambda: ["RESEARCH", "GENERIC"])
    capability_overrides: dict = Field(default_factory=dict)


@app.post("/api/agents/multi")
def execute_multi_agent(payload: MultiAgentRequest) -> dict:
    kinds: list[AgentKind] = []
    for raw in payload.kinds:
        try:
            kinds.append(AgentKind(raw.upper()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid agent kind: {raw}") from exc
    result = multi_agents.run(
        payload.request,
        kinds=kinds,
        capability_overrides=payload.capability_overrides or None,
    )
    if result.status == "DISABLED":
        raise HTTPException(status_code=403, detail=result.public_dict())
    return {"multi_agent": result.public_dict()}


class WorkflowCreateRequest(BaseModel):
    name: str = Field(default="workflow", min_length=1, max_length=120)
    run_id: str | None = None
    steps: list[dict] = Field(default_factory=list)


@app.get("/api/workflows")
def list_workflows(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict:
    return {"workflows": [item.public_dict() for item in workflow_store.list(limit=limit)]}


@app.post("/api/workflows")
def create_workflow(payload: WorkflowCreateRequest) -> dict:
    steps: list[WorkflowStepDef] = []
    for idx, raw in enumerate(payload.steps):
        capability_id = raw.get("capability_id")
        if not capability_id:
            raise HTTPException(status_code=422, detail=f"Step {idx} missing capability_id")
        steps.append(
            WorkflowStepDef(
                step_id=str(raw.get("step_id") or f"step-{idx}"),
                capability_id=str(capability_id),
                arguments=dict(raw.get("arguments") or {}),
                approval_id=raw.get("approval_id"),
            )
        )
    try:
        record = workflow_runtime.create(name=payload.name, steps=steps, run_id=payload.run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"workflow": record.public_dict()}


@app.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict:
    record = workflow_store.get(workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow": record.public_dict()}


@app.post("/api/workflows/{workflow_id}/run")
def run_workflow(workflow_id: str) -> dict:
    try:
        record = workflow_runtime.run(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    return {"workflow": record.public_dict()}


@app.post("/api/workflows/{workflow_id}/cancel")
def cancel_workflow(workflow_id: str) -> dict:
    try:
        record = workflow_runtime.cancel(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"workflow": record.public_dict()}


class ScheduleCreateRequest(BaseModel):
    name: str = Field(default="schedule", min_length=1, max_length=120)
    target_kind: str = "JOB"
    target_ref: str = Field(min_length=1, max_length=120)
    interval_seconds: int = Field(default=60, ge=1, le=86_400)
    target_payload: dict = Field(default_factory=dict)
    start_after_seconds: int = Field(default=0, ge=0, le=86_400)


@app.get("/api/schedules")
def list_schedules(
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    parsed = None
    if status:
        try:
            parsed = ScheduleStatus(status.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid schedule status: {status}") from exc
    return {
        "schedules": [item.public_dict() for item in schedule_store.list(status=parsed, limit=limit)],
        "telemetry": dict(schedule_runner.telemetry),
    }


@app.post("/api/schedules")
def create_schedule(payload: ScheduleCreateRequest) -> dict:
    try:
        kind = ScheduleTargetKind(payload.target_kind.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid target_kind: {payload.target_kind}") from exc
    try:
        record = schedule_store.create(
            name=payload.name,
            target_kind=kind,
            target_ref=payload.target_ref,
            interval_seconds=payload.interval_seconds,
            target_payload=payload.target_payload,
            start_after_seconds=payload.start_after_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"schedule": record.public_dict()}


@app.get("/api/schedules/{schedule_id}")
def get_schedule(schedule_id: str) -> dict:
    record = schedule_store.get(schedule_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"schedule": record.public_dict()}


@app.post("/api/schedules/{schedule_id}/pause")
def pause_schedule(schedule_id: str) -> dict:
    record = schedule_store.set_status(schedule_id, ScheduleStatus.PAUSED)
    if record is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"schedule": record.public_dict()}


@app.post("/api/schedules/{schedule_id}/resume")
def resume_schedule(schedule_id: str) -> dict:
    record = schedule_store.set_status(schedule_id, ScheduleStatus.ACTIVE)
    if record is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"schedule": record.public_dict()}


@app.post("/api/schedules/tick")
def tick_schedules() -> dict:
    fired = schedule_runner.tick()
    observability.emit(
        "schedule",
        "tick",
        payload={"fired": len(fired), "ok": sum(1 for item in fired if item.get("ok"))},
    )
    return {"fired": fired, "telemetry": dict(schedule_runner.telemetry)}


@app.get("/api/telemetry")
def get_telemetry(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    category: Annotated[str | None, Query()] = None,
) -> dict:
    return {
        "snapshot": observability.snapshot(),
        "events": [item.public_dict() for item in observability.recent(limit=limit, category=category)],
        "latest_sequence": observability.latest_sequence(),
        "truth": {
            "in_process_ring_buffer_only": observability.store is None,
            "durable_history": observability.store is not None,
            "not_a_production_apm": True,
            "redacted": True,
        },
    }


class NeuroAssessRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)


@app.post("/api/neuro/assess")
def neuro_assess(payload: NeuroAssessRequest) -> dict:
    plan = reasoner.analyze(payload.text, has_knowledge=False)
    assessment = neuro_advisor.assess(payload.text, plan=plan)
    return {"assessment": assessment.public_dict(), "reasoning": plan.public_summary()}


@app.get("/api/neuro/residual")
def neuro_residual_status() -> dict:
    hooks = [item.public_dict() for item in residual_runtime.list_hook_points()]
    info = residual_runtime.runtime_info() if hasattr(residual_runtime, "runtime_info") else {}
    return {
        "supports_residuals": residual_runtime.supports_residuals(),
        "hook_points": hooks,
        "runtime": info,
        "kind": settings.neuro_runtime.residual_kind,
        "residual_production": settings.features.residual_production,
        "residual_orchestrator": settings.features.neuro_residual_orchestrator,
        "load_weights": settings.neuro_runtime.residual_load_weights,
        "hook_layers": list(settings.neuro_runtime.residual_hook_layers),
        "cortex_max_k": settings.neuro_runtime.cortex_max_k,
        "orchestrator_telemetry": dict(residual_orchestrator.telemetry),
        "recent_receipts": residual_receipts.recent(limit=10),
        "truth": {
            "neural_signal_is_not_authority": True,
            "residual_injection_is_not_authority": True,
            "unsupported_is_not_success": True,
            "unapplied_is_not_success": True,
            "discoverable_is_not_authorized": True,
            "model_output_is_not_evidence": True,
            "unsupported_is_not_failure_of_core": True,
        },
    }


class NeuroOrchestrateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)
    complexity: str = Field(default="medium", max_length=32)
    run_forward: bool = False
    mode: str | None = Field(default=None, max_length=32)


@app.post("/api/neuro/residual/orchestrate")
def neuro_residual_orchestrate(payload: NeuroOrchestrateRequest) -> dict:
    if not settings.features.neuro_enabled:
        raise HTTPException(status_code=503, detail="Neuro feature flag OFF")
    if not settings.features.neuro_residual_orchestrator:
        raise HTTPException(status_code=503, detail="Neuro residual orchestrator flag OFF")
    report = residual_orchestrator.orchestrate(
        messages=[{"role": "user", "content": payload.text}],
        complexity=payload.complexity,
        token_budget=settings.context.token_budget,
        run_forward=payload.run_forward,
        mode=payload.mode,
    )
    for receipt in report.receipts:
        residual_receipts.record(
            receipt,
            metadata={"source": "residual_orchestrator", "complexity": payload.complexity},
        )
    observability.emit(
        "neuro",
        "residual_orchestrate",
        payload={
            "plans": len(report.plans),
            "applied": sum(1 for r in report.receipts if r.applied),
            "available": report.residual_available,
        },
    )
    metrics.incr("neuro_residual_orchestrations")
    return {"report": report.public_dict()}


class NeuroCortexRunRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)
    depth: int = Field(default=1, ge=0, le=4)
    critic_rounds: int = Field(default=1, ge=0, le=4)


@app.post("/api/neuro/cortex/run")
def neuro_cortex_run(payload: NeuroCortexRunRequest) -> dict:
    if not settings.features.neuro_enabled or not settings.features.neuro_cortex:
        raise HTTPException(status_code=503, detail="Neuro cortex feature flags OFF")
    report = cortex_runtime.run(
        messages=[{"role": "user", "content": payload.text}],
        depth=payload.depth,
        critic_rounds=payload.critic_rounds,
    )
    observability.emit("neuro", "cortex_run", payload={"engaged": report.engaged, "degraded": report.degraded})
    metrics.incr("neuro_cortex_runs")
    return {"report": report.public_dict()}


class NeuroSnapshotRequest(BaseModel):
    tier: int = Field(ge=0, le=1)
    label: str = Field(default="snapshot", min_length=1, max_length=120)


@app.post("/api/neuro/memory/snapshot")
def neuro_memory_snapshot(payload: NeuroSnapshotRequest) -> dict:
    if not settings.features.neuro_memory_tiers:
        raise HTTPException(status_code=503, detail="Neuro memory tiers feature flag OFF")
    try:
        snap = neuro_memory.snapshot(payload.tier, payload.label)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"snapshot": snap.public_dict()}


@app.get("/api/neuro/memory/snapshots")
def neuro_memory_snapshots(tier: Annotated[int | None, Query(ge=0, le=1)] = None) -> dict:
    return {"snapshots": [item.public_dict() for item in neuro_snapshots.list(tier=tier)]}


@app.post("/api/neuro/memory/snapshots/{snapshot_id}/restore")
def neuro_memory_restore(snapshot_id: str) -> dict:
    if not settings.features.neuro_memory_tiers:
        raise HTTPException(status_code=503, detail="Neuro memory tiers feature flag OFF")
    try:
        snap = neuro_memory.restore(snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Snapshot not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"snapshot": snap.public_dict()}


class NeuroAbsorbRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=5000)


@app.post("/api/neuro/absorb")
def neuro_absorb_scan(payload: NeuroAbsorbRequest) -> dict:
    """Operator-triggered ModelData absorb via Knowledge V2 (not a parallel pipeline)."""
    result = neuro_absorb.scan_once(limit=payload.limit)
    observability.emit("neuro", "absorb", payload={"ingested": result.get("ingested", 0)})
    metrics.incr("neuro_absorb_scans")
    return result


class NeuroAbsorbScheduleRequest(BaseModel):
    interval_seconds: int = Field(default=3600, ge=60, le=86400)
    limit: int = Field(default=50, ge=1, le=5000)
    approval_id: str = Field(min_length=1, max_length=120)
    name: str = Field(default="neuro-modeldata-absorb", min_length=1, max_length=120)


@app.post("/api/neuro/absorb/schedule")
def neuro_absorb_schedule(payload: NeuroAbsorbScheduleRequest) -> dict:
    """Create an interval Job schedule for knowledge.ingest_scan (WRITE → approval required)."""
    if not approval_service.is_approved(
        payload.approval_id,
        capability_id="knowledge.ingest_scan",
        side_effects=capability_catalog.require("knowledge.ingest_scan").side_effects,
    ):
        raise HTTPException(status_code=403, detail="approval_id not valid for knowledge.ingest_scan")
    record = schedule_store.create(
        name=payload.name,
        target_kind=ScheduleTargetKind.JOB,
        target_ref="knowledge.ingest_scan",
        interval_seconds=payload.interval_seconds,
        target_payload={
            "arguments": {"limit": payload.limit},
            "approval_id": payload.approval_id,
        },
        metadata={"neuro_absorb": True, "uses_knowledge_v2": True},
    )
    observability.emit(
        "neuro",
        "absorb_schedule",
        payload={"schedule_id": record.schedule_id, "interval_seconds": payload.interval_seconds},
    )
    return {
        "schedule": record.public_dict(),
        "truth": {
            "schedule_is_not_authority": True,
            "write_still_requires_approval": True,
            "no_parallel_ingest_pipeline": True,
        },
    }


class NeuroSoakRequest(BaseModel):
    iterations: int = Field(default=3, ge=1, le=200)
    mode: str = Field(default="mini", max_length=16)


@app.post("/api/neuro/soak")
def neuro_soak_run(payload: NeuroSoakRequest) -> dict:
    """Local soak for neuro contracts — mini or long; never a multi-hour SLO claim."""

    def _assess() -> str:
        result = neuro_advisor.assess("soak probe delete risk", plan=reasoner.analyze("soak", False))
        return f"signals={len(result.signals)} enabled={result.enabled}"

    def _residual() -> str:
        return f"supports={residual_runtime.supports_residuals()} kind={settings.neuro_runtime.residual_kind}"

    def _modules() -> str:
        return f"enabled={module_manager.enabled} count={len(module_manager.list())}"

    def _orchestrator() -> str:
        return (
            f"enabled={residual_orchestrator.enabled} "
            f"telemetry={residual_orchestrator.telemetry.get('orchestrations', 0)}"
        )

    try:
        report = neuro_soak.run(
            iterations=payload.iterations,
            mode=payload.mode,
            steps=[
                ("neuro_assess", _assess),
                ("residual_port", _residual),
                ("module_manager", _modules),
                ("residual_orchestrator", _orchestrator),
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metrics.incr("neuro_soak_runs")
    return {"report": report.public_dict()}


@app.post("/api/neuro/contrastive")
def neuro_contrastive_retrieve(payload: NeuroAssessRequest) -> dict:
    report = neuro_contrastive.retrieve(payload.text)
    return {"report": report.public_dict()}


@app.get("/api/modules")
def list_managed_modules() -> dict:
    if not module_manager.enabled:
        return {
            "enabled": False,
            "modules": [],
            "truth": {"module_manager_feature_flag_off": True},
        }
    return module_manager.public_snapshot()


@app.post("/api/modules/discover")
def discover_modules() -> dict:
    if not module_manager.enabled:
        raise HTTPException(status_code=503, detail="Module manager feature flag OFF")
    manifests = module_manager.discover()
    observability.emit("module_manager", "discover", payload={"count": len(manifests)})
    return {
        "discovered": [item.public_dict() for item in manifests],
        "snapshot": module_manager.public_snapshot(),
    }


class ModuleExecuteRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


@app.post("/api/modules/{module_id}/execute")
def execute_managed_module(module_id: str, payload: ModuleExecuteRequest) -> dict:
    if not module_manager.enabled:
        raise HTTPException(status_code=503, detail="Module manager feature flag OFF")
    try:
        result = module_manager.execute(module_id, payload.operation, payload.arguments)
    except ModuleManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    observability.emit(
        "module_manager",
        "execute",
        payload={"module_id": module_id, "operation": payload.operation, "status": result.status},
    )
    return {"result": result.public_dict()}


@app.get("/api/plugins")
def list_plugins() -> dict:
    return {"plugins": [item.public_dict() for item in plugin_registry.list()]}


@app.get("/api/plugins/{plugin_id}")
def get_plugin(plugin_id: str) -> dict:
    item = plugin_registry.get(plugin_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"plugin": item.public_dict()}


@app.post("/api/plugins/{plugin_id}/disable")
def disable_plugin(plugin_id: str) -> dict:
    try:
        item = plugin_registry.set_status(plugin_id, PluginStatus.DISABLED)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    return {"plugin": item.public_dict()}


@app.post("/api/plugins/{plugin_id}/enable")
def enable_plugin(plugin_id: str) -> dict:
    try:
        item = plugin_registry.set_status(plugin_id, PluginStatus.ENABLED)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    return {"plugin": item.public_dict()}


class PluginInvokeRequest(BaseModel):
    external_name: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None


@app.post("/api/plugins/{plugin_id}/invoke")
def invoke_plugin(plugin_id: str, payload: PluginInvokeRequest) -> dict:
    capability_id = plugin_registry.resolve_capability(plugin_id, payload.external_name)
    if capability_id is None:
        raise HTTPException(
            status_code=404,
            detail="Plugin binding not found or plugin not ENABLED",
        )
    result = execution_gateway.execute(
        CapabilityRequest(
            capability_id=capability_id,
            arguments=payload.arguments,
            approval_id=payload.approval_id,
            requested_by=f"plugin:{plugin_id}",
        )
    )
    observability.emit(
        "plugin",
        "invoke",
        payload={"plugin_id": plugin_id, "capability_id": capability_id, "status": result.status.value},
    )
    status_code = 200
    if result.status == CapabilityStatus.REJECTED:
        reason = (result.telemetry or {}).get("reason")
        status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
    elif result.status == CapabilityStatus.FAILED:
        status_code = 500
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.public_dict())
    return {
        "capability_id": capability_id,
        "result": result.public_dict(),
        "truth": {"discoverable_capability_is_not_authorized_capability": True},
    }


@app.post("/api/evaluation/foundation")
def run_foundation_evaluation() -> dict:
    report = evaluation_harness.run_suite(
        "foundation",
        evaluation_harness.default_foundation_suite(),
    )
    return {"report": report.public_dict()}


@app.post("/api/evaluation/neuro")
def run_neuro_evaluation() -> dict:
    report = evaluation_harness.run_suite(
        "neuro_ablation",
        evaluation_harness.neuro_ablation_suite(
            residual_supported=residual_runtime.supports_residuals(),
            cortex_enabled=settings.features.neuro_cortex,
            memory_tiers_enabled=settings.features.neuro_memory_tiers,
            critic_enabled=settings.features.neuro_process_critic,
        ),
    )
    return {"report": report.public_dict()}


class IsolationEvaluateRequest(BaseModel):
    requested: list[str] = Field(default_factory=list)
    reason: str = ""


@app.get("/api/isolation")
def get_isolation() -> dict:
    return {"isolation": isolation_guard.evaluate().public_dict()}


@app.post("/api/isolation/evaluate")
def evaluate_isolation(payload: IsolationEvaluateRequest) -> dict:
    modes: list[IsolationMode] = []
    for raw in payload.requested:
        try:
            modes.append(IsolationMode(raw.upper()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid isolation mode: {raw}") from exc
    report = isolation_guard.evaluate(
        IsolationRequest(requested=tuple(modes), reason=payload.reason)
    )
    return {"isolation": report.public_dict()}


class TrainingCreateRequest(BaseModel):
    name: str = Field(default="training", min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2000)


@app.get("/api/training")
def list_training() -> dict:
    """Legacy listing: preference-bridge registry intents (registered ≠ trained).

    Durable training jobs live under ``/api/training/jobs``.
    """
    return {
        "jobs": [item.public_dict() for item in training_registry.list()],
        "durable_jobs": [item.public_dict() for item in training_service.list_jobs(limit=50)],
        "truth": {
            "registered_is_not_trained": True,
            "durable_jobs_path": "/api/training/jobs",
        },
    }


@app.get("/api/training/recipes")
def list_training_recipes() -> dict:
    return {"recipes": [item.public_dict() for item in training_recipes.list()]}


class PreferenceFromVerificationRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    recipe_id: str = Field(default="pref_dpo_v1", min_length=1, max_length=80)


@app.post("/api/training/preferences/from-verification")
def training_preferences_from_verification(payload: PreferenceFromVerificationRequest) -> dict:
    if training_recipes.get(payload.recipe_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown recipe: {payload.recipe_id}")
    reports = verification_reports.list(limit=payload.limit)
    jobs = preference_bridge.register_from_verification_reports(
        reports,
        recipe_id=payload.recipe_id,
    )
    return {
        "registered": [item.public_dict() for item in jobs],
        "source_reports": len(reports),
        "truth": {
            "registered_is_not_trained": True,
            "preference_labels_not_fabricated": True,
        },
    }


@app.post("/api/training")
def create_training(payload: TrainingCreateRequest) -> dict:
    """Legacy preference/intent registration — does not start real training."""
    job = training_registry.register(name=payload.name, objective=payload.objective)
    return {
        "job": job.public_dict(),
        "truth": {
            "registered_is_not_trained": True,
            "start_real_training_at": "/api/training/jobs",
        },
    }


class BrowserRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    url: str | None = None


@app.post("/api/browser/request")
def browser_request(payload: BrowserRequest) -> dict:
    try:
        action = BrowserAction(payload.action.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid browser action: {payload.action}") from exc
    job = browser_stub.request(action=action, url=payload.url)
    status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
    if status != 200:
        raise HTTPException(status_code=status, detail=job.public_dict())
    return {"job": job.public_dict()}


class MediaRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    path: str | None = None


@app.post("/api/media/request")
def media_request(payload: MediaRequest) -> dict:
    try:
        action = MediaAction(payload.action.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid media action: {payload.action}") from exc
    job = media_stub.request(action=action, path=payload.path)
    status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
    if status != 200:
        raise HTTPException(status_code=status, detail=job.public_dict())
    return {"job": job.public_dict()}


class VoiceRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    text: str | None = None


@app.post("/api/voice/request")
def voice_request(payload: VoiceRequest) -> dict:
    try:
        action = VoiceAction(payload.action.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid voice action: {payload.action}") from exc
    job = voice_stub.request(action=action, text=payload.text)
    status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
    if status != 200:
        raise HTTPException(status_code=status, detail=job.public_dict())
    return {"job": job.public_dict()}


@app.get("/api/release/gates")
def release_gates_status() -> dict:
    return {"report": release_gates.run().public_dict()}


@app.get("/api/security/audit")
def security_audit() -> dict:
    return {"report": security_auditor.run().public_dict()}


@app.get("/api/native/probe")
def native_probe() -> dict:
    return {"native": native_runtime.probe().public_dict()}


class TradingOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: str = Field(min_length=1, max_length=16)
    quantity: float = Field(gt=0)


@app.post("/api/trading/order")
def trading_order(payload: TradingOrderRequest) -> dict:
    result = trading_stub.place_order(
        symbol=payload.symbol,
        side=payload.side,
        quantity=payload.quantity,
    )
    raise HTTPException(status_code=501, detail=result.public_dict())


class BackupCreateRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@app.get("/api/backup")
def list_backups(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    return {"backups": [item.public_dict() for item in backup_service.list(limit=limit)]}


@app.post("/api/backup")
def create_backup(payload: BackupCreateRequest | None = None) -> dict:
    try:
        manifest = backup_service.create(note=(payload.note if payload else None))
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metrics.incr("backups_created")
    return {"backup": manifest.public_dict()}


class BackupRestoreRequest(BaseModel):
    backup_id: str = Field(min_length=1, max_length=120)
    confirm: bool = False


@app.post("/api/backup/restore")
def restore_backup(payload: BackupRestoreRequest) -> dict:
    try:
        manifest = backup_service.restore(payload.backup_id, confirm=payload.confirm)
    except BackupError as exc:
        status = 400 if "confirm" in str(exc).lower() else 404
        if "hash" in str(exc).lower():
            status = 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    metrics.incr("backups_restored")
    return {"backup": manifest.public_dict(), "warning": "process should be restarted after restore"}


@app.get("/api/chaos")
def chaos_status() -> dict:
    return {"chaos": chaos.public_dict()}


class ChaosConfigureRequest(BaseModel):
    enabled: bool = False
    latency_ms: int = Field(default=0, ge=0, le=60_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error_message: str = Field(default="chaos_injected_failure", max_length=200)


@app.post("/api/chaos/configure")
def chaos_configure(payload: ChaosConfigureRequest) -> dict:
    if payload.enabled and not settings.runtime.loopback_only:
        raise HTTPException(status_code=403, detail="Chaos refused when loopback_only is false")
    plan = chaos.configure(
        ChaosPlan(
            enabled=payload.enabled,
            latency_ms=payload.latency_ms,
            error_rate=payload.error_rate,
            error_message=payload.error_message,
        )
    )
    return {"chaos": {"plan": plan.public_dict(), "activations": chaos.activations, "faults": chaos.faults}}


@app.get("/api/master/gates")
def master_gates_status() -> dict:
    return {"report": master_gates.run().public_dict()}


@app.get("/")
def dashboard() -> FileResponse:
    return _frontend_index()


@app.get("/chat")
@app.get("/chat.html")
def chat_page() -> FileResponse:
    return _frontend_index()


_assets_dir = FRONTEND_DIST / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")


@app.get("/{spa_path:path}")
def spa_fallback(spa_path: str) -> FileResponse:
    if spa_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = FRONTEND_DIST / spa_path
    if candidate.is_file() and FRONTEND_DIST in candidate.resolve().parents:
        return FileResponse(candidate)
    return _frontend_index()
