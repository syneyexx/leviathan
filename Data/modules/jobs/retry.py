"""Retry policy for durable job execution."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class RetryPolicy:
    """Bounded exponential (or linear) backoff with optional jitter."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff: str = "exponential"  # "exponential" | "linear" | "fixed"
    jitter: float = 0.1

    def delay_for_attempt(self, attempt: int) -> float:
        """Return delay seconds before the next attempt (1-indexed attempt that failed)."""
        n = max(1, int(attempt))
        base = max(0.0, float(self.base_delay))
        ceiling = max(base, float(self.max_delay))
        kind = (self.backoff or "exponential").lower()
        if kind == "fixed":
            delay = base
        elif kind == "linear":
            delay = base * n
        else:
            delay = base * (2 ** (n - 1))
        delay = min(delay, ceiling)
        jitter = max(0.0, min(1.0, float(self.jitter)))
        if jitter > 0 and delay > 0:
            spread = delay * jitter
            delay = max(0.0, delay + random.uniform(-spread, spread))
            delay = min(delay, ceiling)
        return delay

    def can_retry(self, attempt_number: int) -> bool:
        return int(attempt_number) < int(self.max_attempts)

    def classify_retryable(self, error: Any = None, *, error_code: str | None = None) -> bool:
        """Heuristic classification: timeouts / transient codes retry; policy rejects do not."""
        code = (error_code or "").strip().upper()
        if code:
            if code in {
                "REJECTED",
                "CANCELLED",
                "NOT_RETRYABLE",
                "VALIDATION_ERROR",
                "PERMISSION_DENIED",
                "APPROVAL_REQUIRED",
            }:
                return False
            if code in {
                "TIMEOUT",
                "TEMPORARY",
                "TRANSIENT",
                "UNAVAILABLE",
                "LEASE_EXPIRED",
                "WORKER_CRASH",
                "RETRYABLE",
            }:
                return True

        if error is None:
            return True

        if isinstance(error, BaseException):
            name = type(error).__name__.upper()
            text = str(error).upper()
        else:
            name = ""
            text = str(error).upper()

        non_retry_tokens = (
            "NOT RETRYABLE",
            "VALIDATION",
            "PERMISSION",
            "APPROVAL",
            "REJECTED",
            "CANCELLED",
            "UNAUTHORIZED",
        )
        if any(tok in text for tok in non_retry_tokens) or any(tok in name for tok in non_retry_tokens):
            return False

        retry_tokens = ("TIMEOUT", "TEMPORARY", "TRANSIENT", "UNAVAILABLE", "CONNECTION", "DEADLOCK")
        if any(tok in text for tok in retry_tokens) or any(tok in name for tok in retry_tokens):
            return True

        # Default: treat unknown failures as retryable until attempts are exhausted.
        return True


DEFAULT_RETRY_POLICY = RetryPolicy()
