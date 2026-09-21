"""On-demand function runtime — registry, lifecycle, lazy load, cleanup."""

from .builtins import build_default_registry, register_builtin_functions
from .registry import FunctionRegistry
from .runtime import FunctionRuntime
from .types import (
    FunctionCallStatus,
    FunctionDefinition,
    FunctionResult,
    LifecycleMode,
    SideEffect,
)

__all__ = [
    "FunctionCallStatus",
    "FunctionDefinition",
    "FunctionRegistry",
    "FunctionResult",
    "FunctionRuntime",
    "LifecycleMode",
    "SideEffect",
    "build_default_registry",
    "register_builtin_functions",
]
