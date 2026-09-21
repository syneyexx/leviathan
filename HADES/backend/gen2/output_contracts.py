"""Strict typed contracts for model outputs used by Gen2 / reasoning paths.

Distinguishes:
- model unreachable
- model invoked but invalid output
- valid output with insufficient quality (caller decides quality)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ContractError:
    field: str
    message: str
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "message": self.message, "code": self.code}


class ModelOutputValidationError(ValueError):
    def __init__(self, errors: list[ContractError], *, kind: str = "invalid_output") -> None:
        self.errors = errors
        self.kind = kind
        detail = "; ".join(f"{e.field}:{e.message}" for e in errors) or kind
        super().__init__(f"{kind}:{detail}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "errors": [e.to_dict() for e in self.errors],
            "message": str(self),
        }


def _err(field: str, message: str, code: str) -> ContractError:
    return ContractError(field=field, message=message, code=code)


def parse_bool_strict(value: Any, *, field: str = "value") -> tuple[bool | None, ContractError | None]:
    """Accept real bools and common string/int encodings; reject ambiguous truthiness."""
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1) and math.isfinite(float(value)):
            return bool(int(value)), None
        return None, _err(field, f"non_binary_numeric:{value}", "type")
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True, None
        if lowered in {"false", "no", "0"}:
            return False, None
        return None, _err(field, f"unrecognized_bool_string:{value}", "type")
    if value is None:
        return None, _err(field, "missing", "missing")
    return None, _err(field, f"wrong_type:{type(value).__name__}", "type")


def parse_confidence(value: Any, *, field: str = "confidence") -> tuple[float | None, ContractError | None]:
    """Preserve valid zero; reject missing/non-finite/out-of-range."""
    if value is None:
        return None, _err(field, "missing", "missing")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, _err(field, f"not_numeric:{value!r}", "type")
    if not math.isfinite(number):
        return None, _err(field, "non_finite", "range")
    if number < 0.0 or number > 1.0:
        return None, _err(field, f"out_of_range:{number}", "range")
    return number, None


def validate_committee_stance(payload: Any) -> dict[str, Any]:
    """Validate committee/live specialist JSON stance."""
    errors: list[ContractError] = []
    if not isinstance(payload, dict):
        raise ModelOutputValidationError(
            [_err("$", "expected_object", "type")],
            kind="invalid_output",
        )
    claim = payload.get("claim")
    if claim is None or (isinstance(claim, str) and not claim.strip()):
        errors.append(_err("claim", "missing_or_empty", "missing"))
    elif not isinstance(claim, str):
        errors.append(_err("claim", f"wrong_type:{type(claim).__name__}", "type"))

    confidence, cerr = parse_confidence(payload.get("confidence"), field="confidence")
    if cerr:
        errors.append(cerr)

    supported, serr = parse_bool_strict(payload.get("supported"), field="supported")
    if serr:
        errors.append(serr)

    rationale = payload.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        errors.append(_err("rationale", f"wrong_type:{type(rationale).__name__}", "type"))

    if errors:
        raise ModelOutputValidationError(errors, kind="invalid_output")

    return {
        "claim": str(claim).strip(),
        "confidence": float(confidence if confidence is not None else 0.0),
        "supported": bool(supported),
        "rationale": str(rationale or "").strip() or "Live specialist output.",
    }


def validate_plan_payload(payload: Any) -> dict[str, Any]:
    """Minimal plan contract: goal + steps list with titles."""
    errors: list[ContractError] = []
    if not isinstance(payload, dict):
        raise ModelOutputValidationError([_err("$", "expected_object", "type")])
    goal = payload.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        errors.append(_err("goal", "missing_or_empty", "missing"))
    steps = payload.get("steps")
    if not isinstance(steps, list):
        errors.append(_err("steps", "expected_list", "type"))
        steps = []
    clean_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(_err(f"steps[{index}]", "expected_object", "type"))
            continue
        title = step.get("title") or step.get("name")
        if not isinstance(title, str) or not title.strip():
            errors.append(_err(f"steps[{index}].title", "missing_or_empty", "missing"))
            continue
        clean_steps.append(
            {
                "title": title.strip(),
                "instruction": str(step.get("instruction") or step.get("detail") or title).strip(),
                "depends_on": list(step.get("depends_on") or []),
            }
        )
    if errors:
        raise ModelOutputValidationError(errors)
    return {"goal": str(goal).strip(), "steps": clean_steps}


def validate_tool_call_payload(payload: Any) -> dict[str, Any]:
    errors: list[ContractError] = []
    if not isinstance(payload, dict):
        raise ModelOutputValidationError([_err("$", "expected_object", "type")])
    name = payload.get("name") or payload.get("tool") or payload.get("tool_name")
    if not isinstance(name, str) or not name.strip():
        errors.append(_err("name", "missing_or_empty", "missing"))
    args = payload.get("arguments")
    if args is None:
        args = payload.get("args") or {}
    if not isinstance(args, dict):
        errors.append(_err("arguments", "expected_object", "type"))
        args = {}
    if errors:
        raise ModelOutputValidationError(errors)
    return {"name": str(name).strip(), "arguments": dict(args)}


def validate_verification_payload(payload: Any) -> dict[str, Any]:
    errors: list[ContractError] = []
    if not isinstance(payload, dict):
        raise ModelOutputValidationError([_err("$", "expected_object", "type")])
    passed, perr = parse_bool_strict(payload.get("passed"), field="passed")
    if perr:
        errors.append(perr)
    issues = payload.get("issues")
    if issues is None:
        issues = []
    if not isinstance(issues, list):
        errors.append(_err("issues", "expected_list", "type"))
        issues = []
    evidence_refs = payload.get("evidence_refs")
    if evidence_refs is None:
        evidence_refs = []
    if not isinstance(evidence_refs, list):
        errors.append(_err("evidence_refs", "expected_list", "type"))
        evidence_refs = []
    if errors:
        raise ModelOutputValidationError(errors)
    return {
        "passed": bool(passed),
        "issues": [str(i) for i in issues],
        "evidence_refs": [str(r) for r in evidence_refs],
        "final": payload.get("final"),
        "incomplete": bool(payload.get("incomplete")) if payload.get("incomplete") is not None else False,
    }
