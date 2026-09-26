"""W04 — Model capability and inference contract enforcement.

Canonical owner for transport-level honesty:
- tool-calling: probe/record; never silently drop requested tools
- structured / json_schema: deterministic repair or fail closed (UNAVAILABLE)
- context bounds: refuse or truncate with an explicit signal (no silent overflow)

Reasoning stream channel separation lives in streaming.py; this module
records capability outcomes and structured/context contracts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.models.contracts import CapabilityState
from Data.modules.models.errors import (
    CAPABILITY_NOT_SUPPORTED,
    CONTEXT_WINDOW_EXCEEDED,
    ModelControlError,
)

# Fail-closed structured outcome — never pretend schema satisfaction.
STRUCTURED_RESPONSE_UNAVAILABLE = "STRUCTURED_RESPONSE_UNAVAILABLE"
TOOL_CALLING_DROPPED = "TOOL_CALLING_DROPPED"
CONTEXT_TRUNCATED = "CONTEXT_TRUNCATED"


class ContextOverflowPolicy(str, Enum):
    REFUSE = "refuse"
    TRUNCATE = "truncate"


@dataclass
class ToolCallingRecord:
    """Honest record of whether tools were requested, transported, and observed."""

    requested: bool
    tools_in_payload: bool
    feature_state: str
    tool_calls_returned: bool = False
    measured_state: str = CapabilityState.UNMEASURED.value
    silently_dropped: bool = False
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "toolsInPayload": self.tools_in_payload,
            "featureState": self.feature_state,
            "toolCallsReturned": self.tool_calls_returned,
            "measuredState": self.measured_state,
            "silentlyDropped": self.silently_dropped,
            "detail": self.detail,
            "truth": {
                "requested_tools_never_silently_dropped": not self.silently_dropped,
                "supported_requires_measurement_or_roundtrip": True,
            },
        }


@dataclass
class StructuredResponseResult:
    """Outcome of schema-constrained response handling."""

    requested: bool
    schema: dict[str, Any] | None
    status: str  # satisfied | repaired | UNAVAILABLE | not_requested
    parsed: Any = None
    repaired: bool = False
    repair_notes: list[str] = field(default_factory=list)
    detail: str | None = None
    schema_satisfied: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "status": self.status,
            "repaired": self.repaired,
            "repairNotes": list(self.repair_notes),
            "schemaSatisfied": self.schema_satisfied,
            "detail": self.detail,
            "hasParsed": self.parsed is not None,
            "truth": {
                "structured_success_requires_schema_satisfaction": True,
                "unavailable_is_not_structured_success": self.status
                != "UNAVAILABLE"
                or not self.schema_satisfied,
            },
        }


@dataclass
class ContextBoundSignal:
    """Explicit signal when context is refused or truncated — never silent."""

    policy: str
    applied: str  # fit | refused | truncated | unknown
    original_tokens: int | None = None
    final_tokens: int | None = None
    usable_tokens: int | None = None
    context_window: int | None = None
    truncated: bool = False
    refused: bool = False
    dropped_message_count: int = 0
    code: str | None = None
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "applied": self.applied,
            "originalTokens": self.original_tokens,
            "finalTokens": self.final_tokens,
            "usableTokens": self.usable_tokens,
            "contextWindow": self.context_window,
            "truncated": self.truncated,
            "refused": self.refused,
            "droppedMessageCount": self.dropped_message_count,
            "code": self.code,
            "detail": self.detail,
            "truth": {
                "no_silent_context_overflow": True,
                "truncation_is_explicit": (not self.truncated) or self.code == CONTEXT_TRUNCATED,
            },
        }


def extract_json_schema(response_format: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull the JSON Schema object from an OpenAI-style response_format, if any."""
    if not isinstance(response_format, dict):
        return None
    rf_type = str(response_format.get("type") or "")
    if rf_type == "json_schema":
        body = response_format.get("json_schema")
        if isinstance(body, dict):
            schema = body.get("schema")
            if isinstance(schema, dict):
                return schema
            # Some providers nest the schema at the top of json_schema.
            if "type" in body or "properties" in body:
                return body
        return None
    if rf_type == "json_object":
        # Free-form JSON object — no schema to satisfy beyond parseable object.
        return {"type": "object"}
    return None


def validate_json_schema(payload: Any, schema: dict[str, Any], *, path: str = "$") -> tuple[bool, str]:
    """Minimal recursive JSON Schema subset (type/required/properties/enum/minmax/items)."""
    if not isinstance(schema, dict):
        return True, "no schema"
    expected_type = schema.get("type")
    if expected_type:
        type_ok = {
            "object": isinstance(payload, dict),
            "array": isinstance(payload, list),
            "string": isinstance(payload, str),
            "number": isinstance(payload, (int, float)) and not isinstance(payload, bool),
            "integer": isinstance(payload, int) and not isinstance(payload, bool),
            "boolean": isinstance(payload, bool),
            "null": payload is None,
        }.get(str(expected_type))
        if type_ok is False:
            return False, f"{path}: expected type {expected_type}, got {type(payload).__name__}"
    if "enum" in schema and payload not in schema["enum"]:
        return False, f"{path}: value not in enum"
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        if "minimum" in schema and payload < schema["minimum"]:
            return False, f"{path}: below minimum"
        if "maximum" in schema and payload > schema["maximum"]:
            return False, f"{path}: above maximum"
    if isinstance(payload, dict):
        required = list(schema.get("required") or [])
        missing = [k for k in required if k not in payload]
        if missing:
            return False, f"{path}: missing required keys: {missing}"
        props = dict(schema.get("properties") or {})
        for key, subschema in props.items():
            if key not in payload:
                continue
            if isinstance(subschema, dict):
                ok, detail = validate_json_schema(payload[key], subschema, path=f"{path}.{key}")
                if not ok:
                    return False, detail
    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(payload):
            ok, detail = validate_json_schema(item, schema["items"], path=f"{path}[{i}]")
            if not ok:
                return False, detail
    return True, "ok"


def deterministic_json_repair(text: str) -> tuple[Any | None, list[str]]:
    """Tier-0 deterministic JSON repair. Returns (parsed, notes) or (None, notes)."""
    notes: list[str] = []
    if not isinstance(text, str):
        return None, ["non-string content"]
    raw = text.strip()
    if not raw:
        return None, ["empty content"]

    candidates = [raw]

    # Strip markdown fences.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        notes.append("stripped_markdown_fence")
        candidates.insert(0, fence.group(1).strip())

    # Extract first object/array span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            span = raw[start : end + 1]
            if span not in candidates:
                notes.append(f"extracted_{'object' if opener == '{' else 'array'}_span")
                candidates.append(span)

    for cand in candidates:
        try:
            return json.loads(cand), notes
        except json.JSONDecodeError:
            pass
        # Trailing commas before } or ]
        repaired = re.sub(r",(\s*[}\]])", r"\1", cand)
        if repaired != cand:
            notes.append("removed_trailing_commas")
            try:
                return json.loads(repaired), notes
            except json.JSONDecodeError:
                pass
        # Single-quoted keys/strings → double quotes (conservative).
        if "'" in cand and '"' not in cand:
            swapped = cand.replace("'", '"')
            notes.append("single_to_double_quotes")
            try:
                return json.loads(swapped), notes
            except json.JSONDecodeError:
                pass

    return None, notes or ["unparseable"]


def enforce_structured_response(
    text: str,
    response_format: dict[str, Any] | None,
    *,
    fail_closed: bool = True,
) -> StructuredResponseResult:
    """Validate (and optionally repair) structured output. Fail closed → UNAVAILABLE."""
    schema = extract_json_schema(response_format)
    if response_format is None or schema is None and not (
        isinstance(response_format, dict) and response_format.get("type") in {"json_schema", "json_object"}
    ):
        return StructuredResponseResult(
            requested=False,
            schema=None,
            status="not_requested",
            schema_satisfied=False,
        )

    # json_schema without body is still a requested structured contract.
    if schema is None and isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        result = StructuredResponseResult(
            requested=True,
            schema=None,
            status="UNAVAILABLE",
            detail="json_schema response_format missing schema body",
            schema_satisfied=False,
        )
        if fail_closed:
            raise ModelControlError(
                code=STRUCTURED_RESPONSE_UNAVAILABLE,
                message=result.detail or "structured response unavailable",
                http_status=503,
                details=result.public_dict(),
            )
        return result

    assert schema is not None
    parsed: Any | None = None
    repaired = False
    notes: list[str] = []

    try:
        parsed = json.loads(text.strip()) if text.strip() else None
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        parsed, notes = deterministic_json_repair(text)
        repaired = parsed is not None

    if parsed is None:
        result = StructuredResponseResult(
            requested=True,
            schema=schema,
            status="UNAVAILABLE",
            repaired=False,
            repair_notes=notes,
            detail="content is not parseable JSON after deterministic repair",
            schema_satisfied=False,
        )
        if fail_closed:
            raise ModelControlError(
                code=STRUCTURED_RESPONSE_UNAVAILABLE,
                message=result.detail or "structured response unavailable",
                http_status=503,
                details=result.public_dict(),
            )
        return result

    ok, detail = validate_json_schema(parsed, schema)
    if not ok:
        result = StructuredResponseResult(
            requested=True,
            schema=schema,
            status="UNAVAILABLE",
            parsed=parsed,
            repaired=repaired,
            repair_notes=notes,
            detail=detail,
            schema_satisfied=False,
        )
        if fail_closed:
            raise ModelControlError(
                code=STRUCTURED_RESPONSE_UNAVAILABLE,
                message=f"structured response failed schema: {detail}",
                http_status=503,
                details=result.public_dict(),
            )
        return result

    return StructuredResponseResult(
        requested=True,
        schema=schema,
        status="repaired" if repaired else "satisfied",
        parsed=parsed,
        repaired=repaired,
        repair_notes=notes,
        detail=detail,
        schema_satisfied=True,
    )


def probe_tool_calling_transport(
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    payload_fields: dict[str, Any],
    feature_states: dict[str, str],
) -> ToolCallingRecord:
    """Record whether requested tools survived dialect adaptation (never silent drop)."""
    requested = tools is not None or tool_choice is not None
    if not requested:
        return ToolCallingRecord(
            requested=False,
            tools_in_payload=False,
            feature_state=CapabilityState.UNMEASURED.value,
            measured_state=CapabilityState.UNMEASURED.value,
            detail="tools not requested",
        )

    tools_in_payload = "tools" in payload_fields or "tool_choice" in payload_fields
    feature_state = str(
        feature_states.get("tool_calling") or CapabilityState.UNMEASURED.value
    )
    silently_dropped = requested and not tools_in_payload and feature_state == CapabilityState.SUPPORTED.value
    if silently_dropped:
        raise ModelControlError(
            code=TOOL_CALLING_DROPPED,
            message=(
                "Requested tools were marked SUPPORTED but omitted from provider payload "
                "(silent drop forbidden)"
            ),
            http_status=500,
            details={
                "featureState": feature_state,
                "payloadKeys": sorted(payload_fields.keys()),
            },
        )
    if requested and not tools_in_payload:
        # UNSUPPORTED/UNMEASURED without payload is only legal when reject_unsupported=False
        # and the dialect recorded rejection — still not a silent drop.
        return ToolCallingRecord(
            requested=True,
            tools_in_payload=False,
            feature_state=feature_state,
            measured_state=feature_state,
            silently_dropped=False,
            detail="tools requested but not in payload; feature state recorded (not silent)",
        )
    return ToolCallingRecord(
        requested=True,
        tools_in_payload=True,
        feature_state=feature_state,
        measured_state=CapabilityState.UNMEASURED.value,
        silently_dropped=False,
        detail="tools present in provider payload; awaiting response measurement",
    )


def record_tool_calling_response(
    record: ToolCallingRecord,
    *,
    tool_calls: Any,
) -> ToolCallingRecord:
    """Update measurement from provider response (roundtrip observed or not)."""
    if not record.requested:
        return record
    returned = bool(tool_calls)
    if returned:
        measured = CapabilityState.SUPPORTED.value
        detail = "tool_calls present in provider response"
    elif record.tools_in_payload:
        # Tools sent but model answered without tool_calls — still transported;
        # capability remains UNMEASURED for roundtrip (model chose not to call).
        measured = CapabilityState.UNMEASURED.value
        detail = "tools transported; no tool_calls in this response (not a silent drop)"
    else:
        measured = record.feature_state
        detail = record.detail
    return ToolCallingRecord(
        requested=record.requested,
        tools_in_payload=record.tools_in_payload,
        feature_state=record.feature_state,
        tool_calls_returned=returned,
        measured_state=measured,
        silently_dropped=False,
        detail=detail,
    )


def _estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += max(1, (len(content) + 3) // 4) + 4
        else:
            total += 4
    return total


def enforce_context_bounds(
    messages: list[dict[str, Any]],
    *,
    context_window: int | None,
    max_output_tokens: int | None = None,
    policy: ContextOverflowPolicy | str = ContextOverflowPolicy.REFUSE,
    usable_fraction: float = 0.72,
) -> tuple[list[dict[str, Any]], ContextBoundSignal]:
    """Refuse or truncate when over limit. Always returns an explicit signal."""
    if isinstance(policy, str):
        policy = ContextOverflowPolicy(policy)
    if context_window is None or int(context_window) <= 0:
        return list(messages), ContextBoundSignal(
            policy=policy.value,
            applied="unknown",
            context_window=context_window,
            detail="context window unknown — capacity UNMEASURED",
        )

    window = int(context_window)
    reserve = int(max_output_tokens or max(256, int(window * 0.18)))
    usable = max(1, int(window * usable_fraction) - reserve)
    original = _estimate_message_tokens(messages)
    if original <= usable:
        return list(messages), ContextBoundSignal(
            policy=policy.value,
            applied="fit",
            original_tokens=original,
            final_tokens=original,
            usable_tokens=usable,
            context_window=window,
        )

    if policy == ContextOverflowPolicy.REFUSE:
        signal = ContextBoundSignal(
            policy=policy.value,
            applied="refused",
            original_tokens=original,
            final_tokens=original,
            usable_tokens=usable,
            context_window=window,
            refused=True,
            code=CONTEXT_WINDOW_EXCEEDED,
            detail=f"input tokens {original} exceed usable budget {usable}",
        )
        raise ModelControlError(
            code=CONTEXT_WINDOW_EXCEEDED,
            message=signal.detail or "context window exceeded",
            http_status=409,
            details=signal.public_dict(),
        )

    # Truncate: keep system messages + newest messages that fit.
    system = [m for m in messages if str(m.get("role") or "") == "system"]
    rest = [m for m in messages if str(m.get("role") or "") != "system"]
    kept_rev: list[dict[str, Any]] = []
    dropped = 0
    # Start with system cost.
    used = _estimate_message_tokens(system)
    for msg in reversed(rest):
        cost = _estimate_message_tokens([msg])
        if used + cost <= usable:
            kept_rev.append(msg)
            used += cost
        else:
            dropped += 1
    kept = list(reversed(kept_rev))
    # If even a single newest message cannot fit with system, refuse — do not
    # silently send an over-limit payload.
    final_messages = system + kept
    final_tokens = _estimate_message_tokens(final_messages)
    if final_tokens > usable or (not kept and rest):
        signal = ContextBoundSignal(
            policy=policy.value,
            applied="refused",
            original_tokens=original,
            final_tokens=final_tokens,
            usable_tokens=usable,
            context_window=window,
            refused=True,
            dropped_message_count=dropped,
            code=CONTEXT_WINDOW_EXCEEDED,
            detail="truncation cannot bring context under usable budget",
        )
        raise ModelControlError(
            code=CONTEXT_WINDOW_EXCEEDED,
            message=signal.detail or "context window exceeded",
            http_status=409,
            details=signal.public_dict(),
        )

    return final_messages, ContextBoundSignal(
        policy=policy.value,
        applied="truncated",
        original_tokens=original,
        final_tokens=final_tokens,
        usable_tokens=usable,
        context_window=window,
        truncated=True,
        dropped_message_count=dropped,
        code=CONTEXT_TRUNCATED,
        detail=f"dropped {dropped} older non-system message(s)",
    )


def raise_if_tools_unsupported_when_required(
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    feature_states: dict[str, str],
) -> None:
    """When tools are required and dialect marked UNSUPPORTED, fail closed."""
    if tools is None and tool_choice is None:
        return
    state = feature_states.get("tool_calling")
    if state == CapabilityState.UNSUPPORTED.value:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="tool_calling is UNSUPPORTED for this dialect — tools not silently dropped",
            http_status=400,
            details={"feature": "tool_calling", "state": state},
        )
