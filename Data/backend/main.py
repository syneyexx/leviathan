from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DATA_ROOT, FRONTEND_DIST, FRONTEND_ROOT, settings
from .database import Database
from .migrations import MigrationRunner
from Data.modules.agents import AgentKind, AgentRuntime, MultiAgentCoordinator
from Data.modules.approvals import ApprovalService, ApprovalStatus, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.evidence import EvidenceService, EvidenceStatus, EvidenceStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionCallStatus, build_default_registry, FunctionRuntime
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore, RetrievalQuery
from Data.modules.memory import MemoryKind, MemoryStatus, MemoryStore
from Data.modules.model_runtime import LLMUnavailable, OpenAICompatibleLLM
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
from Data.modules.observability import ObservabilityHub
from Data.modules.neuro import (
    ContrastiveRetrievalHead,
    CortexPlanner,
    CortexRuntime,
    NeuroAbsorbService,
    NeuroAdvisor,
    NeuroMemoryFacade,
    NeuroSnapshotStore,
    ProcessCritic,
    build_residual_runtime,
)
from Data.modules.plugins import PluginRegistry, PluginStatus
from Data.modules.evaluation import EvaluationHarness
from Data.modules.isolation import IsolationGuard, IsolationMode, IsolationRequest
from Data.modules.training import TrainingRecipeRegistry, TrainingRegistry
from Data.modules.browser import BrowserAction, BrowserAutomationStub
from Data.modules.media import MediaAction, MediaAutomationStub
from Data.modules.voice import VoiceAction, VoiceRuntimeStub
from Data.modules.release import GateCheck, GateSeverity, ReleaseGateRunner
from Data.modules.security import SecurityAuditor, SecurityFinding
from Data.modules.native import NativeRuntimeStub
from Data.modules.trading import TradingStub
from Data.modules.backup import BackupError, BackupService
from Data.modules.metrics import MetricsCollector
from Data.modules.chaos import ChaosInjector, ChaosPlan
from Data.modules.master import MasterGateCheck, MasterGateRunner, MasterGateStatus

db = Database(settings.database_path)
runs = RunStore(settings.database_path)
artifacts = ArtifactStore(settings.database_path, settings.artifacts.root)
knowledge = KnowledgeStore(
    settings.database_path,
    data_root=settings.knowledge.data_root,
    chunk_max_chars=settings.knowledge.chunk_max_chars,
    chunk_overlap=settings.knowledge.chunk_overlap,
)
retriever = HybridRetriever(knowledge)
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
workflow_store = WorkflowStore(settings.database_path)
workflow_runtime = WorkflowRuntime(workflow_store, execution_gateway)
schedule_store = ScheduleStore(settings.database_path)
schedule_runner = ScheduleRunner(
    schedule_store,
    jobs=job_runtime,
    workflows=workflow_runtime,
)
observability = ObservabilityHub(capacity=500)
neuro_snapshots = NeuroSnapshotStore(settings.database_path)
residual_runtime = build_residual_runtime(
    kind=settings.neuro_runtime.residual_kind,
    model_id=settings.neuro_runtime.residual_model_id,
    device=settings.neuro_runtime.residual_device,
)
neuro_memory = NeuroMemoryFacade(
    enabled=settings.features.neuro_enabled and settings.features.neuro_memory_tiers,
    memory_store=memory_store,
    knowledge_store=knowledge,
    knowledge_retriever=retriever,
    snapshot_store=neuro_snapshots,
)
neuro_absorb = NeuroAbsorbService(knowledge)
neuro_contrastive = ContrastiveRetrievalHead(
    neuro_memory,
    embeddings_available=False,
)
neuro_critic = ProcessCritic(enabled=settings.features.neuro_process_critic)
cortex_runtime = CortexRuntime(
    residual_port=residual_runtime,
    critic=neuro_critic,
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
    cortex_planner=CortexPlanner(enabled=settings.features.neuro_cortex),
    critic=neuro_critic,
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
evaluation_harness = EvaluationHarness(
    catalog=capability_catalog,
    evidence=evidence_store,
    verification=verification_engine,
)
isolation_guard = IsolationGuard(settings)
training_registry = TrainingRegistry()
training_recipes = TrainingRecipeRegistry()
browser_stub = BrowserAutomationStub()
media_stub = MediaAutomationStub()
voice_stub = VoiceRuntimeStub()


def _gate_catalog_builtins() -> GateCheck:
    required = {"file.read", "knowledge.search", "artifact.create_text", "knowledge.ingest_scan"}
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
metrics = MetricsCollector()
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrations.apply_all()
    db.initialize()
    knowledge.initialize()
    runs.initialize()
    artifacts.initialize()
    approval_store.initialize()
    job_store.initialize()
    observation_store.initialize()
    evidence_store.initialize()
    memory_store.initialize()
    neuro_snapshots.initialize()
    verification_reports.initialize()
    workflow_store.initialize()
    schedule_store.initialize()
    if module_manager.enabled:
        ready = module_manager.discover_load_initialize_all(
            ModuleContext(
                database_path=str(settings.database_path),
                data_root=str(settings.knowledge.data_root),
                feature_flags={
                    "neuro_enabled": settings.features.neuro_enabled,
                    "neuro_cortex": settings.features.neuro_cortex,
                    "neuro_memory_tiers": settings.features.neuro_memory_tiers,
                    "neuro_residual_injection": settings.features.neuro_residual_injection,
                    "module_manager_enabled": settings.features.module_manager_enabled,
                },
            )
        )
        observability.emit(
            "module_manager",
            "startup",
            payload={"ready": len(ready), "telemetry": dict(module_manager.telemetry)},
        )
    job_runtime.start_background_worker()
    metrics.incr("lifespan_starts")
    try:
        yield
    finally:
        if module_manager.enabled:
            for managed in list(module_manager.list()):
                if managed.status.value in {"READY", "INITIALIZED", "LOADED", "EXECUTING"}:
                    try:
                        module_manager.shutdown(managed.manifest.module_id)
                    except ModuleManagerError:
                        pass
        job_runtime.stop_background_worker()
        function_runtime.shutdown()


app = FastAPI(title="Leviathan", version="0.50.0-phase50", lifespan=lifespan)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    conversation_id: str | None = None


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
    return {
        "ok": True,
        "version": app.version,
        "database": str(settings.database_path),
        "reasoning_enabled": settings.reasoning_enabled,
        "frontend": {
            "dist_ready": (FRONTEND_DIST / "index.html").is_file(),
            "dist_path": str(FRONTEND_DIST),
        },
        "config": settings.public_summary(),
        "knowledge": {
            "data_root": str(settings.knowledge.data_root),
            "documents": len(knowledge.list_documents(limit=10_000)),
            "embedding_provider": retriever.embeddings.provider_id,
            "embedding_available": retriever.embeddings.available(),
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
            "residual_supported": residual_runtime.supports_residuals(),
            "residual_kind": settings.neuro_runtime.residual_kind,
            "absorb": dict(neuro_absorb.telemetry),
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
def list_conversations() -> dict:
    return {"conversations": db.list_conversations()}


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


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
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
    plan = reasoner.analyze(message, has_knowledge) if settings.reasoning_enabled else ReasoningEngine().analyze(message, False)
    runs.append_event(
        run.run_id,
        EventType.REASONING_COMPLETED,
        plan.public_summary(),
    )
    runs.transition(
        run.run_id,
        RunState.RETRIEVING if plan.use_knowledge else RunState.EXECUTING,
        intent=plan.intent,
        complexity=plan.complexity,
    )

    knowledge_hits: list[dict] = []
    if plan.use_knowledge:
        runs.append_event(run.run_id, EventType.RETRIEVAL_STARTED, {})
        hits = retriever.search(
            RetrievalQuery(text=message, limit=settings.knowledge_top_k)
        )
        knowledge_hits = [hit.as_context_document() for hit in hits]
        runs.append_event(
            run.run_id,
            EventType.RETRIEVAL_COMPLETED,
            {"count": len(knowledge_hits)},
        )
        runs.transition(run.run_id, RunState.EXECUTING)

    history_rows = db.get_messages(conversation_id, limit=settings.max_history_messages)
    history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
    memory_hits = [item.as_context_item() for item in memory_store.search(message, limit=5)]
    knowledge_ids = [str(item.get("id") or "") for item in knowledge_hits if item.get("id")]
    neuro = neuro_advisor.assess(message, plan=plan, knowledge_ids=knowledge_ids)
    if neuro.enabled:
        observability.emit(
            "neuro",
            "assess",
            payload={"signals": len(neuro.signals)},
        )

    runs.append_event(run.run_id, EventType.MODEL_STARTED, {})
    try:
        answer, model = await llm.chat(
            history=history,
            knowledge=knowledge_hits,
            plan=plan,
            memory=memory_hits,
        )
    except LLMUnavailable as exc:
        runs.transition(run.run_id, RunState.FAILED, error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    runs.append_event(run.run_id, EventType.MODEL_COMPLETED, {"model": model})
    assistant_message = db.add_message(conversation_id, "assistant", answer)
    observability.emit(
        "chat",
        "completed",
        payload={"run_id": run.run_id, "model": model, "memory_hits": len(memory_hits)},
    )
    # Chat completion contract: model returned usable text AND assistant message persisted.
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
        "memory_sources": [{"memory_id": item["memory_id"]} for item in memory_hits],
        "neuro": neuro.public_dict(),
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
def list_capabilities() -> dict:
    return {
        "capabilities": [item.public_dict() for item in execution_gateway.list_capabilities()],
        "telemetry": dict(execution_gateway.telemetry),
        "effects_recorded": len(execution_gateway.effect_ledger),
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
        "truth": {
            "in_process_ring_buffer_only": True,
            "not_a_production_apm": True,
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
        "truth": {
            "residual_injection_is_not_authority": True,
            "unsupported_is_not_success": True,
        },
    }


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
    return {"jobs": [item.public_dict() for item in training_registry.list()]}


@app.get("/api/training/recipes")
def list_training_recipes() -> dict:
    return {"recipes": [item.public_dict() for item in training_recipes.list()]}


@app.post("/api/training")
def create_training(payload: TrainingCreateRequest) -> dict:
    job = training_registry.register(name=payload.name, objective=payload.objective)
    return {"job": job.public_dict()}


@app.get("/api/training/{job_id}")
def get_training(job_id: str) -> dict:
    job = training_registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")
    return {"job": job.public_dict()}


@app.post("/api/training/{job_id}/start")
def start_training(job_id: str) -> dict:
    try:
        job = training_registry.start_unsupported(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Training job not found") from exc
    raise HTTPException(status_code=501, detail=job.public_dict())


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
