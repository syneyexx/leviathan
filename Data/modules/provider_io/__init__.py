"""Provider I/O execution plane — outbound external API work for LEVIATHAN.

Owned by the ``provider_io`` worker pool under the generic WorkerSupervisor.
The Control Plane submits durable jobs; workers own HTTP/SDK sessions,
retries, circuit breakers, and streaming transport.

Local model residency remains owned by the Model Control Plane.
Bulk dataset downloads remain owned by the dataset worker.
"""

from .errors import ProviderError, ProviderErrorCode
from .facade import ProviderExecutionClient, get_provider_client
from .types import (
    ProviderExecutionResult,
    ProviderRequest,
    StreamEvent,
    StreamEventType,
)

__all__ = [
    "ProviderError",
    "ProviderErrorCode",
    "ProviderExecutionClient",
    "ProviderExecutionResult",
    "ProviderRequest",
    "StreamEvent",
    "StreamEventType",
    "get_provider_client",
]
