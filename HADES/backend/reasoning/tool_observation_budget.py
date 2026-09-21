"""Single total character budget for model-facing tool observations."""

from __future__ import annotations

import json
from typing import Any

_CORE_KEYS = ("status", "error", "exit_code", "retryable")


def _json_len(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False))


def _clip_field(text: str, limit: int) -> tuple[str, dict[str, int] | None]:
    raw = str(text or "")
    if limit <= 0:
        return "", {"original_chars": len(raw), "kept_chars": 0}
    if len(raw) <= limit:
        return raw, None
    return raw[:limit], {"original_chars": len(raw), "kept_chars": limit}


def build_bounded_tool_observation(
    result: dict[str, Any],
    *,
    max_chars: int | None,
    structured_output: Any | None = None,
) -> dict[str, Any]:
    """Build observation dict honoring one shared budget across text + structured fields.

    Core failure fields (status, error, exit_code) are never truncated.
    """
    row = dict(result)
    structured = structured_output if structured_output is not None else row.get("structured_output")
    if structured is not None and not isinstance(structured, (dict, list)):
        structured = {"value": structured}

    base: dict[str, Any] = {
        "status": row.get("status"),
        "error": row.get("error"),
        "exit_code": row.get("exit_code"),
        "retryable": bool(row.get("retryable")),
    }
    if max_chars is None:
        payload = {
            **base,
            "stdout": str(row.get("stdout") or ""),
            "stderr": str(row.get("stderr") or ""),
            "output": str(row.get("output") or ""),
        }
        if structured is not None:
            payload["structured_output"] = structured
        return payload

    budget = max(256, int(max_chars))
    truncation: dict[str, Any] = {"budget_chars": budget, "fields": {}}
    used = _json_len({**base, "stdout": "", "stderr": "", "output": ""})
    remaining = max(0, budget - used)

    status = str(base.get("status") or "").lower()
    failed = status in {"failed", "error", "blocked", "approval_required"} or base.get("error")

    field_order = ("stderr", "stdout", "output") if failed else ("stdout", "output", "stderr")
    text_values: dict[str, str] = {}
    for field in field_order:
        raw = str(row.get(field) or "")
        if remaining <= 0:
            if raw:
                text_values[field] = ""
                truncation["fields"][field] = {"original_chars": len(raw), "kept_chars": 0}
            else:
                text_values[field] = ""
            continue
        clipped, meta = _clip_field(raw, remaining)
        text_values[field] = clipped
        if meta:
            truncation["fields"][field] = meta
        remaining -= len(clipped)

    structured_out: Any | None = None
    if structured is not None:
        try:
            structured_text = json.dumps(structured, ensure_ascii=False)
        except Exception:
            structured_text = str(structured)
        if remaining > 0 and len(structured_text) <= remaining:
            structured_out = structured
            remaining -= len(structured_text)
        elif remaining > 0:
            clipped, meta = _clip_field(structured_text, remaining)
            try:
                structured_out = json.loads(clipped) if clipped.startswith(("{", "[")) else clipped
            except Exception:
                structured_out = clipped
            if meta:
                truncation["fields"]["structured_output"] = meta
            remaining = 0
        else:
            truncation["fields"]["structured_output"] = {
                "original_chars": len(structured_text),
                "kept_chars": 0,
            }

    payload = {**base, **text_values}
    if structured_out is not None:
        payload["structured_output"] = structured_out
    if truncation["fields"]:
        truncation["truncated"] = True
        payload["_truncation"] = truncation
    return payload


def observation_payload_json(result: dict[str, Any], *, limit: int | None) -> str:
    structured = result.get("structured_output")
    try:
        from execution_truth import strip_model_authority_fields

        if isinstance(structured, dict):
            structured = strip_model_authority_fields(structured)
    except Exception:
        pass
    payload = build_bounded_tool_observation(result, max_chars=limit, structured_output=structured)
    return json.dumps(payload, ensure_ascii=False)
