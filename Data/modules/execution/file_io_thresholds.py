"""Centralized thresholds for size-aware filesystem workload classification.

Conservative defaults preserve current FunctionRuntime safe ceilings
(text read ~1 MiB, CSV inspect ~2 MiB). Large / recursive / unbounded work
escalates to EXTERNAL_REQUIRED → file_io worker.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class FileIoThresholds:
    """Canonical inline ceilings for filesystem capabilities."""

    max_inline_read_bytes: int = 1_000_000
    max_inline_write_bytes: int = 1_000_000
    max_inline_hash_bytes: int = 1_000_000
    max_inline_copy_bytes: int = 1_000_000
    max_inline_csv_bytes: int = 2_000_000
    max_inline_csv_rows: int = 20
    max_inline_directory_entries: int = 200
    max_inline_recursion_depth: int = 0  # recursive=true always escalates
    max_inline_scanned_bytes: int = 8_000_000
    max_inline_result_bytes: int = 256_000
    max_inline_scan_duration_ms: int = 2_000
    stream_chunk_bytes: int = 1_048_576
    csv_field_max_bytes: int = 8_388_608

    def public_dict(self) -> dict[str, Any]:
        return {
            "max_inline_read_bytes": self.max_inline_read_bytes,
            "max_inline_write_bytes": self.max_inline_write_bytes,
            "max_inline_hash_bytes": self.max_inline_hash_bytes,
            "max_inline_copy_bytes": self.max_inline_copy_bytes,
            "max_inline_csv_bytes": self.max_inline_csv_bytes,
            "max_inline_csv_rows": self.max_inline_csv_rows,
            "max_inline_directory_entries": self.max_inline_directory_entries,
            "max_inline_recursion_depth": self.max_inline_recursion_depth,
            "max_inline_scanned_bytes": self.max_inline_scanned_bytes,
            "max_inline_result_bytes": self.max_inline_result_bytes,
            "max_inline_scan_duration_ms": self.max_inline_scan_duration_ms,
            "stream_chunk_bytes": self.stream_chunk_bytes,
            "csv_field_max_bytes": self.csv_field_max_bytes,
        }


_CACHED: FileIoThresholds | None = None


def load_file_io_thresholds(*, refresh: bool = False) -> FileIoThresholds:
    """Load thresholds from environment (cached)."""
    global _CACHED
    if _CACHED is not None and not refresh:
        return _CACHED
    _CACHED = FileIoThresholds(
        max_inline_read_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_READ_BYTES", 1_000_000),
        max_inline_write_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_WRITE_BYTES", 1_000_000),
        max_inline_hash_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_HASH_BYTES", 1_000_000),
        max_inline_copy_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_COPY_BYTES", 1_000_000),
        max_inline_csv_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_CSV_BYTES", 2_000_000),
        max_inline_csv_rows=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_CSV_ROWS", 20),
        max_inline_directory_entries=_env_int(
            "LEVIATHAN_FILE_IO_MAX_INLINE_DIRECTORY_ENTRIES", 200
        ),
        max_inline_recursion_depth=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_RECURSION_DEPTH", 0),
        max_inline_scanned_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_SCANNED_BYTES", 8_000_000),
        max_inline_result_bytes=_env_int("LEVIATHAN_FILE_IO_MAX_INLINE_RESULT_BYTES", 256_000),
        max_inline_scan_duration_ms=_env_int(
            "LEVIATHAN_FILE_IO_MAX_INLINE_SCAN_DURATION_MS", 2_000
        ),
        stream_chunk_bytes=_env_int("LEVIATHAN_FILE_IO_STREAM_CHUNK_BYTES", 1_048_576),
        csv_field_max_bytes=_env_int("LEVIATHAN_FILE_IO_CSV_FIELD_MAX_BYTES", 8_388_608),
    )
    return _CACHED


# Capabilities owned by the generic file_io worker when externally queued.
FILE_IO_CAPABILITIES: frozenset[str] = frozenset(
    {
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
    }
)

# Always EXTERNAL_REQUIRED at the static baseline (never inline in API).
FILE_IO_ALWAYS_EXTERNAL: frozenset[str] = frozenset(
    {
        "file.parse_csv",
        "file.profile_csv",
        "file.process_parquet",
        "filesystem.scan",
    }
)
