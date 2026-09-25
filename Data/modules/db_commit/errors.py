"""DB Commit Coordinator errors."""

from __future__ import annotations


class DbCommitError(Exception):
    code: str = "DB_COMMIT_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code


class DbCommitBackpressureError(DbCommitError):
    code = "DB_COMMIT_BACKPRESSURE"


class DbCommitSpoolUnavailableError(DbCommitError):
    code = "DB_COMMIT_SPOOL_UNAVAILABLE"


class PayloadHashMismatchError(DbCommitError):
    code = "PAYLOAD_HASH_MISMATCH"


class UnknownOperationError(DbCommitError):
    code = "UNKNOWN_OPERATION"


class InvalidIntentError(DbCommitError):
    code = "INVALID_INTENT"


class ForbiddenPayloadPathError(DbCommitError):
    code = "FORBIDDEN_PAYLOAD_PATH"


class TerminalCommitError(DbCommitError):
    """Non-retryable handler failure."""

    code = "TERMINAL_COMMIT_ERROR"
