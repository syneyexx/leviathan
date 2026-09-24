"""Cross-provider execution policy: deadlines, retries, rate limits, circuits."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.common.retry import RetryPolicy, compute_backoff_seconds

from .errors import ProviderError, ProviderErrorCode, RETRYABLE_CODES


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class ProviderIoSettings:
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0
    total_deadline_seconds: float = 120.0
    stream_idle_timeout_seconds: float = 60.0
    max_attempts: int = 4
    retry_base_seconds: float = 0.5
    retry_max_seconds: float = 30.0
    retry_jitter_ratio: float = 0.25
    per_provider_concurrency: int = 4
    circuit_failure_threshold: int = 5
    circuit_cooldown_seconds: float = 30.0
    circuit_half_open_max: int = 1
    max_buffered_stream_events: int = 2000
    max_response_bytes: int = 8_000_000
    queue_capacity: int = 500

    @classmethod
    def load(cls) -> ProviderIoSettings:
        return cls(
            connect_timeout_seconds=_env_float("LEVIATHAN_PROVIDER_CONNECT_TIMEOUT", 10.0),
            read_timeout_seconds=_env_float("LEVIATHAN_PROVIDER_READ_TIMEOUT", 60.0),
            total_deadline_seconds=_env_float("LEVIATHAN_PROVIDER_DEADLINE", 120.0),
            stream_idle_timeout_seconds=_env_float("LEVIATHAN_PROVIDER_STREAM_IDLE_TIMEOUT", 60.0),
            max_attempts=_env_int("LEVIATHAN_PROVIDER_MAX_ATTEMPTS", 4),
            retry_base_seconds=_env_float("LEVIATHAN_PROVIDER_RETRY_BASE", 0.5),
            retry_max_seconds=_env_float("LEVIATHAN_PROVIDER_RETRY_MAX", 30.0),
            per_provider_concurrency=_env_int("LEVIATHAN_PROVIDER_CONCURRENCY", 4),
            circuit_failure_threshold=_env_int("LEVIATHAN_PROVIDER_CIRCUIT_THRESHOLD", 5),
            circuit_cooldown_seconds=_env_float("LEVIATHAN_PROVIDER_CIRCUIT_COOLDOWN", 30.0),
            max_buffered_stream_events=_env_int("LEVIATHAN_PROVIDER_STREAM_BUFFER", 2000),
            max_response_bytes=_env_int("LEVIATHAN_PROVIDER_MAX_RESPONSE_BYTES", 8_000_000),
            queue_capacity=_env_int("LEVIATHAN_PROVIDER_QUEUE_CAPACITY", 500),
        )

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=self.max_attempts,
            base_seconds=self.retry_base_seconds,
            max_seconds=self.retry_max_seconds,
            jitter_ratio=self.retry_jitter_ratio,
        )


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    provider: str
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    half_open_max: int = 1
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    opened_at: float = 0.0
    half_open_inflight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def allow(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self.state == CircuitState.OPEN:
                if now - self.opened_at >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_inflight = 0
                else:
                    raise ProviderError(
                        ProviderErrorCode.PROVIDER_CIRCUIT_OPEN,
                        f"Circuit open for provider {self.provider}",
                        provider=self.provider,
                        retryable=True,
                        retry_after_seconds=max(
                            0.0, self.cooldown_seconds - (now - self.opened_at)
                        ),
                    )
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_inflight >= self.half_open_max:
                    raise ProviderError(
                        ProviderErrorCode.PROVIDER_CIRCUIT_OPEN,
                        f"Circuit half-open probe busy for {self.provider}",
                        provider=self.provider,
                        retryable=True,
                    )
                self.half_open_inflight += 1

    def record_success(self) -> None:
        with self._lock:
            self.failure_count = 0
            self.half_open_inflight = 0
            self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                self.half_open_inflight = 0
                return
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()

    def public_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "provider": self.provider,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "opened_at": self.opened_at or None,
            }


class ProviderConcurrencyGate:
    """Process-local per-provider concurrency. Cross-process limits use pool size."""

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def _sem(self, provider: str) -> threading.Semaphore:
        with self._lock:
            if provider not in self._semaphores:
                self._semaphores[provider] = threading.Semaphore(self._limit)
            return self._semaphores[provider]

    def acquire(self, provider: str, *, timeout: float | None = None) -> bool:
        return self._sem(provider).acquire(timeout=timeout)

    def release(self, provider: str) -> None:
        self._sem(provider).release()


class RateLimitTracker:
    """Tracks Retry-After and recent rate-limit hits per provider (process-local)."""

    def __init__(self) -> None:
        self._blocked_until: dict[str, float] = {}
        self._recent: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=64))
        self._lock = threading.Lock()

    def observe_rate_limit(self, provider: str, *, retry_after: float | None) -> None:
        with self._lock:
            now = time.monotonic()
            wait = float(retry_after) if retry_after is not None else 5.0
            self._blocked_until[provider] = max(
                self._blocked_until.get(provider, 0.0), now + max(0.0, wait)
            )
            self._recent[provider].append(now)

    def wait_seconds(self, provider: str) -> float:
        with self._lock:
            until = self._blocked_until.get(provider, 0.0)
            return max(0.0, until - time.monotonic())

    def public_dict(self, provider: str) -> dict[str, Any]:
        with self._lock:
            return {
                "provider": provider,
                "blocked_for_seconds": max(
                    0.0, self._blocked_until.get(provider, 0.0) - time.monotonic()
                ),
                "recent_hits": len(self._recent.get(provider, ())),
            }


@dataclass
class DeadlineBudget:
    """Total wall-clock budget for a logical request (not reset per retry)."""

    total_seconds: float
    started_at: float = field(default_factory=time.monotonic)
    queue_wait_seconds: float = 0.0

    def remaining(self) -> float:
        return max(0.0, self.total_seconds - (time.monotonic() - self.started_at))

    def raise_if_exhausted(self) -> None:
        if self.remaining() <= 0:
            raise ProviderError(
                ProviderErrorCode.EXECUTION_DEADLINE_EXCEEDED,
                "Provider execution deadline exceeded",
                retryable=False,
            )

    def timeout_for_attempt(self, *, connect: float, read: float) -> tuple[float, float]:
        rem = self.remaining()
        if rem <= 0:
            self.raise_if_exhausted()
        return (min(connect, rem), min(read, rem))


class ProviderPolicyRegistry:
    """Process-local shared policy objects for one provider_io worker."""

    def __init__(self, settings: ProviderIoSettings | None = None) -> None:
        self.settings = settings or ProviderIoSettings.load()
        self.circuits: dict[str, CircuitBreaker] = {}
        self.concurrency = ProviderConcurrencyGate(self.settings.per_provider_concurrency)
        self.rate_limits = RateLimitTracker()
        self._lock = threading.Lock()
        self.telemetry: dict[str, Any] = {
            "calls": 0,
            "success": 0,
            "failure": 0,
            "cancelled": 0,
            "retries": 0,
            "rate_limited": 0,
            "circuit_open": 0,
        }

    def circuit(self, provider: str) -> CircuitBreaker:
        with self._lock:
            if provider not in self.circuits:
                self.circuits[provider] = CircuitBreaker(
                    provider=provider,
                    failure_threshold=self.settings.circuit_failure_threshold,
                    cooldown_seconds=self.settings.circuit_cooldown_seconds,
                    half_open_max=self.settings.circuit_half_open_max,
                )
            return self.circuits[provider]

    def should_retry(
        self,
        error: ProviderError,
        *,
        attempt: int,
        emitted_output: bool,
        budget: DeadlineBudget,
        idempotency_class: str,
    ) -> bool:
        if emitted_output:
            # Never transparently restart after semantic tokens left the worker.
            return False
        if attempt + 1 >= self.settings.max_attempts:
            return False
        if budget.remaining() <= 0.05:
            return False
        if error.code not in RETRYABLE_CODES and not error.retryable:
            return False
        if error.code == ProviderErrorCode.PROVIDER_AUTH_FAILED:
            return False
        if (
            idempotency_class == "NON_IDEMPOTENT_WRITE"
            and error.code
            not in {
                ProviderErrorCode.PROVIDER_TIMEOUT,
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
            }
        ):
            # Unknown outcome on mutation: do not blindly repeat.
            if error.http_status is None:
                return False
        return True

    def backoff(self, attempt: int, *, retry_after: float | None = None) -> float:
        return compute_backoff_seconds(
            attempt,
            policy=self.settings.retry_policy(),
            retry_after=retry_after,
        )

    def public_status(self) -> dict[str, Any]:
        with self._lock:
            circuits = {k: v.public_dict() for k, v in self.circuits.items()}
        return {
            "settings": {
                "connect_timeout_seconds": self.settings.connect_timeout_seconds,
                "read_timeout_seconds": self.settings.read_timeout_seconds,
                "total_deadline_seconds": self.settings.total_deadline_seconds,
                "max_attempts": self.settings.max_attempts,
                "per_provider_concurrency": self.settings.per_provider_concurrency,
                "queue_capacity": self.settings.queue_capacity,
            },
            "telemetry": dict(self.telemetry),
            "circuits": circuits,
        }
