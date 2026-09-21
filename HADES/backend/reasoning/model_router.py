"""Central model routing on top of LM Studio OpenAI-compatible endpoints.

Capabilities are not inferred from model names alone. Prefer provider metadata,
explicit settings, or a bounded capability probe.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


FallbackReason = Literal[
    "unavailable",
    "timeout",
    "error",
    "capacity",
    "capability_missing",
    "explicit",
]


@dataclass(slots=True)
class ModelCapabilities:
    model_id: str
    available: bool = True
    context_limit: int | None = None
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None
    supports_streaming: bool | None = None
    source: str = "unknown"  # provider | config | probe | default
    error_count: int = 0
    latency_ms_ema: float | None = None
    last_error: str | None = None
    last_checked_at: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelSelection:
    model_id: str
    reason: str
    profile_hint: str | None = None
    fallback_from: str | None = None
    fallback_reason: FallbackReason | None = None
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _CapacityLane:
    """Dynamic capacity lane: live limit changes do not drop waiters or reset inflight.

    ``limit is None`` means Unlimited — never coerced to a magic large integer.
    """

    def __init__(self, limit: int | None = 1) -> None:
        self.limit: int | None = None if limit is None else max(0, int(limit))
        self.inflight = 0
        self.waiters = 0
        self._cond: asyncio.Condition | None = None

    def _ensure(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    def set_limit(self, limit: int | None) -> None:
        self.limit = None if limit is None else max(0, int(limit))
        cond = self._cond
        if cond is None:
            return

        async def _notify() -> None:
            async with cond:
                cond.notify_all()

        try:
            asyncio.get_running_loop().create_task(_notify())
        except RuntimeError:
            pass

    async def acquire(self, *, timeout_s: float | None = None) -> None:
        cond = self._ensure()
        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        async with cond:
            self.waiters += 1
            try:
                while self.limit is not None and self.inflight >= int(self.limit):
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("capacity wait timed out")
                        try:
                            await asyncio.wait_for(cond.wait(), timeout=remaining)
                        except asyncio.TimeoutError as exc:
                            raise TimeoutError("capacity wait timed out") from exc
                    else:
                        await cond.wait()
                self.inflight += 1
            finally:
                self.waiters = max(0, self.waiters - 1)

    async def release(self) -> None:
        cond = self._ensure()
        async with cond:
            self.inflight = max(0, self.inflight - 1)
            cond.notify_all()


class ModelRouter:
    """Select models per role/task with shared capacity and fallback order."""

    def __init__(self) -> None:
        self._caps: dict[str, ModelCapabilities] = {}
        self._lanes: dict[str, _CapacityLane] = {}
        self._locks: dict[str, asyncio.Semaphore] = {}  # legacy alias kept for tests inspecting attrs
        self._inflight: dict[str, int] = {}
        self._lock = None  # bound per running loop
        self._global_lane = _CapacityLane(limit=None)

    def remember_provider_models(self, models: list[dict[str, Any]]) -> None:
        for item in models:
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            caps = self._caps.get(model_id) or ModelCapabilities(model_id=model_id, source="provider")
            caps.available = True
            caps.source = "provider"
            # OpenAI-compatible payloads sometimes include max_model_len / context_length.
            for key in ("max_model_len", "context_length", "max_context_length", "context_window"):
                if item.get(key) is not None:
                    try:
                        caps.context_limit = int(item[key])
                    except Exception:
                        pass
            meta = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
            if "tools" in meta:
                caps.supports_tools = bool(meta.get("tools"))
            if "structured_output" in meta or "json" in meta:
                caps.supports_structured_output = bool(meta.get("structured_output", meta.get("json")))
            if "streaming" in meta:
                caps.supports_streaming = bool(meta.get("streaming"))
            caps.last_checked_at = time.time()
            self._caps[model_id] = caps

    def apply_config_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        for model_id, values in (overrides or {}).items():
            caps = self._caps.get(model_id) or ModelCapabilities(model_id=model_id, source="config")
            if "context_limit" in values and values["context_limit"] is not None:
                caps.context_limit = int(values["context_limit"])
            if "supports_tools" in values:
                caps.supports_tools = bool(values["supports_tools"])
            if "supports_structured_output" in values:
                caps.supports_structured_output = bool(values["supports_structured_output"])
            if "supports_streaming" in values:
                caps.supports_streaming = bool(values["supports_streaming"])
            caps.source = "config" if caps.source == "unknown" else caps.source
            caps.notes.append("config_override")
            self._caps[model_id] = caps

    def record_result(self, model_id: str, *, ok: bool, latency_ms: float | None = None, error: str | None = None) -> None:
        caps = self._caps.get(model_id) or ModelCapabilities(model_id=model_id, source="default")
        if ok:
            if latency_ms is not None:
                if caps.latency_ms_ema is None:
                    caps.latency_ms_ema = float(latency_ms)
                else:
                    caps.latency_ms_ema = (0.7 * caps.latency_ms_ema) + (0.3 * float(latency_ms))
        else:
            caps.error_count += 1
            caps.last_error = (error or "error")[:500]
            if caps.error_count >= 3:
                caps.available = False
                caps.notes.append("marked_unavailable_after_errors")
        caps.last_checked_at = time.time()
        self._caps[model_id] = caps

    def mark_available(self, model_id: str, available: bool = True) -> None:
        caps = self._caps.get(model_id) or ModelCapabilities(model_id=model_id, source="default")
        caps.available = available
        if available:
            caps.error_count = 0
        self._caps[model_id] = caps

    def get_capabilities(self, model_id: str) -> ModelCapabilities:
        return self._caps.get(model_id) or ModelCapabilities(model_id=model_id, source="default")

    def _ensure_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = getattr(self, "_loop_locks", {}).get(id(loop))
        if lock is None:
            if not hasattr(self, "_loop_locks"):
                self._loop_locks = {}
            lock = asyncio.Lock()
            self._loop_locks[id(loop)] = lock
        return lock

    def reset_capacity(self) -> None:
        """Drop lane state (tests / recovery). Inflight work must be stopped first."""
        self._lanes.clear()
        self._locks.clear()
        self._inflight.clear()
        self._global_lane = _CapacityLane(limit=self._global_lane.limit)

    def set_global_limit(self, limit: int | None) -> None:
        """Live global concurrency change — waiters re-check; inflight is preserved."""
        self._global_lane.set_limit(limit)

    def _lane(self, key: str, limit: int | None) -> _CapacityLane:
        # Never replace an in-use lane: recreating drops waiters and leaks holds.
        lane = self._lanes.get(key)
        if lane is None:
            lane = _CapacityLane(limit)
            self._lanes[key] = lane
        else:
            # Update limit in place so live setting changes apply without losing waiters.
            if lane.limit != (None if limit is None else max(0, int(limit))):
                lane.set_limit(limit)
        return lane

    def _semaphore(self, key: str, limit: int) -> asyncio.Semaphore:
        """Legacy helper kept for older tests; prefer acquire/release lanes."""
        sem = self._locks.get(key)
        if sem is None:
            sem = asyncio.Semaphore(max(1, int(limit)))
            setattr(sem, "_hades_limit", max(1, int(limit)))
            self._locks[key] = sem
        return sem

    async def acquire(
        self,
        model_id: str,
        *,
        endpoint: str,
        limit: int | None = 1,
        timeout_s: float | None = None,
    ) -> None:
        """Acquire endpoint/model capacity. ``limit=None`` means Unlimited for that lane."""
        key = f"{endpoint}::{model_id}"
        # Global lane first (None = unlimited shared ceiling).
        await self._global_lane.acquire(timeout_s=timeout_s)
        try:
            await self._lane(key, limit).acquire(timeout_s=timeout_s)
        except Exception:
            await self._global_lane.release()
            raise
        async with self._ensure_lock():
            self._inflight[key] = self._inflight.get(key, 0) + 1

    async def release(self, model_id: str, *, endpoint: str) -> None:
        key = f"{endpoint}::{model_id}"
        lane = self._lanes.get(key)
        if lane is not None:
            await lane.release()
        await self._global_lane.release()
        # Legacy semaphore path
        sem = self._locks.get(key)
        if sem is not None:
            try:
                sem.release()
            except ValueError:
                pass
        async with self._ensure_lock():
            self._inflight[key] = max(0, self._inflight.get(key, 0) - 1)

    def capacity_overview(self) -> dict[str, Any]:
        return {
            "global": {"limit": self._global_lane.limit, "inflight": self._global_lane.inflight, "waiters": self._global_lane.waiters},
            "lanes": {
                key: {"limit": lane.limit, "inflight": lane.inflight, "waiters": lane.waiters}
                for key, lane in self._lanes.items()
            },
            "inflight": dict(self._inflight),
        }

    def select(
        self,
        *,
        default_model: str | None,
        explicit_model: str | None = None,
        role_model: str | None = None,
        fallback_order: list[str] | None = None,
        require_tools: bool = False,
        require_structured: bool = False,
        endpoint: str | None = None,
        allow_cloud: bool = False,
        known_local_ids: set[str] | None = None,
    ) -> ModelSelection:
        """Explicit choice wins; then role preference; then default; then fallbacks.

        Fallbacks never silently send local data to a cloud endpoint.
        Invalid input is not retried endlessly across models — caller must pass a
        bounded fallback_order.
        """
        local_ids = known_local_ids or set(self._caps.keys())

        def _is_cloud(model_id: str) -> bool:
            lower = model_id.lower()
            return any(token in lower for token in ("openai/", "anthropic/", "google/", "cloud/", "azure"))

        def _eligible(model_id: str) -> tuple[bool, str]:
            if not model_id:
                return False, "empty"
            if not allow_cloud and _is_cloud(model_id):
                return False, "cloud_blocked"
            caps = self.get_capabilities(model_id)
            if known_local_ids is not None and model_id not in known_local_ids and model_id not in self._caps:
                # Unknown but explicitly requested — still allow; honest missing handled by caller.
                pass
            if caps.available is False:
                return False, "unavailable"
            if require_tools and caps.supports_tools is False:
                return False, "capability_missing"
            if require_structured and caps.supports_structured_output is False:
                return False, "capability_missing"
            return True, "ok"

        # 1) Explicit conversation/task choice is leading.
        if explicit_model:
            ok, why = _eligible(explicit_model)
            if ok:
                return ModelSelection(
                    model_id=explicit_model,
                    reason="explicit_choice",
                    endpoint=endpoint,
                    metadata={"local_ids": sorted(local_ids)[:20]},
                )
            # Explicit but currently unavailable → try fallbacks, record reason.
            for candidate in fallback_order or []:
                if candidate == explicit_model:
                    continue
                ok2, _ = _eligible(candidate)
                if ok2:
                    return ModelSelection(
                        model_id=candidate,
                        reason="fallback_after_explicit_unavailable",
                        fallback_from=explicit_model,
                        fallback_reason="unavailable" if why == "unavailable" else "capability_missing",
                        endpoint=endpoint,
                    )
            return ModelSelection(
                model_id=explicit_model,
                reason="explicit_choice_unavailable",
                endpoint=endpoint,
                metadata={"eligible": False, "why": why},
            )

        # 2) Role-specific preference
        if role_model:
            ok, why = _eligible(role_model)
            if ok:
                return ModelSelection(model_id=role_model, reason="role_preference", profile_hint=None, endpoint=endpoint)

        # 3) Default
        if default_model:
            ok, why = _eligible(default_model)
            if ok:
                return ModelSelection(model_id=default_model, reason="default", endpoint=endpoint)

        # 4) Fallback order
        chain = list(fallback_order or [])
        if default_model and default_model not in chain:
            chain.insert(0, default_model)
        for candidate in chain:
            ok, why = _eligible(candidate)
            if ok:
                return ModelSelection(
                    model_id=candidate,
                    reason="fallback",
                    fallback_from=default_model,
                    fallback_reason="unavailable",
                    endpoint=endpoint,
                )

        # Honest missing model
        missing = explicit_model or role_model or default_model or (fallback_order[0] if fallback_order else "")
        return ModelSelection(
            model_id=missing or "",
            reason="no_eligible_model",
            endpoint=endpoint,
            metadata={"message": "Geen geschikt lokaal model beschikbaar."},
        )

    def lookup_empirical_recommendation(
        self,
        *,
        task_type: str,
        metric: str = "pass",
        matrix_lookup: Any | None = None,
    ) -> dict[str, Any]:
        """D7: read-only capability-matrix lookup. No hardcoded model IDs.

        ``matrix_lookup`` should be a callable(task_type, metric) -> dict|None
        (typically Gen2Store.best_model_for / eval_lab.recommend_model).
        Without data/callable → fail clean with source=no_empirical_data.
        """
        if not callable(matrix_lookup):
            return {
                "model_id": None,
                "task_type": task_type,
                "metric": metric,
                "score": None,
                "samples": 0,
                "source": "no_empirical_data",
                "note": "No matrix lookup provided; refuse to hardcode a model.",
            }
        try:
            row = matrix_lookup(task_type, metric)
        except TypeError:
            # recommend_model(store, task_type, metric=...) style via partial from caller
            row = matrix_lookup(task_type)
        except Exception as exc:  # noqa: BLE001
            return {
                "model_id": None,
                "task_type": task_type,
                "metric": metric,
                "score": None,
                "samples": 0,
                "source": "no_empirical_data",
                "error": f"{type(exc).__name__}:{exc}"[:300],
                "note": "Matrix lookup failed cleanly — no hardcoded fallback model.",
            }
        if not row or not (row.get("model_id") if isinstance(row, dict) else None):
            return {
                "model_id": None,
                "task_type": task_type,
                "metric": metric,
                "score": None,
                "samples": 0,
                "source": "no_empirical_data",
                "note": "Run Eval Lab first; no hardcoded model preference.",
            }
        data = dict(row)
        data.setdefault("source", "empirical_matrix")
        data.setdefault("task_type", task_type)
        data.setdefault("metric", metric)
        # Never invent availability — caller still checks provider presence.
        return data


# Process-wide router instance (tests may replace).
model_router = ModelRouter()
