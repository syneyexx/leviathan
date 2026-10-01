"""Bounded JSON Schema validation for ExecutionGateway (Draft 2020-12).

Trusted capability input schemas are precompiled and cached. Pathological
schemas (oversized, over-nested, or excessively wide) are rejected using the
same byte/structure ceilings as MCP tool schemas.

Supported draft: JSON Schema Draft 2020-12 via ``jsonschema.Draft202012Validator``.
Draft-07 schemas that are Draft 2020-12-compatible are accepted when they do
not rely on removed keywords.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from Data.modules.mcp.limits import DEFAULT_MCP_LIMITS

SUPPORTED_JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SUPPORTED_JSON_SCHEMA_DRAFT_NAME = "Draft 2020-12"

MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 2_048
MAX_ENUM_VALUES = 256
MAX_PROPERTIES_PER_OBJECT = 256
MAX_CACHE_ENTRIES = 256

_CACHE_LOCK = threading.Lock()
_VALIDATOR_CACHE: dict[str, Any] = {}


class SchemaValidationError(ValueError):
    """Raised when arguments fail schema validation or the schema is unsafe."""

    def __init__(self, message: str, *, reason: str = "validation") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SchemaLimits:
    max_schema_bytes: int = DEFAULT_MCP_LIMITS.max_tool_schema_bytes
    max_depth: int = MAX_SCHEMA_DEPTH
    max_nodes: int = MAX_SCHEMA_NODES
    max_enum_values: int = MAX_ENUM_VALUES
    max_properties_per_object: int = MAX_PROPERTIES_PER_OBJECT


DEFAULT_SCHEMA_LIMITS = SchemaLimits()


def _stable_schema_key(schema: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reject_pathological_schema(
    schema: Any,
    *,
    limits: SchemaLimits | None = None,
) -> None:
    """Raise SchemaValidationError when a schema exceeds MCP/execution ceilings."""
    caps = limits or DEFAULT_SCHEMA_LIMITS
    if not isinstance(schema, dict):
        raise SchemaValidationError("input_schema must be an object", reason="bad_schema")
    try:
        encoded = json.dumps(schema, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(
            f"input_schema is not JSON-serializable: {exc}", reason="bad_schema"
        ) from exc
    if len(encoded) > caps.max_schema_bytes:
        raise SchemaValidationError(
            f"input_schema exceeds max_schema_bytes ({len(encoded)} > {caps.max_schema_bytes})",
            reason="bad_schema",
        )

    nodes = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > caps.max_nodes:
            raise SchemaValidationError(
                f"input_schema exceeds max_nodes ({caps.max_nodes})",
                reason="bad_schema",
            )
        if depth > caps.max_depth:
            raise SchemaValidationError(
                f"input_schema exceeds max_depth ({caps.max_depth})",
                reason="bad_schema",
            )
        if not isinstance(node, dict):
            if isinstance(node, list):
                for item in node:
                    walk(item, depth + 1)
            return
        props = node.get("properties")
        if isinstance(props, dict):
            if len(props) > caps.max_properties_per_object:
                raise SchemaValidationError(
                    f"properties exceeds max_properties_per_object ({caps.max_properties_per_object})",
                    reason="bad_schema",
                )
            for sub in props.values():
                walk(sub, depth + 1)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, depth + 1)
        elif isinstance(items, list):
            for sub in items:
                walk(sub, depth + 1)
        for combinator in ("oneOf", "anyOf", "allOf"):
            branch = node.get(combinator)
            if isinstance(branch, list):
                for sub in branch:
                    walk(sub, depth + 1)
        if "not" in node:
            walk(node.get("not"), depth + 1)
        if "if" in node:
            walk(node.get("if"), depth + 1)
        if "then" in node:
            walk(node.get("then"), depth + 1)
        if "else" in node:
            walk(node.get("else"), depth + 1)
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            walk(additional, depth + 1)
        pattern_props = node.get("patternProperties")
        if isinstance(pattern_props, dict):
            for sub in pattern_props.values():
                walk(sub, depth + 1)
        enum_vals = node.get("enum")
        if isinstance(enum_vals, list) and len(enum_vals) > caps.max_enum_values:
            raise SchemaValidationError(
                f"enum exceeds max_enum_values ({caps.max_enum_values})",
                reason="bad_schema",
            )
        defs = node.get("$defs") or node.get("definitions")
        if isinstance(defs, dict):
            for sub in defs.values():
                walk(sub, depth + 1)

    walk(schema, 0)


def _build_validator(schema: dict[str, Any]) -> Any:
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
    except ImportError as exc:  # pragma: no cover
        raise SchemaValidationError(
            "jsonschema package required for Draft 2020-12 validation",
            reason="bad_schema",
        ) from exc
    try:
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except SchemaError as exc:
        raise SchemaValidationError(
            f"Invalid JSON Schema (Draft 2020-12): {exc}", reason="bad_schema"
        ) from exc


def get_compiled_validator(
    schema: dict[str, Any],
    *,
    limits: SchemaLimits | None = None,
    schema_hash: str | None = None,
) -> Any:
    """Return a cached Draft202012Validator for a trusted schema."""
    reject_pathological_schema(schema, limits=limits)
    key = schema_hash or _stable_schema_key(schema)
    with _CACHE_LOCK:
        cached = _VALIDATOR_CACHE.get(key)
        if cached is not None:
            return cached
        validator = _build_validator(schema)
        if len(_VALIDATOR_CACHE) >= MAX_CACHE_ENTRIES:
            _VALIDATOR_CACHE.pop(next(iter(_VALIDATOR_CACHE)))
        _VALIDATOR_CACHE[key] = validator
        return validator


def clear_validator_cache() -> None:
    with _CACHE_LOCK:
        _VALIDATOR_CACHE.clear()


def validate_args_against_schema(
    schema: dict[str, Any] | None,
    args: dict[str, Any],
    *,
    schema_hash: str | None = None,
    limits: SchemaLimits | None = None,
) -> None:
    """Validate ``args`` against a capability input schema."""
    if not schema:
        if not isinstance(args, dict):
            raise SchemaValidationError("arguments must be an object", reason="validation")
        return
    if not isinstance(args, dict):
        raise SchemaValidationError("arguments must be an object", reason="validation")
    effective = dict(schema)
    if "type" not in effective and (
        "properties" in effective
        or "required" in effective
        or "additionalProperties" in effective
    ):
        effective["type"] = "object"
    validator = get_compiled_validator(effective, limits=limits, schema_hash=schema_hash)
    errors = sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    err = errors[0]
    path = ".".join(str(p) for p in err.absolute_path) or "$"
    raise SchemaValidationError(
        f"Argument validation failed at {path}: {err.message}", reason="validation"
    )
