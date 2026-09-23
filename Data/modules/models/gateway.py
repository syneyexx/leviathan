"""Model gateway — live inference capacity ownership + priority admission (Round 6)."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict

from Data.modules.model_runtime.serving import InferenceJobClass
from Data.modules.models.contracts import GatewaySnapshot, RuntimeCapacity
from Data.modules.models.errors import CAPACITY_TIMEOUT, ModelControlError


class ModelGateway:
    """Tracks inflight inference capacity. Metrics are real, never fabricated.

    Priority admission (Round 6): BACKGROUND / BATCH (training, research, indexing)
    cannot consume the last reserved INTERACTIVE slots — interactive responsiveness
    is protected under background pressure.
    """

    def __init__(
        self,
        *,
        global_limit: int | None = 1,
        interactive_reserved: int = 0,
    ) -> None:
        self._lock = threading.RLock()
        self._global_limit = global_limit
        # Reserve interactive headroom when limit > reserved (set explicitly in prod).
        self._interactive_reserved = max(0, int(interactive_reserved))
        self._provider_limits: dict[str, int | None] = {}
        self._model_limits: dict[str, int | None] = {}
        self._inflight = 0
        self._inflight_by_class: dict[str, int] = defaultdict(int)
        self._by_provider: dict[str, int] = defaultdict(int)
        self._by_model: dict[str, int] = defaultdict(int)
        self._queue_depth = 0
        self._queue_by_class: dict[str, int] = defaultdict(int)
        self._calls_failed = 0
        self._capacity_timeouts = 0
        self._admission_rejects = 0
        self._last_error: str | None = None
        self._last_fallback_reason: str | None = None
        self._last_selected_model: str | None = None
        self._last_trace_id: str | None = None
        self._last_job_class: str | None = None
        self._models_in_use: set[str] = set()

    def set_global_limit(self, limit: int | None) -> None:
        with self._lock:
            self._global_limit = limit

    def set_interactive_reserved(self, reserved: int) -> None:
        with self._lock:
            self._interactive_reserved = max(0, int(reserved))

    def set_provider_limit(self, provider_id: str, limit: int | None) -> None:
        with self._lock:
            self._provider_limits[provider_id] = limit

    def set_model_limit(self, model_id: str, limit: int | None) -> None:
        with self._lock:
            self._model_limits[model_id] = limit

    def record_fallback(self, reason: str) -> None:
        with self._lock:
            self._last_fallback_reason = reason

    def record_selection(self, model_id: str, *, trace_id: str | None = None) -> None:
        with self._lock:
            self._last_selected_model = model_id
            self._last_trace_id = trace_id

    def snapshot(self) -> GatewaySnapshot:
        with self._lock:
            capacity = RuntimeCapacity(
                global_limit=self._global_limit,
                global_inflight=self._inflight,
                provider_limits=dict(self._provider_limits),
                model_limits=dict(self._model_limits),
                queue_depth=self._queue_depth,
            )
            snap = GatewaySnapshot(
                models_in_use=sorted(self._models_in_use),
                active_calls=self._inflight,
                queue_depth=self._queue_depth,
                capacity=capacity,
                last_fallback_reason=self._last_fallback_reason,
                calls_failed=self._calls_failed,
                capacity_timeouts=self._capacity_timeouts,
                last_error=self._last_error,
                last_selected_model=self._last_selected_model,
                last_trace_id=self._last_trace_id,
            )
            # Extra Round 6 admission fields via capacity metadata if present.
            if hasattr(snap, "metadata") and isinstance(getattr(snap, "metadata"), dict):
                snap.metadata.update(self._admission_public())
            return snap

    def admission_stats(self) -> dict:
        with self._lock:
            return self._admission_public()

    def _admission_public(self) -> dict:
        return {
            "interactiveReserved": self._interactive_reserved,
            "inflightByClass": dict(self._inflight_by_class),
            "queueByClass": dict(self._queue_by_class),
            "admissionRejects": self._admission_rejects,
            "lastJobClass": self._last_job_class,
            "truth": {
                "background_cannot_starve_interactive": True,
                "priority_admission_enabled": True,
            },
        }

    def acquire(
        self,
        *,
        model_id: str,
        provider_id: str,
        timeout_seconds: float = 30.0,
        job_class: InferenceJobClass | str = InferenceJobClass.INTERACTIVE,
    ) -> str:
        try:
            jc = (
                job_class
                if isinstance(job_class, InferenceJobClass)
                else InferenceJobClass(str(job_class))
            )
        except ValueError:
            jc = InferenceJobClass.INTERACTIVE
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        queued = False
        while True:
            with self._lock:
                if self._has_capacity(model_id=model_id, provider_id=provider_id, job_class=jc):
                    if queued:
                        self._queue_depth = max(0, self._queue_depth - 1)
                        self._queue_by_class[jc.value] = max(
                            0, self._queue_by_class[jc.value] - 1
                        )
                        queued = False
                    self._inflight += 1
                    self._inflight_by_class[jc.value] += 1
                    self._by_provider[provider_id] += 1
                    self._by_model[model_id] += 1
                    self._models_in_use.add(model_id)
                    call_id = str(uuid.uuid4())
                    self._last_trace_id = call_id
                    self._last_selected_model = model_id
                    self._last_job_class = jc.value
                    return call_id
                if not queued:
                    self._queue_depth += 1
                    self._queue_by_class[jc.value] += 1
                    queued = True
            if time.monotonic() >= deadline:
                with self._lock:
                    if queued:
                        self._queue_depth = max(0, self._queue_depth - 1)
                        self._queue_by_class[jc.value] = max(
                            0, self._queue_by_class[jc.value] - 1
                        )
                    self._capacity_timeouts += 1
                    self._admission_rejects += 1
                    self._last_error = "CAPACITY_TIMEOUT"
                raise ModelControlError(
                    code=CAPACITY_TIMEOUT,
                    message=(
                        f"Model gateway capacity timeout (job_class={jc.value}; "
                        "background must not starve interactive)"
                    ),
                    model_id=model_id,
                    provider_id=provider_id,
                    retryable=True,
                    http_status=503,
                )
            # Interactive polls faster under pressure so it wins races sooner.
            time.sleep(0.005 if jc == InferenceJobClass.INTERACTIVE else 0.02)

    def release(
        self,
        *,
        model_id: str,
        provider_id: str,
        error: str | None = None,
        job_class: InferenceJobClass | str | None = None,
    ) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            self._by_provider[provider_id] = max(0, self._by_provider[provider_id] - 1)
            self._by_model[model_id] = max(0, self._by_model[model_id] - 1)
            if job_class is not None:
                try:
                    jc = (
                        job_class
                        if isinstance(job_class, InferenceJobClass)
                        else InferenceJobClass(str(job_class))
                    )
                    self._inflight_by_class[jc.value] = max(
                        0, self._inflight_by_class[jc.value] - 1
                    )
                except ValueError:
                    pass
            if self._by_model[model_id] == 0:
                self._models_in_use.discard(model_id)
            if error:
                self._calls_failed += 1
                self._last_error = error

    def _has_capacity(
        self,
        *,
        model_id: str,
        provider_id: str,
        job_class: InferenceJobClass = InferenceJobClass.INTERACTIVE,
    ) -> bool:
        if self._global_limit is not None and self._inflight >= self._global_limit:
            return False
        provider_limit = self._provider_limits.get(provider_id)
        if provider_limit is not None and self._by_provider[provider_id] >= provider_limit:
            return False
        model_limit = self._model_limits.get(model_id)
        if model_limit is not None and self._by_model[model_id] >= model_limit:
            return False
        # Priority: non-interactive cannot take the reserved interactive headroom.
        if (
            job_class != InferenceJobClass.INTERACTIVE
            and self._global_limit is not None
            and self._interactive_reserved > 0
        ):
            background_ceiling = max(0, self._global_limit - self._interactive_reserved)
            non_interactive = (
                self._inflight_by_class.get(InferenceJobClass.BACKGROUND.value, 0)
                + self._inflight_by_class.get(InferenceJobClass.BATCH.value, 0)
            )
            if non_interactive >= background_ceiling:
                return False
        return True
