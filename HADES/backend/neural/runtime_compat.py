"""Checkpoint / runtime compatibility validation (Phase 9).

Validate *before* tensors are attached to the live runtime. Failures raise
typed ``NeuralCheckpointIncompatible`` — never silent shape errors mid-infer.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from neural.contracts import NeuralRuntimeIdentity
from neural.errors import NeuralCheckpointIncompatible


def validate_memory_checkpoint_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_hidden_size: int,
    expected_architecture_version: str | None = None,
    expected_schema_version: int | None = 2,
    expected_injection_layers: Sequence[int] | None = None,
) -> None:
    """Fail closed when a memory checkpoint cannot bind to the runtime geometry."""
    got_dim = int(manifest.get("dim", -1))
    if got_dim != int(expected_hidden_size):
        raise NeuralCheckpointIncompatible(
            "checkpoint hidden_size mismatch",
            detail={
                "checkpoint_hidden_size": got_dim,
                "runtime_hidden_size": int(expected_hidden_size),
            },
        )
    if expected_schema_version is not None:
        got_schema = int(manifest.get("schema_version", -1))
        if got_schema != int(expected_schema_version):
            raise NeuralCheckpointIncompatible(
                "checkpoint schema version mismatch",
                detail={
                    "checkpoint_schema_version": got_schema,
                    "runtime_schema_version": int(expected_schema_version),
                },
            )
    if expected_architecture_version is not None:
        got_arch = str(manifest.get("architecture_version") or "")
        if got_arch != expected_architecture_version:
            raise NeuralCheckpointIncompatible(
                "checkpoint memory architecture mismatch",
                detail={
                    "checkpoint_architecture_version": got_arch,
                    "runtime_architecture_version": expected_architecture_version,
                },
            )
    cfg = dict(manifest.get("config") or {})
    if expected_injection_layers is not None and "injection_layers" in cfg:
        got_layers = [int(x) for x in cfg.get("injection_layers") or []]
        want = [int(x) for x in expected_injection_layers]
        if got_layers != want:
            raise NeuralCheckpointIncompatible(
                "checkpoint injection layer mismatch",
                detail={
                    "checkpoint_injection_layers": got_layers,
                    "runtime_injection_layers": want,
                },
            )


def validate_identity_for_checkpoint(
    identity: NeuralRuntimeIdentity,
    manifest: Mapping[str, Any],
) -> None:
    validate_memory_checkpoint_manifest(
        manifest,
        expected_hidden_size=identity.hidden_size,
        expected_architecture_version=identity.neural_architecture_version,
        expected_schema_version=2,
        expected_injection_layers=identity.injection_layers,
    )
