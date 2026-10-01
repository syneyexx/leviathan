"""Capability probing — tiny, cancellable, cached.

Probes measure real transport behavior. Declared config alone never upgrades
a capability to SUPPORTED. Provider offline/auth/timeout ≠ UNSUPPORTED.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable

from Data.modules.models.capability_vocabulary import (
    CANONICAL_CAPABILITIES,
    normalize_capability_name,
)
from Data.modules.models.contracts import CapabilityState, VerifiedCapability
from Data.modules.models.errors import (
    MODEL_PROBE_CANCELLED,
    PROVIDER_AUTH_FAILED,
    PROVIDER_OFFLINE,
    REQUEST_TIMEOUT,
    ModelControlError,
)
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


# Default probe set — every capability Leviathan may claim as verified must
# have a real probe path or return UNMEASURED honestly.
DEFAULT_PROBE_CAPABILITIES = [
    "chat",
    "streaming",
    "structuredOutput",
    "jsonSchemaResponse",
    "toolCalling",
    "parallelToolCalls",
    "logprobs",
    "reasoning",
    "reasoningEffort",
    "streamingToolDeltas",
    "multiCandidate",
    "vision",
    "embeddings",
    "coding",
]


class CapabilityProbeService:
    def __init__(
        self,
        store: ModelStore,
        registry: ModelRegistry,
        *,
        get_adapter: Callable[[str], Any],
    ) -> None:
        self.store = store
        self.registry = registry
        self._get_adapter = get_adapter
        # probe_id → cancel Event; model_id → active probe_id (single-flight)
        self._cancel: dict[str, asyncio.Event] = {}
        self._active_probe_by_model: dict[str, str] = {}
        self._model_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def _lock_for(self, model_id: str) -> asyncio.Lock:
        lock = self._model_locks.get(model_id)
        if lock is None:
            lock = asyncio.Lock()
            self._model_locks[model_id] = lock
        return lock

    def list_for_model(self, model_id: str) -> list[VerifiedCapability]:
        model = self.registry.get(model_id)
        declared = model.capabilities.public_dict()
        stored = {
            row["capability"]: row for row in self.store.list_capability_results(model_id)
        }
        results: list[VerifiedCapability] = []
        for name in CANONICAL_CAPABILITIES:
            declared_state = declared.get(name, CapabilityState.UNKNOWN.value)
            row = stored.get(name)
            results.append(
                VerifiedCapability(
                    capability=name,
                    declared=CapabilityState(declared_state),
                    verified=CapabilityState(row["verified"]) if row else CapabilityState.UNKNOWN,
                    last_tested_at=row.get("last_tested_at") if row else None,
                    detail=row.get("detail") if row else None,
                )
            )
        return results

    async def probe(
        self,
        model_id: str,
        *,
        capabilities: list[str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> list[VerifiedCapability]:
        probe_id = str(uuid.uuid4())
        cancel = asyncio.Event()
        self._cancel[probe_id] = cancel
        lock = self._lock_for(model_id)
        async with lock:
            # Single-flight per model: cancel prior in-flight probe identity.
            prior = self._active_probe_by_model.get(model_id)
            if prior and prior in self._cancel:
                self._cancel[prior].set()
                prior_task = self._tasks.get(prior)
                if prior_task and not prior_task.done():
                    prior_task.cancel()
            self._active_probe_by_model[model_id] = probe_id
            current = asyncio.current_task()
            if current is not None:
                self._tasks[probe_id] = current
            try:
                return await self._probe_locked(
                    model_id,
                    capabilities=capabilities,
                    timeout_seconds=timeout_seconds,
                    cancel=cancel,
                    probe_id=probe_id,
                )
            finally:
                self._cancel.pop(probe_id, None)
                self._tasks.pop(probe_id, None)
                if self._active_probe_by_model.get(model_id) == probe_id:
                    self._active_probe_by_model.pop(model_id, None)

    async def _probe_locked(
        self,
        model_id: str,
        *,
        capabilities: list[str] | None,
        timeout_seconds: float,
        cancel: asyncio.Event,
        probe_id: str,
    ) -> list[VerifiedCapability]:
        model = self.registry.get(model_id)
        adapter = self._get_adapter(model.provider_id)
        raw_targets = capabilities or list(DEFAULT_PROBE_CAPABILITIES)
        targets: list[str] = []
        for name in raw_targets:
            canonical = normalize_capability_name(name)
            if canonical and canonical not in targets:
                targets.append(canonical)
        results: list[VerifiedCapability] = []
        for name in targets:
            if cancel.is_set():
                break
            declared = CapabilityState(
                model.capabilities.public_dict().get(name, CapabilityState.UNKNOWN.value)
            )
            verified = CapabilityState.UNKNOWN
            detail: str | None = None
            try:
                task = asyncio.create_task(
                    self._probe_one(
                        adapter,
                        model_id,
                        name,
                        timeout_seconds=timeout_seconds,
                        cancel=cancel,
                    )
                )
                self._tasks[f"{probe_id}:{name}"] = task
                try:
                    verified, detail = await asyncio.wait_for(
                        task, timeout=timeout_seconds + 0.5
                    )
                finally:
                    self._tasks.pop(f"{probe_id}:{name}", None)
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
            except asyncio.CancelledError:
                verified = CapabilityState.UNKNOWN
                detail = "probe_cancelled"
                raise
            except asyncio.TimeoutError:
                verified = CapabilityState.UNKNOWN
                detail = "probe_timeout"
            except ModelControlError as exc:
                verified, detail = self._classify_probe_error(exc)
            except Exception as exc:  # noqa: BLE001
                verified = CapabilityState.UNKNOWN
                detail = f"probe_failed:{type(exc).__name__}:{exc}"

            if cancel.is_set():
                # Do not commit results after cancellation.
                break

            now = utc_now()
            self.store.upsert_capability_result(
                {
                    "model_id": model_id,
                    "capability": name,
                    "declared": declared.value,
                    "verified": verified.value,
                    "last_tested_at": now,
                    "detail": detail,
                }
            )
            results.append(
                VerifiedCapability(
                    capability=name,
                    declared=declared,
                    verified=verified,
                    last_tested_at=now,
                    detail=detail,
                )
            )
        return results

    @staticmethod
    def _classify_probe_error(exc: ModelControlError) -> tuple[CapabilityState, str]:
        """Provider offline/auth/timeout is NOT capability UNSUPPORTED."""
        code = str(exc.code or "")
        if code in {PROVIDER_OFFLINE, "PROVIDER_UNAVAILABLE", "NETWORK_BLOCKED"}:
            return CapabilityState.UNKNOWN, f"provider_unavailable:{exc.message}"
        if code in {PROVIDER_AUTH_FAILED, "AUTH_ERROR"}:
            return CapabilityState.UNKNOWN, f"provider_auth_failed:{exc.message}"
        if code in {REQUEST_TIMEOUT, "TIMEOUT", MODEL_PROBE_CANCELLED}:
            return CapabilityState.UNKNOWN, f"probe_timeout:{exc.message}"
        if code in {"CAPABILITY_NOT_SUPPORTED", "MODEL_UNSUPPORTED"}:
            return CapabilityState.UNSUPPORTED, exc.message
        return CapabilityState.UNKNOWN, f"probe_failed:{code}:{exc.message}"

    async def _probe_one(
        self,
        adapter: Any,
        model_id: str,
        name: str,
        *,
        timeout_seconds: float,
        cancel: asyncio.Event,
    ) -> tuple[CapabilityState, str | None]:
        if cancel.is_set():
            return CapabilityState.UNKNOWN, "probe_cancelled"

        hook = getattr(adapter, "probe_capability", None)
        if callable(hook):
            outcome = await asyncio.wait_for(
                hook(model_id, capability=name),
                timeout=timeout_seconds,
            )
            return self._interpret_hook_outcome(name, outcome)

        if name == "chat":
            coro = adapter.test_inference(model_id, prompt="Reply with OK", max_tokens=4)
            outcome = await asyncio.wait_for(coro, timeout=timeout_seconds)
            ok = bool(outcome.get("ok"))
            return (
                CapabilityState.SUPPORTED if ok else CapabilityState.UNSUPPORTED,
                f"latencyMs={outcome.get('latencyMs')}",
            )

        if name == "streaming":
            return await self._probe_streaming(
                adapter, model_id, timeout_seconds=timeout_seconds, cancel=cancel
            )

        if name == "structuredOutput":
            return await self._probe_structured(
                adapter, model_id, timeout_seconds=timeout_seconds, require_schema=False
            )

        if name == "jsonSchemaResponse":
            return await self._probe_structured(
                adapter, model_id, timeout_seconds=timeout_seconds, require_schema=True
            )

        if name == "toolCalling":
            tool_hook = getattr(adapter, "test_tool_calling", None)
            if callable(tool_hook):
                outcome = await asyncio.wait_for(tool_hook(model_id), timeout=timeout_seconds)
                if outcome.get("tool_call_roundtrip"):
                    return CapabilityState.SUPPORTED, "tool call roundtrip observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "no tool call")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_tool_calling probe — not inferred from config",
            )

        if name == "parallelToolCalls":
            hook_ptc = getattr(adapter, "test_parallel_tool_calls", None)
            if callable(hook_ptc):
                outcome = await asyncio.wait_for(hook_ptc(model_id), timeout=timeout_seconds)
                if outcome.get("parallel_tool_calls"):
                    return CapabilityState.SUPPORTED, "parallel tool calls observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "no parallel tools")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_parallel_tool_calls probe",
            )

        if name == "logprobs":
            logprob_hook = getattr(adapter, "test_logprobs", None)
            if callable(logprob_hook):
                outcome = await asyncio.wait_for(logprob_hook(model_id), timeout=timeout_seconds)
                if outcome.get("logprobs_present"):
                    return CapabilityState.SUPPORTED, "logprobs present in response"
                return CapabilityState.UNSUPPORTED, "logprobs requested but absent"
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_logprobs probe — not inferred from config",
            )

        if name == "reasoning":
            reason_hook = getattr(adapter, "test_reasoning", None)
            if callable(reason_hook):
                outcome = await asyncio.wait_for(reason_hook(model_id), timeout=timeout_seconds)
                if outcome.get("reasoning_usage"):
                    return CapabilityState.SUPPORTED, "reasoning usage fields observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "no reasoning usage")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_reasoning probe — not inferred from config",
            )

        if name == "reasoningEffort":
            effort_hook = getattr(adapter, "test_reasoning_effort", None)
            if callable(effort_hook):
                outcome = await asyncio.wait_for(effort_hook(model_id), timeout=timeout_seconds)
                if outcome.get("ok"):
                    return CapabilityState.SUPPORTED, "reasoning_effort accepted"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "rejected")
            return CapabilityState.UNMEASURED, "adapter has no test_reasoning_effort probe"

        if name == "streamingToolDeltas":
            std_hook = getattr(adapter, "test_streaming_tool_deltas", None)
            if callable(std_hook):
                outcome = await asyncio.wait_for(std_hook(model_id), timeout=timeout_seconds)
                if outcome.get("streaming_tool_deltas"):
                    return CapabilityState.SUPPORTED, "streaming tool deltas observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "absent")
            return (
                CapabilityState.UNMEASURED,
                "streamingToolDeltas requires verified probe or authoritative provider report",
            )

        if name == "multiCandidate":
            mc_hook = getattr(adapter, "test_multi_candidate", None)
            if callable(mc_hook):
                outcome = await asyncio.wait_for(mc_hook(model_id), timeout=timeout_seconds)
                if outcome.get("multi_candidate"):
                    return CapabilityState.SUPPORTED, "n>1 candidates observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "absent")
            return CapabilityState.UNMEASURED, "adapter has no test_multi_candidate probe"

        if name == "vision":
            vision_hook = getattr(adapter, "test_vision", None)
            if callable(vision_hook):
                outcome = await asyncio.wait_for(vision_hook(model_id), timeout=timeout_seconds)
                if outcome.get("ok"):
                    return CapabilityState.SUPPORTED, "vision roundtrip observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "vision failed")
            return CapabilityState.UNMEASURED, "adapter has no test_vision probe"

        if name == "embeddings":
            emb_hook = getattr(adapter, "test_embeddings", None)
            if callable(emb_hook):
                outcome = await asyncio.wait_for(emb_hook(model_id), timeout=timeout_seconds)
                if outcome.get("ok") and outcome.get("dimensions"):
                    return (
                        CapabilityState.SUPPORTED,
                        f"embedding dims={outcome.get('dimensions')}",
                    )
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "embeddings failed")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_embeddings probe — not inferred from config",
            )

        if name == "coding":
            # Coding is a soft semantic label — no transport probe invents SUPPORTED.
            return (
                CapabilityState.UNMEASURED,
                "coding capability is semantic; not verified by transport probe",
            )

        return CapabilityState.UNMEASURED, "probe not implemented for this capability"

    async def _probe_streaming(
        self,
        adapter: Any,
        model_id: str,
        *,
        timeout_seconds: float,
        cancel: asyncio.Event,
    ) -> tuple[CapabilityState, str | None]:
        """Real bounded streaming roundtrip — never a non-stream completion."""
        stream_hook = getattr(adapter, "test_streaming", None)
        if callable(stream_hook):
            outcome = await asyncio.wait_for(stream_hook(model_id), timeout=timeout_seconds)
            if outcome.get("stream_ok") or outcome.get("ok"):
                return CapabilityState.SUPPORTED, str(outcome.get("detail") or "streaming deltas observed")
            return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "streaming failed")

        # Prefer adapter.stream_tokens / stream_inference if present.
        stream_fn = getattr(adapter, "stream_tokens", None) or getattr(adapter, "stream_inference", None)
        if callable(stream_fn):
            deltas = 0
            try:

                async def _consume() -> int:
                    nonlocal deltas
                    agen = stream_fn(model_id, prompt="Reply with OK", max_tokens=4)
                    if asyncio.iscoroutine(agen):
                        agen = await agen
                    async for _chunk in agen:
                        if cancel.is_set():
                            break
                        deltas += 1
                        if deltas >= 1:
                            break
                    return deltas

                count = await asyncio.wait_for(_consume(), timeout=timeout_seconds)
                if cancel.is_set():
                    return CapabilityState.UNKNOWN, "probe_cancelled"
                if count >= 1:
                    return CapabilityState.SUPPORTED, f"streaming_deltas={count}"
                return CapabilityState.UNSUPPORTED, "stream opened but no deltas"
            except ModelControlError as exc:
                return self._classify_probe_error(exc)
            except Exception as exc:  # noqa: BLE001
                return CapabilityState.UNKNOWN, f"streaming_probe_failed:{exc}"

        # OpenAI-compatible adapters: force stream=True via test_inference if supported.
        test = getattr(adapter, "test_inference", None)
        if callable(test):
            try:
                outcome = await asyncio.wait_for(
                    test(model_id, prompt="Reply with OK", max_tokens=4, stream=True),
                    timeout=timeout_seconds,
                )
                if outcome.get("stream") is True and outcome.get("ok"):
                    return CapabilityState.SUPPORTED, "stream=true roundtrip ok"
                if outcome.get("ok") and outcome.get("stream") is not True:
                    # Adapter ignored stream request — do NOT claim SUPPORTED.
                    return (
                        CapabilityState.UNMEASURED,
                        "adapter test_inference does not perform real streaming",
                    )
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "stream failed")
            except TypeError:
                # test_inference does not accept stream= — cannot claim streaming.
                return (
                    CapabilityState.UNMEASURED,
                    "adapter cannot open a streaming roundtrip",
                )
        return CapabilityState.UNMEASURED, "no streaming probe transport available"

    async def _probe_structured(
        self,
        adapter: Any,
        model_id: str,
        *,
        timeout_seconds: float,
        require_schema: bool,
    ) -> tuple[CapabilityState, str | None]:
        schema_hook = getattr(adapter, "test_structured_output", None)
        if callable(schema_hook):
            outcome = await asyncio.wait_for(
                schema_hook(
                    model_id,
                    schema={
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                    },
                ),
                timeout=timeout_seconds,
            )
            if outcome.get("schema_valid"):
                return CapabilityState.SUPPORTED, "schema-valid JSON response"
            if require_schema:
                if outcome.get("ok") and outcome.get("json_parsed"):
                    return (
                        CapabilityState.UNVERIFIED,
                        "JSON parsed but native json_schema response_format not verified",
                    )
                return CapabilityState.UNSUPPORTED, str(
                    outcome.get("detail") or "json_schema probe failed"
                )
            if outcome.get("ok") and outcome.get("json_parsed"):
                return (
                    CapabilityState.UNVERIFIED,
                    "JSON parsed but schema validation failed",
                )
            return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "structured probe failed")

        if require_schema:
            return (
                CapabilityState.UNMEASURED,
                "no native json_schema probe — not inferred from json_object heuristics",
            )

        coro = adapter.test_inference(
            model_id,
            prompt='Reply with only JSON: {"ok":true}',
            max_tokens=16,
        )
        outcome = await asyncio.wait_for(coro, timeout=timeout_seconds)
        preview = str(outcome.get("preview") or "")
        try:
            parsed = json.loads(preview[preview.find("{") : preview.rfind("}") + 1])
            valid = isinstance(parsed, dict) and "ok" in parsed
        except Exception:  # noqa: BLE001
            valid = False
        if valid:
            return (
                CapabilityState.UNVERIFIED,
                "heuristic JSON parse — not native json_schema response_format probe",
            )
        return CapabilityState.UNSUPPORTED, "no parseable JSON object in probe response"

    @staticmethod
    def _interpret_hook_outcome(
        name: str, outcome: Any
    ) -> tuple[CapabilityState, str | None]:
        if not isinstance(outcome, dict):
            return CapabilityState.UNKNOWN, "probe hook returned non-dict"
        state_raw = outcome.get("state") or outcome.get("verified")
        if state_raw:
            try:
                return CapabilityState(str(state_raw)), outcome.get("detail")
            except ValueError:
                pass
        if outcome.get("provider_unavailable") or outcome.get("timeout"):
            return CapabilityState.UNKNOWN, outcome.get("detail") or "provider_unavailable"
        if outcome.get("ok") or outcome.get("supported"):
            return CapabilityState.SUPPORTED, outcome.get("detail")
        if outcome.get("unsupported"):
            return CapabilityState.UNSUPPORTED, outcome.get("detail")
        if outcome.get("unmeasured"):
            return CapabilityState.UNMEASURED, outcome.get("detail")
        return CapabilityState.UNKNOWN, outcome.get("detail") or f"probe={name}"

    def cancel(self, model_id: str) -> bool:
        """Cancel active probe(s) for a model. Cancels in-flight tasks when possible."""
        probe_id = self._active_probe_by_model.get(model_id)
        cancelled = False
        if probe_id:
            event = self._cancel.get(probe_id)
            if event:
                event.set()
                cancelled = True
            task = self._tasks.get(probe_id)
            if task and not task.done():
                task.cancel()
                cancelled = True
            # Cancel per-capability subtasks
            for key, task in list(self._tasks.items()):
                if key.startswith(f"{probe_id}:") and not task.done():
                    task.cancel()
                    cancelled = True
        # Legacy: also set any cancel event keyed by model_id (compat)
        legacy = self._cancel.get(model_id)
        if legacy:
            legacy.set()
            cancelled = True
        return cancelled
