"""Compatibility shim — prefer `infrastructure.native`.

This module re-exports the refactored native facade so existing imports
(`from native_runtime import ...`) keep working during the incremental migration.
"""

from __future__ import annotations

from infrastructure.native import (  # noqa: F401
    PROTOCOL_VERSION,
    NativeRuntimeClient,
    NativeRuntimeError,
    NativeRuntimeFacade,
    NativeStatus,
    configure_native_client,
    get_native_client,
    locate_native_executable,
    repo_root,
    set_native_client,
)

__all__ = [
    "PROTOCOL_VERSION",
    "NativeRuntimeClient",
    "NativeRuntimeError",
    "NativeRuntimeFacade",
    "NativeStatus",
    "configure_native_client",
    "get_native_client",
    "locate_native_executable",
    "repo_root",
    "set_native_client",
]
