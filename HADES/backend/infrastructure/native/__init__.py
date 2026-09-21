"""Native companion runtime package.

Canonical imports:
  from infrastructure.native import NativeRuntimeFacade, get_native_client

`backend/native_runtime.py` remains a compatibility re-export.
"""

from .facade import (
    NativeRuntimeClient,
    NativeRuntimeFacade,
    NativeStatus,
    PROTOCOL_VERSION,
    configure_native_client,
    get_native_client,
    locate_native_executable,
    repo_root,
    set_native_client,
)
from .errors import NativeRuntimeError

__all__ = [
    "NativeRuntimeClient",
    "NativeRuntimeFacade",
    "NativeRuntimeError",
    "NativeStatus",
    "PROTOCOL_VERSION",
    "configure_native_client",
    "get_native_client",
    "locate_native_executable",
    "repo_root",
    "set_native_client",
]
