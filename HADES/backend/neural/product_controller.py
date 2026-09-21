"""Phase 21: production Neural product controller.

Hardens start/stop/restart/capacity/OOM/cancellation around NeuralRuntimeBoundary
without changing Normal HADES startup when Neural is disabled.

HADES startup (Neural disabled)
  -> no PyTorch allocation
  -> Neural controller idle / unhealthy=false only if never started

HADES startup (Neural enabled)
  -> validate config
  -> start runtime
  -> checkpoint compatibility
  -> health
  -> ready only when inference possible
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from neural.contracts import NeuralInferRequest, NeuralMode, NeuralRuntimeState
from neural.domain_memory import DomainMemoryRegistry, NeuralDomain
from neural.errors import (
    NeuralCapacityExceeded,
    NeuralRuntimeOOM,
)
from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig


@dataclass
class NeuralCapacityConfig:
    max_concurrent_infer: int = 1
    acquire_timeout_s: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NeuralPersistenceManifest:
    """Durable Neural product state that must survive restart."""

    schema_version: int = 1
    mode: str = "off"
    allow: bool = False
    slow_checkpoint_id: str | None = None
    known_good_checkpoint_id: str | None = None
    candidate_checkpoint_id: str | None = None
    adapter_id: str | None = None
    domain_registry: dict[str, Any] = field(default_factory=dict)
    last_promotion: str | None = None
    last_rollback: str | None = None
    last_rejection: str | None = None
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NeuralPersistenceManifest":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in dict(raw).items() if k in known})


class NeuralProductController:
    """Process-local Neural product façade with capacity + persistence."""

    def __init__(
        self,
        *,
        work_dir: str | Path | None = None,
        capacity: NeuralCapacityConfig | None = None,
        domain_registry: DomainMemoryRegistry | None = None,
    ) -> None:
        self.work_dir = Path(work_dir) if work_dir else Path(".hades_neural_runtime")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity or NeuralCapacityConfig()
        self.domains = domain_registry or DomainMemoryRegistry()
        self.boundary = NeuralRuntimeBoundary()
        self._lock = threading.RLock()
        self._infer_slots = threading.BoundedSemaphore(self.capacity.max_concurrent_infer)
        self._inflight = 0
        self._started = False
        self._manifest = NeuralPersistenceManifest()
        self._load_manifest()

    # --- persistence -----------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.work_dir / "neural_product_manifest.json"

    def _load_manifest(self) -> None:
        path = self.manifest_path
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._manifest = NeuralPersistenceManifest.from_dict(raw)
            if self._manifest.domain_registry:
                self.domains = DomainMemoryRegistry.from_dict(self._manifest.domain_registry)
        except Exception:  # noqa: BLE001 — corrupt manifest must not crash HADES
            self._manifest = NeuralPersistenceManifest()

    def save_manifest(self) -> NeuralPersistenceManifest:
        with self._lock:
            self._manifest.domain_registry = self.domains.to_dict()
            self._manifest.updated_at = time.time()
            tmp = self.manifest_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.manifest_path)
            return NeuralPersistenceManifest.from_dict(self._manifest.to_dict())

    # --- lifecycle -------------------------------------------------------

    def start(
        self,
        *,
        mode: NeuralMode | str = NeuralMode.OFF,
        isolation: str = "inprocess",
        auto_load_model: bool = True,
        allow: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if isinstance(mode, str):
                mode = NeuralMode(mode)
            if not allow or mode is NeuralMode.OFF:
                # Explicit idle: no engine allocation.
                self._started = False
                self._manifest.allow = False
                self._manifest.mode = NeuralMode.OFF.value
                self.save_manifest()
                return self.status()
            health = self.boundary.start(
                NeuralRuntimeStartConfig(
                    isolation=isolation,
                    mode=mode,
                    work_dir=self.work_dir,
                    auto_load_model=auto_load_model,
                )
            )
            self._started = health.state is NeuralRuntimeState.READY or health.state is NeuralRuntimeState.DEGRADED
            self._manifest.allow = True
            self._manifest.mode = mode.value
            self.save_manifest()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._started or self.boundary.health().state not in {
                NeuralRuntimeState.STOPPED,
                NeuralRuntimeState.UNAVAILABLE,
            }:
                self.boundary.stop()
            self._started = False
            return self.status()

    def restart(self) -> dict[str, Any]:
        """Stop then restore from persisted manifest (Slow checkpoint + domains)."""
        with self._lock:
            allow = self._manifest.allow
            mode = self._manifest.mode
            known_good = self._manifest.known_good_checkpoint_id or self._manifest.slow_checkpoint_id
            self.stop()
            status = self.start(mode=mode, allow=allow, auto_load_model=True)
            # Checkpoint re-attach is caller-provided via store_root; record intent.
            status["restored_checkpoint_id"] = known_good
            status["domain_registry"] = self.domains.to_dict()
            return status

    def infer(self, request: NeuralInferRequest | Mapping[str, Any]) -> Any:
        acquired = self._infer_slots.acquire(timeout=self.capacity.acquire_timeout_s)
        if not acquired:
            raise NeuralCapacityExceeded(
                "neural inference capacity exhausted",
                detail=self.capacity.to_dict(),
            )
        with self._lock:
            self._inflight += 1
        try:
            try:
                return self.boundary.infer(request)
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                if "out of memory" in message or "oom" in message:
                    raise NeuralRuntimeOOM(
                        "neural runtime out of memory",
                        detail={"cause": str(exc)},
                    ) from exc
                raise
        finally:
            with self._lock:
                self._inflight = max(0, self._inflight - 1)
            self._infer_slots.release()

    def cancel(self) -> None:
        self.boundary.cancel()

    def record_promotion(self, checkpoint_id: str, *, domain: NeuralDomain | str = NeuralDomain.GENERAL) -> None:
        with self._lock:
            self.domains.bump_version(domain, checkpoint_id=checkpoint_id)
            self._manifest.slow_checkpoint_id = checkpoint_id
            self._manifest.known_good_checkpoint_id = checkpoint_id
            self._manifest.candidate_checkpoint_id = None
            self._manifest.last_promotion = checkpoint_id
            self.save_manifest()

    def record_rejection(self, checkpoint_id: str, *, domain: NeuralDomain | str = NeuralDomain.GENERAL) -> None:
        with self._lock:
            self.domains.record_candidate(domain, checkpoint_id)
            self._manifest.candidate_checkpoint_id = checkpoint_id
            self._manifest.last_rejection = checkpoint_id
            self.save_manifest()

    def record_rollback(self, checkpoint_id: str, *, domain: NeuralDomain | str = NeuralDomain.GENERAL) -> None:
        with self._lock:
            self.domains.record_rollback(domain, checkpoint_id)
            self._manifest.last_rollback = checkpoint_id
            self._manifest.candidate_checkpoint_id = None
            if self._manifest.known_good_checkpoint_id:
                self._manifest.slow_checkpoint_id = self._manifest.known_good_checkpoint_id
            self.save_manifest()

    def status(self) -> dict[str, Any]:
        health = self.boundary.health()
        metrics = self.boundary.metrics()
        ready = bool(
            health.state is NeuralRuntimeState.READY
            and health.process_alive
            and health.base_model_loaded
        )
        return {
            "ready": ready,
            "started": self._started,
            "allow": self._manifest.allow,
            "mode": self._manifest.mode,
            "health": health.to_dict(),
            "metrics": metrics.to_dict(),
            "capacity": {
                **self.capacity.to_dict(),
                "inflight": self._inflight,
            },
            "persistence": self._manifest.to_dict(),
            "domains": self.domains.to_dict(),
            "artifacts": {
                "base_model": "frozen_backbone",
                "hades_adapter": self._manifest.adapter_id,
                "fast_memory": "ephemeral_session",
                "slow_memory": self._manifest.slow_checkpoint_id or self._manifest.known_good_checkpoint_id,
                "exact_brain": "separate",
            },
        }


# Process-local singleton used by HTTP routes (lazy; no torch at import).
_CONTROLLER: NeuralProductController | None = None
_CONTROLLER_LOCK = threading.Lock()


def get_neural_product_controller(*, work_dir: str | Path | None = None) -> NeuralProductController:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = NeuralProductController(work_dir=work_dir)
        return _CONTROLLER


def reset_neural_product_controller_for_tests() -> None:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is not None:
            try:
                _CONTROLLER.stop()
            except Exception:  # noqa: BLE001
                pass
        _CONTROLLER = None
