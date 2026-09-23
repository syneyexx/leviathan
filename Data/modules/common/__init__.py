"""Shared durable I/O, path safety, retry, process helpers, and architecture contracts."""

from .atomic import atomic_write_bytes, atomic_write_text, ensure_dir
from .correlation import CorrelationIds, TraceContext, new_id
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
]
