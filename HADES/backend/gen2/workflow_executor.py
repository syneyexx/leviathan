"""Authoritative Gen2 workflow executor (A06).

Modes:
- dry_run: validation/plan only (delegates to workflows.dry_run)
- sandbox: isolated skill_runtime primitives only — never product-ready
- product: real adapters (CodingAgent / ResearchRunner / PluginManager /
  model gateway / ArtifactService), long-running outside HTTP when async

One executor owns control: cancel / pause / resume / timeout / approvals.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from gen2.skill_runtime import SKILL_ACTION_HANDLERS, execute_skill_step
from gen2.store import Gen2Store, utc_now
from gen2.workflow_adapters import (
    PRODUCT_ACTIONS,
    WorkflowServices,
    execute_product_action,
    resolve_bindings,
    workflow_definition_hash,
)

RecordFn = Callable[..., dict[str, Any]]

HITL_STEP_TYPES = frozenset({"approve", "choose", "provide_secret"})

_EXECUTOR_POOL: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.RLock()
_CONTROL: dict[str, dict[str, Any]] = {}


def _pool() -> ThreadPoolExecutor:
    global _EXECUTOR_POOL
    with _EXECUTOR_LOCK:
        if _EXECUTOR_POOL is None:
            _EXECUTOR_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hades-wf-exec")
        return _EXECUTOR_POOL


def _control_for(run_id: str) -> dict[str, Any]:
    with _EXECUTOR_LOCK:
        return _CONTROL.setdefault(
            run_id,
            {
                "cancel_requested": False,
                "pause_requested": False,
                "paused": False,
                "resume_event": threading.Event(),
            },
        )


def request_cancel(run_id: str) -> dict[str, Any]:
    ctl = _control_for(run_id)
    ctl["cancel_requested"] = True
    ctl["resume_event"].set()
    return {"run_id": run_id, "cancel_requested": True}


def request_pause(run_id: str) -> dict[str, Any]:
    ctl = _control_for(run_id)
    ctl["pause_requested"] = True
    return {"run_id": run_id, "pause_requested": True}


def request_resume(run_id: str) -> dict[str, Any]:
    ctl = _control_for(run_id)
    ctl["pause_requested"] = False
    ctl["paused"] = False
    ctl["resume_event"].set()
    return {"run_id": run_id, "resume_requested": True}


def _topo_order(steps: list[dict[str, Any]]) -> list[str]:
    deps_map: dict[str, list[str]] = {
        str(s["id"]): [str(d) for d in (s.get("depends_on") or [])] for s in steps if s.get("id")
    }
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"dependency cycle involving:{node}")
        if node in visited:
            return
        visiting.add(node)
        for dep in deps_map.get(node, []):
            if dep in deps_map:
                visit(dep)
        visiting.remove(node)
        visited.add(node)
        ordered.append(node)

    for sid in deps_map:
        visit(sid)
    return ordered


def _sum_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [u for u in usages if isinstance(u, dict) and u.get("source") == "measured"]
    if not measured:
        return {"source": "not_measured", "total_tokens": None, "note": "no_fabricated_tokens"}
    total = 0
    any_total = False
    for u in measured:
        for key in ("total_tokens", "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
            if u.get(key) is not None:
                try:
                    total += int(u[key])
                    any_total = True
                except (TypeError, ValueError):
                    pass
    if not any_total:
        return {"source": "not_measured", "total_tokens": None, "note": "measured_rows_without_counts"}
    return {"source": "measured", "total_tokens": total, "contributing_steps": len(measured)}


def _is_product_workflow(ir: dict[str, Any]) -> bool:
    if str(ir.get("fixture_kind") or "").lower() in {"heritage", "heritage_demo", "demo"}:
        return False
    tags = {str(t).lower() for t in (ir.get("pattern_tags") or [])}
    if "heritage" in tags or "demo" in tags or "heritage_demo" in tags:
        return False
    for step in ir.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("type") or "action") in HITL_STEP_TYPES:
            continue
        action = str(step.get("action") or "").strip()
        if action in PRODUCT_ACTIONS:
            return True
    return str(ir.get("fixture_kind") or "").lower() == "product"


def execute_sandbox(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    run_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Isolated skill_runtime handlers only. Never claims product readiness."""
    from gen2.workflows import normalize_workflow_ir, validate_workflow, _evaluate_success_checks

    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    errors = validate_workflow(ir)
    if errors:
        result = {
            "mode": "sandbox",
            "live_execution": False,
            "product_ready": False,
            "passed": False,
            "status": "failed",
            "validation_errors": errors,
            "step_results": [],
            "note": "Sandbox-run refused: IR invalid.",
        }
        run = store.create_workflow_run(
            workflow_id=workflow_id,
            version=int(ir.get("version") or 1),
            mode="sandbox",
            status="failed",
            result=result,
        )
        return {**result, "run_id": run["id"], "workflow_id": workflow_id}

    definition_hash = workflow_definition_hash(ir)
    # Product workflows cannot be "tested" via sandbox simulation.
    if is_product_workflow(ir):
        result = {
            "mode": "sandbox",
            "live_execution": False,
            "product_ready": False,
            "passed": False,
            "status": "failed",
            "step_results": [
                {
                    "id": "__gate__",
                    "action": "",
                    "passed": False,
                    "executed": False,
                    "detail": "product_action_requires_product_mode",
                    "error": "product_action_requires_product_mode",
                }
            ],
            "definition_hash": definition_hash,
            "note": (
                "Sandbox refused: product workflows require /execute (product mode). "
                "Heritage demos use skill_runtime primitives only."
            ),
            "metrics": {
                "latency_ms": 0,
                "tool_failures": 1,
                "cost_tokens": None,
                "usage": {"source": "not_measured", "total_tokens": None},
                "passed": False,
                "definition_hash": definition_hash,
            },
        }
        run = store.create_workflow_run(
            workflow_id=workflow_id,
            version=int(ir.get("version") or 1),
            mode="sandbox",
            status="failed",
            result=result,
        )
        _update_evidence(
            store,
            workflow_id,
            mode="sandbox",
            run_id=run["id"],
            passed=False,
            definition_hash=definition_hash,
            awaiting=None,
            product_ready=False,
        )
        record(
            workflow_id,
            "VERIFICATION",
            {
                "mode": "sandbox",
                "status": "failed",
                "passed": False,
                "run_id": run["id"],
                "product_ready": False,
                "definition_hash": definition_hash,
                "reason": "product_action_requires_product_mode",
            },
            component="workflows",
        )
        return {**result, "run_id": run["id"], "workflow_id": workflow_id}

    started = time.perf_counter()
    order = _topo_order(list(ir.get("steps") or []))
    ctx: dict[str, Any] = {
        "artifacts": [],
        "steps": {},
        "checkpoints": [],
        "run_inputs": dict(run_inputs or {}),
    }
    step_results: list[dict[str, Any]] = []
    tool_failures = 0
    awaiting_step: dict[str, Any] | None = None
    # Empty IR / zero executable steps must not default to successful "completed".
    if not order:
        status = "failed"
        passed = False
        step_results.append(
            {
                "index": 0,
                "id": "__empty__",
                "type": "noop",
                "action": "",
                "passed": False,
                "executed": False,
                "detail": "empty_workflow",
                "error": "empty_workflow",
            }
        )
        tool_failures = 1
        usages: list[dict[str, Any]] = []
        latency_ms = int((time.perf_counter() - started) * 1000)
        success_checks = _evaluate_success_checks(
            ir,
            ctx={**ctx, "hitl_resolved": False, "paper_only": bool(ctx.get("paper_only"))},
        )
        result = {
            "mode": "sandbox",
            "live_execution": False,
            "product_ready": False,
            "passed": False,
            "status": "failed",
            "step_results": step_results,
            "success_checks": success_checks,
            "definition_hash": definition_hash,
            "note": "empty_workflow",
            "metrics": {
                "latency_ms": latency_ms,
                "tool_failures": tool_failures,
                "cost_tokens": None,
                "usage": {"source": "not_measured", "total_tokens": None},
                "executed_count": 0,
                "passed": False,
                "definition_hash": definition_hash,
            },
        }
        run = store.create_workflow_run(
            workflow_id=workflow_id,
            version=int(ir.get("version") or 1),
            mode="sandbox",
            status="failed",
            result=result,
        )
        _update_evidence(
            store,
            workflow_id,
            {
                "mode": "sandbox",
                "status": "failed",
                "passed": False,
                "run_id": run["id"],
                "product_ready": False,
                "definition_hash": definition_hash,
                "reason": "empty_workflow",
            },
            component="workflows",
        )
        return {**result, "run_id": run["id"], "workflow_id": workflow_id}

    status = "completed"
    passed = True
    usages: list[dict[str, Any]] = []

    steps_by_id = {str(s["id"]): s for s in ir["steps"]}
    for index, sid in enumerate(order):
        step = steps_by_id[sid]
        stype = str(step.get("type") or "action").lower()
        if stype in HITL_STEP_TYPES:
            awaiting_step = {
                "step_id": sid,
                "type": stype,
                "prompt": step.get("prompt") or step.get("description") or stype,
                "choices": list(step.get("choices") or []),
            }
            status = "awaiting_human"
            passed = False
            step_results.append(
                {
                    "index": index,
                    "id": sid,
                    "type": stype,
                    "action": "",
                    "passed": False,
                    "executed": False,
                    "detail": "awaiting_human",
                }
            )
            break

        action = str(step.get("action") or "").strip()
        if action in PRODUCT_ACTIONS:
            # Clear separation: product adapters are not simulated as success in sandbox.
            entry = {
                "index": index,
                "id": sid,
                "type": stype,
                "action": action,
                "passed": False,
                "executed": False,
                "detail": "product_action_requires_product_mode",
                "error": "product_action_requires_product_mode",
            }
            step_results.append(entry)
            tool_failures += 1
            passed = False
            status = "failed"
            break

        bound_inputs = resolve_bindings(
            dict(step.get("inputs") or {}),
            ctx=ctx,
            run_inputs=dict(run_inputs or {}),
        )
        skill_step = {
            "action": action,
            "inputs": bound_inputs,
            "success_criteria": step.get("success_criteria") or [],
            "description": step.get("description") or "",
        }
        result = execute_skill_step(skill_step, index=index, ctx=ctx)
        entry = result.to_dict()
        entry["id"] = sid
        entry["type"] = stype
        entry["duration_ms"] = entry.get("duration_ms") or 0
        # No fictional token increments — sandbox primitives do not measure tokens.
        entry["usage"] = {"source": "not_measured", "total_tokens": None}
        step_results.append(entry)
        ctx["steps"][sid] = {"outputs": entry.get("outputs") or {}, "passed": result.passed}
        usages.append(entry["usage"])
        if not result.passed:
            tool_failures += 1
            passed = False
            status = "failed"
            break

    latency_ms = int((time.perf_counter() - started) * 1000)
    success_checks = _evaluate_success_checks(
        ir,
        ctx={
            **ctx,
            "hitl_resolved": False,
            "paper_only": bool(ctx.get("paper_only")),
        },
    )
    if status == "completed":
        if any(c["check"] == "artifacts_recorded" and not c["passed"] for c in success_checks):
            passed = False
            status = "failed"

    usage_summary = _sum_usage(usages)
    metrics_delta = {
        "latency_ms": latency_ms,
        "tool_failures": tool_failures,
        "cost_tokens": usage_summary.get("total_tokens"),
        "usage": usage_summary,
        "executed_count": sum(1 for s in step_results if s.get("executed")),
        "passed": passed and status == "completed",
        "definition_hash": definition_hash,
    }
    result = {
        "mode": "sandbox",
        "live_execution": False,
        "product_ready": False,
        "passed": bool(metrics_delta["passed"]),
        "status": status,
        "step_results": step_results,
        "artifacts": list(ctx.get("artifacts") or []),
        "success_checks": success_checks,
        "awaiting_human": awaiting_step,
        "metrics": metrics_delta,
        "definition_hash": definition_hash,
        "checkpoints": list(ctx.get("checkpoints") or []),
        "note": (
            "Sandbox uses skill_runtime primitives only; not live Coding/Research/Plugin execution. "
            "Does not promote product readiness. "
            + ("Paused for human-in-the-loop." if status == "awaiting_human" else "")
        ).strip(),
    }
    run = store.create_workflow_run(
        workflow_id=workflow_id,
        version=int(ir.get("version") or 1),
        mode="sandbox",
        status=status if status != "completed" else ("passed" if passed else "failed"),
        result=result,
    )
    _update_evidence(
        store,
        workflow_id,
        mode="sandbox",
        run_id=run["id"],
        passed=bool(metrics_delta["passed"]),
        definition_hash=definition_hash,
        awaiting=awaiting_step,
        product_ready=False,
    )
    record(
        workflow_id,
        "VERIFICATION",
        {
            "mode": "sandbox",
            "status": status,
            "passed": result["passed"],
            "run_id": run["id"],
            "product_ready": False,
            "definition_hash": definition_hash,
        },
        component="workflows",
    )
    return {**result, "run_id": run["id"], "workflow_id": workflow_id}


def start_product_run(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    services: WorkflowServices,
    run_inputs: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
    async_mode: bool = True,
    blocking: bool = False,
) -> dict[str, Any]:
    """Start product execution. Non-blocking by default (HTTP-safe)."""
    from gen2.workflows import normalize_workflow_ir, validate_workflow

    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    errors = validate_workflow(ir)
    definition_hash = workflow_definition_hash(ir)
    if errors:
        result = {
            "mode": "product",
            "live_execution": False,
            "product_ready": False,
            "passed": False,
            "status": "failed",
            "validation_errors": errors,
            "step_results": [],
            "note": "Product run refused: IR invalid.",
            "definition_hash": definition_hash,
        }
        run = store.create_workflow_run(
            workflow_id=workflow_id,
            version=int(ir.get("version") or 1),
            mode="product",
            status="failed",
            result=result,
        )
        return {**result, "run_id": run["id"], "workflow_id": workflow_id}

    # Create run first so HTTP can return immediately.
    bootstrap = {
        "mode": "product",
        "live_execution": True,
        "product_ready": False,
        "passed": False,
        "status": "queued",
        "step_results": [],
        "definition_hash": definition_hash,
        "run_inputs": dict(run_inputs or {}),
        "timeout_seconds": timeout_seconds,
        "note": "Product run queued on authoritative workflow executor.",
    }
    run = store.create_workflow_run(
        workflow_id=workflow_id,
        version=int(ir.get("version") or 1),
        mode="product",
        status="queued",
        result=bootstrap,
    )
    run_id = run["id"]
    _control_for(run_id)  # init control plane
    definition = dict(row.get("definition") or {})
    definition["active_run_id"] = run_id
    store.update_workflow(workflow_id, definition=definition)
    record(
        workflow_id,
        "RUN_CREATED",
        {"kind": "workflow_product", "run_id": run_id, "definition_hash": definition_hash},
        component="workflows",
    )

    def _job() -> dict[str, Any]:
        return _execute_product_body(
            store,
            record,
            workflow_id,
            run_id=run_id,
            ir=ir,
            services=services,
            run_inputs=dict(run_inputs or {}),
            timeout_seconds=timeout_seconds,
            definition_hash=definition_hash,
        )

    if blocking or not async_mode:
        return _job()

    future: Future[dict[str, Any]] = _pool().submit(_job)
    # Attach future id for diagnostics only.
    bootstrap["status"] = "running"
    bootstrap["executor"] = "thread_pool"
    store.update_workflow_run(run_id, status="running", result=bootstrap)
    # Do not wait — return accepted handle.
    _ = future
    return {
        **bootstrap,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "accepted": True,
        "poll": f"/api/gen2/workflows/{workflow_id}/runs/{run_id}",
    }


def _execute_product_body(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    run_id: str,
    ir: dict[str, Any],
    services: WorkflowServices,
    run_inputs: dict[str, Any],
    timeout_seconds: float | None,
    definition_hash: str,
) -> dict[str, Any]:
    from gen2.workflows import _evaluate_success_checks

    ctl = _control_for(run_id)
    started = time.perf_counter()
    deadline = (started + float(timeout_seconds)) if timeout_seconds else None
    order = _topo_order(list(ir.get("steps") or []))
    ctx: dict[str, Any] = {
        "artifacts": [],
        "steps": {},
        "checkpoints": [],
        "run_inputs": run_inputs,
        "toolcall_ids": [],
    }
    step_results: list[dict[str, Any]] = []
    tool_failures = 0
    awaiting_step: dict[str, Any] | None = None
    # Empty IR must not succeed merely because the loop did nothing.
    if not order:
        status = "failed"
        passed = False
        step_results.append(
            {
                "index": 0,
                "id": "__empty__",
                "type": "noop",
                "action": "",
                "passed": False,
                "executed": False,
                "detail": "empty_workflow",
                "error": "empty_workflow",
            }
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        success_checks = _evaluate_success_checks(
            ir,
            ctx={**ctx, "hitl_resolved": False, "paper_only": bool(ctx.get("paper_only"))},
        )
        result = {
            "mode": "product",
            "live_execution": True,
            "product_ready": False,
            "passed": False,
            "status": "failed",
            "step_results": step_results,
            "success_checks": success_checks,
            "definition_hash": definition_hash,
            "note": "empty_workflow",
            "metrics": {
                "latency_ms": latency_ms,
                "tool_failures": 1,
                "cost_tokens": None,
                "usage": {"source": "not_measured", "total_tokens": None},
                "executed_count": 0,
                "passed": False,
                "definition_hash": definition_hash,
                "failed_step_id": "__empty__",
            },
        }
        store.update_workflow_run(run_id, status="failed", result=result)
        return result

    status = "completed"
    passed = True
    usages: list[dict[str, Any]] = []
    failed_step_id: str | None = None

    def control_check() -> None:
        if ctl.get("cancel_requested"):
            raise _Cancel("cancelled")
        if deadline is not None and time.perf_counter() > deadline:
            raise _Cancel("timeout")
        if ctl.get("pause_requested"):
            ctl["paused"] = True
            store.update_workflow_run(
                run_id,
                status="paused",
                result={
                    "mode": "product",
                    "live_execution": True,
                    "status": "paused",
                    "step_results": step_results,
                    "definition_hash": definition_hash,
                    "note": "Paused at control checkpoint (Work Runtime-compatible).",
                },
            )
            ctl["resume_event"].clear()
            ctl["resume_event"].wait(timeout=3600)
            ctl["paused"] = False
            if ctl.get("cancel_requested"):
                raise _Cancel("cancelled")
            store.update_workflow_run(run_id, status="running")

    store.update_workflow_run(
        run_id,
        status="running",
        result={
            "mode": "product",
            "live_execution": True,
            "product_ready": False,
            "passed": False,
            "status": "running",
            "step_results": [],
            "definition_hash": definition_hash,
            "started_at": utc_now(),
        },
    )

    steps_by_id = {str(s["id"]): s for s in ir["steps"]}
    resume_after = str(run_inputs.get("_resume_after") or "").strip()
    skip_until_done = bool(resume_after)
    try:
        for index, sid in enumerate(order):
            if skip_until_done:
                if sid == resume_after:
                    skip_until_done = False
                    step = steps_by_id[sid]
                    stype_resume = str(step.get("type") or "action").lower()
                    action_resume = str(step.get("action") or "").strip()
                    # Synthetic approval pause parked a product action under the same step id.
                    # When approval_id is now present, re-enter normal execution for that action.
                    reenter_product = (
                        stype_resume not in HITL_STEP_TYPES
                        and action_resume in PRODUCT_ACTIONS
                        and bool(run_inputs.get("approval_id") or run_inputs.get("approval_request_id"))
                    )
                    if not reenter_product:
                        step_results.append(
                            {
                                "index": index,
                                "id": sid,
                                "type": stype_resume,
                                "passed": True,
                                "executed": False,
                                "detail": "human_already_decided",
                            }
                        )
                        continue
                    # Fall through to normal product execution with persisted approval.
                else:
                    # Replay prior product outputs are not re-executed on resume; mark skipped.
                    step_results.append(
                        {
                            "index": index,
                            "id": sid,
                            "type": str(steps_by_id[sid].get("type") or "action"),
                            "passed": True,
                            "executed": False,
                            "detail": "skipped_before_resume",
                        }
                    )
                    continue
            control_check()
            step = steps_by_id[sid]
            stype = str(step.get("type") or "action").lower()
            if stype in HITL_STEP_TYPES:
                # Approval-compatible pause (same family as Work Runtime stop_and_ask).
                awaiting_step = {
                    "step_id": sid,
                    "type": stype,
                    "prompt": step.get("prompt") or step.get("description") or stype,
                    "choices": list(step.get("choices") or []),
                }
                status = "awaiting_human"
                passed = False
                step_results.append(
                    {
                        "index": index,
                        "id": sid,
                        "type": stype,
                        "action": "",
                        "passed": False,
                        "executed": False,
                        "detail": "awaiting_human",
                    }
                )
                break

            action = str(step.get("action") or "").strip()
            bound_inputs = resolve_bindings(
                dict(step.get("inputs") or {}),
                ctx=ctx,
                run_inputs=run_inputs,
            )

            # Permission ask gates → ApprovalService only (never run_inputs booleans).
            # preapproved / approved_by_user in run_inputs are informational/audit only.
            permissions = dict(ir.get("permissions") or {})
            _ = bool(run_inputs.get("preapproved") or run_inputs.get("approved_by_user"))
            has_persisted_approval = _workflow_product_approval_ok(
                services,
                run_inputs,
                workflow_id=workflow_id,
                action=action,
                step_id=sid,
            )
            if (
                action in PRODUCT_ACTIONS
                and not has_persisted_approval
                and _needs_approval(action, permissions, bound_inputs)
            ):
                if services.approval_service is not None:
                    try:
                        from mcp_host.policy import workflow_product_scope

                        scope = workflow_product_scope(
                            workflow_id=workflow_id, action=action, step_id=sid
                        )
                        req = services.approval_service.create_tool_approval(
                            plugin_id=f"workflow:{workflow_id}",
                            tool_name=action,
                            arguments=bound_inputs,
                            expected_effect=f"workflow product step {sid}:{action}",
                            task_id=run_id,
                            run_id=run_id,
                            step_id=sid,
                            scope=scope,
                        )
                        awaiting_step = {
                            "step_id": sid,
                            "type": "approve",
                            "prompt": f"Approve product step {action}?",
                            "choices": ["approve", "reject"],
                            "approval_request_id": (req or {}).get("id"),
                        }
                        status = "awaiting_human"
                        passed = False
                        step_results.append(
                            {
                                "index": index,
                                "id": sid,
                                "type": "approve",
                                "action": action,
                                "passed": False,
                                "executed": False,
                                "detail": "approval_required",
                                "approval_request_id": (req or {}).get("id"),
                            }
                        )
                        break
                    except Exception:
                        # If approval service cannot create, fail closed for ask perms.
                        raise RuntimeError("approval_required_but_unavailable")
                else:
                    raise RuntimeError("approval_required_but_unavailable")

            if action in PRODUCT_ACTIONS:
                adapter = execute_product_action(
                    action,
                    bound_inputs,
                    services=services,
                    ctx=ctx,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    step_id=sid,
                    control_check=control_check,
                    record=record,
                )
                # Honor declared success_criteria (output:<key>) against adapter outputs.
                for criterion in step.get("success_criteria") or []:
                    key = str(criterion).strip()
                    if key.startswith("output:"):
                        out_key = key.split(":", 1)[1]
                        if out_key not in (adapter.outputs or {}):
                            adapter.passed = False
                            adapter.detail = f"success_criteria_missing:{out_key}"
                            adapter.error = adapter.detail
                entry = adapter.to_dict()
                entry["index"] = index
                entry["id"] = sid
                entry["type"] = stype
                step_results.append(entry)
                ctx["steps"][sid] = {"outputs": adapter.outputs, "passed": adapter.passed}
                ctx["toolcall_ids"].extend(adapter.toolcall_ids)
                usages.append(adapter.usage or {})
                ctx.setdefault("checkpoints", []).append(
                    {"step_id": sid, "action": action, "checkpoint": adapter.checkpoint}
                )
                # Persist progress after each step.
                store.update_workflow_run(
                    run_id,
                    status="running",
                    result={
                        "mode": "product",
                        "live_execution": True,
                        "status": "running",
                        "step_results": step_results,
                        "definition_hash": definition_hash,
                        "checkpoints": ctx.get("checkpoints"),
                    },
                )
                if not adapter.passed:
                    tool_failures += 1
                    passed = False
                    status = "failed"
                    failed_step_id = sid
                    break
            elif action in SKILL_ACTION_HANDLERS:
                # Allow primitives inside product workflows (setup/assert helpers).
                result = execute_skill_step(
                    {
                        "action": action,
                        "inputs": bound_inputs,
                        "success_criteria": step.get("success_criteria") or [],
                    },
                    index=index,
                    ctx=ctx,
                )
                entry = result.to_dict()
                entry["id"] = sid
                entry["type"] = stype
                entry["usage"] = {"source": "not_measured", "total_tokens": None}
                step_results.append(entry)
                ctx["steps"][sid] = {"outputs": entry.get("outputs") or {}, "passed": result.passed}
                usages.append(entry["usage"])
                if not result.passed:
                    tool_failures += 1
                    passed = False
                    status = "failed"
                    failed_step_id = sid
                    break
            else:
                entry = {
                    "index": index,
                    "id": sid,
                    "type": stype,
                    "action": action,
                    "passed": False,
                    "executed": False,
                    "detail": "unknown_action:no_handler",
                    "error": "unknown_action:no_handler",
                }
                step_results.append(entry)
                tool_failures += 1
                passed = False
                status = "failed"
                failed_step_id = sid
                break
    except _Cancel as exc:
        status = str(exc.detail)
        passed = False
        failed_step_id = failed_step_id or (step_results[-1]["id"] if step_results else None)

    latency_ms = int((time.perf_counter() - started) * 1000)
    success_checks = _evaluate_success_checks(
        ir,
        ctx={**ctx, "hitl_resolved": False, "paper_only": bool(ctx.get("paper_only"))},
    )
    if status == "completed":
        if any(c["check"] == "artifacts_recorded" and not c["passed"] for c in success_checks):
            # Prefer durable artifact_persist evidence when declared.
            if not ctx.get("artifacts"):
                passed = False
                status = "failed"

    usage_summary = _sum_usage(usages)
    product_ready = bool(passed and status == "completed" and _is_product_workflow(ir))
    metrics = {
        "latency_ms": latency_ms,
        "tool_failures": tool_failures,
        "cost_tokens": usage_summary.get("total_tokens"),
        "usage": usage_summary,
        "executed_count": sum(1 for s in step_results if s.get("executed")),
        "passed": passed and status == "completed",
        "definition_hash": definition_hash,
        "failed_step_id": failed_step_id,
    }
    result = {
        "mode": "product",
        "live_execution": True,
        "product_ready": product_ready,
        "passed": bool(metrics["passed"]),
        "status": status if status != "completed" else ("passed" if passed else "failed"),
        "step_results": step_results,
        "artifacts": list(ctx.get("artifacts") or []),
        "toolcall_ids": list(ctx.get("toolcall_ids") or []),
        "success_checks": success_checks,
        "awaiting_human": awaiting_step,
        "run_inputs": dict(run_inputs or {}),
        "metrics": metrics,
        "definition_hash": definition_hash,
        "checkpoints": list(ctx.get("checkpoints") or []),
        "failed_step_id": failed_step_id,
        "finished_at": utc_now(),
        "note": (
            "Product execution via CodingAgent/ResearchRunner/PluginManager/model gateway/ArtifactService. "
            + (
                f"Stopped at failed step {failed_step_id}."
                if failed_step_id
                else ("Paused for human approval." if status == "awaiting_human" else "")
            )
        ).strip(),
    }
    terminal = result["status"]
    store.update_workflow_run(run_id, status=terminal, result=result)
    _update_evidence(
        store,
        workflow_id,
        mode="product",
        run_id=run_id,
        passed=bool(metrics["passed"]),
        definition_hash=definition_hash,
        awaiting=awaiting_step,
        product_ready=product_ready,
    )
    record(
        workflow_id,
        "TERMINAL" if terminal in {"passed", "failed", "cancelled", "timeout"} else "VERIFICATION",
        {
            "mode": "product",
            "status": terminal,
            "passed": result["passed"],
            "run_id": run_id,
            "product_ready": product_ready,
            "definition_hash": definition_hash,
            "failed_step_id": failed_step_id,
        },
        component="workflows",
    )
    # Clear active run when terminal.
    if terminal not in {"awaiting_human", "paused", "running", "queued"}:
        row = store.get_workflow(workflow_id) or {}
        definition = dict(row.get("definition") or {})
        if definition.get("active_run_id") == run_id:
            definition.pop("active_run_id", None)
            store.update_workflow(workflow_id, definition=definition)
    with _EXECUTOR_LOCK:
        _CONTROL.pop(run_id, None)
    return {**result, "run_id": run_id, "workflow_id": workflow_id}


class _Cancel(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _needs_approval(action: str, permissions: dict[str, Any], inputs: dict[str, Any]) -> bool:
    """Ask-permissions require approval before side-effecting adapters."""
    fs = str(permissions.get("filesystem") or "ask").lower()
    net = str(permissions.get("network") or "deny").lower()
    if action == "coding_agent" and fs == "ask":
        return True
    if action == "research_runner" and (fs == "ask" or (net == "ask" and inputs.get("allow_web"))):
        return True
    if action == "plugin_invoke" and fs == "ask":
        return True
    return False


def _workflow_product_approval_ok(
    services: WorkflowServices,
    run_inputs: dict[str, Any],
    *,
    workflow_id: str,
    action: str,
    step_id: str | None = None,
) -> bool:
    """True only when a persisted ApprovalService decision matches this product action.

    ``run_inputs['preapproved']`` / ``approved_by_user`` are ignored for authority.
    """
    approval_id = run_inputs.get("approval_id") or run_inputs.get("approval_request_id")
    if not approval_id or services.approval_service is None:
        return False
    from mcp_host.policy import resolve_scoped_approval, workflow_product_scope

    # Prefer exact step scope; also accept action-scoped approval without step_id
    # (resume after HITL may re-enter the same action).
    scopes = [
        workflow_product_scope(workflow_id=workflow_id, action=action, step_id=step_id),
        workflow_product_scope(workflow_id=workflow_id, action=action),
    ]
    for scope in scopes:
        if resolve_scoped_approval(
            services.approval_service,
            approval_id=str(approval_id),
            expected_scope=scope,
        ):
            return True
    return False


def _update_evidence(
    store: Gen2Store,
    workflow_id: str,
    *,
    mode: str,
    run_id: str,
    passed: bool,
    definition_hash: str,
    awaiting: dict[str, Any] | None,
    product_ready: bool,
) -> None:
    row = store.get_workflow(workflow_id)
    if not row:
        return
    definition = dict(row.get("definition") or {})
    evidence = dict(definition.get("test_evidence") or {})
    if mode == "sandbox":
        evidence["last_sandbox_run_id"] = run_id
        evidence["last_sandbox_run_passed"] = passed
        evidence["last_sandbox_definition_hash"] = definition_hash
        # Explicit: sandbox never sets product_ready.
        evidence["last_sandbox_product_ready"] = False
    elif mode == "product":
        evidence["last_product_run_id"] = run_id
        evidence["last_product_run_passed"] = passed
        evidence["last_product_definition_hash"] = definition_hash
        evidence["last_product_ready"] = bool(product_ready and passed)
    if awaiting:
        evidence["awaiting_run_id"] = run_id
        evidence["awaiting_step"] = awaiting
    elif passed and mode == "product":
        evidence.pop("awaiting_run_id", None)
        evidence.pop("awaiting_step", None)
    definition["test_evidence"] = evidence
    store.update_workflow(workflow_id, definition=definition)


def resume_product_after_hitl(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    resolved_step_id: str,
    *,
    services: WorkflowServices,
    timeout_seconds: float | None = None,
    blocking: bool = True,
) -> dict[str, Any]:
    """Continue a product run after HITL/approval (remaining steps only)."""
    from gen2.workflows import normalize_workflow_ir

    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    evidence = dict((row.get("definition") or {}).get("test_evidence") or {})
    prior_inputs = {}
    run_id = evidence.get("awaiting_run_id")
    approval_id = None
    if run_id:
        prior = store.get_workflow_run(str(run_id))
        if prior:
            prior_result = dict(prior.get("result") or {})
            prior_inputs = dict(prior_result.get("run_inputs") or {})
            awaiting = prior_result.get("awaiting_human") or evidence.get("awaiting_step") or {}
            if isinstance(awaiting, dict):
                approval_id = awaiting.get("approval_request_id") or awaiting.get("approval_id")
    # Prefer ApprovalService id from the paused step; never invent from booleans.
    resume_inputs = {**prior_inputs, "_resume_after": resolved_step_id}
    # Drop boolean claims — they are not authorization authority.
    resume_inputs.pop("preapproved", None)
    resume_inputs.pop("approved_by_user", None)
    if approval_id:
        resume_inputs["approval_id"] = approval_id
    # Start a fresh product continuation run bound to same definition hash.
    return start_product_run(
        store,
        record,
        workflow_id,
        services=services,
        run_inputs=resume_inputs,
        timeout_seconds=timeout_seconds,
        async_mode=not blocking,
        blocking=blocking,
    )


# Re-export for services/promotion helpers.
is_product_workflow = _is_product_workflow
