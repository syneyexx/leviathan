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
from .metadata import METADATA_SCHEMA_VERSION, normalize_capability_metadata, schema_hash
from .receipts import CapabilityCallReceipt, CapabilityReceiptStore, build_receipt_from_result
from .types import (
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

__all__ = [
    "METADATA_SCHEMA_VERSION",
    "CapabilityCallReceipt",
    "CapabilityCatalog",
    "CapabilityDefinition",
    "CapabilityProviderKind",
    "CapabilityReceiptStore",
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
    "build_receipt_from_result",
    "normalize_capability_metadata",
    "schema_hash",
]
