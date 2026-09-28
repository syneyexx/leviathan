"""Typed file I/O errors — reuse codes; do not proliferate near-duplicates."""

from __future__ import annotations

from enum import Enum


class FileIoErrorCode(str, Enum):
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_ACCESS_DENIED = "FILE_ACCESS_DENIED"
    FILE_TOO_LARGE_INLINE = "FILE_TOO_LARGE_INLINE"
    FILE_IO_UNAVAILABLE = "FILE_IO_UNAVAILABLE"
    FILE_CHANGED_DURING_READ = "FILE_CHANGED_DURING_READ"
    FILE_COPY_FAILED = "FILE_COPY_FAILED"
    FILE_HASH_FAILED = "FILE_HASH_FAILED"
    CSV_PARSE_FAILED = "CSV_PARSE_FAILED"
    CSV_PROFILE_FAILED = "CSV_PROFILE_FAILED"
    PARQUET_UNAVAILABLE = "PARQUET_UNAVAILABLE"
    PARQUET_PROCESS_FAILED = "PARQUET_PROCESS_FAILED"
    FILESYSTEM_SCAN_LIMIT_EXCEEDED = "FILESYSTEM_SCAN_LIMIT_EXCEEDED"
    PATH_OUTSIDE_ROOT = "PATH_OUTSIDE_ROOT"
    SYMLINK_ESCAPE = "SYMLINK_ESCAPE"
    CANCELLED = "CANCELLED"
    WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    BINARY_REFUSED = "BINARY_REFUSED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"


class FileIoError(Exception):
    def __init__(self, code: FileIoErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.code = code.value if isinstance(code, FileIoErrorCode) else str(code)
        self.message = message

    def public_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}
