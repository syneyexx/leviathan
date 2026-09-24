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
    "research": PoolDefinition(
        pool_id="research",
        entrypoint="Data.modules.workers.entrypoints.research",
        default_count=1,
        job_kinds=("research.",),
        resource_classes=("CPU_HEAVY", "NETWORK_BOUND", "MODEL_INFERENCE"),
        description="Durable research orchestration and child retrieval jobs",
        max_count=4,
    ),
    "coding": PoolDefinition(
        pool_id="coding",
        entrypoint="Data.modules.workers.entrypoints.coding",
        default_count=1,
        job_kinds=("coding.advance",),
        resource_classes=("CPU_HEAVY", "MODEL_INFERENCE"),
        description="Coding session advancement",
        max_count=2,
    ),
    "agents": PoolDefinition(
        pool_id="agents",
        entrypoint="Data.modules.workers.entrypoints.agents",
        default_count=1,
        job_kinds=("agent.",),
        resource_classes=("CPU_LIGHT", "MODEL_INFERENCE"),
        description="Long-running agent missions",
    ),
    "knowledge_prepare": PoolDefinition(
        pool_id="knowledge_prepare",
        entrypoint="Data.modules.workers.entrypoints.knowledge_prepare",
        default_count=1,
        job_kinds=("knowledge.prepare",),
        resource_classes=("CPU_HEAVY", "MEMORY_HEAVY"),
        description="Chunking, embeddings prep, entity extraction",
    ),
    "knowledge_commit": PoolDefinition(
        pool_id="knowledge_commit",
        entrypoint="Data.modules.workers.entrypoints.knowledge_commit",
        default_count=1,
        job_kinds=("knowledge.commit",),
        description="Single serialized canonical knowledge commit lane",
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
        description="Evaluation suite execution",
    ),
    "training_control": PoolDefinition(
        pool_id="training_control",
        entrypoint="Data.modules.workers.entrypoints.training_control",
        default_count=1,
        job_kinds=("training.",),
        resource_classes=("GPU_EXCLUSIVE", "BATCH"),
        description="Training-control ownership of trainer subprocess",
        max_count=1,
    ),
    "market_sim": PoolDefinition(
        pool_id="market_sim",
        entrypoint="Data.modules.workers.entrypoints.market_sim",
        default_count=1,
        job_kinds=("market_sim.",),
        resource_classes=("CPU_HEAVY",),
        description="Market simulation advancement",
    ),
    "backup": PoolDefinition(
        pool_id="backup",
        entrypoint="Data.modules.workers.entrypoints.backup",
        default_count=1,
        job_kinds=("backup.",),
        resource_classes=("IO_HEAVY",),
        description="Backup creation",
        max_count=1,
    ),
    "maintenance": PoolDefinition(
        pool_id="maintenance",
        entrypoint="Data.modules.workers.entrypoints.maintenance",
        default_count=1,
        job_kinds=("maintenance.",),
        resource_classes=("MAINTENANCE_EXCLUSIVE",),
        description="Lease recovery, stale cleanup, reconciliation",
        max_count=1,
    ),
    "telemetry": PoolDefinition(
        pool_id="telemetry",
        entrypoint="Data.modules.workers.entrypoints.telemetry",
        default_count=0,
        job_kinds=("telemetry.",),
        description="Optional external telemetry sampler (API owns by default)",
        max_count=1,
    ),
}


def default_pool_counts() -> dict[str, int]:
    return {pid: defn.default_count for pid, defn in POOL_CATALOG.items()}


def pool_for_capability(capability_id: str) -> str:
    """Map a capability id to the owning pool (most specific prefix wins)."""
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
