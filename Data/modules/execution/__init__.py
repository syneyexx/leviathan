"""Execution plane — capabilities, gateway, policy boundary."""

from Data.modules.function_runtime.types import SideEffect

from .builtins import build_default_catalog
from .catalog import CapabilityCatalog
from .gateway import EffectRecord, ExecutionGateway, GatewayRejection
from .types import (
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

__all__ = [
    "CapabilityCatalog",
    "CapabilityDefinition",
    "CapabilityProviderKind",
    "CapabilityRequest",
    "CapabilityResult",
    "CapabilityStatus",
    "EffectRecord",
    "ExecutionGateway",
    "GatewayRejection",
    "SideEffect",
    "build_default_catalog",
]
