"""Worker pool catalog — smallest coherent set covering LEVIATHAN domains."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PoolDefinition:
    pool_id: str
    entrypoint: str
    """Module path: ``Data.modules.workers.entrypoints.general`` or script relative path."""

    default_count: int = 1
    job_kinds: tuple[str, ...] = ()
    """Capability / job-kind prefixes this pool claims. Empty = general catch-all."""

    resource_classes: tuple[str, ...] = ("CPU_LIGHT",)
    description: str = ""
    max_count: int = 8

    def public_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "entrypoint": self.entrypoint,
            "default_count": self.default_count,
            "job_kinds": list(self.job_kinds),
            "resource_classes": list(self.resource_classes),
            "description": self.description,
            "max_count": self.max_count,
        }


# Entrypoints are argv-safe Python module targets launched as:
#   python -m Data.modules.workers.entrypoints.<name>
POOL_CATALOG: dict[str, PoolDefinition] = {
    "general": PoolDefinition(
        pool_id="general",
        entrypoint="Data.modules.workers.entrypoints.general",
        default_count=1,
        job_kinds=(),
        description="General capability jobs not owned by a specialist pool",
    ),
    "file_io": PoolDefinition(
        pool_id="file_io",
        entrypoint="Data.modules.workers.entrypoints.file_io",
        default_count=1,
        job_kinds=(
            "file.read",
            "file.write",
            "file.copy",
            "file.hash",
            "file.inspect_csv",
            "file.parse_csv",
            "file.profile_csv",
            "file.process_parquet",
            "file.list",
            "workspace.list",
            "workspace.search",
            "filesystem.scan",
        ),
        resource_classes=("IO_HEAVY", "MEMORY_HEAVY", "CPU_HEAVY"),
        description=(
            "Generic heavy filesystem I/O — large reads/writes/copies/hashes, "
            "CSV/Parquet processing, recursive directory scans. Not dataset or "
            "source_ingestion domain ownership."
        ),
        max_count=2,
    ),
    "scheduler": PoolDefinition(
        pool_id="scheduler",
        entrypoint="Data.modules.workers.entrypoints.scheduler",
        default_count=1,
        job_kinds=("schedule.tick",),
        description="Singleton schedule evaluation — enqueue only",
        max_count=1,
    ),
    "workflow": PoolDefinition(
        pool_id="workflow",
        entrypoint="Data.modules.workers.entrypoints.workflow",
        default_count=1,
        job_kinds=("workflow.advance",),
        description="Durable workflow continuation",
    ),
    "source_ingestion": PoolDefinition(
        pool_id="source_ingestion",
        entrypoint="Data.modules.workers.entrypoints.source_ingestion",
        default_count=1,
        job_kinds=("source_ingestion.process", "source_ingestion.brain_retry"),
        resource_classes=("IO_HEAVY", "CPU_HEAVY"),
        description="Archive/file parse and brain retry",
    ),
    "dataset": PoolDefinition(
        pool_id="dataset",
        entrypoint="Data.modules.workers.entrypoints.dataset",
        default_count=1,
        job_kinds=("dataset.process", "dataset."),
        resource_classes=("IO_HEAVY", "CPU_HEAVY", "MEMORY_HEAVY"),
        description="Dataset download/profile/index/export — kernel claim owner when externalized",
    ),
    "provider_io": PoolDefinition(
        pool_id="provider_io",
        entrypoint="Data.modules.workers.entrypoints.provider_io",
        default_count=2,
        job_kinds=(
            "provider.",
            "provider.http",
            "provider.chat.complete",
            "provider.chat.stream",
            "provider.market.fetch",
            "provider.alpaca.paper",
            "provider.hf.list",
        ),
        resource_classes=("NETWORK_BOUND", "CPU_LIGHT"),
        description=(
            "External provider / SaaS I/O — remote LLM HTTP, search APIs, "
            "bounded market/HF metadata fetches, Alpaca paper trading "
            "(not bulk dataset or model downloads; not long-lived market streams)"
        ),
        max_count=8,
    ),
    "market_feed": PoolDefinition(
        pool_id="market_feed",
        entrypoint="Data.modules.workers.entrypoints.market_feed",
        default_count=1,
        job_kinds=(
            "provider.market.stream",
            "provider.market.stream.stop",
        ),
        resource_classes=("NETWORK_BOUND", "CPU_LIGHT"),
        description=(
            "Long-lived public market data streams (Binance combined kline/trade) — "
            "never order/trading endpoints; checkpoints are CONTROL-sized"
        ),
        max_count=4,
    ),
    "model_download": PoolDefinition(
        pool_id="model_download",
        entrypoint="Data.modules.workers.entrypoints.model_download",
        default_count=1,
        job_kinds=(
            "model_download.",
            "model_download.start",
            "model_import.local",
        ),
        resource_classes=("IO_HEAVY", "NETWORK_BOUND", "MEMORY_HEAVY", "CPU_HEAVY"),
        description=(
            "Heavy model acquisition (Hugging Face / Ollama pull) and large "
            "local model import/verification — not provider_io, not serving"
        ),
        max_count=2,
    ),
    "model_runtime": PoolDefinition(
        pool_id="model_runtime",
        entrypoint="Data.modules.workers.entrypoints.model_runtime",
        default_count=1,
        job_kinds=(
            "model_runtime.",
            "model_runtime.load",
            "model_runtime.unload",
            "model_runtime.reconcile",
            "model_runtime.benchmark",
            "model_runtime.probe",
            "model_runtime.inference_test",
            "model_runtime.start",
            "model_runtime.stop",
            "model.serving.start",
            "model.serving.stop",
            "model.serving.reconcile",
        ),
        resource_classes=("CPU_LIGHT", "MODEL_INFERENCE", "GPU_SHARED", "IO_HEAVY"),
        description=(
            "Singleton managed model-serving lifecycle owner — start/stop/"
            "reconcile ServingSupervisor children, benchmarks, inference probes. "
            "Operator-owned Ollama/LM Studio are never killed. "
            "Not Model Control Plane registry; not model_download acquisition."
        ),
        max_count=1,
    ),
    "mcp_execution": PoolDefinition(
        pool_id="mcp_execution",
        entrypoint="Data.modules.workers.entrypoints.mcp_execution",
        default_count=1,
        job_kinds=(
            "mcp.call",
            "mcp.connect",
            "mcp.list_tools",
            "mcp.",
        ),
        resource_classes=("NETWORK_BOUND", "CPU_LIGHT"),
        description=(
            "Live MCP connect/handshake/list/tools/call — stdio spawn and HTTP "
            "network I/O owned by mcp_execution (not FastAPI)"
        ),
        max_count=4,
    ),
    "research": PoolDefinition(
        pool_id="research",
        entrypoint="Data.modules.workers.entrypoints.research",
        default_count=1,
        job_kinds=("research.", "web.search", "web.fetch", "web."),
        resource_classes=("CPU_HEAVY", "NETWORK_BOUND", "MODEL_INFERENCE"),
        description="Durable research orchestration and child retrieval jobs",
        max_count=4,
    ),
    "memory": PoolDefinition(
        pool_id="memory",
        entrypoint="Data.modules.workers.entrypoints.memory",
        default_count=1,
        job_kinds=("memory.",),
        resource_classes=("CPU_HEAVY", "MEMORY_HEAVY", "MODEL_INFERENCE"),
        description=(
            "Heavy Memory consolidation/enrichment — not general; "
            "trust gates preserved (AGENT_PROPOSED ≠ VERIFIED)"
        ),
        max_count=2,
    ),
    "brain_compute": PoolDefinition(
        pool_id="brain_compute",
        entrypoint="Data.modules.workers.entrypoints.brain_compute",
        default_count=1,
        job_kinds=("brain.", "brain.compute."),
        resource_classes=("CPU_HEAVY", "MEMORY_HEAVY", "MODEL_INFERENCE"),
        description=(
            "Heavy DERIVED Brain computation only — Brain remains a facade; "
            "never a Brain/graph database or competing Knowledge/Memory store"
        ),
        max_count=2,
    ),
    "coding": PoolDefinition(
        pool_id="coding",
        entrypoint="Data.modules.workers.entrypoints.coding",
        default_count=1,
        job_kinds=(
            "coding.advance",
            "coding.run_tests",
            "coding.test",
            "coding.semantic_map.build",
            "coding.verify",
            "coding.git.clone",
            "coding.git.fetch",
            "coding.git.update",
            "coding.git.checkout",
            "coding.repo.analyze",
        ),
        resource_classes=("CPU_HEAVY", "MODEL_INFERENCE", "IO_HEAVY", "NETWORK_BOUND", "MEMORY_HEAVY"),
        description="Coding rounds, semantic analysis, verify, and coding-domain Git",
        max_count=2,
    ),
    "module_runtime": PoolDefinition(
        pool_id="module_runtime",
        entrypoint="Data.modules.workers.entrypoints.module_runtime",
        default_count=1,
        job_kinds=(
            "external.module.install",
            "external.module.update",
            "external.module.upgrade",
            "external.module.invoke",
            "external.module.start",
            "external.module.stop",
            "external.module.restart",
            "external.module.ensure_ready",
        ),
        resource_classes=(
            "IO_HEAVY",
            "NETWORK_BOUND",
            "CPU_HEAVY",
            "MEMORY_HEAVY",
            "GPU_SHARED",
            "GPU_EXCLUSIVE",
        ),
        description=(
            "External module install/update/upgrade, CLI/script/process-service "
            "lifecycle, and network module invocation. MCP-backed modules use "
            "mcp_execution for tools/call. max_count=1 for process-service ownership."
        ),
        max_count=1,
    ),
    "agents": PoolDefinition(
        pool_id="agents",
        entrypoint="Data.modules.workers.entrypoints.agents",
        default_count=1,
        job_kinds=("agent.",),
        resource_classes=("CPU_LIGHT", "MODEL_INFERENCE"),
        description="Long-running agent missions",
    ),
    "agent_signals": PoolDefinition(
        pool_id="agent_signals",
        entrypoint="Data.modules.workers.entrypoints.agent_signals",
        default_count=1,
        job_kinds=("agent_signal.",),
        resource_classes=("CPU_LIGHT",),
        description="LEVIATHAN Signal Fabric delivery / retry / housekeeping",
        max_count=4,
    ),
    "knowledge_prepare": PoolDefinition(
        pool_id="knowledge_prepare",
        entrypoint="Data.modules.workers.entrypoints.knowledge_prepare",
        default_count=1,
        job_kinds=(
            "knowledge.prepare",
            "knowledge.ingest_scan",
            "knowledge.ingest_document",
            "knowledge.ingest_path",
            "knowledge.reconcile",
            "external.knowledge.assimilate",
        ),
        resource_classes=("CPU_HEAVY", "MEMORY_HEAVY"),
        description=(
            "Chunking, embeddings prep, entity extraction, semantic reconciliation, "
            "external Knowledge assimilation planning (bulk writes via db_commit)"
        ),
    ),
    "knowledge_commit": PoolDefinition(
        pool_id="knowledge_commit",
        entrypoint="Data.modules.workers.entrypoints.knowledge_commit",
        default_count=0,
        job_kinds=(),
        description=(
            "Deprecated specialized knowledge commit lane — bulk Knowledge COMMIT_WRITE "
            "is owned by db_commit. Kept for catalog compatibility (desired=0)."
        ),
        max_count=1,
    ),
    "db_commit": PoolDefinition(
        pool_id="db_commit",
        entrypoint="Data.modules.workers.entrypoints.db_commit",
        default_count=1,
        job_kinds=("db_commit.", "knowledge.commit"),
        resource_classes=("IO_HEAVY", "DB_SERIAL"),
        description=(
            "Single serialized DB Commit Coordinator — all COMMIT_WRITE bulk mutations"
        ),
        max_count=1,
    ),
    "embedding": PoolDefinition(
        pool_id="embedding",
        entrypoint="Data.modules.workers.entrypoints.embedding",
        default_count=1,
        job_kinds=("embedding.",),
        resource_classes=("GPU_SHARED", "CPU_HEAVY", "MEMORY_HEAVY"),
        description="Specialist embedding batches",
    ),
    "rerank": PoolDefinition(
        pool_id="rerank",
        entrypoint="Data.modules.workers.entrypoints.rerank",
        default_count=0,
        job_kinds=("rerank.",),
        resource_classes=("GPU_SHARED", "CPU_HEAVY"),
        description="Specialist reranking (disabled until backend configured)",
    ),
    "browser": PoolDefinition(
        pool_id="browser",
        entrypoint="Data.modules.workers.entrypoints.browser",
        default_count=1,
        job_kinds=("browser.",),
        resource_classes=("NETWORK_BOUND", "CPU_HEAVY", "MEMORY_HEAVY"),
        description=(
            "Singleton browser automation / Playwright / Chromium / QA crawl owner. "
            "max_count=1 until session affinity/sharding exists — session state "
            "(cookies, pages, JS) must not split across workers."
        ),
        max_count=1,
    ),
    "media": PoolDefinition(
        pool_id="media",
        entrypoint="Data.modules.workers.entrypoints.media",
        default_count=1,
        job_kinds=("media.",),
        resource_classes=("IO_HEAVY", "CPU_HEAVY", "MEMORY_HEAVY"),
        description=(
            "Deterministic media transforms (FFmpeg/FFprobe/image) and media "
            "orchestration for generation/vision via Model Control Plane. "
            "Not Voice ASR/TTS; not Document AI OCR; not a second model runtime."
        ),
        max_count=2,
    ),
    "document_ai": PoolDefinition(
        pool_id="document_ai",
        entrypoint="Data.modules.workers.entrypoints.document_ai",
        default_count=0,
        job_kinds=("document_ai.", "ocr."),
        resource_classes=("GPU_SHARED", "CPU_HEAVY"),
        description="OCR / document AI — honest unavailable when backend missing",
    ),
    "evaluation": PoolDefinition(
        pool_id="evaluation",
        entrypoint="Data.modules.workers.entrypoints.evaluation",
        default_count=1,
        job_kinds=("evaluation.",),
        resource_classes=("CPU_HEAVY", "MODEL_INFERENCE"),
        description=(
            "Evaluation / benchmark / regression / ablation / release validation / "
            "statistics / soak / chaos orchestration — max_count=2 so full suites "
            "do not fan out unbounded"
        ),
        max_count=2,
    ),
    "training_control": PoolDefinition(
        pool_id="training_control",
        entrypoint="Data.modules.workers.entrypoints.training_control",
        default_count=1,
        job_kinds=("training.",),
        resource_classes=("GPU_EXCLUSIVE", "BATCH", "IO_HEAVY", "CPU_HEAVY"),
        description="Training-control ownership of trainer subprocess + integrity/hash",
        max_count=1,
    ),
    "market_sim": PoolDefinition(
        pool_id="market_sim",
        entrypoint="Data.modules.workers.entrypoints.market_sim",
        default_count=1,
        job_kinds=(
            "market_sim.",
            "market_sim.data.scan",
            "market_sim.data.import",
            "market_sim.data.validate",
            "market_sim.data.profile",
            "market_sim.data.convert",
            "market_sim.assurance.scan",
        ),
        resource_classes=("CPU_HEAVY", "MEMORY_HEAVY", "IO_HEAVY"),
        description=(
            "MarketSim domain owner — simulation slices, research/learning, "
            "qualification, market-data scan/import/validate/profile/convert, "
            "portfolio ticks, institutional assurance"
        ),
        max_count=2,
    ),
    "voice": PoolDefinition(
        pool_id="voice",
        entrypoint="Data.modules.workers.entrypoints.voice",
        default_count=1,
        job_kinds=(
            "voice.",
            "voice.start_session",
            "voice.transcribe",
            "voice.synthesize",
            "voice.barge_in",
            "voice.preprocess",
            "voice.postprocess",
        ),
        resource_classes=("CPU_LIGHT", "CPU_HEAVY", "MEMORY_HEAVY", "MODEL_INFERENCE"),
        description=(
            "Singleton realtime voice transport/session owner — ASR/TTS/"
            "preprocess/postprocess. No horizontal scale until session affinity."
        ),
        max_count=1,
    ),
    "backup": PoolDefinition(
        pool_id="backup",
        entrypoint="Data.modules.workers.entrypoints.backup",
        default_count=1,
        job_kinds=("backup.",),
        resource_classes=("IO_HEAVY",),
        description="Backup creation and backup verification (not restore)",
        max_count=1,
    ),
    "maintenance": PoolDefinition(
        pool_id="maintenance",
        entrypoint="Data.modules.workers.entrypoints.maintenance",
        default_count=1,
        job_kinds=("maintenance.",),
        resource_classes=("MAINTENANCE_EXCLUSIVE",),
        description=(
            "Singleton exclusive DB/system maintenance — integrity/VACUUM/ANALYZE/"
            "blocking checkpoint/reconcile/cleanup/restore cutover"
        ),
        max_count=1,
    ),
    "sqlite_ops": PoolDefinition(
        pool_id="sqlite_ops",
        entrypoint="Data.modules.workers.entrypoints.sqlite_ops",
        default_count=1,
        job_kinds=("sqlite_ops.",),
        resource_classes=("IO_HEAVY", "CPU_HEAVY", "MEMORY_HEAVY"),
        description=(
            "Heavy READ-ONLY operator SQLite work — query/scan/search/analytics/"
            "export. Never INSERT/UPDATE/DELETE/VACUUM/ANALYZE/restore."
        ),
        max_count=1,
    ),
    "security": PoolDefinition(
        pool_id="security",
        entrypoint="Data.modules.workers.entrypoints.security",
        default_count=1,
        job_kinds=("security.",),
        resource_classes=("CPU_HEAVY", "IO_HEAVY"),
        description=(
            "Deep repository/dependency/integrity security audits — never "
            "auto-fix dependencies; secrets redacted"
        ),
        max_count=1,
    ),
    "telemetry": PoolDefinition(
        pool_id="telemetry",
        entrypoint="Data.modules.workers.entrypoints.telemetry",
        default_count=0,
        job_kinds=("telemetry.", "diagnostics."),
        resource_classes=("CPU_LIGHT", "IO_HEAVY"),
        description=(
            "Heavy hardware sampling windows and diagnostics collection. "
            "default_count=0 until explicitly enabled; not hosted in FastAPI "
            "for long-running samplers."
        ),
        max_count=1,
    ),
}


def default_pool_counts() -> dict[str, int]:
    return {pid: defn.default_count for pid, defn in POOL_CATALOG.items()}


def pool_for_capability(
    capability_id: str,
    *,
    worker_kind: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Map a capability id to the owning pool (most specific prefix wins).

    Dynamic MODULE capabilities may not share a fixed prefix — when
    ``worker_kind`` / metadata ``worker_kind`` / ``worker_pool`` is present,
    that owner wins over prefix matching.
    """
    meta = dict(metadata or {})
    explicit = (
        (worker_kind or "").strip()
        or str(meta.get("worker_kind") or "").strip()
        or str(meta.get("worker_pool") or "").strip()
    )
    if explicit and explicit in POOL_CATALOG:
        return explicit

    cap = str(capability_id or "")
    best: str | None = None
    best_len = -1
    for pool_id, defn in POOL_CATALOG.items():
        for kind in defn.job_kinds:
            if not kind:
                continue
            if kind.endswith("."):
                if cap.startswith(kind) and len(kind) > best_len:
                    best = pool_id
                    best_len = len(kind)
            elif cap == kind and len(kind) > best_len:
                best = pool_id
                best_len = len(kind)
    return best or "general"
