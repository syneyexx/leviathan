"""Executable skill workflow steps — free text is description, not proof of a handler.

A workflow step must resolve to a known action with validated inputs/outputs.
Unknown or free-text-only steps fail the benchmark.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class SkillStepResult:
    index: int
    action: str
    passed: bool
    detail: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Handler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _handler_echo(inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    message = str(inputs.get("message") or inputs.get("text") or "").strip()
    if not message:
        raise ValueError("echo requires message")
    return {"echo": message, "ok": True}


def _handler_assert_nonempty(inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    value = inputs.get("value", inputs.get("text", ""))
    if value is None or str(value).strip() == "":
        raise ValueError("assert_nonempty failed")
    return {"value": value, "ok": True}


def _handler_record_artifact(inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    name = str(inputs.get("name") or "artifact").strip()
    content = str(inputs.get("content") or "").strip()
    if not content:
        raise ValueError("record_artifact requires content")
    artifacts = ctx.setdefault("artifacts", [])
    artifacts.append({"name": name, "content": content[:4000]})
    return {"artifact": name, "bytes": len(content), "ok": True}


def _handler_check_ctx_flag(inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    flag = str(inputs.get("flag") or "").strip()
    if not flag:
        raise ValueError("check_ctx_flag requires flag")
    if not ctx.get(flag):
        raise ValueError(f"ctx flag missing: {flag}")
    return {"flag": flag, "ok": True}


def _handler_set_ctx_flag(inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    flag = str(inputs.get("flag") or "").strip()
    if not flag:
        raise ValueError("set_ctx_flag requires flag")
    ctx[flag] = True
    return {"flag": flag, "ok": True}


# Actions that prove an executable handler exists for the candidate workflow.
SKILL_ACTION_HANDLERS: dict[str, Handler] = {
    "echo": _handler_echo,
    "assert_nonempty": _handler_assert_nonempty,
    "record_artifact": _handler_record_artifact,
    "check_ctx_flag": _handler_check_ctx_flag,
    "set_ctx_flag": _handler_set_ctx_flag,
}

PLACEHOLDER_NAMES = frozenset({"todo", "pass", "noop", "broken", "tbd", "placeholder"})


def normalize_skill_step(step: Any, index: int = 0) -> dict[str, Any]:
    """Normalize string or dict workflow entries into an executable step contract."""
    if isinstance(step, dict):
        action = str(step.get("action") or step.get("op") or step.get("name") or "").strip()
        inputs = dict(step.get("inputs") or {})
        outputs = dict(step.get("outputs") or {})
        success = step.get("success_criteria") or step.get("success") or []
        if isinstance(success, str):
            success = [success]
        description = str(step.get("description") or step.get("label") or "").strip()
        return {
            "index": index,
            "action": action,
            "inputs": inputs,
            "outputs": outputs,
            "success_criteria": list(success),
            "description": description,
            "raw": step,
        }
    name = str(step or "").strip()
    return {
        "index": index,
        "action": name,
        "inputs": {},
        "outputs": {},
        "success_criteria": [],
        "description": name,
        "raw": step,
    }


def execute_skill_step(
    step: Any,
    *,
    index: int = 0,
    ctx: dict[str, Any] | None = None,
) -> SkillStepResult:
    """Execute one workflow step against the known handler registry."""
    ctx = ctx if ctx is not None else {}
    normalized = normalize_skill_step(step, index=index)
    action = str(normalized.get("action") or "").strip()
    if not action:
        return SkillStepResult(
            index=index,
            action="",
            passed=False,
            detail="empty_or_missing_action",
            executed=False,
        )
    if action.lower() in PLACEHOLDER_NAMES:
        return SkillStepResult(
            index=index,
            action=action,
            passed=False,
            detail="placeholder_action_rejected",
            executed=False,
        )
    handler = SKILL_ACTION_HANDLERS.get(action)
    if handler is None:
        # Free-text description without a known handler is not proof of execution.
        return SkillStepResult(
            index=index,
            action=action,
            passed=False,
            detail="unknown_action:no_handler",
            inputs=dict(normalized.get("inputs") or {}),
            executed=False,
        )
    try:
        outputs = handler(dict(normalized.get("inputs") or {}), ctx)
        if not isinstance(outputs, dict):
            raise ValueError("handler_did_not_return_dict")
        if outputs.get("ok") is False:
            raise ValueError("handler_reported_not_ok")
        # Optional success criteria: require keys present in outputs.
        for criterion in normalized.get("success_criteria") or []:
            key = str(criterion).strip()
            if key.startswith("output:"):
                out_key = key.split(":", 1)[1]
                if out_key not in outputs:
                    raise ValueError(f"success_criteria_missing:{out_key}")
        return SkillStepResult(
            index=index,
            action=action,
            passed=True,
            detail="workflow_step_executed",
            inputs=dict(normalized.get("inputs") or {}),
            outputs=outputs,
            executed=True,
        )
    except Exception as exc:
        return SkillStepResult(
            index=index,
            action=action,
            passed=False,
            detail=f"handler_failed:{exc}",
            inputs=dict(normalized.get("inputs") or {}),
            executed=True,
        )


def execute_skill_workflow(workflow: list[Any]) -> dict[str, Any]:
    """Run all steps in an isolated in-memory context; return aggregate result."""
    ctx: dict[str, Any] = {"artifacts": []}
    results: list[SkillStepResult] = []
    if not workflow:
        return {
            "passed": False,
            "step_results": [
                SkillStepResult(index=0, action="", passed=False, detail="empty_workflow").to_dict()
            ],
            "artifacts": [],
            "executed_count": 0,
        }
    for index, step in enumerate(workflow):
        results.append(execute_skill_step(step, index=index, ctx=ctx))
    passed = all(r.passed for r in results) and all(r.executed for r in results)
    return {
        "passed": passed,
        "step_results": [r.to_dict() for r in results],
        "artifacts": list(ctx.get("artifacts") or []),
        "executed_count": sum(1 for r in results if r.executed),
        "pass_rate": round(sum(1 for r in results if r.passed) / max(1, len(results)), 4),
    }
