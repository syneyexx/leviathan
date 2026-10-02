"""Execution plane — capabilities, gateway, policy boundary."""

from Data.modules.function_runtime.types import SideEffect

from .builtins import build_default_catalog
from .catalog import CapabilityCatalog
from .gateway import EffectRecord, ExecutionGateway, GatewayRejection
from .http_status import gateway_status_http_code
from .idempotency import CapabilityIdempotencyStore, execution_fingerprint
from .manifest import (
    FrontierCapabilityManifest,
    ManifestAvailability,
    ManifestEntry,
    build_frontier_manifest,
)
from .metadata import METADATA_SCHEMA_VERSION, normalize_capability_metadata, schema_hash
from .schema_validation import (
    SUPPORTED_JSON_SCHEMA_DRAFT_NAME,
    SchemaValidationError,
    validate_args_against_schema,
)
from .catalog_reconcile import reconcile_dynamic_catalog
from .receipts import CapabilityCallReceipt, CapabilityReceiptStore, build_receipt_from_result
from .types import (
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from .workload import (
    ExecutionWorkloadClass,
    api_may_execute_inline,
    classify_capability,
    classify_request_workload,
    execution_class_metadata,
    externalize_api_enabled,
    is_external_required,
    running_in_worker_process,
)

__all__ = [
    "METADATA_SCHEMA_VERSION",
    "CapabilityCallReceipt",
    "CapabilityCatalog",
    "CapabilityDefinition",
    "CapabilityIdempotencyStore",
    "CapabilityProviderKind",
    "CapabilityReceiptStore",
    "CapabilityRequest",
    "CapabilityResult",
    "CapabilityStatus",
    "EffectRecord",
    "ExecutionGateway",
    "ExecutionWorkloadClass",
    "FrontierCapabilityManifest",
    "GatewayRejection",
    "ManifestAvailability",
    "ManifestEntry",
    "SideEffect",
    "api_may_execute_inline",
    "build_default_catalog",
    "build_frontier_manifest",
    "build_receipt_from_result",
    "classify_capability",
    "classify_request_workload",
    "execution_class_metadata",
    "execution_fingerprint",
    "externalize_api_enabled",
    "gateway_status_http_code",
    "is_external_required",
    "normalize_capability_metadata",
    "running_in_worker_process",
    "schema_hash",
    "SUPPORTED_JSON_SCHEMA_DRAFT_NAME",
    "SchemaValidationError",
    "validate_args_against_schema",
    "reconcile_dynamic_catalog",
]

from .computer_use import ComputerUseLoop, propose_actions_from_model_text, run_computer_use_loop  # noqa: E402,F401
