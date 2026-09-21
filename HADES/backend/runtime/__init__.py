"""HADES runtime package — execution gateway and related contracts."""

from .execution_gateway import (
    EXECUTION_GATEWAY_MODULE,
    PRIVILEGED_INVOCATION_TYPES,
    PUBLIC_INVOCATION_TYPES,
    PolicyModuleUnavailable,
    assert_public_invocation_type,
    enforce_policies_fail_closed,
    may_skip_tool_policies,
    normalize_invocation_type,
)

__all__ = [
    "EXECUTION_GATEWAY_MODULE",
    "PRIVILEGED_INVOCATION_TYPES",
    "PUBLIC_INVOCATION_TYPES",
    "PolicyModuleUnavailable",
    "assert_public_invocation_type",
    "enforce_policies_fail_closed",
    "may_skip_tool_policies",
    "normalize_invocation_type",
]
