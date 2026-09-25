"""Generic worker supervisor — process pools for durable job execution.

Model-serving workers remain owned by the Model Control Plane / ServingSupervisor.
This package owns research, dataset, ingestion, coding, evaluation, provider_io,
and other background execution pools only.
"""

from .admission import ResourceAdmission, ResourceClass
from .events import (
    WorkerEvent,
    WorkerEventEmitter,
    WorkerEventKind,
    format_duration_ms,
    format_terminal_message,
    get_worker_event_emitter,
    resolve_human_title,
    sanitize_human_label,
    set_worker_event_emitter,
)
from .pools import POOL_CATALOG, PoolDefinition, default_pool_counts
from .protocol import (
    WORKER_PROTOCOL_VERSION,
    SupervisorHealth,
    WorkerInstanceState,
    WorkerRegistration,
)
from .registry import WorkerRegistry
from .supervisor import WorkerSupervisor
from .settings import WorkerSettings, load_worker_settings

__all__ = [
    "POOL_CATALOG",
    "PoolDefinition",
    "ResourceAdmission",
    "ResourceClass",
    "SupervisorHealth",
    "WORKER_PROTOCOL_VERSION",
    "WorkerEvent",
    "WorkerEventEmitter",
    "WorkerEventKind",
    "WorkerInstanceState",
    "WorkerRegistration",
    "WorkerRegistry",
    "WorkerSettings",
    "WorkerSupervisor",
    "default_pool_counts",
    "format_duration_ms",
    "format_terminal_message",
    "get_worker_event_emitter",
    "load_worker_settings",
    "resolve_human_title",
    "sanitize_human_label",
    "set_worker_event_emitter",
]
