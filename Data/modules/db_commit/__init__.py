"""DB Commit Coordinator — serialized COMMIT_WRITE fabric for LEVIATHAN.

Deterministic infrastructure (not an AI agent). One external worker owns
physical bulk SQLite mutations. CONTROL_WRITE remains tiny and direct.
"""

from .types import (
    COMMIT_INTENT_SCHEMA_VERSION,
    AckStatus,
    CommitHealth,
    CommitIntent,
    CommitPriority,
    CommitReceipt,
    CommitReceiptStatus,
    FailureKind,
    WriterAck,
)
from .errors import (
    DbCommitBackpressureError,
    DbCommitError,
    DbCommitSpoolUnavailableError,
    PayloadHashMismatchError,
    UnknownOperationError,
)
from .settings import DbCommitSettings, load_db_commit_settings
from .receipts import CommitReceiptStore
from .spool import CommitSpool, SpoolItem
from .handlers.registry import CommitHandlerRegistry, build_default_registry
from .producer import CommitProducer, SubmitResult
from .writer import DbCommitCoordinator
from .ipc import CommitIpcClient, CommitIpcServer, ipc_endpoint_path
from .status import DbCommitStatus

__all__ = [
    "COMMIT_INTENT_SCHEMA_VERSION",
    "AckStatus",
    "CommitHealth",
    "CommitIntent",
    "CommitPriority",
    "CommitProducer",
    "CommitReceipt",
    "CommitReceiptStatus",
    "CommitReceiptStore",
    "CommitSpool",
    "CommitHandlerRegistry",
    "CommitIpcClient",
    "CommitIpcServer",
    "DbCommitBackpressureError",
    "DbCommitCoordinator",
    "DbCommitError",
    "DbCommitSettings",
    "DbCommitSpoolUnavailableError",
    "DbCommitStatus",
    "FailureKind",
    "PayloadHashMismatchError",
    "SpoolItem",
    "SubmitResult",
    "UnknownOperationError",
    "WriterAck",
    "build_default_registry",
    "ipc_endpoint_path",
    "load_db_commit_settings",
]
