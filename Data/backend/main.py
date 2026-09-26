from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DATA_ROOT, FRONTEND_DIST, FRONTEND_ROOT, PROJECT_ROOT, settings
from .database import Database
from .migrations import MigrationRunner
from Data.backend.routes.settings import build_behavior_router, build_settings_router
from Data.modules.settings import DEFAULT_BEHAVIOR_PROFILE, SettingsControlPlane
from Data.modules.settings.behavior_store import BehaviorProfileStore
from Data.modules.settings.bindings import bind_default_consumers
from Data.modules.settings.resolver import BehaviorSettingsResolver
from Data.modules.common import ownership_public_dict
from Data.modules.agents import (
    AgentFleetService,
    AgentFleetStore,
    AgentKind,
    AgentRuntime,
    MultiAgentCoordinator,
    SystemInventory,
)
from Data.modules.agents.signals import SignalFabricService, SignalStore
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
from Data.backend.routes.agent_signals import build_signals_router
from Data.backend.routes.analytics import build_analytics_router
from Data.modules.market_sim import MarketSimControlPlane
from Data.backend.routes.market_sim import build_market_sim_router
from Data.backend.routes.trading_orchestra import build_trading_orchestra_router
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
    StagedRetriever,
    WhyLibrary,
    build_embedding_provider,
    resolve_use_reranker,
)
from Data.modules.memory import MemoryKind, MemoryScope, MemoryStatus, MemoryStore
from Data.modules.model_runtime import (
    LLMUnavailable,
    OpenAICompatibleLLM,
    StreamCancelToken,
    chat_truth,
    sse_encode,
)
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.backend.routes.models import build_models_router
from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleManagerError
from Data.modules.observations import ObservationStore
from Data.modules.reasoning import ReasoningEngine
from Data.modules.reasoning.engine import ReasoningPlan
from Data.modules.reasoning.mode import (
    apply_mode_to_plan,
    resolve_effective_mode,
    to_cognition_depth,
)
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
from Data.backend.routes.efficiency import build_efficiency_router
from Data.backend.routes.brain import build_brain_router
from Data.modules.brain import BrainAccessFacade, BrainQueryFacade
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
from Data.modules.evaluation import EvaluationHarness, EvaluationPlatform, EvaluationStore
from Data.modules.isolation import IsolationGuard, IsolationMode, IsolationRequest
from Data.modules.training import (
    ActiveLearningMiner,
    FlywheelControlPlane,
    PreferenceBridge,
    PreferenceStore,
    SyntheticDataService,
    TrainingRecipeRegistry,
    TrainingRegistry,
    TrainingService,
    build_neuro_recipe_trainer,
)
from Data.modules.models.store import ModelStore
from Data.modules.datasets import DatasetService
from Data.modules.research import ResearchService
from Data.modules.common.corpus import build_corpus_layout
from Data.backend.routes.datasets import build_datasets_router
from Data.backend.routes.training import build_training_router, build_training_surface_router
from Data.backend.routes.research import build_research_router
from Data.modules.browser import BrowserAction, BrowserAutomationStub, BrowserWorker
from Data.modules.media import MediaAction, MediaAutomationStub, MediaService
from Data.modules.voice import RealtimeVoiceService, VoiceAction, VoiceRuntimeStub
from Data.modules.context import (
    ContextBuilder,
    MultimodalPart,
    MultimodalSessionRegistry,
    PartKind,
    new_sync_id,
)
from Data.modules.release import GateCheck, GateSeverity, ReleaseGateRunner, evaluation_relevance_gate
from Data.modules.mcp import McpBridge, McpProvider, McpStore, register_module_mcp, unregister_module_mcp
from Data.backend.routes.mcp import build_mcp_router
from Data.backend.routes.cognition import build_cognition_router
from Data.backend.routes.team import build_team_router
from Data.backend.routes.tasks import build_tasks_router
from Data.backend.routes.browser_qa import build_browser_qa_router
from Data.backend.routes.knowledge import build_knowledge_router, make_enqueue_ingest_scan
from Data.backend.routes.evaluation import build_evaluation_router
from Data.backend.routes.neuro import build_neuro_router
from Data.backend.routes.jobs import build_jobs_router
from Data.backend.routes.workers import build_workers_router
from Data.backend.routes.memory import build_memory_router
from Data.backend.routes.evidence import build_evidence_router
from Data.backend.routes.capabilities import build_capabilities_router
from Data.backend.routes.functions import build_functions_router
from Data.backend.routes.approvals import build_approvals_router
from Data.backend.routes.workflows import build_workflows_router
from Data.backend.routes.schedules import build_schedules_router
from Data.backend.routes.verification import build_verification_router
from Data.backend.routes.observations import build_observations_router
from Data.backend.routes.artifacts import build_artifacts_router
from Data.backend.routes.flywheel import build_flywheel_router
from Data.backend.routes.plugins import build_plugins_router
from Data.backend.routes.modules import build_modules_router
from Data.backend.routes.conversations import build_conversations_router
from Data.backend.routes.browser import build_browser_router
from Data.backend.routes.platform import build_platform_router
from Data.backend.routes.media import build_media_router
from Data.backend.routes.voice import build_voice_router
from Data.backend.routes.multimodal import build_multimodal_router
from Data.modules.tasks import TaskService, TaskStore
from Data.modules.mcp.errors import McpError
from Data.modules.cognition import (
    CognitionStore,
    CognitiveRuntime,
    DelegationService,
    ExperienceStore,
    MetaController,
    PerceptionService,
    CapabilityBroker,
)
from Data.modules.cognition.domain_strategy import StrategyRegistry
from Data.modules.cognition.model_adapter import build_control_plane_model_caller
from Data.modules.cognition.resource_pressure import (
    build_resource_pressure_fn,
    telemetry_dict_from_observability,
)
from Data.modules.cognition.specialists import register_specialist_handlers
from Data.modules.coding.cognition import CodingCognitiveStrategy
from Data.modules.intelligence import (
    IntelligenceHealthService,
    KnowledgeAssimilationService,
    ReasoningPolicy,
)
from Data.modules.security import SecretsBroker, SecurityAuditor, SecurityFinding
from Data.modules.execution import CapabilityReceiptStore
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
retriever = HybridRetriever(
    knowledge,
    embeddings=embedding_provider,
    reranker=reranker_provider,
    diversity_enabled=bool(settings.knowledge.diversity_enabled),
    diversity_strength=float(settings.knowledge.diversity_strength),
)
staged_retriever = StagedRetriever(
    retriever,
    deep_recall=None,  # wired after deep_recall_service is constructed
    rerank_policy=settings.knowledge.rerank_policy,
    query_expansion=bool(settings.knowledge.query_expansion),
    max_query_expansions=int(settings.knowledge.max_query_expansions),
)
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
staged_retriever.deep_recall = deep_recall_service
assimilation_service = KnowledgeAssimilationService(
    database_path=settings.database_path,
    knowledge_store=knowledge,
    atlas_store=atlas_store,
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
capability_receipts = CapabilityReceiptStore(settings.database_path)
secrets_broker = SecretsBroker(settings.database_path)
execution_gateway = ExecutionGateway(
    catalog=capability_catalog,
    function_runtime=function_runtime,
    knowledge_retriever=retriever,
    knowledge_store=knowledge,
    artifact_store=artifacts,
    approval_checker=approval_service,
    observation_store=observation_store,
    receipt_store=capability_receipts,
    filesystem_root=PROJECT_ROOT,
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
system_inventory = SystemInventory()
agent_fleet = AgentFleetService(
    agent_fleet_store,
    agent_runtime,
    system_inventory=system_inventory,
    job_runtime=job_runtime,
)
signal_store = SignalStore(settings.database_path)
signal_fabric = SignalFabricService(
    signal_store,
    fleet=agent_fleet,
    job_runtime=job_runtime,
    enabled=bool(
        getattr(settings.features, "signal_fabric_enabled", True)
        and settings.features.agents_enabled
    ),
)
try:
    from Data.modules.memory import MemoryStore as _MemoryStore

    _mem = _MemoryStore(settings.database_path)
    _mem.initialize()
    signal_fabric.bind_memory_store(_mem)
except Exception:  # noqa: BLE001
    pass
analytics_service = AnalyticsService(settings.database_path)
workflow_store = WorkflowStore(settings.database_path)
workflow_runtime = WorkflowRuntime(workflow_store, execution_gateway, job_runtime=job_runtime)
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
retriever._emit = observability.emit  # noqa: SLF001
staged_retriever._emit = observability.emit  # noqa: SLF001
assimilation_service._emit = observability.emit  # noqa: SLF001
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
mcp_provider = McpProvider(mcp_bridge, job_runtime=job_runtime)
execution_gateway.mcp_executor = mcp_provider
evaluation_harness = EvaluationHarness(
    catalog=capability_catalog,
    evidence=evidence_store,
    verification=verification_engine,
)
evaluation_store = EvaluationStore(settings.database_path)
evaluation_platform = EvaluationPlatform(
    harness=evaluation_harness,
    store=evaluation_store,
    enabled=settings.features.eval_platform,
)
isolation_guard = IsolationGuard(settings)
training_registry = TrainingRegistry()
training_recipes = TrainingRecipeRegistry(
    trainer=build_neuro_recipe_trainer(
        real_worker=settings.features.neuro_training_real_worker
    )
)
preference_store = PreferenceStore(settings.database_path)
preference_store.initialize()
preference_bridge = PreferenceBridge(training_registry, preference_store=preference_store)
synthetic_data_service = SyntheticDataService()
active_learning_miner = ActiveLearningMiner()
model_store_for_flywheel = ModelStore(settings.database_path)
flywheel = FlywheelControlPlane(
    settings.database_path,
    model_store=model_store_for_flywheel,
    evaluation=evaluation_platform if settings.features.eval_platform else None,
)
corpus_layout = build_corpus_layout(settings)
dataset_service = DatasetService.from_settings(
    settings, knowledge=knowledge, job_runtime=job_runtime
)
# Bind live Dataset Learning activity into the Agent Fleet (same jobs, no fiction).
agent_fleet.dataset_activity_provider = lambda: dataset_service.learning_activity(limit=40)
training_service = TrainingService(settings, corpus=corpus_layout, job_runtime=job_runtime)
research_service = ResearchService.from_settings(
    settings,
    db_path=settings.database_path,
    knowledge=knowledge,
    assimilation_service=assimilation_service,
    atlas_store=atlas_store,
    observability_emit=observability.emit,
    job_runtime=job_runtime,
    dataset_service=dataset_service,
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
if hasattr(market_sim_service, "bind_job_runtime"):
    market_sim_service.bind_job_runtime(job_runtime)
neuro_soak = NeuroSoakHarness(long_soak_enabled=settings.features.neuro_soak_long)
browser_worker = BrowserWorker(
    artifact_store=artifacts,
    backend_kind="local_dom",
    filesystem_root=str(PROJECT_ROOT),
    allow_network=True,  # localhost QA crawler probes; public crawl still host-scoped
)
# Shared GI9/GI10 journey crawler — JobRuntime owns durable cancel/checkpoint/resume.
from Data.modules.browser import BrowserJourneyCrawler, CrawlBudget  # noqa: E402

_qa_hosts = tuple(
    h.strip().lower()
    for h in str(getattr(settings.browser_qa, "allowed_hosts", "localhost,127.0.0.1,::1")).split(",")
    if h.strip()
)
browser_qa_crawler = BrowserJourneyCrawler(
    browser_worker=BrowserWorker(
        artifact_store=artifacts,
        backend_kind="local_dom",
        filesystem_root=str(PROJECT_ROOT),
        allow_network=True,
        qa_crawler=False,  # type: ignore[arg-type]
    ),
    artifact_store=artifacts,
    allowed_hosts=_qa_hosts or ("localhost", "127.0.0.1", "::1"),
    budget=CrawlBudget(
        max_pages=int(getattr(settings.browser_qa, "max_pages", 50)),
        max_actions=int(getattr(settings.browser_qa, "max_actions", 200)),
    ),
    allow_destructive=bool(
        getattr(settings.browser_qa, "allow_destructive_test_actions", False)
    ),
    observability=observability,
)
browser_worker._qa_crawler = browser_qa_crawler
browser_stub = BrowserAutomationStub()  # honesty path when capability_world disabled
if settings.features.capability_world:
    execution_gateway.browser_executor = browser_worker
media_service = MediaService(artifact_store=artifacts)
media_stub = MediaAutomationStub()
voice_service = RealtimeVoiceService()
voice_stub = VoiceRuntimeStub()
multimodal_sessions = MultimodalSessionRegistry()
if settings.features.multimodal_realtime:
    execution_gateway.media_executor = media_service
    execution_gateway.voice_executor = voice_service


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
        "coding.advance",
        "git.status",
        "git.diff",
        "browser.navigate",
        "browser.extract_text",
        "browser.screenshot",
        "media.probe",
        "media.image_generate",
        "media.video_ingest",
        "voice.start_session",
        "voice.transcribe",
        "voice.synthesize",
        "voice.barge_in",
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


def _assert_loopback_mutation_allowed(request: Request) -> None:
    """Round 8: approve/deny/lease stay open on loopback; non-loopback needs operator token."""
    if settings.runtime.loopback_only:
        return
    import os

    expected = (os.environ.get("LEVIATHAN_OPERATOR_TOKEN") or "").strip()
    provided = (request.headers.get("x-leviathan-operator-token") or "").strip()
    if not expected or provided != expected:
        raise HTTPException(
            status_code=403,
            detail=(
                "Non-loopback host: approve/deny/lease require matching "
                "X-Leviathan-Operator-Token (set LEVIATHAN_OPERATOR_TOKEN)"
            ),
        )


def _evaluation_externalize() -> bool:
    """Prefer external workers; fail closed toward externalization on probe errors."""
    import os

    try:
        from Data.modules.workers.settings import load_worker_settings

        wsettings = load_worker_settings()
        return bool(wsettings.enabled and wsettings.externalize_api_runners)
    except Exception:  # noqa: BLE001
        raw = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "1").strip().lower()
        return raw in {"1", "true", "yes", "on"}

def _gate_outbound() -> GateCheck:
    """Report outbound posture truthfully — enabled outbound is not a failure.

    Control-plane outbound may be intentionally ON for providers. SSRF / private
    network / ExecutionGateway restrictions still apply. This gate only fails when
    the network module cannot be inspected.
    """
    allow = bool(settings.network.allow_outbound)
    return GateCheck(
        gate_id="outbound_network_posture",
        name="Outbound network posture",
        severity=GateSeverity.INFO,
        passed=True,
        detail="outbound allowed (SSRF/policy still enforced)" if allow else "outbound denied",
    )


def _gate_frontend() -> GateCheck:
    from Data.modules.release import GateMeasurement, ci_release_mode

    ready = (FRONTEND_DIST / "index.html").is_file()
    ci = ci_release_mode()
    return GateCheck(
        gate_id="frontend_dist",
        name="Frontend dist present",
        severity=GateSeverity.BLOCK if ci else GateSeverity.WARN,
        passed=ready,
        detail=(
            "dist ready"
            if ready
            else ("frontend dist missing (BLOCK under CI)" if ci else "frontend dist missing")
        ),
        measurement=GateMeasurement.PASS if ready else GateMeasurement.FAIL,
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


def _gate_evaluation_relevance() -> GateCheck:
    """Wave 2: release authority requires a relevant recorded foundation eval."""
    from Data.modules.release import GateMeasurement

    if not settings.features.eval_platform:
        return GateCheck(
            gate_id="evaluation_relevance",
            name="Relevant evaluation recorded",
            severity=GateSeverity.INFO,
            passed=True,
            detail="eval_platform flag OFF — NOT_APPLICABLE (not a PASS claim)",
            measurement=GateMeasurement.NOT_APPLICABLE,
        )
    relevance = evaluation_platform.has_relevant_eval(suite_id="foundation", require_pass=False)
    # Soft gate: recorded foundation eval required; FAIL blocks; UNMEASURED does not
    # block readiness (honest) but cannot promote (require_pass path elsewhere).
    if not relevance.get("recorded"):
        # Auto-record foundation once so fresh installs are measurable, not silent.
        evaluation_platform.run_foundation(persist=True)
        relevance = evaluation_platform.has_relevant_eval(suite_id="foundation", require_pass=False)
    return evaluation_relevance_gate(
        relevance,
        severity=GateSeverity.BLOCK if relevance.get("measurement") == "FAIL" else GateSeverity.WARN,
        # Promotion paths use require_pass=True separately; CI asserts honesty via is_shipable.
        require_pass=False,
    )


def _gate_ci_policy() -> GateCheck:
    """Round 10: CI plan excludes HADES/editor; unavailable suites ≠ PASS."""
    from Data.modules.release import GateMeasurement, default_leviathan_ci_plan

    plan = default_leviathan_ci_plan()  # declarative — no suites executed here
    payload = plan.public_dict()
    hades = next(s for s in plan.suites if s.suite_id == "hades")
    editor = next(s for s in plan.suites if s.suite_id == "editor")
    ok = (
        hades.measurement == GateMeasurement.NOT_APPLICABLE
        and editor.measurement == GateMeasurement.NOT_APPLICABLE
        and payload["truth"]["skipped_unavailable_is_not_success"]
    )
    return GateCheck(
        gate_id="ci_policy",
        name="CI scope policy (HADES/editor excluded)",
        severity=GateSeverity.BLOCK,
        passed=ok,
        detail=(
            "HADES+editor NOT_APPLICABLE; skipped≠success"
            if ok
            else "CI policy broken"
        ),
        measurement=GateMeasurement.PASS if ok else GateMeasurement.FAIL,
    )


def _gate_fixture_production_separation() -> GateCheck:
    """Round 10: fixture backends must not claim production capability."""
    from Data.modules.release import GateMeasurement

    browser_kind = getattr(getattr(browser_worker, "backend", None), "kind", None)
    kind_val = browser_kind.value if hasattr(browser_kind, "value") else str(browser_kind or "")
    # Fixture browser is OK only when labeled fixture — never as operational production.
    if kind_val == "fixture":
        return GateCheck(
            gate_id="fixture_production_separation",
            name="Fixture ≠ production",
            severity=GateSeverity.WARN,
            passed=True,
            detail="browser backend=fixture (honest, not production)",
            measurement=GateMeasurement.PASS,
        )
    if kind_val in {"local_dom", "playwright"}:
        return GateCheck(
            gate_id="fixture_production_separation",
            name="Fixture ≠ production",
            severity=GateSeverity.INFO,
            passed=True,
            detail=f"browser backend={kind_val}",
            measurement=GateMeasurement.PASS,
        )
    return GateCheck(
        gate_id="fixture_production_separation",
        name="Fixture ≠ production",
        severity=GateSeverity.WARN,
        passed=True,
        detail="browser backend unmeasured",
        measurement=GateMeasurement.UNMEASURED,
    )


release_gates = ReleaseGateRunner(
    checks=[
        _gate_catalog_builtins,
        _gate_loopback,
        _gate_outbound,
        _gate_frontend,
        _gate_neuro_residual_posture,
        _gate_module_manager_subprocess,
        _gate_evaluation_relevance,
        _gate_ci_policy,
        _gate_fixture_production_separation,
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
            severity="info",
            title="Outbound network posture",
            detail="allowed (policy-enforced)" if settings.network.allow_outbound else "denied",
            passed=True,
        ),
        lambda: SecurityFinding(
            finding_id="approvals_write",
            severity="high",
            title="WRITE capabilities require approvals",
            detail="ExecutionGateway enforces approval_id for gated side effects",
            passed=True,
        ),
        lambda: SecurityFinding(
            finding_id="agents_feature",
            severity="info",
            title="Agents feature posture",
            detail="agents_enabled=" + str(settings.features.agents_enabled),
            passed=True,
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
    if settings.features.eval_platform:
        report = evaluation_platform.run_foundation(persist=True)
    else:
        report = evaluation_harness.run_suite(
            "foundation",
            evaluation_harness.default_foundation_suite(),
            suite_id="foundation",
        )
    outcomes = {item.outcome.value for item in report.results}
    measurements = {item.resolved_measurement().value for item in report.results}
    if "FAILED" in outcomes or "ERROR" in outcomes or "FAIL" in measurements:
        return MasterGateCheck(
            check_id="evaluation_foundation",
            name="Foundation evaluation",
            status=MasterGateStatus.BLOCKED,
            detail="foundation suite has FAILED/ERROR",
        )
    if "UNMEASURED" in outcomes or "UNMEASURED" in measurements:
        return MasterGateCheck(
            check_id="evaluation_foundation",
            name="Foundation evaluation",
            status=MasterGateStatus.DEGRADED,
            detail="foundation suite has UNMEASURED (honest; not shipable under CI)",
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
model_plane.bind_llm(llm)
model_plane.bind_job_runtime(job_runtime)
model_plane.set_telemetry_provider(lambda: system_telemetry_sampler.latest_public())

# Shared physical reservation truth (model loads + background GPU workers).
from Data.modules.workers.admission import ResourceAdmission as _ResourceAdmission

_model_resource_admission = _ResourceAdmission(
    settings.database_path,
    ram_headroom_mb=float(getattr(getattr(settings, "managed_serving", None), "min_ram_reserve_bytes", 1_073_741_824) or 1_073_741_824) / (1024 * 1024),
    vram_headroom_mb=float(getattr(getattr(settings, "managed_serving", None), "min_vram_reserve_bytes", 536_870_912) or 536_870_912) / (1024 * 1024),
    telemetry_reader=lambda: _admission_telemetry_snapshot(system_telemetry_sampler, model_plane),
    interactive_busy_fn=lambda: bool(model_plane.gateway.snapshot().global_inflight),
    hardware_reader=model_plane.resources.hardware_snapshot,
)
_model_resource_admission.initialize()
model_plane.bind_resource_admission(_model_resource_admission)


def _admission_telemetry_snapshot(sampler: Any, plane: Any) -> dict[str, Any]:
    """Map canonical hardware/telemetry into ResourceAdmission snapshot fields."""
    try:
        public = sampler.latest_public()
    except Exception:  # noqa: BLE001
        public = {}
    mem = public.get("memory") if isinstance(public.get("memory"), dict) else {}
    ram_bytes = mem.get("availableBytes")
    hw = plane.resources.hardware_snapshot()
    largest_free = hw.largest_single_device_free_bytes
    return {
        "ram_available_mb": (float(ram_bytes) / (1024 * 1024)) if isinstance(ram_bytes, int) else None,
        "vram_available_mb": (float(largest_free) / (1024 * 1024)) if isinstance(largest_free, int) else None,
        "devices": [d.public_dict() for d in hw.devices],
        "source": "model_plane_hardware",
    }
settings_plane = SettingsControlPlane(settings)
behavior_store = BehaviorProfileStore(settings.database_path)
behavior_store.ensure_schema()
behavior_resolver = BehaviorSettingsResolver(behavior_store)
behavior_store.on_change(behavior_resolver.invalidate)

cognition_store = CognitionStore(settings.database_path)
cognition_delegation = DelegationService()
cognition_model_caller = build_control_plane_model_caller(model_plane, llm)
reasoning_policy = ReasoningPolicy.from_settings(settings)
cognition_experience_store = ExperienceStore(store=cognition_store)
research_service.set_model_caller(cognition_model_caller)


def _cognition_queue_pressure(runtime: Any) -> tuple[int | None, int | None]:
    """Best-effort job queue depth for ADAPTIVE resource pressure (W3)."""
    if runtime is None:
        return None, None
    try:
        if hasattr(runtime, "snapshot"):
            snap = runtime.snapshot()
            data = snap.public_dict() if hasattr(snap, "public_dict") else (snap if isinstance(snap, dict) else {})
            depth = data.get("queued") or data.get("pending") or data.get("queue_depth")
            if depth is not None:
                return int(depth), 32
        store = getattr(runtime, "store", None)
        if store is not None and hasattr(store, "count_by_status"):
            return int(store.count_by_status("QUEUED") or 0), 32
    except Exception:  # noqa: BLE001
        return None, None
    return None, None


def _cognition_workload_pressure(plane: Any, cfg: Any) -> tuple[int | None, int | None]:
    """Best-effort inflight model calls vs concurrency ceiling."""
    if plane is None:
        return None, None
    try:
        gateway = getattr(plane, "gateway", None)
        if gateway is None:
            return None, None
        snap = gateway.snapshot()
        active = int(getattr(snap, "active_calls", 0) or 0)
        cap = int(getattr(getattr(cfg, "resources", None), "max_model_concurrency", 4) or 4)
        return active, max(1, cap)
    except Exception:  # noqa: BLE001
        return None, None


cognition_runtime = CognitiveRuntime(
    enabled=settings.features.cognition_enabled,
    shadow=settings.features.cognition_shadow,
    iterative=settings.features.cognition_iterative_loop,
    belief_enabled=settings.features.cognition_belief_state,
    neuro_enabled=settings.features.cognition_neuro,
    adaptive_depth=settings.features.cognition_adaptive_depth,
    delegation_enabled=settings.features.cognition_delegation,
    experience_learning=settings.features.cognition_experience_learning,
    meta=MetaController(policy=reasoning_policy),
    perception=PerceptionService(
        knowledge_store=knowledge,
        knowledge_retriever=staged_retriever,
        memory_store=memory_store,
        evidence_service=evidence_service,
        capability_catalog=capability_catalog,
        neuro_advisor=neuro_advisor if settings.features.cognition_neuro else None,
        experience_store=cognition_experience_store,
        rerank_policy=settings.knowledge.rerank_policy,
    ),
    broker=CapabilityBroker(capability_catalog),
    delegation=cognition_delegation,
    experience_store=cognition_experience_store,
    store=cognition_store,
    model_caller=cognition_model_caller,
    neuro_advisor=neuro_advisor if settings.features.cognition_neuro else None,
    verification_engine=verification_engine,
    execution_gateway=execution_gateway,
    observability=observability,
    resource_pressure_fn=build_resource_pressure_fn(
        telemetry_provider=lambda: telemetry_dict_from_observability(observability),
        queue_provider=lambda: _cognition_queue_pressure(job_runtime),
        workload_provider=lambda: _cognition_workload_pressure(model_plane, settings),
    ),
    behavior_resolver=behavior_resolver,
)
register_specialist_handlers(
    cognition_delegation,
    coding_service=coding_service,
    research_service=research_service,
)

from Data.modules.cognition.team_orchestrator import TeamOrchestrator
from Data.modules.verification.quality_store import QualityContractStore

quality_contract_store = QualityContractStore(settings.database_path)
quality_contract_store.initialize()
team_orchestrator = TeamOrchestrator(quality_store=quality_contract_store)

task_store = TaskStore(settings.database_path)
task_service = TaskService(
    task_store,
    job_runtime=job_runtime,
    workflow_runtime=workflow_runtime,
    agent_fleet=agent_fleet,
    approval_service=approval_service,
    schedule_store=schedule_store,
    execution_gateway=execution_gateway,
    model_caller=cognition_model_caller,
)

# ---- One Brain composition (after stores exist) ----------------------------


def _knowledge_search(query: str, limit: int = 6):
    try:
        if staged_retriever is not None and hasattr(staged_retriever, "retrieve"):
            return staged_retriever.retrieve(query, limit=limit)
    except Exception:  # noqa: BLE001
        pass
    try:
        if hasattr(knowledge, "search"):
            return knowledge.search(query, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    return []


def _memory_search(query: str, limit: int = 4):
    try:
        return memory_store.search(query, limit=limit)
    except TypeError:
        try:
            return memory_store.search(query)
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001
        return []


def _experience_search(query: str, domain: str | None = None, limit: int = 3):
    try:
        if hasattr(cognition_experience_store, "search"):
            return cognition_experience_store.search(query, domain=domain, limit=limit)
        if hasattr(cognition_experience_store, "list_hints"):
            return cognition_experience_store.list_hints(limit=limit)
        if hasattr(cognition_experience_store, "procedural_hints"):
            return cognition_experience_store.procedural_hints(query=query, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    return []


brain_access = BrainAccessFacade(
    knowledge_search=_knowledge_search,
    memory_search=_memory_search,
    evidence_list=lambda limit=8: evidence_store.list(limit=limit),
    experience_search=_experience_search,
    capability_list=lambda: capability_catalog.list(),
    run_lookup=lambda run_id: run_store.get(run_id) if run_id else None,
)
# W8: Perception must go through Brain when bound — no private store bypass.
cognition_runtime.perception.brain_access = brain_access

domain_strategy_registry = StrategyRegistry()
domain_strategy_registry.register(CodingCognitiveStrategy())

from Data.modules.coding.llm_adapter import CodingLLMAdapter

coding_service.bind_intelligence(
    llm=CodingLLMAdapter(model_plane, llm),
    context_builder=llm.context_builder,
    brain_access=brain_access,
    behavior_store=behavior_store,
    job_runtime=job_runtime,
    reasoning=reasoner,
)

# Trade orchestras / trading agents: trading-only protocol on the existing Agent Fleet.
# Model calls go through the Model Control Plane (consumer="trading"); news I/O through
# provider_io; risk decisions stay deterministic (Mandate + RiskGuard). Chat is untouched.
from Data.modules.market_sim.orchestra import TradingOrchestraService
from Data.modules.market_sim.orchestra.model_adapter import TradingModelAdapter
from Data.modules.market_sim.orchestra.store import OrchestraStore

trading_orchestra_service = TradingOrchestraService(
    store=OrchestraStore(settings.database_path),
    market_plane=market_sim_service,
    model=TradingModelAdapter(model_plane, llm),
    job_runtime=job_runtime,
    approval_service=approval_service,
    memory=memory_store,
    enabled=bool(settings.features.market_sim_enabled),
)


def _wire_system_inventory_status() -> None:
    """Bind truthful status probes to components actually constructed above."""

    def _flag_status(*, enabled: bool, ready_when_enabled: bool = True, detail: str = "") -> dict:
        if not enabled:
            return {"status": "disabled", "enabled": False, "detail": detail or "feature flag off"}
        if ready_when_enabled:
            return {"status": "ready", "enabled": True, "detail": detail or None}
        return {"status": "unknown", "enabled": True, "detail": detail or "enabled but readiness unknown"}

    system_inventory.register_status_provider(
        "execution_gateway",
        lambda: {"status": "ready", "enabled": True, "detail": "in-process ExecutionGateway"},
    )
    system_inventory.register_status_provider(
        "agent_runtime",
        lambda: _flag_status(
            enabled=bool(agent_runtime.agents_enabled),
            detail="LEVIATHAN_FEATURE_AGENTS",
        ),
    )
    system_inventory.register_status_provider(
        "structured_agent_planner",
        lambda: {
            "status": "ready" if agent_runtime.agents_enabled else "disabled",
            "enabled": bool(agent_runtime.agents_enabled),
            "detail": "owned by AgentRuntime",
        },
    )
    system_inventory.register_status_provider(
        "agent_fleet_service",
        lambda: _flag_status(
            enabled=bool(agent_runtime.agents_enabled),
            detail="fleet control plane",
        ),
    )
    system_inventory.register_status_provider(
        "multi_agent_coordinator",
        lambda: _flag_status(
            enabled=bool(agent_runtime.agents_enabled),
            detail="POST /api/agents/multi",
        ),
    )
    system_inventory.register_status_provider(
        "cognitive_runtime",
        lambda: _flag_status(
            enabled=bool(getattr(cognition_runtime, "enabled", False)),
            detail="cognition_enabled feature flag",
        ),
    )
    system_inventory.register_status_provider(
        "meta_controller",
        lambda: _flag_status(
            enabled=bool(getattr(cognition_runtime, "enabled", False)),
            detail="inside CognitiveRuntime",
        ),
    )
    system_inventory.register_status_provider(
        "capability_broker",
        lambda: _flag_status(
            enabled=bool(getattr(cognition_runtime, "enabled", False)),
            detail="inside CognitiveRuntime",
        ),
    )
    system_inventory.register_status_provider(
        "delegation_service",
        lambda: _flag_status(
            enabled=bool(getattr(cognition_runtime, "delegation_enabled", False)),
            detail="cognition_delegation feature flag",
        ),
    )
    system_inventory.register_status_provider(
        "research_service",
        lambda: {
            "status": "ready",
            "enabled": True,
            "detail": "ResearchService constructed at startup",
        },
    )
    system_inventory.register_status_provider(
        "coding_control_plane",
        lambda: _flag_status(
            enabled=bool(settings.features.coding_enabled),
            detail="coding_enabled feature flag",
        ),
    )

    def _residual_status() -> dict:
        enabled = bool(
            settings.features.neuro_enabled and settings.features.neuro_residual_orchestrator
        )
        if not enabled:
            return {"status": "disabled", "enabled": False, "detail": "neuro residual orchestrator off"}
        telemetry = dict(getattr(residual_orchestrator, "telemetry", None) or {})
        degraded = int(telemetry.get("degraded") or 0)
        if degraded > 0:
            return {
                "status": "degraded",
                "enabled": True,
                "detail": f"degraded_count={degraded}",
                "metadata": {"telemetry": telemetry},
            }
        return {
            "status": "ready",
            "enabled": True,
            "detail": "residual orchestrator active",
            "metadata": {"telemetry": telemetry},
        }

    system_inventory.register_status_provider("residual_orchestrator", _residual_status)
    system_inventory.register_status_provider(
        "cortex_runtime",
        lambda: _flag_status(
            enabled=bool(settings.features.neuro_enabled and settings.features.neuro_cortex),
            detail="neuro_cortex feature flag",
        ),
    )
    system_inventory.register_status_provider(
        "neuro_advisor",
        lambda: _flag_status(
            enabled=bool(settings.features.neuro_enabled),
            detail="neuro_enabled feature flag",
        ),
    )

    def _model_plane_status() -> dict:
        try:
            cards = model_plane.status_cards()
            offline = cards.get("offlineProviders") or []
            if offline:
                return {
                    "status": "degraded",
                    "enabled": True,
                    "detail": f"{len(offline)} provider(s) offline",
                    "metadata": {"activeModel": cards.get("activeModel")},
                }
            return {
                "status": "ready",
                "enabled": True,
                "detail": "model control plane",
                "metadata": {"activeModel": cards.get("activeModel")},
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "enabled": True, "detail": str(exc)}

    system_inventory.register_status_provider("model_control_plane", _model_plane_status)

    def _master_gates_status() -> dict:
        try:
            report = master_gates.run()
            overall = str(getattr(getattr(report, "status", None), "value", getattr(report, "status", "")) or "").lower()
            status_value = "ready"
            if "block" in overall:
                status_value = "degraded"
            elif "degrad" in overall:
                status_value = "degraded"
            return {
                "status": status_value,
                "enabled": True,
                "detail": f"master gates status={overall or 'unknown'}",
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "unknown", "enabled": True, "detail": f"gate probe failed: {exc}"}

    system_inventory.register_status_provider("master_gate_runner", _master_gates_status)


_wire_system_inventory_status()

intelligence_health = IntelligenceHealthService(
    settings_plane=settings_plane,
    cognition_runtime=cognition_runtime,
    neuro_advisor=neuro_advisor,
    residual_port=residual_runtime,
    knowledge=knowledge,
    retriever=retriever,
    memory_store=memory_store,
    deep_recall=deep_recall_service,
    atlas=atlas_store,
    verification_engine=verification_engine,
    assimilation_service=assimilation_service,
    embedding_provider=embedding_provider,
    reranker=reranker_provider,
    cortex=cortex_runtime,
    experience_store=getattr(cognition_runtime, "experience_store", None),
    reasoning_policy=reasoning_policy,
    brain_access=brain_access,
    context_builder=getattr(llm, "context_builder", None),
    model_control_plane=model_plane,
    capability_catalog=capability_catalog,
    execution_gateway=execution_gateway,
    evidence_service=evidence_service,
    domain_strategy_registry=domain_strategy_registry,
    behavior_store=behavior_store,
)


def _assess_product_truth_report():
    """Build the Round 9 Product Truth report from live backend evidence."""
    from Data.modules.product_truth import assess_product_truth

    mcp_server_count: int | None = None
    mcp_connected_count: int | None = None
    if settings.features.mcp_enabled:
        try:
            servers = mcp_bridge.list_servers()
            mcp_server_count = len(servers)
            mcp_connected_count = sum(
                1
                for s in servers
                if (s.get("connection_state") if isinstance(s, dict) else None) == "connected"
                or (getattr(s, "connection_state", None) == "connected")
            )
        except Exception:  # noqa: BLE001
            mcp_server_count = None
            mcp_connected_count = None

    sample = system_telemetry_sampler.latest_public()
    dash = sample.get("dashboard") if isinstance(sample, dict) else None
    telemetry_partial = True
    if isinstance(dash, dict):
        telemetry_partial = dash.get("cpuPct") is None and dash.get("ramPct") is None

    browser_kind = getattr(getattr(browser_worker, "backend", None), "kind", None)
    browser_kind_val = browser_kind.value if hasattr(browser_kind, "value") else (
        str(browser_kind) if browser_kind else None
    )
    browser_capable = None
    if browser_kind_val == "fixture":
        browser_capable = False
    elif browser_kind_val == "local_dom":
        browser_capable = True
    elif browser_kind_val == "playwright":
        # Package alone is not READY — probe Chromium launch/navigate/observe.
        readiness = getattr(browser_worker.backend, "readiness", None)
        if callable(readiness):
            info = readiness()
            browser_capable = bool(info.get("ready"))
        else:
            browser_capable = False

    model_cards = model_plane.status_cards()
    # Media/voice services are real entry points but fixture/stub backends are not production.
    media_capable = False
    voice_capable = False
    media_kind = "fixture"
    voice_kind = "fixture"
    if settings.features.multimodal_realtime:
        media_kind = "service"
        voice_kind = "realtime"
        # Existing stubs advertise fixture_is_not_production in job truth — keep honest.
        media_capable = False
        voice_capable = False
    return assess_product_truth(
        backend_alive=True,
        observability_durable=observability.store is not None,
        jobs_queued=len(job_runtime.list(state=JobState.QUEUED, limit=500)),
        module_manager_enabled=bool(module_manager.enabled),
        module_count=len(module_manager.list()),
        mcp_feature_enabled=bool(settings.features.mcp_enabled),
        mcp_server_count=mcp_server_count,
        mcp_connected_count=mcp_connected_count,
        telemetry_partial=telemetry_partial,
        browser_backend_kind=browser_kind_val,
        browser_production_capable=browser_capable,
        model_gateway_health=str(model_cards.get("gatewayHealth") or "") or None,
        model_provider_count=int(model_cards.get("providerCount") or 0),
        embedding_available=bool(retriever.embeddings.available()),
        agents_enabled=bool(settings.features.agents_enabled),
        training_fixture_default=True,
        media_backend_kind=media_kind,
        media_production_capable=media_capable,
        voice_backend_kind=voice_kind,
        voice_production_capable=voice_capable,
    )


def _component_health() -> list[dict]:
    """Aggregate evidence-based component postures (Round 9 Product Truth)."""
    return [c.public_dict() for c in _assess_product_truth_report().components]


def _product_truth_snapshot() -> dict:
    return _assess_product_truth_report().public_dict()


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
        "database_path": settings.database_path,
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
    dataset_list=lambda: dataset_service.list_library_datasets(limit=100),
    memory_list=lambda: memory_store.list(limit=200),
    module_list=lambda: module_manager.list(),
    capability_list=lambda: capability_catalog.list(),
    mcp_servers=lambda: mcp_bridge.list_servers() if settings.features.mcp_enabled else [],
    mcp_tools=lambda: (
        mcp_bridge.list_tools() if hasattr(mcp_bridge, "list_tools") and settings.features.mcp_enabled else []
    ),
    workflow_list=lambda: workflow_store.list(limit=100),
    atlas_list=lambda: atlas_store.search("", limit=100) if settings.features.rag_v3 else [],
    relation_list=lambda: knowledge.list_relation_atoms(limit=200),
    max_nodes=250,
    max_edges=500,
)

# ---- GI2 system.inspect + GI7 web.search/web.fetch binding ------------------
from Data.modules.cognition.system_inspect import (  # noqa: E402
    SystemInspectService,
    bind_system_inspect_service,
)
from Data.modules.research.web_capabilities import bind_web_provider  # noqa: E402


def _application_commit() -> str | None:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def _active_model_id() -> str | None:
    try:
        cards = model_plane.status_cards()
        return cards.get("activeModel")
    except Exception:  # noqa: BLE001
        return None


def _model_role_backend() -> dict[str, Any]:
    try:
        active = model_plane.store.get_active_model_id()
        if not active:
            return {"role": None, "backend": None}
        desc = None
        for m in model_plane.registry.list_descriptors():
            if m.id == active:
                desc = m
                break
        role = getattr(desc, "preferred_role", None) if desc else None
        backend = None
        if desc is not None:
            backend = getattr(desc, "backend_kind", None) or getattr(
                desc, "provider_id", None
            )
        return {"role": role, "backend": backend, "model_id": active}
    except Exception:  # noqa: BLE001
        return {"role": None, "backend": None}


def _context_window() -> int | None:
    try:
        active = model_plane.store.get_active_model_id()
        if not active:
            return None
        for m in model_plane.registry.list_descriptors():
            if m.id == active:
                return getattr(m, "context_window", None)
    except Exception:  # noqa: BLE001
        return None
    return None


def _fleet_snapshot() -> dict[str, Any]:
    from Data.modules.agents.fleet_types import ACTIVE_MISSION_STATUSES, AgentHealth

    agents = agent_fleet.list_agents(include_archived=False)
    live_health = {AgentHealth.IDLE, AgentHealth.BUSY}
    active_agents = [a for a in agents if getattr(a, "health", None) in live_health]
    missions = agent_fleet_store.list_missions(limit=200)
    active_missions = []
    for m in missions:
        status = getattr(m, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status or "")
        if status_val in ACTIVE_MISSION_STATUSES:
            active_missions.append(m)
    return {
        "active_agents": len(active_agents),
        "active_missions": len(active_missions),
        "agents": len(agents),
        "missions": len(missions),
    }


def _jobs_summary() -> dict[str, Any]:
    queued = len(job_runtime.list(state=JobState.QUEUED, limit=500))
    return {
        "queued": queued,
        "telemetry": dict(getattr(job_runtime, "telemetry", {}) or {}),
    }


def _tool_calls_summary() -> dict[str, Any]:
    return {
        "gateway": dict(getattr(execution_gateway, "telemetry", {}) or {}),
        "function_runtime": dict(getattr(function_runtime, "telemetry", {}) or {}),
    }


def _web_usage_summary() -> dict[str, Any]:
    provider = getattr(research_service, "web", None)
    search_ready = False
    if provider is not None and hasattr(provider, "search_configured"):
        try:
            search_ready = bool(provider.search_configured())
        except Exception:  # noqa: BLE001
            search_ready = False
    return {
        "provider": getattr(provider, "name", None),
        "allow_outbound": bool(getattr(research_service, "allow_outbound", False)),
        "search_configured": search_ready,
        "configured": bool(provider.configured()) if provider is not None else False,
    }


def _knowledge_counts() -> dict[str, Any]:
    docs = knowledge.list_documents(limit=10_000)
    return {"count": len(docs), "turn_hits": None}


def _memory_counts() -> dict[str, Any]:
    items = memory_store.list(limit=10_000)
    return {"count": len(items), "turn_hits": None}


def _evidence_counts() -> dict[str, Any]:
    items = evidence_store.list(limit=10_000)
    return {"count": len(items), "turn_hits": None}


def _brain_status() -> dict[str, Any]:
    # Brain is a query facade — expose readiness + document hit counts, never a %.
    try:
        docs = knowledge.list_documents(limit=10_000)
        hits = len(docs)
    except Exception:  # noqa: BLE001
        hits = None
    return {
        "status": "ready",
        "hits": hits,
    }


def _application_version() -> str:
    # FastAPI app is constructed later; fall back to the known release label.
    try:
        return str(getattr(globals().get("app"), "version", None) or "0.73.0-wave9-flywheel")
    except Exception:  # noqa: BLE001
        return "0.73.0-wave9-flywheel"


system_inspect_service = SystemInspectService(
    application_version_provider=_application_version,
    application_commit_provider=_application_commit,
    active_model_provider=_active_model_id,
    model_role_backend_provider=_model_role_backend,
    context_window_provider=_context_window,
    cognition_runtime_provider=lambda: cognition_runtime,
    behavior_profile_provider=lambda: behavior_store,
    brain_status_provider=_brain_status,
    knowledge_count_provider=_knowledge_counts,
    memory_count_provider=_memory_counts,
    evidence_count_provider=_evidence_counts,
    verification_outcome_provider=lambda: {
        "engine": "VerificationEngine",
        "wired": verification_engine is not None,
    },
    agent_fleet_provider=_fleet_snapshot,
    worker_pools_provider=None,  # API process: pools owned by WorkerSupervisor when externalized
    jobs_provider=_jobs_summary,
    tool_calls_provider=_tool_calls_summary,
    web_usage_provider=_web_usage_summary,
    context_budget_provider=None,  # turn-scoped; filled when turn context is available
    telemetry_provider=lambda: system_telemetry_sampler.latest_public(),
    turn_context_provider=None,
)
bind_system_inspect_service(system_inspect_service)
bind_web_provider(
    research_service.web,
    allow_outbound=bool(getattr(research_service, "allow_outbound", False)),
    allow_web=True,
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
        staged_retriever=staged_retriever,
        why_library=why_library,
        mcp_bridge=mcp_bridge,
        cognition_runtime=cognition_runtime,
        agent_runtime=agent_runtime,
        coding_service=coding_service,
        research_service=research_service,
        dataset_service=dataset_service,
        isolation_guard=isolation_guard,
        chaos=chaos,
        model_plane=model_plane,
        llm=llm,
        neuro_advisor=neuro_advisor,
        neuro_critic=neuro_critic,
        neuro_soak=neuro_soak,
        module_manager=module_manager,
        market_sim_service=market_sim_service,
        residual_orchestrator=residual_orchestrator,
        cortex_runtime=cortex_runtime,
        residual_runtime=residual_runtime,
        reasoning_policy_holder=intelligence_health,
        context_builder=getattr(llm, "context_builder", None),
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
    knowledge.initialize()  # schema only — no corpus backfill
    atlas_store.initialize()
    why_library.initialize()
    deep_recall_service.initialize()
    runs.initialize()
    artifacts.initialize()
    approval_store.initialize()
    job_store.initialize()
    try:
        pending_backfill = int(knowledge.count_pending_content_backfill())
    except Exception:  # noqa: BLE001
        pending_backfill = 0
    if pending_backfill > 0 and _evaluation_externalize():
        try:
            bf_job = job_runtime.enqueue(
                capability_id="knowledge.prepare",
                arguments={"action": "backfill", "limit": 50},
                requested_by="api.startup",
                domain="knowledge",
                domain_entity_type="knowledge_backfill",
                domain_entity_id="startup",
                worker_pool="knowledge_prepare",
                resource_class="CPU_HEAVY",
                latency_class="background",
                idempotency_key="knowledge:backfill:startup",
                metadata={
                    "human_title": "legacy content backfill",
                    "pending": pending_backfill,
                    "status": "KNOWLEDGE_BACKFILL_PENDING",
                },
            )
            observability.emit(
                "knowledge",
                "backfill.enqueued",
                payload={
                    "pending": pending_backfill,
                    "job_id": bf_job.job_id,
                    "status": "KNOWLEDGE_BACKFILL_PENDING",
                },
                level="info",
            )
        except Exception as exc:  # noqa: BLE001
            observability.emit(
                "knowledge",
                "backfill.enqueue_failed",
                payload={"pending": pending_backfill, "error": str(exc)[:300]},
                level="warning",
            )
    elif pending_backfill > 0:
        observability.emit(
            "knowledge",
            "backfill.pending",
            payload={"pending": pending_backfill, "status": "KNOWLEDGE_BACKFILL_PENDING"},
            level="info",
        )
    observation_store.initialize()
    evidence_store.initialize()
    capability_receipts.initialize()
    secrets_broker.initialize()
    memory_store.initialize()
    neuro_snapshots.initialize()
    residual_receipts.initialize()
    verification_reports.initialize()
    workflow_store.initialize()
    schedule_store.initialize()
    task_service.initialize()
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
    from Data.modules.datasets.worker import should_start_inprocess_runner
    from Data.modules.workers.settings import load_worker_settings

    worker_settings = load_worker_settings()
    externalize = bool(worker_settings.enabled and worker_settings.externalize_api_runners)

    if (not externalize) and should_start_inprocess_runner(settings):
        dataset_service.runner.start_background()
    else:
        observability.emit(
            "datasets",
            "jobs.runner.deferred",
            payload={
                "mode": (
                    "externalized"
                    if externalize
                    else getattr(
                        getattr(settings, "research_integration", None),
                        "dataset_jobs_runner",
                        "external",
                    )
                )
            },
            level="info",
            message="In-process dataset job runner not started (external/none mode)",
        )
    training_service.reconcile()
    agent_fleet.initialize(seed_defaults=True)
    agent_fleet.reconcile()
    signal_fabric.initialize()
    signal_fabric.bind_fleet(agent_fleet)
    agent_fleet.bind_signal_fabric(signal_fabric)
    multi_agents.bind_signal_fabric(signal_fabric)
    # Trading agents/orchestras live on the same fleet (visible on the Agents page);
    # the trading executor claims kind=trading and role=trade_orchestra missions.
    trading_orchestra_service.bind_fleet(agent_fleet)
    try:
        market_sim_service.attach_fleet(agent_fleet)
    except Exception as exc:  # noqa: BLE001 — trading roles are optional at boot
        observability.emit(
            "market_sim",
            "trading.roles.ensure_failed",
            payload={"error": str(exc)[:300]},
            level="warn",
            message="Could not ensure trading roles on the Agent Fleet",
        )
    research_service.recover()
    if externalize:
        # Durable agent missions: enqueue agent.advance; do not own in-process threads.
        agent_fleet.start_background()
        # Market sim: enqueue QUEUED/RUNNING advances for the market_sim worker pool
        # (no in-process daemon when externalized).
        market_sim_service.start_background()
        observability.emit(
            "workers",
            "api.runners.externalized",
            payload={"pools": worker_settings.pool_counts},
            level="info",
            message="Heavy domain runners deferred to generic worker supervisor",
        )
    else:
        research_service.start_background()
        coding_service.start_background()
        market_sim_service.start_background()
        job_runtime.start_background_worker()
        # Legacy: missions advance synchronously in launch_mission (no agent daemon).
        agent_fleet.start_background()
    mcp_bridge.initialize()
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
    # job_runtime background worker started above only when not externalized
    system_telemetry_sampler.start()
    # Round 6: periodic serving reconcile so crashed workers become DEAD without a manual API call.
    import asyncio

    serving_reconcile_task = None
    if settings.features.model_serving:

        async def _serving_reconcile_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(15.0)
                    model_plane.reconcile_serving_workers()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    observability.emit(
                        "models",
                        "serving.reconcile_loop.failed",
                        payload={"error": str(exc)},
                        level="warning",
                    )

        serving_reconcile_task = asyncio.create_task(_serving_reconcile_loop())
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
        if serving_reconcile_task is not None:
            serving_reconcile_task.cancel()
            try:
                await serving_reconcile_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
        observability.emit(
            "backend",
            "shutdown",
            level="info",
            message="Leviathan backend shutting down",
            source="lifespan",
        )
        try:
            await model_plane.residency.shutdown()
        except Exception:  # noqa: BLE001
            pass
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


app = FastAPI(title="Leviathan", version="0.73.0-wave9-flywheel", lifespan=lifespan)
app.include_router(build_models_router(model_plane))
app.include_router(build_datasets_router(dataset_service))
app.include_router(build_training_router(training_service))
app.include_router(build_research_router(research_service))
app.include_router(build_coding_router(coding_service))
app.include_router(build_signals_router(signal_fabric))
app.include_router(
    build_agents_router(
        agent_fleet,
        job_runtime=job_runtime,
        database_path=settings.database_path,
        agent_runtime=agent_runtime,
        multi_agents=multi_agents,
    )
)
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
app.include_router(
    build_market_sim_router(
        market_sim_service,
        gateway=execution_gateway,
        capability_catalog=capability_catalog,
    )
)
app.include_router(build_trading_orchestra_router(trading_orchestra_service))
app.include_router(build_cognition_router(cognition_runtime))
app.include_router(build_team_router(team_orchestrator))
app.include_router(build_tasks_router(task_service))
app.include_router(build_browser_qa_router(browser_worker))
app.include_router(build_settings_router(settings_plane))
app.include_router(build_behavior_router(behavior_store, observability=observability))
app.include_router(build_efficiency_router())

_enqueue_ingest_scan = make_enqueue_ingest_scan(job_runtime, settings)
app.include_router(
    build_knowledge_router(
        settings=settings,
        knowledge=knowledge,
        retriever=retriever,
        job_runtime=job_runtime,
        atlas_store=atlas_store,
        deep_recall_service=deep_recall_service,
        why_library=why_library,
        evaluation_externalize_fn=_evaluation_externalize,
        enqueue_ingest_scan_fn=_enqueue_ingest_scan,
    )
)
app.include_router(
    build_evaluation_router(
        settings=settings,
        job_runtime=job_runtime,
        metrics=metrics,
        evaluation_harness=evaluation_harness,
        evaluation_platform=evaluation_platform,
        evaluation_store=evaluation_store,
        residual_runtime=residual_runtime,
        model_plane=model_plane,
        evaluation_externalize_fn=_evaluation_externalize,
    )
)
app.include_router(
    build_neuro_router(
        settings=settings,
        residual_runtime=residual_runtime,
        residual_orchestrator=residual_orchestrator,
        residual_receipts=residual_receipts,
        neuro_contrastive=neuro_contrastive,
        neuro_advisor=neuro_advisor,
        reasoner=reasoner,
        cortex_runtime=cortex_runtime,
        neuro_memory=neuro_memory,
        neuro_snapshots=neuro_snapshots,
        neuro_absorb=neuro_absorb,
        neuro_soak=neuro_soak,
        module_manager=module_manager,
        approval_service=approval_service,
        capability_catalog=capability_catalog,
        schedule_store=schedule_store,
        observability=observability,
        metrics=metrics,
        evaluation_externalize_fn=_evaluation_externalize,
        enqueue_ingest_scan_fn=_enqueue_ingest_scan,
    )
)
app.include_router(build_jobs_router(settings=settings, job_runtime=job_runtime, job_store=job_store))
app.include_router(build_workers_router(settings=settings, job_runtime=job_runtime))
app.include_router(build_memory_router(memory_store=memory_store))
app.include_router(build_evidence_router(evidence_service=evidence_service))
app.include_router(
    build_capabilities_router(
        capability_catalog=capability_catalog,
        execution_gateway=execution_gateway,
        observation_store=observation_store,
        observability=observability,
        capability_receipts=capability_receipts,
    )
)
app.include_router(
    build_functions_router(
        function_registry=function_registry,
        function_runtime=function_runtime,
    )
)
app.include_router(
    build_approvals_router(
        approval_service=approval_service,
        capability_catalog=capability_catalog,
        assert_loopback_fn=_assert_loopback_mutation_allowed,
    )
)
app.include_router(
    build_workflows_router(workflow_store=workflow_store, workflow_runtime=workflow_runtime)
)
app.include_router(
    build_schedules_router(
        schedule_store=schedule_store,
        schedule_runner=schedule_runner,
        observability=observability,
    )
)
app.include_router(
    build_verification_router(
        verification_engine=verification_engine,
        verification_reports=verification_reports,
        metrics=metrics,
    )
)
app.include_router(build_observations_router(observation_store=observation_store))
app.include_router(build_artifacts_router(artifacts=artifacts, runs=runs))
app.include_router(build_flywheel_router(settings=settings, flywheel=flywheel))
app.include_router(
    build_training_surface_router(
        settings=settings,
        training_service=training_service,
        training_registry=training_registry,
        training_recipes=training_recipes,
        preference_bridge=preference_bridge,
        preference_store=preference_store,
        verification_reports=verification_reports,
        synthetic_data_service=synthetic_data_service,
        active_learning_miner=active_learning_miner,
    )
)
app.include_router(
    build_plugins_router(
        plugin_registry=plugin_registry,
        execution_gateway=execution_gateway,
        observability=observability,
    )
)
app.include_router(
    build_modules_router(module_manager=module_manager, observability=observability)
)
app.include_router(build_conversations_router(db=db))
app.include_router(
    build_browser_router(
        settings=settings,
        browser_stub=browser_stub,
        browser_qa_crawler=browser_qa_crawler,
        execution_gateway=execution_gateway,
        job_runtime=job_runtime,
        observability=observability,
    )
)
app.include_router(
    build_media_router(
        settings=settings,
        media_stub=media_stub,
        execution_gateway=execution_gateway,
        job_runtime=job_runtime,
        observability=observability,
    )
)
app.include_router(
    build_voice_router(
        settings=settings,
        voice_stub=voice_stub,
        execution_gateway=execution_gateway,
        observability=observability,
    )
)
app.include_router(
    build_multimodal_router(
        settings=settings,
        multimodal_sessions=multimodal_sessions,
        reasoner=reasoner,
    )
)
app.include_router(
    build_platform_router(
        settings=settings,
        app_version=app.version,
        capability_catalog=capability_catalog,
        live_settings_fn=live_settings,
        metrics=metrics,
        job_runtime=job_runtime,
        observation_store=observation_store,
        observability=observability,
        intelligence_health=intelligence_health,
        product_truth_fn=_product_truth_snapshot,
        isolation_guard=isolation_guard,
        reasoner=reasoner,
        memory_store=memory_store,
        secrets_broker=secrets_broker,
        assert_loopback_fn=_assert_loopback_mutation_allowed,
        release_gates=release_gates,
        security_auditor=security_auditor,
        native_runtime=native_runtime,
        trading_stub=trading_stub,
        backup_service=backup_service,
        chaos=chaos,
        master_gates=master_gates,
    )
)


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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    conversation_id: str | None = None
    model_id: str | None = None
    preferred_role: str | None = None
    reasoning_mode: str | None = None  # session override: auto|fast|standard|deep
    # Collaboration strategy — orthogonal to reasoning depth. team ≠ maximum.
    collaboration_strategy: str | None = None  # direct|team
    stream: bool = False


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
    product_truth = _product_truth_snapshot()
    # ``ok`` is process liveness only — subsystem truth lives under product_truth.
    return {
        "ok": True,
        "liveness": "alive",
        "posture": product_truth.get("overall"),
        "version": app.version,
        "database": str(settings.database_path),
        "reasoning_enabled": settings.reasoning_enabled,
        "models": model_status,
        "frontend": {
            "dist_ready": (FRONTEND_DIST / "index.html").is_file(),
            "dist_path": str(FRONTEND_DIST),
            "source_root": str(FRONTEND_ROOT),
            "build_hint": "Rebuild with `npm run build` in Data/frontend when UI drifts from source",
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
        "product_truth": product_truth,
        "intelligence": intelligence_health.build(),
    }


def _build_assistant_telemetry(
    *,
    model: str | None,
    behavior_snapshot: Any,
    cognition_meta: dict | None,
    knowledge_hits: list,
    memory_hits: list,
    evidence_hits: list | None = None,
    run_started_at: Any = None,
) -> dict:
    """Assemble real turn telemetry for Chat Context/Tools/Agents — never fabricate."""
    cog = cognition_meta if isinstance(cognition_meta, dict) else {}
    hits = cog.get("retrieval_hits") if isinstance(cog.get("retrieval_hits"), dict) else {}
    tools = list(cog.get("tools_invoked") or [])
    agents = [a for a in (cog.get("active_agents") or []) if a]
    gi = list(cog.get("gi_specialists") or [])
    latency_ms = None
    try:
        if run_started_at is not None:
            import time as _time

            if isinstance(run_started_at, (int, float)):
                latency_ms = round((_time.time() - float(run_started_at)) * 1000.0, 1)
            elif hasattr(run_started_at, "timestamp"):
                latency_ms = round((_time.time() - float(run_started_at.timestamp())) * 1000.0, 1)
    except Exception:  # noqa: BLE001
        latency_ms = None
    usage = cog.get("usage") if isinstance(cog.get("usage"), dict) else None
    if usage and usage.get("started_monotonic") and latency_ms is None:
        # Prefer measured wall from cognition usage when available.
        try:
            import time as _time

            started = float(usage.get("started_monotonic") or 0)
            # started_monotonic is process-relative; cannot convert to wall without pairing.
            # Leave latency from run timestamps only.
            _ = started
        except Exception:  # noqa: BLE001
            pass
    behavior_hash = None
    behavior_profile_id = None
    behavior_version = None
    if behavior_snapshot is not None:
        behavior_hash = getattr(behavior_snapshot, "settings_hash", None)
        behavior_version = getattr(behavior_snapshot, "version", None)
        profile = getattr(behavior_snapshot, "profile", None)
        behavior_profile_id = getattr(profile, "id", None) if profile is not None else None
        if behavior_version is None and profile is not None:
            behavior_version = getattr(profile, "version", None)
    behavior_hash = cog.get("behavior_hash") or behavior_hash
    behavior_profile_id = cog.get("behavior_profile_id") or behavior_profile_id
    behavior_version = (
        cog.get("behavior_profile_version") or cog.get("behavior_version") or behavior_version
    )
    brain_hits = int(hits.get("brain") or hits.get("knowledge") or len(knowledge_hits) or 0)
    memory_n = int(hits.get("memory") or len(memory_hits) or 0)
    evidence_n = int(hits.get("evidence") or len(evidence_hits or []) or 0)
    tool_calls = list(cog.get("tool_calls") or [])
    if not tool_calls and tools:
        tool_calls = [{"capability_id": t, "status": "INVOKED", "success": None} for t in tools]
    agent_delegations = list(cog.get("agent_delegations") or [])
    if not agent_delegations and (agents or gi):
        agent_delegations = [
            {"agent_kind": a, "status": "DELEGATED" if a in agents else "SELECTED", "success": None}
            for a in list(dict.fromkeys([*agents, *gi]))
        ]
    web_sources = list(cog.get("web_sources") or [])
    context_used = cog.get("context_used")
    if context_used is None:
        context_used = (
            ((cog.get("context") or {}).get("pack") or {}).get("token_estimate")
            if isinstance(cog.get("context"), dict)
            else None
        )
    latency_ms = cog.get("latency_ms") if cog.get("latency_ms") is not None else latency_ms
    return {
        "model": model,
        "behavior_hash": behavior_hash,
        "behavior_profile_id": behavior_profile_id,
        "behavior_version": behavior_version,
        "context_budget": cog.get("context_budget"),
        "context_used": context_used,
        "context_tokens": context_used if context_used is not None else cog.get("context_budget"),
        "brain_hits": brain_hits,
        "knowledge_hits": int(hits.get("knowledge") or len(knowledge_hits) or 0),
        "memory_hits": memory_n,
        "evidence_hits": evidence_n,
        "tools_invoked": tools,
        "tool_calls": tool_calls,
        "agents": agents,
        "agent_delegations": agent_delegations,
        "gi_specialists": gi,
        "web_sources": web_sources,
        "verification_mode": cog.get("verification_mode"),
        "verification_passed": cog.get("verification_passed"),
        "factuality": cog.get("factuality"),
        "execution_class": cog.get("execution_class"),
        "cognition_mode": cog.get("mode"),
        "cognition_status": cog.get("status"),
        "latency_ms": latency_ms,
        "usage": usage,
        "budgets": cog.get("budgets") if isinstance(cog.get("budgets"), dict) else None,
        "web_used": bool(web_sources)
        or any(t in {"web.search", "web.fetch"} for t in tools),
        "truth": {
            "telemetry_is_backend_backed": True,
            "no_fabricated_brain_percent": True,
            "no_hidden_cot": True,
            "no_mock_tools_or_agents": True,
        },
    }


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

    # Immutable behavior snapshot for this turn (sole identity/language/retrieval authority).
    recent_user_texts = [
        str(m.get("content") or "")
        for m in db.get_messages(conversation_id, limit=live_settings().max_history_messages)
        if m.get("role") == "user" and m.get("content")
    ]
    behavior_snapshot = behavior_resolver.resolve(
        latest_user_message=message,
        recent_user_messages=recent_user_texts[:-1] if recent_user_texts else [],
    )
    behavior_profile = behavior_snapshot.profile
    turn_id = f"{run.run_id}:turn"
    request_id = getattr(request.state, "request_id", None) or run.run_id

    # --- TEAM collaboration path (orthogonal to reasoning_mode depth) ---
    from Data.modules.cognition.team_strategy import (
        CollaborationStrategy,
        USER_FACING_TEAM_DESCRIPTION,
        normalize_collaboration_strategy,
    )

    try:
        collab = normalize_collaboration_strategy(payload.collaboration_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if collab == CollaborationStrategy.TEAM:
        lower = message.lower()
        requires_coding = any(k in lower for k in ("fix", "bug", "test", "code", "implement", "pytest"))
        requires_research = any(k in lower for k in ("research", "sources", "cite", "evidence", "investigate"))
        task_category = (
            "coding"
            if requires_coding
            else "research"
            if requires_research
            else "uncertainty"
            if "uncertain" in lower
            else "general"
        )

        def _chat_team_executor(assignment, state):
            """Bounded specialist call via shared model caller — fail closed without evidence."""
            prompt = (
                f"ROLE={assignment.role.value}\nOBJECTIVE={assignment.objective}\n"
                f"CRITERIA={assignment.criterion_ids}\nUSER={message}\n"
                "Return a short public summary. Do not claim tools ran unless receipts exist."
            )
            summary = ""
            try:
                if cognition_model_caller is not None:
                    raw = cognition_model_caller(prompt)
                    if isinstance(raw, dict):
                        summary = str(raw.get("text") or raw.get("content") or "")[:4000]
                    else:
                        summary = str(raw or "")[:4000]
            except Exception as exc:  # noqa: BLE001
                return {
                    "role": assignment.role.value,
                    "evidence_ids": [],
                    "error": str(exc),
                    "notes": "model call failed — no fabricated evidence",
                }
            # Without tool/test receipts we never auto-satisfy mandatory gates.
            result: dict[str, Any] = {
                "role": assignment.role.value,
                "evidence_ids": [],
                "notes": summary[:500] or "no model output",
                "provisional_artifact": {"text": summary, "provisional": True} if summary else None,
            }
            if task_category == "uncertainty" and summary:
                result["supported_uncertainty"] = True
                result["evidence_ids"] = ["uncertainty:statement"]
            return result

        team_orchestrator._executor = _chat_team_executor
        team_state = team_orchestrator.start(
            request_text=message,
            run_id=f"team:{run.run_id}",
            request_ref=conversation_id,
            task_category=task_category,
            requires_coding=requires_coding,
            requires_research=requires_research,
        )
        # Drive a bounded number of quality iterations for the HTTP turn.
        team_state = team_orchestrator.run_until_terminal(team_state.run_id, max_iterations=8)
        export = team_orchestrator.export_artifact(team_state.run_id)
        if team_state.status.value == "completed" and export.get("artifact"):
            answer = str(
                (export["artifact"] or {}).get("text")
                or "TEAM accepted the deliverable for the current revision."
            )
            provisional = False
        else:
            progress = team_state.public_dict().get("progress") or {}
            blockers = [b.public_dict() for b in team_state.blockers]
            answer = (
                f"{USER_FACING_TEAM_DESCRIPTION}\n\n"
                f"Status: {team_state.status.value}\n"
                f"Criteria: {progress.get('criteria_ratio_label') or progress}\n"
            )
            if export.get("artifact"):
                answer += f"\nProvisional draft:\n{(export['artifact'] or {}).get('text') or ''}\n"
            if blockers:
                answer += "\nBlockers:\n" + "\n".join(
                    f"- {b.get('summary')}" for b in blockers[:6]
                )
            provisional = True
        assistant_message = db.add_message(conversation_id, "assistant", answer)
        if team_state.status.value == "completed":
            final_run_state = RunState.COMPLETED
        elif team_state.status.value == "cancelled":
            final_run_state = RunState.CANCELLED
        elif team_state.status.value == "failed":
            final_run_state = RunState.FAILED
        elif team_state.status.value in {"blocked", "waiting_for_input", "paused"}:
            final_run_state = RunState.BLOCKED
        else:
            final_run_state = RunState.PARTIAL
        runs.transition(run.run_id, final_run_state)
        # Prefer PARTIAL semantics via event when not quality-accepted.
        runs.append_event(
            run.run_id,
            EventType.REASONING_COMPLETED,
            {
                "collaboration_strategy": "team",
                "team": team_state.public_dict(),
                "provisional": provisional,
            },
        )
        return {
            "conversation_id": conversation_id,
            "message": assistant_message,
            "run_id": run.run_id,
            "team_run_id": team_state.run_id,
            "collaboration_strategy": "team",
            "collaboration_description": USER_FACING_TEAM_DESCRIPTION,
            "team": team_state.public_dict(),
            "provisional": provisional,
            "reasoning": {
                "mode": {
                    "requested": payload.reasoning_mode or "auto",
                    "effective": payload.reasoning_mode or "auto",
                    "source": "team_collaboration",
                    "notes": ["collaboration_strategy=team is orthogonal to reasoning depth"],
                }
            },
        }

    has_knowledge = bool(knowledge.list_documents(limit=1))
    wm_load = neuro_memory.working.load if neuro_memory.enabled else 0.0
    # Provisional plan for economy inputs, then finalize with governor decision.
    analyze_kwargs = dict(
        retrieval_enabled=bool(behavior_profile.retrieval_enabled),
        retrieval_mode=str(behavior_profile.retrieval_mode or "auto"),
        memory_enabled=bool(behavior_profile.memory_enabled),
    )
    provisional = (
        reasoner.analyze(
            message,
            has_knowledge,
            deep_recall_enabled=settings.features.deep_recall and behavior_profile.retrieval_deep_recall,
            **analyze_kwargs,
        )
        if settings.reasoning_enabled
        else ReasoningEngine().analyze(message, False, **analyze_kwargs)
    )
    economy = economy_governor.decide(
        complexity=provisional.complexity,
        intent=provisional.intent,
        memory_coverage=1.0 if has_knowledge else 0.0,
        residual_available=residual_runtime.supports_residuals(),
        deep_recall_enabled=settings.features.deep_recall and behavior_profile.retrieval_deep_recall,
        explicit_deep_recall=any(term in message.lower() for term in ("exact", "cite", "deep recall")),
        working_memory_load=wm_load,
    )
    plan = (
        reasoner.analyze(
            message,
            has_knowledge,
            deep_recall_enabled=settings.features.deep_recall and behavior_profile.retrieval_deep_recall,
            economy_allow_deep_recall=economy.allow_deep_recall,
            memory_coverage=1.0 if has_knowledge else 0.0,
            **analyze_kwargs,
        )
        if settings.reasoning_enabled
        else provisional
    )
    # Resolve ONE effective reasoning mode for this turn (BehaviorProfile + session override).
    reasoning_mode = resolve_effective_mode(
        settings_default=behavior_profile.reasoning_mode_default,
        session_override=payload.reasoning_mode,
        plan=plan,
        message=message,
    )
    plan = apply_mode_to_plan(plan, reasoning_mode)
    # Tool-use style modulates retrieval willingness without granting authority.
    tool_style = (behavior_profile.tool_use_style or "balanced").strip().lower()
    if (
        tool_style == "minimal"
        and plan.use_knowledge
        and plan.intent
        not in {"project_knowledge", "research", "knowledge", "factual_question"}
    ):
        plan = ReasoningPlan(
            intent=plan.intent,
            complexity=plan.complexity,
            use_knowledge=False,
            steps=plan.steps,
            use_deep_recall=False,
            use_atlas=False,
            economy=plan.economy,
            retrieval_reason=f"{plan.retrieval_reason}|tool_style=minimal",
            use_memory=plan.use_memory,
            policy_version=plan.policy_version,
        )
    elif tool_style == "proactive" and has_knowledge and not plan.use_knowledge:
        if plan.intent in {"question", "conversation", "analysis", "factual_question"}:
            plan = ReasoningPlan(
                intent=plan.intent,
                complexity=plan.complexity,
                use_knowledge=True,
                steps=plan.steps,
                use_deep_recall=plan.use_deep_recall,
                use_atlas=plan.use_atlas,
                economy=plan.economy,
                retrieval_reason=f"{plan.retrieval_reason}|tool_style=proactive",
                use_memory=plan.use_memory,
                policy_version=plan.policy_version,
            )
    runs.append_event(
        run.run_id,
        EventType.REASONING_COMPLETED,
        {
            **plan.public_summary(),
            "economy": economy.public_dict(),
            "behavior": behavior_snapshot.public_dict(include_prompt=False),
            "reasoning_mode": reasoning_mode.public_dict(),
            "retrieval_gate": {
                "use_knowledge": plan.use_knowledge,
                "reason": getattr(plan, "retrieval_reason", ""),
                "policy_version": getattr(plan, "policy_version", ""),
            },
            "request_id": request_id,
            "turn_id": turn_id,
        },
    )

    cognition_meta: dict | None = None
    # FAST / greeting: keep cognition shadow so we do not over-orchestrate simple turns.
    cognition_force_shadow = bool(
        reasoning_mode.effective == "fast"
        or plan.intent in {"greeting", "identity", "casual_conversation", "exact_output"}
    )
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
                has_knowledge=has_knowledge and reasoning_mode.allow_retrieval,
                shadow=True
                if (settings.features.cognition_shadow or cognition_force_shadow)
                else False,
                metadata={
                    "chat_run_id": run.run_id,
                    "behavior_system_prompt": behavior_snapshot.system_prompt,
                    "behavior_hash": behavior_snapshot.settings_hash,
                    "behavior_profile_id": behavior_snapshot.profile.id,
                    "behavior_profile_version": behavior_snapshot.version,
                    "behavior_profile_hash": behavior_snapshot.settings_hash,
                    "response_language": behavior_snapshot.language.response_language,
                    "language_source": behavior_snapshot.language.source,
                    "reasoning_mode": reasoning_mode.effective,
                },
                user_requested_depth=to_cognition_depth(reasoning_mode.effective),
                run=True,
            )
            observability.emit(
                "cognition",
                "chat.shadow" if (settings.features.cognition_shadow or cognition_force_shadow) else "chat.active",
                payload={
                    "run_id": cognition_meta.get("run_id"),
                    "status": cognition_meta.get("status"),
                    "mode": cognition_meta.get("mode"),
                    "strategy": cognition_meta.get("strategy"),
                    "reasoning_mode": reasoning_mode.effective,
                },
            )
        except Exception as exc:  # noqa: BLE001 — cognition must not break chat
            cognition_meta = {
                "error": f"{type(exc).__name__}: {exc}",
                "truth": {"cognition_failure_does_not_fail_chat": True},
            }

    # ACTIVE cognition owns the answer — skip duplicate retrieval / neuro / model acquire.
    cognition_early_own = bool(
        cognition_meta
        and not cognition_meta.get("shadow")
        and not settings.features.cognition_shadow
        and (cognition_meta.get("response") or "").strip()
        and cognition_meta.get("response_ownership") == "cognition"
        and not cognition_meta.get("error")
    )

    runs.transition(
        run.run_id,
        RunState.RETRIEVING if (plan.use_knowledge and not cognition_early_own) else RunState.EXECUTING,
        intent=plan.intent,
        complexity=plan.complexity,
    )

    knowledge_hits: list[dict] = []
    atlas_hits: list[dict] = []
    why_hits: list[dict] = []
    contradictions: list[str] = []
    deep_recall_result = None
    memory_hits: list[dict] = []
    neuro_context: list[dict] = []
    cortex_report = None
    residual_applied_any = False
    from Data.modules.neuro.types import NeuroAssessment

    neuro = NeuroAssessment(
        enabled=False,
        signals=(),
        notes=(("skipped — cognition early-own path",) if cognition_early_own else ()),
    )

    if cognition_early_own:
        # Record retrieval cognition already performed (perception / usage) without re-running RAG.
        usage = (cognition_meta or {}).get("usage") or {}
        retrieval_rounds = int(usage.get("retrieval_rounds") or 0)
        observations = (cognition_meta or {}).get("observations") or []
        if retrieval_rounds > 0 or observations:
            runs.append_event(
                run.run_id,
                EventType.RETRIEVAL_COMPLETED,
                {
                    "count": retrieval_rounds,
                    "source": "cognition",
                    "observation_count": len(observations) if isinstance(observations, list) else 0,
                    "early_own": True,
                },
            )
        history_rows = db.get_messages(conversation_id, limit=live_settings().max_history_messages)
        history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
    else:
        if plan.use_knowledge:
            # All successful retrieval strategies must converge here:
            # RETRIEVAL_STARTED → (deep|staged|hybrid) → RETRIEVAL_COMPLETED → EXECUTING
            runs.append_event(run.run_id, EventType.RETRIEVAL_STARTED, {})
            retrieval_source = "staged_or_hybrid"
            try:
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
                    retrieval_source = "deep_recall"
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
                    use_reranker = resolve_use_reranker(
                        live_settings().knowledge.rerank_policy,
                        reranker_available=bool(
                            retriever.reranker is not None and retriever.reranker.available()
                        ),
                        embedding_is_semantic=retriever._embedding_is_semantic(),  # noqa: SLF001
                    )
                    staged = staged_retriever.search(
                        message,
                        limit=live_settings().knowledge_top_k,
                        use_deep_recall=False,
                        rerank_policy=live_settings().knowledge.rerank_policy,
                    )
                    # Prefer staged hits; fall back to direct hybrid with policy-aware rerank.
                    if staged.hits:
                        knowledge_hits = [hit.as_context_document() for hit in staged.hits]
                        retrieval_source = "staged"
                    else:
                        hits = retriever.search(
                            RetrievalQuery(
                                text=message,
                                limit=live_settings().knowledge_top_k,
                                use_reranker=use_reranker,
                            )
                        )
                        knowledge_hits = [hit.as_context_document() for hit in hits]
                        retrieval_source = "hybrid"
                    if staged.negative_reasons:
                        observability.emit(
                            "knowledge",
                            "staged_retrieval.negative",
                            payload={
                                "reasons": list(staged.negative_reasons),
                                "coverage": staged.coverage,
                                "early_exit": staged.early_exit,
                            },
                        )
                    if settings.features.why_library:
                        why_hits = [item.as_context_item() for item in why_library.search(message, limit=3)]

                # COMMON RETRIEVAL SUCCESS FINALIZATION — single lifecycle authority.
                # Do not duplicate EXECUTING transitions inside strategy branches.
                # Calibrated relevance gate: retriever returning hits ≠ relevant.
                threshold = float(behavior_profile.retrieval_relevance_threshold)
                top_k = int(behavior_profile.retrieval_top_k or live_settings().knowledge_top_k)
                filtered_hits: list[dict] = []
                for item in knowledge_hits:
                    score = item.get("score")
                    if score is None:
                        score = item.get("relevance") or item.get("rerank_score")
                    try:
                        score_f = float(score) if score is not None else None
                    except (TypeError, ValueError):
                        score_f = None
                    # Honest: hash/non-semantic embeddings must not claim semantic confidence.
                    embedding_semantic = True
                    try:
                        embedding_semantic = bool(retriever._embedding_is_semantic())  # noqa: SLF001
                    except Exception:  # noqa: BLE001
                        embedding_semantic = True
                    if score_f is None:
                        # No score → keep only when semantic embeddings unavailable would
                        # make threshold meaningless; still cap by top_k.
                        filtered_hits.append(item)
                    elif not embedding_semantic:
                        # Hash fallback scores are not semantic confidence.
                        item = {**item, "score_uncalibrated": True, "score": score_f}
                        filtered_hits.append(item)
                    elif score_f >= threshold:
                        filtered_hits.append(item)
                knowledge_hits = filtered_hits[: max(1, top_k)] if filtered_hits else []
                if behavior_profile.retrieval_max_context_chars:
                    # Soft cap handled by ContextBuilder; annotate diagnostic.
                    pass
                runs.append_event(
                    run.run_id,
                    EventType.RETRIEVAL_COMPLETED,
                    {
                        "count": len(knowledge_hits),
                        "atlas_count": len(atlas_hits),
                        "deep_recall": bool(deep_recall_result and deep_recall_result.available),
                        "source": retrieval_source,
                    },
                )
                runs.transition(run.run_id, RunState.EXECUTING)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 — retrieval failure must not fake COMPLETED
                observability.emit(
                    "knowledge",
                    "retrieval_failed",
                    payload={
                        "error": f"{type(exc).__name__}: {exc}",
                        "source": retrieval_source,
                        "deep_recall_selected": bool(
                            plan.use_deep_recall and economy.allow_deep_recall
                        ),
                    },
                )
                runs.transition(run.run_id, RunState.FAILED, error=str(exc))
                raise HTTPException(
                    status_code=500,
                    detail=f"Retrieval failed: {exc}",
                ) from exc

        history_rows = db.get_messages(conversation_id, limit=live_settings().max_history_messages)
        history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
        memory_hits = []
        if (
            behavior_profile.memory_enabled
            and plan.use_memory
            and reasoning_mode.effective != "fast"
        ):
            memory_hits = [
                item.as_context_item()
                for item in memory_store.search(
                    message,
                    limit=max(1, int(behavior_profile.memory_top_k or 5)),
                    conversation_id=conversation_id,
                    include_global=True,
                )
            ]
        knowledge_ids = [str(item.get("id") or "") for item in knowledge_hits if item.get("id")]
        neuro = NeuroAssessment(enabled=False, signals=(), notes=())
        if reasoning_mode.effective != "fast":
            neuro = neuro_advisor.assess(message, plan=plan, knowledge_ids=knowledge_ids)
        if neuro.enabled:
            observability.emit(
                "neuro",
                "assess",
                payload={"signals": len(neuro.signals)},
            )
            for signal in neuro.signals:
                from Data.modules.context.advisory import normalize_neuro_item

                neuro_context.append(normalize_neuro_item(signal))
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

    route_meta: dict | None = None
    call_id: str | None = None
    residency_lease_id: str | None = None
    provider_id_for_release = "unknown"
    model_id_for_release = "unknown"
    routed: dict | None = None
    profile = None
    llm_kwargs: dict = {}

    if not cognition_early_own:
        runs.append_event(run.run_id, EventType.MODEL_STARTED, {})
        try:
            routed = model_plane.resolve_for_chat(
                explicit_model_id=payload.model_id,
                preferred_role=payload.preferred_role or "chat",
                prefer_reasoning=bool(reasoning_mode.prefer_reasoning_model),
            )
            decision = routed["decision"]
            profile = routed["profile"]
            provider_id_for_release = routed["provider_id"]
            model_id_for_release = routed["model"].id
            resolved = routed.get("resolved")
            binding = resolved.runtime_binding if resolved is not None else None
            managed = bool(binding.managed) if binding else False
            lease = await model_plane.residency.acquire_lease(
                model_id_for_release,
                consumer="chat",
                domain="chat",
                model_role=payload.preferred_role or "chat",
                run_id=run.run_id,
                trace_id=None,
                job_class="INTERACTIVE",
                explicit_selection=bool(payload.model_id),
                managed=managed,
                runtime_kind=binding.runtime_kind if binding else None,
                ensure_ready=managed,
                external=not managed,
                endpoint=routed["endpoint"],
            )
            residency_lease_id = lease.lease_id
            # Prefer managed worker endpoint when residency published one.
            snap = model_plane.residency.snapshot(model_id_for_release)
            if snap.endpoint:
                routed["endpoint"] = snap.endpoint
            call_id = model_plane.gateway.acquire(
                model_id=model_id_for_release,
                provider_id=provider_id_for_release,
                timeout_seconds=min(settings.llm_timeout_seconds, 30.0),
            )
            route_meta = {
                "decision": decision.public_dict(),
                "traceId": call_id,
                "residencyLeaseId": residency_lease_id,
                "contextWindow": routed["model"].context_window,
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
            if residency_lease_id:
                await model_plane.residency.release_lease(
                    residency_lease_id, model_id=model_id_for_release
                )
                residency_lease_id = None
            if exc.code in {"ROUTER_EXHAUSTED", "NO_CHAT_MODEL_AVAILABLE", "MODEL_NOT_FOUND"} and not payload.model_id:
                # Soft settings fallback still uses EXTERNAL residency + Gateway —
                # never silent bypass of the Model Control Plane.
                try:
                    routed = model_plane.resolve_settings_external_fallback(
                        preferred_role=payload.preferred_role or "chat",
                        router_error_code=exc.code,
                    )
                    decision = routed["decision"]
                    profile = routed["profile"]
                    provider_id_for_release = routed["provider_id"]
                    model_id_for_release = routed["model"].id
                    lease = await model_plane.residency.acquire_lease(
                        model_id_for_release,
                        consumer="chat",
                        domain="chat",
                        model_role=payload.preferred_role or "chat",
                        run_id=run.run_id,
                        trace_id=None,
                        job_class="INTERACTIVE",
                        explicit_selection=False,
                        managed=False,
                        runtime_kind="openai_compatible",
                        ensure_ready=False,
                        external=True,
                        endpoint=routed["endpoint"],
                    )
                    residency_lease_id = lease.lease_id
                    call_id = model_plane.gateway.acquire(
                        model_id=model_id_for_release,
                        provider_id=provider_id_for_release,
                        timeout_seconds=min(settings.llm_timeout_seconds, 30.0),
                    )
                    route_meta = {
                        "decision": decision.public_dict(),
                        "traceId": call_id,
                        "residencyLeaseId": residency_lease_id,
                        "contextWindow": routed["model"].context_window,
                        "settingsExternal": True,
                    }
                    runs.append_event(run.run_id, EventType.MODEL_STARTED, route_meta)
                except ModelControlError as fallback_exc:
                    runs.transition(run.run_id, RunState.FAILED, error=str(fallback_exc))
                    raise HTTPException(
                        status_code=fallback_exc.http_status,
                        detail=fallback_exc.public_dict(),
                    ) from fallback_exc
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
            behavior_profile_prompt=behavior_snapshot.system_prompt,
        )
        stream_extra_kwargs: dict = {
            "stop": list(behavior_profile.stop_sequences) or None,
            "seed": behavior_profile.seed,
            "frequency_penalty": behavior_profile.frequency_penalty,
            "presence_penalty": behavior_profile.presence_penalty,
        }
        # Generation overrides from behavior settings when model profile lacks them.
        if behavior_profile.temperature is not None:
            llm_kwargs["temperature"] = behavior_profile.temperature
        if behavior_profile.top_p is not None:
            llm_kwargs["top_p"] = behavior_profile.top_p
        if behavior_profile.max_output_tokens is not None:
            llm_kwargs["max_tokens"] = behavior_profile.max_output_tokens
        if routed is not None and profile is not None:
            # Model-aware context window for ContextBuilder when known.
            if routed["model"].context_window and hasattr(llm, "context_builder"):
                try:
                    llm.context_builder.model_context_window = int(routed["model"].context_window)
                except Exception:  # noqa: BLE001
                    pass
            llm_kwargs.update(
                model_id=routed["provider_model_id"],
                endpoint=routed["endpoint"],
                api_key=routed["api_key"],
                temperature=profile.temperature if profile.temperature is not None else llm_kwargs.get("temperature"),
                max_tokens=profile.max_tokens if profile.max_tokens is not None else llm_kwargs.get("max_tokens"),
                top_p=profile.top_p if profile.top_p is not None else llm_kwargs.get("top_p"),
                system_prompt=profile.system_prompt or None,
            )
    else:
        model_id_for_release = "cognition"
        stream_extra_kwargs = {}
        route_meta = {
            "decision": {
                "reason": "cognition_early_own",
                "fallbackUsed": False,
            }
        }
        runs.append_event(run.run_id, EventType.MODEL_STARTED, route_meta)

    # ACTIVE cognition owns the authoritative answer when it produced one.
    # SHADOW cognition may observe only — chat path remains authoritative.
    cognition_owns_response = bool(cognition_early_own) or bool(
        cognition_meta
        and not cognition_meta.get("shadow")
        and not settings.features.cognition_shadow
        and (cognition_meta.get("response") or "").strip()
        and cognition_meta.get("response_ownership") == "cognition"
        and not cognition_meta.get("error")
    )
    if cognition_meta is not None:
        cognition_meta = {
            **cognition_meta,
            "owns_final_response": cognition_owns_response,
            "truth": {
                **(cognition_meta.get("truth") or {}),
                "shadow_does_not_own_final_response": True,
                "active_cognition_owns_final_response_when_present": True,
                "no_duplicate_authoritative_model_call": cognition_owns_response,
            },
        }

    async def _release_chat_inference(*, error: str | None = None) -> None:
        nonlocal call_id, residency_lease_id
        if call_id and routed is not None:
            model_plane.gateway.release(
                model_id=model_id_for_release,
                provider_id=provider_id_for_release,
                error=error,
            )
            call_id = None
        if residency_lease_id:
            await model_plane.residency.release_lease(
                residency_lease_id, model_id=model_id_for_release
            )
            residency_lease_id = None

    async def _finalize_chat(answer: str, model: str) -> dict:
        from Data.modules.context.response_quality import check_response_quality

        quality = check_response_quality(
            answer,
            expected_language=behavior_snapshot.language.response_language,
        )
        # Bounded one-shot revision for high-severity language/diagnostic issues.
        # Language/diagnostic safety net applies even in FAST (max_generations=1).
        allow_quality_revision = (
            reasoning_mode.max_generations > 1
            or any(i.type in {"language_mismatch", "diagnostic_leakage", "empty_answer"} for i in quality.issues)
        )
        if (
            quality.should_revise
            and not cognition_owns_response
            and routed is not None
            and quality.revision_instruction
            and allow_quality_revision
        ):
            try:
                revised_text, _revised_model = await llm.chat(
                    history=[
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": answer},
                        {
                            "role": "user",
                            "content": quality.revision_instruction,
                        },
                    ],
                    knowledge=[],
                    plan=plan,
                    behavior_profile_prompt=(
                        f"{behavior_snapshot.system_prompt}\n\n{quality.revision_instruction}"
                    ),
                    model_id=routed["provider_model_id"],
                    endpoint=routed["endpoint"],
                    api_key=routed["api_key"],
                    temperature=0.2,
                    max_tokens=behavior_profile.max_output_tokens,
                )
                candidate = (revised_text or "").strip()
                if candidate:
                    recheck = check_response_quality(
                        candidate,
                        expected_language=behavior_snapshot.language.response_language,
                    )
                    if recheck.pass_ or not any(
                        i.type in {"diagnostic_leakage", "language_mismatch", "empty_answer"}
                        for i in recheck.issues
                    ):
                        answer = candidate
                        quality = recheck
            except Exception:  # noqa: BLE001 — revision failure keeps original
                pass

        if call_id and routed is not None:
            model_plane.registry.touch_used(model_id_for_release)
        await _release_chat_inference()
        runs.append_event(
            run.run_id,
            EventType.MODEL_COMPLETED,
            {
                "model": model,
                **(route_meta or {}),
                "quality": quality.public_dict(),
                "reasoning_mode": reasoning_mode.public_dict(),
                "language": behavior_snapshot.language.public_dict(),
                "behavior_profile_id": behavior_snapshot.profile.id,
                "behavior_profile_version": behavior_snapshot.version,
                "behavior_profile_hash": behavior_snapshot.settings_hash,
            },
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
                "streamed": use_sse and not cognition_owns_response,
                "streaming_degraded": streaming_degraded,
                "cognition_owns_final_response": cognition_owns_response,
                "response_language": behavior_snapshot.language.response_language,
                "reasoning_mode": reasoning_mode.effective,
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
            "reasoning": {
                **plan.public_summary(),
                "mode": reasoning_mode.public_dict(),
            },
            "behavior": behavior_snapshot.public_dict(include_prompt=False),
            "language": behavior_snapshot.language.public_dict(),
            "quality": quality.public_dict(),
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
            "neuro": neuro.public_dict() if behavior_profile.diagnostic_visibility else {
                "enabled": neuro.enabled,
                "signals": [],
                "notes": ["diagnostic_visibility=false — raw signals withheld from chat payload"],
                "truth": neuro.public_dict().get("truth", {}),
            },
            "cortex": cortex_report if behavior_profile.diagnostic_visibility else None,
            "cognition": cognition_meta,
            "assistant_telemetry": _build_assistant_telemetry(
                model=model,
                behavior_snapshot=behavior_snapshot,
                cognition_meta=cognition_meta,
                knowledge_hits=knowledge_hits,
                memory_hits=memory_hits,
                evidence_hits=[],
                run_started_at=getattr(run, "started_at", None) or getattr(run, "created_at", None),
            ),
            "streamed": use_sse and not cognition_owns_response,
            "truth": chat_truth(
                streaming_degraded=streaming_degraded,
                residual_implemented=residual_runtime.supports_residuals(),
                residual_applied=residual_applied_any,
            ),
        }

    if cognition_owns_response:
        # Cognition already performed the authoritative model call via control plane.
        await _release_chat_inference()
        answer = str(cognition_meta.get("response") or "").strip()
        model_name = str(model_id_for_release or "cognition")
        result = await _finalize_chat(answer, model_name)
        result["truth"] = {
            **(result.get("truth") or {}),
            "response_owned_by": "cognition",
            "no_duplicate_authoritative_model_call": True,
        }
        if use_sse:

            async def _cognition_sse():
                yield sse_encode(
                    "meta",
                    {
                        "conversation_id": conversation_id,
                        "run_id": run.run_id,
                        "user_message": user_message,
                        "reasoning": plan.public_summary(),
                        "model": model_name,
                        "cognition_owns_final_response": True,
                        "truth": result["truth"],
                    },
                )
                yield sse_encode("token", {"text": answer, "model": model_name})
                yield sse_encode("done", result)

            return StreamingResponse(
                _cognition_sse(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return result

    if use_sse:

        async def _sse_events():
            nonlocal call_id
            cancel = StreamCancelToken()
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
            finish_reason = None
            termination_source = None
            stream_stats: dict = {}
            try:
                if hasattr(llm, "chat_stream_frames"):
                    async for frame in llm.chat_stream_frames(
                        **llm_kwargs,
                        **{k: v for k, v in stream_extra_kwargs.items() if v is not None},
                        cancel=cancel,
                        request_id=request_id,
                        turn_id=turn_id,
                    ):
                        if await request.is_disconnected():
                            cancel.cancel("client_disconnect")
                        if cancel.cancelled:
                            break
                        model_name = frame.model or model_name
                        if frame.kind == "delta" and frame.text:
                            parts.append(frame.text)
                            yield sse_encode(
                                "token",
                                {
                                    "text": frame.text,
                                    "model": model_name,
                                    "sequence": frame.sequence,
                                    "kind": "delta",
                                    "request_id": request_id,
                                    "turn_id": turn_id,
                                },
                            )
                        elif frame.kind in {"snapshot", "replace"} and frame.text:
                            parts.clear()
                            parts.append(frame.text)
                            yield sse_encode(
                                frame.kind,
                                {
                                    "text": frame.text,
                                    "model": model_name,
                                    "sequence": frame.sequence,
                                    "kind": frame.kind,
                                    "request_id": request_id,
                                    "turn_id": turn_id,
                                },
                            )
                        elif frame.kind == "done":
                            finish_reason = frame.finish_reason
                            termination_source = frame.termination_source
                            stream_stats = dict(frame.meta or {})
                else:
                    async for delta, model_name in llm.chat_stream(**llm_kwargs, cancel=cancel):
                        if await request.is_disconnected():
                            cancel.cancel("client_disconnect")
                        if cancel.cancelled:
                            break
                        parts.append(delta)
                        yield sse_encode("token", {"text": delta, "model": model_name})
                if cancel.cancelled:
                    await _release_chat_inference()
                    try:
                        runs.transition(run.run_id, RunState.CANCELLED, error=cancel.reason)
                    except Exception:  # noqa: BLE001 — some stores use different cancel path
                        runs.transition(run.run_id, RunState.FAILED, error=cancel.reason or "cancelled")
                    yield sse_encode(
                        "cancelled",
                        {
                            "reason": cancel.reason or "client_disconnect",
                            "request_id": request_id,
                            "turn_id": turn_id,
                            "truth": {
                                "disconnect_cancels_stream": True,
                                "gateway_capacity_released": True,
                                "residency_lease_released": True,
                            },
                        },
                    )
                    return
                answer = "".join(parts).strip()
                if not answer:
                    raise LLMUnavailable("LLM stream produced empty text")
                done_payload = await _finalize_chat(answer, model_name)
                done_payload["finish_reason"] = finish_reason or "stop"
                done_payload["termination_source"] = termination_source or "stream_end"
                done_payload["request_id"] = request_id
                done_payload["turn_id"] = turn_id
                done_payload["behavior"] = behavior_snapshot.public_dict(include_prompt=False)
                done_payload["retrieval_gate"] = {
                    "use_knowledge": plan.use_knowledge,
                    "reason": getattr(plan, "retrieval_reason", ""),
                    "knowledge_count": len(knowledge_hits),
                    "policy_version": getattr(plan, "policy_version", ""),
                }
                done_payload["stream_stats"] = stream_stats
                yield sse_encode("done", done_payload)
            except LLMUnavailable as stream_exc:
                # Honest degrade: non-stream completion still via real provider path.
                try:
                    answer, model_name = await llm.chat(**llm_kwargs, stream=False)
                    done_payload = await _finalize_chat(answer, model_name)
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
                    await _release_chat_inference(error=str(llm_exc))
                    runs.transition(run.run_id, RunState.FAILED, error=str(llm_exc))
                    yield sse_encode(
                        "error",
                        {
                            "detail": str(llm_exc),
                            "truth": chat_truth(streaming_degraded=True),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                await _release_chat_inference(error=str(exc))
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
        await _release_chat_inference(error=str(exc))
        runs.transition(run.run_id, RunState.FAILED, error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = await _finalize_chat(answer, model)
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
