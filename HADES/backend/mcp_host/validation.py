"""JSON Schema 2020-12 validation for MCP tool input/output schemas.

Uses the established ``jsonschema`` Draft202012Validator with:
- no remote $ref resolution (SSRF prevention)
- bounded depth / reference expansion
- clear schema-support vs instance-validation distinction
"""

from __future__ import annotations

import re
from typing import Any

try:
    import jsonschema
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError, ValidationError
    from jsonschema.validators import validator_for
except Exception:  # pragma: no cover - dependency optional until installed
    jsonschema = None  # type: ignore
    Draft202012Validator = None  # type: ignore
    SchemaError = Exception  # type: ignore
    ValidationError = Exception  # type: ignore
    validator_for = None  # type: ignore

MAX_SCHEMA_DEPTH = 32
MAX_REF_EXPANSIONS = 64


class SchemaSupportError(ValueError):
    """Schema cannot be safely validated (unsupported / external refs / cycles)."""

    def __init__(self, message: str, *, classification: str = "unsupported_schema") -> None:
        super().__init__(message)
        self.classification = classification


def _reject_external_refs(schema: Any, *, path: str = "$", seen: set[int] | None = None, depth: int = 0) -> None:
    if depth > MAX_SCHEMA_DEPTH:
        raise SchemaSupportError("schema exceeds max depth", classification="schema_depth")
    if isinstance(schema, dict):
        obj_id = id(schema)
        seen = seen or set()
        if obj_id in seen:
            return
        seen.add(obj_id)
        ref = schema.get("$ref")
        if isinstance(ref, str):
            if ref.startswith("http://") or ref.startswith("https://") or ref.startswith("//"):
                raise SchemaSupportError(
                    f"external $ref is not allowed ({path}): {ref}",
                    classification="external_ref",
                )
            if ref.startswith("file:"):
                raise SchemaSupportError(
                    f"file $ref is not allowed ({path}): {ref}",
                    classification="external_ref",
                )
        for key, value in schema.items():
            _reject_external_refs(value, path=f"{path}.{key}", seen=seen, depth=depth + 1)
    elif isinstance(schema, list):
        for idx, item in enumerate(schema):
            _reject_external_refs(item, path=f"{path}[{idx}]", seen=seen, depth=depth + 1)


def analyze_input_schema(schema: Any) -> dict[str, Any]:
    """Soft analysis used at discovery time."""
    if schema is None:
        return {"ok": True, "issues": []}
    if not isinstance(schema, dict):
        return {"ok": False, "issues": ["inputSchema is not a JSON object"], "classification": "invalid_schema"}
    schema_type = schema.get("type", "object")
    if schema_type not in {None, "object"} and not (isinstance(schema_type, list) and "object" in schema_type):
        return {
            "ok": False,
            "issues": [f"unsupported root schema type: {schema_type}"],
            "classification": "unsupported_root",
        }
    try:
        _reject_external_refs(schema)
    except SchemaSupportError as exc:
        return {"ok": False, "issues": [str(exc)], "classification": exc.classification}
    return {"ok": True, "issues": []}


def validate_tool_arguments(schema: Any, arguments: Any) -> dict[str, Any]:
    """Validate ``arguments`` against an MCP tool inputSchema.

    Raises ``ValueError`` on invalid instances.
    Raises ``SchemaSupportError`` when the schema itself cannot be safely evaluated.
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    if schema is None:
        return dict(arguments)
    if not isinstance(schema, dict):
        raise ValueError("inputSchema is not a JSON object")

    analysis = analyze_input_schema(schema)
    if not analysis.get("ok"):
        raise SchemaSupportError(
            "; ".join(analysis.get("issues") or ["unsupported schema"]),
            classification=str(analysis.get("classification") or "unsupported_schema"),
        )

    if jsonschema is None or Draft202012Validator is None:
        return _legacy_validate_object(schema, dict(arguments), path="$")

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaSupportError(f"invalid JSON Schema 2020-12: {exc}", classification="invalid_schema") from exc

    validator = Draft202012Validator(schema, format_checker=None)
    # Prevent remote retrieval even if a reference sneaks in.
    # Draft202012Validator no longer exposes .resolver; external refs are rejected above.
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "$"
        raise ValueError(f"Tool argument validation failed at {path}: {first.message}")
    return dict(arguments)


def validate_structured_output(schema: Any, structured: Any) -> dict[str, Any]:
    """Validate tool structuredContent against advertised outputSchema when present."""
    if schema is None:
        return {"ok": True, "checked": False}
    if structured is None:
        return {"ok": False, "checked": True, "error": "structuredContent missing while outputSchema is advertised"}
    try:
        _reject_external_refs(schema)
    except SchemaSupportError as exc:
        return {"ok": False, "checked": True, "error": str(exc), "classification": exc.classification}
    if jsonschema is None or Draft202012Validator is None:
        return {"ok": True, "checked": False, "warning": "jsonschema unavailable"}
    try:
        Draft202012Validator(schema).validate(structured)
    except ValidationError as exc:
        return {"ok": False, "checked": True, "error": exc.message}
    except SchemaError as exc:
        return {"ok": False, "checked": True, "error": f"invalid outputSchema: {exc}", "classification": "invalid_schema"}
    return {"ok": True, "checked": True}


# --- Fallback subset validator when jsonschema is unavailable -----------------

def _legacy_validate_object(schema: dict[str, Any], value: dict[str, Any], *, path: str) -> dict[str, Any]:
    schema_type = schema.get("type", "object")
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    if schema_type is not None and "object" not in types and schema_type != "object":
        raise ValueError(f"{path}: expected object root for tool arguments")
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required", [])
    required_names = {str(item) for item in required} if isinstance(required, list) else set()
    out = dict(value)
    for name, definition in properties.items():
        if not isinstance(definition, dict):
            continue
        if name not in out and "default" in definition:
            out[name] = definition["default"]
        if name in required_names and name not in out:
            raise ValueError(f"Verplicht toolveld ontbreekt: {name}")
        if name not in out:
            continue
        out[name] = _legacy_validate_value(definition, out[name], path=f"{path}.{name}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(out) - set(properties))
        if unknown:
            raise ValueError("Onbekende toolvelden: " + ", ".join(unknown))
    return out


def _legacy_validate_value(schema: dict[str, Any], actual: Any, *, path: str) -> Any:
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]

    def _matches(type_name: Any) -> bool:
        return (
            type_name in {None, "any"}
            or type_name == "string"
            and isinstance(actual, str)
            or type_name == "array"
            and isinstance(actual, list)
            or type_name == "object"
            and isinstance(actual, dict)
            or type_name == "boolean"
            and isinstance(actual, bool)
            or type_name == "integer"
            and isinstance(actual, int)
            and not isinstance(actual, bool)
            or type_name == "number"
            and isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            or type_name == "null"
            and actual is None
        )

    if expected is not None and not any(_matches(t) for t in expected_types):
        raise ValueError(f"Toolveld '{path}' heeft type {expected} nodig.")
    if "enum" in schema and actual not in schema["enum"]:
        raise ValueError(f"Toolveld '{path}' moet één van de toegestane waarden gebruiken.")
    if "const" in schema and actual != schema["const"]:
        raise ValueError(f"Toolveld '{path}' voldoet niet aan const.")
    if isinstance(actual, (str, list, dict)):
        if "minLength" in schema and len(actual) < int(schema["minLength"]):
            raise ValueError(f"Toolveld '{path}' is te kort.")
        if "maxLength" in schema and len(actual) > int(schema["maxLength"]):
            raise ValueError(f"Toolveld '{path}' is te lang.")
        if "minItems" in schema and isinstance(actual, list) and len(actual) < int(schema["minItems"]):
            raise ValueError(f"Toolveld '{path}' bevat te weinig waarden.")
        if "maxItems" in schema and isinstance(actual, list) and len(actual) > int(schema["maxItems"]):
            raise ValueError(f"Toolveld '{path}' bevat te veel waarden.")
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        if "minimum" in schema and actual < schema["minimum"]:
            raise ValueError(f"Toolveld '{path}' ligt onder de minimumwaarde.")
        if "maximum" in schema and actual > schema["maximum"]:
            raise ValueError(f"Toolveld '{path}' ligt boven de maximumwaarde.")
    if "string" in expected_types and isinstance(actual, str) and schema.get("pattern"):
        try:
            if not re.search(str(schema["pattern"]), actual):
                raise ValueError(f"Toolveld '{path}' voldoet niet aan het vereiste patroon.")
        except re.error as exc:
            raise ValueError(f"Tool-schema voor '{path}' bevat een ongeldig patroon.") from exc
    if isinstance(actual, dict) and ("object" in expected_types or expected is None) and isinstance(schema.get("properties"), dict):
        return _legacy_validate_object(schema, actual, path=path)
    if isinstance(actual, list) and "array" in expected_types and isinstance(schema.get("items"), dict):
        item_schema = schema["items"]
        return [_legacy_validate_value(item_schema, item, path=f"{path}[{idx}]") for idx, item in enumerate(actual)]
    return actual
