"""Generic worker supervisor — process pools for durable job execution.

Model-serving workers remain owned by the Model Control Plane / ServingSupervisor.
This package owns research, dataset, ingestion, coding, evaluation, provider_io,
and other background execution pools only.
"""

from .admission import ResourceAdmission, ResourceClass
from .pools import POOL_CATALOG, PoolDefinition, default_pool_counts
from .protocol import WORKER_PROTOCOL_VERSION, WorkerInstanceState, WorkerRegistration
from .registry import WorkerRegistry
from .supervisor import WorkerSupervisor
from .settings import WorkerSettings, load_worker_settings

__all__ = [
    "POOL_CATALOG",
    "PoolDefinition",
    "ResourceAdmission",
    "ResourceClass",
    "WORKER_PROTOCOL_VERSION",
    "WorkerInstanceState",
    "WorkerRegistration",
    "WorkerRegistry",
    "WorkerSettings",
    "WorkerSupervisor",
    "default_pool_counts",
    "load_worker_settings",
]
