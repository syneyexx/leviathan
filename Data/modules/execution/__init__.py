"""Execution plane — capabilities, gateway, policy boundary."""

from Data.modules.function_runtime.types import SideEffect

from .builtins import build_default_catalog
from .catalog import CapabilityCatalog
from .gateway import EffectRecord, ExecutionGateway, GatewayRejection
from .manifest import (
    FrontierCapabilityManifest,
    ManifestAvailability,
    ManifestEntry,
    build_frontier_manifest,
)
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
    "FrontierCapabilityManifest",
    "GatewayRejection",
    "ManifestAvailability",
    "ManifestEntry",
    "SideEffect",
    "build_default_catalog",
    "build_frontier_manifest",
]
