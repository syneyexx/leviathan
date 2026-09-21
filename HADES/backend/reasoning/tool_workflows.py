"""Validated multi-plugin tool workflow handoffs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


HandoffStatus = Literal["ok", "blocked", "failed", "invalid_input"]


@dataclass(slots=True)
class ToolStepSpec:
    step_id: str
    capability: str
    input_from: list[str]
    input_schema: dict[str, Any]
    expected_output_schema: dict[str, Any]
    success_check: str  # deterministic expression key, e.g. status==completed
    plugin_id: str | None = None
    tool_name: str | None = None
    artifact_ref_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HandoffResult:
    status: HandoffStatus
    step_id: str
    artifact_ref: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error_category: str | None = None
    error: str | None = None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def validate_against_schema(data: Any, schema: dict[str, Any]) -> list[str]:
    """Minimal JSON-Schema subset validation for handoffs (type/required/properties)."""
    errors: list[str] = []
    if not schema:
        return errors
    expected_type = schema.get("type")
    if expected_type:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if _type_name(data) not in types and not (
            _type_name(data) == "integer" and "number" in types
        ):
            errors.append(f"expected type {expected_type}, got {_type_name(data)}")
            return errors
    if schema.get("type") == "object" or isinstance(data, dict):
        if not isinstance(data, dict):
            errors.append("expected object")
            return errors
        for key in schema.get("required") or []:
            if key not in data:
                errors.append(f"missing required field '{key}'")
        props = schema.get("properties") or {}
        for key, subschema in props.items():
            if key in data and isinstance(subschema, dict):
                errors.extend(f"{key}.{err}" if not err.startswith(key) else err for err in validate_against_schema(data[key], subschema))
    return errors


def resolve_inputs(
    spec: ToolStepSpec,
    prior_outputs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, HandoffResult | None]:
    """Build input object from prior artifact refs; never trust free-form model paths alone."""
    merged: dict[str, Any] = {}
    for ref in spec.input_from:
        if ref not in prior_outputs:
            return None, HandoffResult(
                status="invalid_input",
                step_id=spec.step_id,
                error_category="missing_prior_output",
                error=f"Vereiste invoer '{ref}' ontbreekt.",
            )
        payload = prior_outputs[ref]
        if isinstance(payload, dict):
            merged.update(payload)
        else:
            merged[ref] = payload
    schema_errors = validate_against_schema(merged, spec.input_schema)
    if schema_errors:
        return None, HandoffResult(
            status="invalid_input",
            step_id=spec.step_id,
            error_category="schema_validation",
            error="; ".join(schema_errors),
        )
    return merged, None


def evaluate_success(spec: ToolStepSpec, result: dict[str, Any]) -> HandoffResult:
    check = (spec.success_check or "").strip()
    status = str(result.get("status") or "").lower()

    if status in {"blocked", "denied", "permission"}:
        return HandoffResult(
            status="blocked",
            step_id=spec.step_id,
            error_category="permission_or_policy",
            blocked_reason=str(result.get("error") or result.get("blocked_reason") or "Geblokkeerd door policy."),
            output=result if isinstance(result, dict) else {},
        )

    ok = False
    if check in {"status==completed", "status=completed", "completed"}:
        ok = status in {"completed", "succeeded", "success", "ok"}
    elif check.startswith("has:"):
        key = check.split(":", 1)[1]
        ok = key in result and result.get(key) not in (None, "", [], {})
    else:
        ok = status in {"completed", "succeeded", "success", "ok"}

    out_errors = validate_against_schema(result.get("output", result), spec.expected_output_schema)
    if out_errors:
        return HandoffResult(
            status="failed",
            step_id=spec.step_id,
            error_category="output_schema",
            error="; ".join(out_errors),
            output=result if isinstance(result, dict) else {},
        )

    artifact = None
    if spec.artifact_ref_key:
        artifact = result.get(spec.artifact_ref_key) or (result.get("output") or {}).get(spec.artifact_ref_key)

    if not ok:
        return HandoffResult(
            status="failed",
            step_id=spec.step_id,
            error_category="success_check",
            error=str(result.get("error") or f"Success check failed: {check}"),
            output=result if isinstance(result, dict) else {},
        )

    return HandoffResult(
        status="ok",
        step_id=spec.step_id,
        artifact_ref=str(artifact) if artifact is not None else None,
        output=result if isinstance(result, dict) else {"value": result},
    )


def should_retry_alternative(
    *,
    failed: HandoffResult,
    alternative_capability: str,
    original_capability: str,
    side_effects: str = "uncertain",
) -> bool:
    """Only run an alternative when it can fulfill the same intent; avoid uncertain side-effect retries."""
    if failed.status == "blocked":
        return False
    if side_effects == "uncertain":
        return False
    return alternative_capability == original_capability
