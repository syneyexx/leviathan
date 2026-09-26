"""Shared durable I/O, path safety, retry, process helpers, and architecture contracts."""

from .atomic import atomic_write_bytes, atomic_write_text, ensure_dir
from .correlation import CorrelationIds, TraceContext, new_id
from .database_domains import (
    DEFAULT_CONTROL_DB_REL,
    DEFAULT_KNOWLEDGE_DB_REL,
    DEFAULT_LEGACY_DB_REL,
    DEFAULT_MARKET_DB_REL,
    ENV_CONTROL,
    ENV_KNOWLEDGE,
    ENV_LEGACY,
    ENV_MARKET,
    DatabaseDomain,
    DatabasePaths,
    assert_canonical_paths_distinct,
    domain_from_commit_operation,
    resolve_database_paths,
)
from .hashing import sha256_bytes, sha256_file, sha256_text
from .ownership import (
    CANONICAL_OWNERSHIP,
    FORBIDDEN_PRIVATE_DB_FILENAMES,
    SINGLETON_CLASS_OWNERS,
    OwnershipRule,
    ownership_public_dict,
)
from .paths import PathEscapeError, safe_join, safe_relpath
from .process import pid_is_alive, read_pid_file, write_pid_file
from .retry import RetryPolicy, compute_backoff_seconds
from .secrets import looks_like_secret, redact_secrets
from .sqlite_policy import (
    WriteClass,
    control_write,
    ensure_wal,
    is_transient_sqlite_error,
    open_sqlite_connection,
    run_with_busy_retry,
    sqlite_connection,
    sqlite_metrics_snapshot,
    write_transaction,
)

__all__ = [
    "atomic_write_bytes",
    "atomic_write_text",
    "ensure_dir",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "PathEscapeError",
    "safe_join",
    "safe_relpath",
    "pid_is_alive",
    "write_pid_file",
    "read_pid_file",
    "RetryPolicy",
    "compute_backoff_seconds",
    "redact_secrets",
    "looks_like_secret",
    "CorrelationIds",
    "TraceContext",
    "new_id",
    "CANONICAL_OWNERSHIP",
    "FORBIDDEN_PRIVATE_DB_FILENAMES",
    "SINGLETON_CLASS_OWNERS",
    "OwnershipRule",
    "ownership_public_dict",
    "DatabaseDomain",
    "DatabasePaths",
    "DEFAULT_CONTROL_DB_REL",
    "DEFAULT_KNOWLEDGE_DB_REL",
    "DEFAULT_MARKET_DB_REL",
    "DEFAULT_LEGACY_DB_REL",
    "ENV_CONTROL",
    "ENV_KNOWLEDGE",
    "ENV_MARKET",
    "ENV_LEGACY",
    "assert_canonical_paths_distinct",
    "domain_from_commit_operation",
    "resolve_database_paths",
    "WriteClass",
    "control_write",
    "ensure_wal",
    "is_transient_sqlite_error",
    "open_sqlite_connection",
    "run_with_busy_retry",
    "sqlite_connection",
    "sqlite_metrics_snapshot",
    "write_transaction",
]
