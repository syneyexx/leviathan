from __future__ import annotations

import importlib
import inspect
import sys
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable

from .registry import FunctionRegistry
from .types import (
    FunctionCallStatus,
    FunctionDefinition,
    FunctionResult,
    LifecycleMode,
)


class FunctionValidationError(ValueError):
    pass


class FunctionRuntime:
    """Execute registered functions with lazy load, timeout, cancel, cleanup.

    ON_DEMAND functions are unloaded after execution (module removed from
    ``sys.modules`` when safe). WARM_CACHE keeps a bounded LRU of loaded callables.
    """

    def __init__(
        self,
        registry: FunctionRegistry,
        *,
        max_concurrency: int = 2,
        warm_cache_size: int = 2,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if warm_cache_size < 0:
            raise ValueError("warm_cache_size must be >= 0")
        self.registry = registry
        self.max_concurrency = max_concurrency
        self.warm_cache_size = warm_cache_size
        self._semaphore = threading.Semaphore(max_concurrency)
        self._warm: OrderedDict[str, Callable[..., dict[str, Any]]] = OrderedDict()
        self._lock = threading.RLock()
        self._cancel_flags: dict[str, threading.Event] = {}
        self._loaded_modules: dict[str, str] = {}  # function_id -> module name
        self.telemetry: dict[str, Any] = {
            "calls": 0,
            "timeouts": 0,
            "cancellations": 0,
            "failures": 0,
            "lazy_loads": 0,
            "unloads": 0,
            "cache_hits": 0,
        }

    def loaded_function_ids(self) -> set[str]:
        with self._lock:
            return set(self._loaded_modules.keys()) | set(self._warm.keys())

    def is_module_imported(self, module_name: str) -> bool:
        return module_name in sys.modules

    def cancel(self, call_id: str) -> bool:
        flag = self._cancel_flags.get(call_id)
        if flag is None:
            return False
        flag.set()
        return True

    def execute(self, function_id: str, arguments: dict[str, Any] | None = None) -> FunctionResult:
        call_id = str(uuid.uuid4())
        definition = self.registry.require(function_id)
        args = dict(arguments or {})
        cancel_flag = threading.Event()
        self._cancel_flags[call_id] = cancel_flag
        started = time.perf_counter()
        self.telemetry["calls"] += 1

        try:
            self._validate_args(definition, args)
        except FunctionValidationError as exc:
            self.telemetry["failures"] += 1
            return FunctionResult(
                call_id=call_id,
                function_id=function_id,
                status=FunctionCallStatus.REJECTED,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
                telemetry={"validated": False},
            )

        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            self.telemetry["failures"] += 1
            return FunctionResult(
                call_id=call_id,
                function_id=function_id,
                status=FunctionCallStatus.REJECTED,
                error="Function concurrency limit reached",
                duration_ms=(time.perf_counter() - started) * 1000,
                telemetry={"concurrency_rejected": True},
            )

        lazy_loaded = False
        module_name = definition.entrypoint.split(":", 1)[0]
        try:
            fn, lazy_loaded = self._resolve_callable(definition)
            if cancel_flag.is_set():
                self.telemetry["cancellations"] += 1
                return FunctionResult(
                    call_id=call_id,
                    function_id=function_id,
                    status=FunctionCallStatus.CANCELLED,
                    error="Cancelled before execution",
                    duration_ms=(time.perf_counter() - started) * 1000,
                )

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._invoke, fn, args, cancel_flag)
                try:
                    output = future.result(timeout=definition.timeout_seconds)
                except FuturesTimeout:
                    cancel_flag.set()
                    self.telemetry["timeouts"] += 1
                    return FunctionResult(
                        call_id=call_id,
                        function_id=function_id,
                        status=FunctionCallStatus.TIMEOUT,
                        error=f"Timed out after {definition.timeout_seconds}s",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        telemetry={"lazy_loaded": lazy_loaded},
                    )

            if cancel_flag.is_set():
                self.telemetry["cancellations"] += 1
                return FunctionResult(
                    call_id=call_id,
                    function_id=function_id,
                    status=FunctionCallStatus.CANCELLED,
                    error="Cancelled during execution",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    telemetry={"lazy_loaded": lazy_loaded},
                )

            if not isinstance(output, dict):
                raise TypeError("Function must return a dict result")

            return FunctionResult(
                call_id=call_id,
                function_id=function_id,
                status=FunctionCallStatus.COMPLETED,
                output=output,
                duration_ms=(time.perf_counter() - started) * 1000,
                telemetry={
                    "lazy_loaded": lazy_loaded,
                    "lifecycle_mode": definition.lifecycle_mode.value,
                    "module": module_name,
                },
            )
        except Exception as exc:  # noqa: BLE001 — normalized into FunctionResult
            self.telemetry["failures"] += 1
            return FunctionResult(
                call_id=call_id,
                function_id=function_id,
                status=FunctionCallStatus.FAILED,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
                telemetry={"lazy_loaded": lazy_loaded, "module": module_name},
            )
        finally:
            self._semaphore.release()
            self._cancel_flags.pop(call_id, None)
            self._cleanup_after_call(definition, module_name)

    def _invoke(
        self,
        fn: Callable[..., dict[str, Any]],
        args: dict[str, Any],
        cancel_flag: threading.Event,
    ) -> dict[str, Any]:
        if cancel_flag.is_set():
            raise RuntimeError("Cancelled")
        signature = inspect.signature(fn)
        if "cancel_event" in signature.parameters:
            return fn(**args, cancel_event=cancel_flag)
        return fn(**args)

    def _validate_args(self, definition: FunctionDefinition, args: dict[str, Any]) -> None:
        schema = definition.input_schema or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            raise FunctionValidationError("Invalid input_schema on function definition")
        for key in required:
            if key not in args:
                raise FunctionValidationError(f"Missing required argument: {key}")
        for key, value in args.items():
            if key not in properties:
                raise FunctionValidationError(f"Unexpected argument: {key}")
            expected = properties[key].get("type")
            if expected is None:
                continue
            if not self._type_matches(expected, value):
                raise FunctionValidationError(
                    f"Argument {key!r} expected type {expected}, got {type(value).__name__}"
                )

    @staticmethod
    def _type_matches(expected: str, value: Any) -> bool:
        mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        py_type = mapping.get(expected)
        if py_type is None:
            return True
        if expected == "number" and isinstance(value, bool):
            return False
        if expected == "integer" and isinstance(value, bool):
            return False
        return isinstance(value, py_type)

    def _resolve_callable(self, definition: FunctionDefinition) -> tuple[Callable[..., dict[str, Any]], bool]:
        with self._lock:
            if definition.id in self._warm:
                self._warm.move_to_end(definition.id)
                self.telemetry["cache_hits"] += 1
                return self._warm[definition.id], False

        module_name, _, attr = definition.entrypoint.partition(":")
        if not module_name or not attr:
            raise ValueError(f"Invalid entrypoint: {definition.entrypoint}")

        already = module_name in sys.modules
        module = importlib.import_module(module_name)
        lazy_loaded = not already
        if lazy_loaded:
            self.telemetry["lazy_loads"] += 1

        fn = getattr(module, attr, None)
        if fn is None or not callable(fn):
            raise AttributeError(f"Entrypoint callable not found: {definition.entrypoint}")

        with self._lock:
            self._loaded_modules[definition.id] = module_name
            if definition.lifecycle_mode in {LifecycleMode.WARM_CACHE, LifecycleMode.PERSISTENT}:
                self._warm[definition.id] = fn
                while len(self._warm) > self.warm_cache_size:
                    evicted_id, _ = self._warm.popitem(last=False)
                    self._unload_function(evicted_id)

        return fn, lazy_loaded

    def _cleanup_after_call(self, definition: FunctionDefinition, module_name: str) -> None:
        if definition.lifecycle_mode == LifecycleMode.ON_DEMAND:
            self._unload_function(definition.id)
        elif definition.lifecycle_mode == LifecycleMode.PURE:
            # Pure helpers may stay imported; do not force unload.
            with self._lock:
                self._loaded_modules.pop(definition.id, None)
        # WARM_CACHE / PERSISTENT retain until eviction / shutdown.

    def _unload_function(self, function_id: str) -> None:
        with self._lock:
            module_name = self._loaded_modules.pop(function_id, None)
            self._warm.pop(function_id, None)
            if not module_name:
                definition = self.registry.get(function_id)
                if definition:
                    module_name = definition.entrypoint.split(":", 1)[0]
            if not module_name:
                return
            still_needed = any(
                name == module_name for name in self._loaded_modules.values()
            ) or any(
                (
                    self.registry.get(fid)
                    and self.registry.require(fid).entrypoint.startswith(module_name + ":")
                )
                for fid in self._warm
            )
            if still_needed:
                return
            to_delete = [
                name
                for name in list(sys.modules)
                if name == module_name or name.startswith(module_name + ".")
            ]
            for name in to_delete:
                del sys.modules[name]
            self.telemetry["unloads"] += 1

    def shutdown(self) -> None:
        with self._lock:
            ids = list(self._loaded_modules.keys()) + list(self._warm.keys())
        for function_id in set(ids):
            self._unload_function(function_id)
