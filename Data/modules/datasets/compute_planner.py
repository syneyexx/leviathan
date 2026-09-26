"""Select PYTHON_STREAMING vs RUST_NATIVE for dataset data-plane operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from Data.modules.datasets.memory_policy import DatasetMemoryPolicy, resolve_dataset_memory_policy
from Data.modules.workers.native_compute import (
    PARQUET_OPERATIONS,
    SUPPORTED_OPERATIONS,
    NativeCapabilities,
    NativeStatus,
    probe_capabilities,
)


class ComputeBackend(str, Enum):
    PYTHON_STREAMING = "PYTHON_STREAMING"
    RUST_NATIVE = "RUST_NATIVE"


@dataclass(frozen=True)
class BackendPlan:
    backend: ComputeBackend
    operation: str
    native_mode: str
    input_bytes: int | None
    rust_threshold_bytes: int
    native_status: str | None
    fallback_reason: str | None = None
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend.value,
            "selectedBackend": self.backend.value,
            "operation": self.operation,
            "nativeMode": self.native_mode,
            "inputBytes": self.input_bytes,
            "rustThresholdBytes": self.rust_threshold_bytes,
            "nativeStatus": self.native_status,
            "fallbackReason": self.fallback_reason,
            "detail": self.detail,
        }


class ComputeBackendPlanner:
    """Chooses compute backend from operation, size, native capability, and settings."""

    def __init__(
        self,
        *,
        policy: DatasetMemoryPolicy | None = None,
        capabilities: NativeCapabilities | None = None,
        settings: Any | None = None,
    ) -> None:
        self.policy = policy or resolve_dataset_memory_policy(settings=settings)
        self._capabilities = capabilities
        self._settings = settings

    def capabilities(self) -> NativeCapabilities:
        if self._capabilities is None:
            disabled = self.policy.native_mode == "python"
            self._capabilities = probe_capabilities(disabled=disabled)
        return self._capabilities

    def plan(
        self,
        operation: str,
        *,
        input_path: str | Path | None = None,
        input_bytes: int | None = None,
        force_backend: str | None = None,
    ) -> BackendPlan:
        op = str(operation or "").strip()
        size = input_bytes
        if size is None and input_path is not None:
            try:
                size = int(Path(input_path).stat().st_size)
            except OSError:
                size = None

        mode = self.policy.native_mode
        caps = self.capabilities()

        if force_backend:
            forced = str(force_backend).strip().upper()
            if forced in {ComputeBackend.PYTHON_STREAMING.value, "PYTHON"}:
                return BackendPlan(
                    backend=ComputeBackend.PYTHON_STREAMING,
                    operation=op,
                    native_mode=mode,
                    input_bytes=size,
                    rust_threshold_bytes=self.policy.rust_threshold_bytes,
                    native_status=caps.status.value,
                    fallback_reason="forced_python",
                    detail="force_backend=PYTHON_STREAMING",
                )
            if forced in {ComputeBackend.RUST_NATIVE.value, "RUST", "NATIVE"}:
                if caps.status != NativeStatus.AVAILABLE:
                    return BackendPlan(
                        backend=ComputeBackend.PYTHON_STREAMING,
                        operation=op,
                        native_mode=mode,
                        input_bytes=size,
                        rust_threshold_bytes=self.policy.rust_threshold_bytes,
                        native_status=caps.status.value,
                        fallback_reason=f"forced_rust_unavailable:{caps.status.value}",
                        detail=caps.detail,
                    )
                return BackendPlan(
                    backend=ComputeBackend.RUST_NATIVE,
                    operation=op,
                    native_mode=mode,
                    input_bytes=size,
                    rust_threshold_bytes=self.policy.rust_threshold_bytes,
                    native_status=caps.status.value,
                    fallback_reason=None,
                    detail="force_backend=RUST_NATIVE",
                )

        if mode == "python":
            return BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=self.policy.rust_threshold_bytes,
                native_status=caps.status.value,
                fallback_reason="native_mode_python",
                detail="settings force Python streaming",
            )

        if op not in SUPPORTED_OPERATIONS:
            return BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=self.policy.rust_threshold_bytes,
                native_status=caps.status.value,
                fallback_reason="unsupported_native_operation",
                detail=f"operation {op} not in native allowlist",
            )

        if caps.status != NativeStatus.AVAILABLE:
            return BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=self.policy.rust_threshold_bytes,
                native_status=caps.status.value,
                fallback_reason=f"native_{caps.status.value.lower()}",
                detail=caps.detail,
            )

        if mode == "rust":
            return BackendPlan(
                backend=ComputeBackend.RUST_NATIVE,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=self.policy.rust_threshold_bytes,
                native_status=caps.status.value,
                fallback_reason=None,
                detail="native_mode_rust",
            )

        # auto: prefer Rust when input is large enough (or size unknown + available).
        # Parquet-native ops: large parquet inputs (or unknown size / .parquet path)
        # prefer RUST_NATIVE whenever the binary is available.
        threshold = self.policy.rust_threshold_bytes
        looks_parquet = _input_looks_parquet(input_path)
        is_parquet_op = op in PARQUET_OPERATIONS
        if is_parquet_op and (size is None or size >= threshold or looks_parquet):
            return BackendPlan(
                backend=ComputeBackend.RUST_NATIVE,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=threshold,
                native_status=caps.status.value,
                fallback_reason=None,
                detail=(
                    "auto: parquet_* prefers RUST_NATIVE for large/parquet inputs"
                    if looks_parquet or (size is not None and size >= threshold)
                    else "auto: parquet_* size unknown, native available"
                ),
            )
        if size is None:
            return BackendPlan(
                backend=ComputeBackend.RUST_NATIVE,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=threshold,
                native_status=caps.status.value,
                fallback_reason=None,
                detail="auto: size unknown, native available",
            )
        if size >= threshold:
            return BackendPlan(
                backend=ComputeBackend.RUST_NATIVE,
                operation=op,
                native_mode=mode,
                input_bytes=size,
                rust_threshold_bytes=threshold,
                native_status=caps.status.value,
                fallback_reason=None,
                detail=f"auto: input_bytes={size} >= threshold={threshold}",
            )
        return BackendPlan(
            backend=ComputeBackend.PYTHON_STREAMING,
            operation=op,
            native_mode=mode,
            input_bytes=size,
            rust_threshold_bytes=threshold,
            native_status=caps.status.value,
            fallback_reason="below_rust_threshold",
            detail=f"auto: input_bytes={size} < threshold={threshold}",
        )


def _input_looks_parquet(input_path: str | Path | None) -> bool:
    if input_path is None:
        return False
    try:
        return Path(input_path).suffix.lower() == ".parquet"
    except (TypeError, ValueError):
        return False


__all__ = [
    "BackendPlan",
    "ComputeBackend",
    "ComputeBackendPlanner",
]
