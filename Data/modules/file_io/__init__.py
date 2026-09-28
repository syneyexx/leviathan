"""Generic heavy filesystem execution owner — streaming utilities and ops.

Domain workers (dataset, source_ingestion, knowledge, …) keep semantic ownership.
This package implements canonical streaming/chunked primitives for generic
file.* / filesystem.scan capabilities executed by the ``file_io`` worker pool.
"""

from __future__ import annotations

from .errors import FileIoError, FileIoErrorCode
from .ops import (
    copy_file,
    hash_file,
    parse_csv,
    process_parquet,
    profile_csv,
    read_text_streaming,
    scan_filesystem,
    write_text_streaming,
)
from .spill import maybe_spill_result

__all__ = [
    "FileIoError",
    "FileIoErrorCode",
    "copy_file",
    "hash_file",
    "maybe_spill_result",
    "parse_csv",
    "process_parquet",
    "profile_csv",
    "read_text_streaming",
    "scan_filesystem",
    "write_text_streaming",
]
