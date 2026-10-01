"""Durable workflow orchestration — graph + linear; one node/step per advance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
    is_external_required,
)

from .store import WorkflowStore, utc_now
from .types import (
    WorkflowDefinitionStatus,
    WorkflowEdgeDef,
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowGraph,
    WorkflowNodeDef,
    WorkflowNodeKind,
    WorkflowRecord,
    WorkflowState,
    WorkflowStepDef,
    execution_to_legacy_state,
    legacy_to_execution_state,
)
from .variables import build_execution_context, eval_predicate, resolve_value

import hashlib
import json


def _args_fingerprint(arguments: dict | None) -> str:
    payload = json.dumps(arguments or {}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_secret_ref(value) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        ref = value.get("ref") or value.get("secret_ref") or value.get("secret")
        if isinstance(ref, str) and (
            ref.startswith("secret:") or ref.startswith("env:") or ref.startswith("{{")
        ):
            return True
        if value.get("secret") is True and isinstance(ref, str) and ref.strip():
            return True
        return False
    text = str(value).strip()
    return text.startswith("secret:") or text.startswith("env:")


def validate_secret_variables(variables, *, inputs=None) -> None:
    inputs = inputs or {}
    for var in variables:
        secret = bool(getattr(var, "secret", False))
        if not secret:
            type_value = getattr(var, "type_value", None) or str(getattr(var, "var_type", "") or "")
            if str(type_value) != "secret_ref":
                continue
            secret = True
        if not secret:
            continue
        name = str(getattr(var, "name", "") or "")
        required = bool(getattr(var, "required", False))
        provided = inputs.get(name) if name in inputs else getattr(var, "default", None)
        if provided in (None, "", {}):
            if required:
                raise ValueError(
                    f"VARIABLE_VALIDATION_FAILED: required secret {name} missing resolvable secret ref"
                )
            continue
        if not _is_secret_ref(provided):
            raise ValueError(
                f"VARIABLE_VALIDATION_FAILED: secret variable {name} must use a secret ref "
                f"(secret:… / env:…), never plaintext"
            )


class WorkflowRuntime:
    """Execute workflow graphs/steps through the shared Execution Gateway.

    Production path: :meth:`enqueue_advance` creates durable ``workflow.advance``
    jobs; workers advance one node and release. :meth:`run` remains a
    synchronous foreground helper for tests/legacy callers only.

    Addressing: ``workflow_id`` arguments historically identify the runnable
    record. After definition/execution separation that id is the
    ``execution_id``. Definition-level run uses :meth:`run_definition`.
    """

    def __init__(
        self,
        store: WorkflowStore,
        gateway: ExecutionGateway,
        *,
        job_runtime: Any | None = None,
        schedule_store: Any | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.job_runtime = job_runtime
        self.schedule_store = schedule_store

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def bind_schedule_store(self, schedule_store: Any | None) -> None:
        self.schedule_store = schedule_store

    def create(
        self,
        *,
        name: str,
        steps: list[WorkflowStepDef],
        run_id: str | None = None,
    ) -> WorkflowRecord:
        return self.store.create(name=name, steps=steps, run_id=run_id)

    def run_definition(
        self,
        workflow_id: str,
        *,
        requested_by: str = "api",
        trigger_source: str = "MANUAL",
        inputs: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[WorkflowExecution, Any | None]:
        """Create a NEW execution of the current definition version and enqueue."""
        definition = self.store.get_definition(workflow_id)
        if definition is None:
            raise KeyError(f"Unknown workflow definition: {workflow_id}")
        if definition.status == WorkflowDefinitionStatus.ARCHIVED:
            raise ValueError("WORKFLOW_INVALID: archived workflows cannot run")
        if definition.status == WorkflowDefinitionStatus.TEMPLATE:
            raise ValueError("WORKFLOW_INVALID: templates must be duplicated before run")

        validate_secret_variables(definition.variables, inputs=inputs)

        max_concurrent = int((definition.config or {}).get("max_concurrent_executions") or 0)
        key = (idempotency_key or "").strip() or None

        snapshot: dict[str, Any] = {}
        for var in definition.variables:
            if var.secret or str(var.type_value) == "secret_ref":
                raw = (inputs or {}).get(var.name, var.default)
                if raw in (None, "", {}):
                    if var.required:
                        raise ValueError(f"VARIABLE_VALIDATION_FAILED: missing required {var.name}")
                    continue
                if not _is_secret_ref(raw):
                    raise ValueError(
                        f"VARIABLE_VALIDATION_FAILED: secret variable {var.name} must use a secret ref"
                    )
                snapshot[var.name] = (
                    raw if isinstance(raw, dict) else {"secret": True, "ref": str(raw)}
                )
            elif var.name in (inputs or {}):
                snapshot[var.name] = (inputs or {})[var.name]
            elif var.default is not None:
                snapshot[var.name] = var.default
            elif var.required:
                raise ValueError(f"VARIABLE_VALIDATION_FAILED: missing required {var.name}")
        for snap_key, value in (inputs or {}).items():
            snapshot.setdefault(snap_key, value)

        execution = self.store.create_execution(
            workflow_id=workflow_id,
            trigger_source=trigger_source,
            requested_by=requested_by,
            input_snapshot=snapshot,
            idempotency_key=key,
            max_concurrent=max_concurrent,
        )
        job = None
        if self.job_runtime is not None:
            try:
                job = self.enqueue_advance(execution.execution_id, requested_by=requested_by)
            except ValueError:
                job = None
        return execution, job

    def enqueue_advance(
        self,
        workflow_id: str,
        *,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        requested_by: str = "workflow_runtime",
        generation: str | None = None,
    ) -> Any:
        """Enqueue a durable ``workflow.advance`` job (idempotent per step/wait generation)."""
        if self.job_runtime is None:
            raise RuntimeError("job_runtime not bound; cannot enqueue workflow.advance")
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            raise ValueError(f"Workflow already terminal: {record.state.value}")
        execution = self.store.get_execution(workflow_id)
        if execution is not None and execution.state == WorkflowExecutionState.QUEUED:
            execution.state = WorkflowExecutionState.STARTING
            execution.started_at = execution.started_at or utc_now()
            self.store.save_execution(execution)
        elif record.state == WorkflowState.CREATED:
            record.state = WorkflowState.RUNNING
            self.store.save(record)
        step_index = int(record.current_step)
        wait = str((record.metadata or {}).get("wait_reason") or "")
        pending = (record.metadata or {}).get("pending_child_job_id") or ""
        gen = generation or f"{step_index}:{wait}:{pending}:{record.metadata.get('current_node_id') or ''}"
        idem = f"workflow:advance:{workflow_id}:{gen}"
        return self.job_runtime.enqueue(
            capability_id="workflow.advance",
            arguments={"workflow_id": workflow_id},
            run_id=record.run_id,
            requested_by=requested_by,
            idempotency_key=idem,
            domain="workflows",
            domain_entity_type="workflow",
            domain_entity_id=workflow_id,
            worker_pool="workflow",
            parent_job_id=parent_job_id,
            root_job_id=root_job_id or parent_job_id,
            latency_class="background",
            metadata={"workflow_id": workflow_id, "step_index": step_index, "generation": gen},
        )

    def run(self, workflow_id: str) -> WorkflowRecord:
        """TEST-ONLY / legacy foreground helper: run all remaining steps synchronously."""
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            return record
        execution = self.store.get_execution(workflow_id)
        if execution is not None:
            execution.state = WorkflowExecutionState.RUNNING
            execution.started_at = execution.started_at or utc_now()
            self.store.save_execution(execution)
        else:
            record.state = WorkflowState.RUNNING
            self.store.save(record)

        guard = 0
        while guard < 10_000:
            guard += 1
            record = self.advance_one_step(workflow_id)
            wait = str((record.metadata or {}).get("wait_reason") or "")
            if wait == "WAITING_CHILD":
                pending = (record.metadata or {}).get("pending_child_job_id")
                if pending and self.job_runtime is not None:
                    record = self._consume_or_fail_child_foreground(record)
                    continue
                record.state = WorkflowState.FAILED
                record.error = "WORKFLOW_CHILD_UNAVAILABLE"
                return self.store.save(record)
            if wait == "WAITING_DELAY":
                # Foreground tests: treat delay as immediately elapsed via resume path.
                meta = dict(record.metadata or {})
                meta["wait_reason"] = "WAITING_DELAY"
                meta["delay_resume_at"] = "1970-01-01T00:00:00+00:00"
                record.metadata = meta
                self.store.save(record)
                continue
            if wait == "WAITING_APPROVAL":
                return record
            if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
                return record
            if record.current_step >= len(record.steps) and not self._has_graph_remaining(workflow_id):
                return record
        record.state = WorkflowState.FAILED
        record.error = "LOOP_LIMIT_EXCEEDED"
        return self.store.save(record)

    def _has_graph_remaining(self, execution_id: str) -> bool:
        execution = self.store.get_execution(execution_id)
        if execution is None:
            return False
        return execution.state in {
            WorkflowExecutionState.QUEUED,
            WorkflowExecutionState.STARTING,
            WorkflowExecutionState.RUNNING,
            WorkflowExecutionState.WAITING,
            WorkflowExecutionState.WAITING_APPROVAL,
        }

    def _consume_or_fail_child_foreground(self, record: WorkflowRecord) -> WorkflowRecord:
        """TEST-ONLY: resolve a pending child by gateway execute of the same step."""
        meta = dict(record.metadata or {})
        step = record.steps[record.current_step] if record.current_step < len(record.steps) else None
        if step is None:
            record.state = WorkflowState.FAILED
            record.error = "WORKFLOW_INVALID"
            return self.store.save(record)
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=step.capability_id,
                arguments=step.arguments,
                approval_id=step.approval_id,
                run_id=record.run_id,
                requested_by="workflow",
                request_id=f"{record.workflow_id}:{step.step_id}:fg",
            )
        )
        record.step_results.append(
            {
                "step_id": step.step_id,
                "capability_id": step.capability_id,
                "status": result.status.value,
                "result": result.public_dict(),
                "via": "foreground_child_drain",
            }
        )
        meta["pending_child_job_id"] = None
        meta["wait_reason"] = None
        record.metadata = meta
        if result.status != CapabilityStatus.COMPLETED:
            record.state = WorkflowState.FAILED
            record.error = result.error or result.status.value
            return self.store.save(record)
        record.current_step += 1
        if record.current_step >= len(record.steps):
            record.state = WorkflowState.COMPLETED
        return self.store.save(record)

    def advance_one_step(self, workflow_id: str) -> WorkflowRecord:
        """Execute exactly one runnable orchestration unit then persist and return."""
        execution = self.store.get_execution(workflow_id)
        if execution is not None:
            return self._advance_execution(execution)
        # Pure legacy path without execution row (should be rare post-migration).
        return self._advance_legacy_record(workflow_id)

    def resume_with_approval(
        self,
        execution_id: str,
        *,
        approval_id: str | None = None,
        decision: str = "approved",
        requested_by: str = "api",
    ) -> WorkflowRecord:
        """Resume a WAITING_APPROVAL execution after operator approve/reject."""
        execution = self.store.get_execution(execution_id)
        if execution is None:
            raise KeyError(f"Unknown execution: {execution_id}")
        if execution.state != WorkflowExecutionState.WAITING_APPROVAL:
            raise ValueError(
                f"WORKFLOW_INVALID: execution is not WAITING_APPROVAL ({execution.state.value})"
            )
        meta = dict(execution.metadata or {})
        pending = dict(meta.get("pending_approval") or {})
        if not pending:
            raise ValueError("WORKFLOW_INVALID: missing pending_approval binding")

        decision_norm = str(decision or "approved").strip().lower()
        if decision_norm in {"rejected", "deny", "denied", "reject"}:
            meta["wait_reason"] = None
            meta["approval_decision"] = "rejected"
            meta["approval_decided_at"] = utc_now()
            execution.metadata = meta
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "APPROVAL_REJECTED"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        if not approval_id:
            raise ValueError("WORKFLOW_INVALID: approval_id required to resume")

        if pending.get("node_id") and execution.current_node_id not in {
            None,
            pending.get("node_id"),
        }:
            raise ValueError("WORKFLOW_INVALID: pending approval node no longer current")
        if pending.get("node_id") and not execution.current_node_id:
            execution.current_node_id = str(pending["node_id"])

        meta["resume_approval_id"] = str(approval_id)
        meta["approval_decision"] = "approved"
        meta["approval_decided_at"] = utc_now()
        meta["wait_reason"] = None
        execution.metadata = meta
        execution.state = WorkflowExecutionState.RUNNING
        self.store.save_execution(execution)

        record = self._advance_execution(execution)
        if self.job_runtime is not None:
            wait = str((record.metadata or {}).get("wait_reason") or "")
            if record.state == WorkflowState.RUNNING and wait not in {
                "WAITING_APPROVAL",
                "WAITING_DELAY",
                "WAITING_CHILD",
            }:
                try:
                    self.enqueue_advance(
                        execution_id,
                        requested_by=requested_by,
                        generation=f"approval-resume:{approval_id}:{execution.current_node_id}",
                    )
                except Exception:  # noqa: BLE001
                    pass
        return record

    def _resume_delay(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        meta: dict[str, Any],
    ) -> WorkflowRecord:
        """Idempotent delay wake-up: advance past the delay node after deadline."""
        if not meta.get("delay_schedule_id") and self.job_runtime is not None:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "DELAY_WAKEUP_UNAVAILABLE: missing delay_schedule_id"
            meta["wait_reason"] = None
            execution.metadata = meta
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        resume_at = meta.get("delay_resume_at")
        if resume_at:
            try:
                when = datetime.fromisoformat(str(resume_at).replace("Z", "+00:00"))
            except ValueError:
                when = None
            if when is not None and datetime.now(timezone.utc) < when:
                return self.store.get(execution.execution_id)  # type: ignore[return-value]
        sched_id = meta.get("delay_schedule_id")
        if sched_id and self.schedule_store is not None and str(sched_id) != "foreground":
            try:
                from Data.modules.schedules.types import ScheduleStatus

                self.schedule_store.set_status(str(sched_id), ScheduleStatus.DISABLED)
            except Exception:  # noqa: BLE001
                pass
        meta["wait_reason"] = None
        meta["delay_resume_at"] = None
        meta["delay_wakeup_consumed_at"] = utc_now()
        execution.metadata = meta
        execution.state = WorkflowExecutionState.RUNNING
        delay_node = meta.get("delay_node_id")
        if delay_node and execution.current_node_id == delay_node:
            self._move_to_next(execution, graph, handle=None)
        elif not delay_node:
            self._move_to_next(execution, graph, handle=None)
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _advance_execution(self, execution: WorkflowExecution) -> WorkflowRecord:
        if execution.state in {
            WorkflowExecutionState.COMPLETED,
            WorkflowExecutionState.FAILED,
            WorkflowExecutionState.CANCELLED,
        }:
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        if execution.state == WorkflowExecutionState.CANCELLING:
            return self._finalize_cancel(execution)

        version = self.store.get_version(execution.workflow_id, execution.workflow_version)
        if version is None:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "WORKFLOW_INVALID: missing pinned version"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        graph = version.graph
        meta = dict(execution.metadata or {})
        cursor = dict(execution.cursor or {})
        wait = str(meta.get("wait_reason") or "")
        pending = meta.get("pending_child_job_id")

        if wait == "WAITING_CHILD" and pending:
            return self._resume_child_execution(execution, graph, str(pending))

        if wait == "WAITING_APPROVAL":
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        if wait == "WAITING_DELAY":
            return self._resume_delay(execution, graph, meta)

        if execution.state in {WorkflowExecutionState.QUEUED, WorkflowExecutionState.STARTING}:
            execution.state = WorkflowExecutionState.RUNNING
            execution.started_at = execution.started_at or utc_now()

        node_id = execution.current_node_id or cursor.get("current_node_id")
        if not node_id:
            # Fall back to linear step mode using projected steps.
            return self._advance_linear_from_execution(execution, graph)

        by_id = {n.node_id: n for n in graph.nodes}
        node = by_id.get(str(node_id))
        if node is None:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = f"WORKFLOW_INVALID: unknown node {node_id}"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        kind = node.kind_value
        ctx = self._execution_context(execution, version.variables)

        if kind == WorkflowNodeKind.TRIGGER.value:
            self._append_node_result(execution, node, status="COMPLETED", output={"triggered": True})
            self._move_to_next(execution, graph, handle=None)
            self.store.save_execution(execution)
            # Trigger is not a billable step — continue into the next node in this advance.
            return self._advance_execution(execution)

        if kind == WorkflowNodeKind.CONDITION.value:
            return self._run_condition(execution, graph, node, ctx)

        if kind == WorkflowNodeKind.LOOP.value:
            return self._run_loop(execution, graph, node, ctx)

        if kind == WorkflowNodeKind.DELAY.value:
            return self._run_delay(execution, graph, node)

        if kind in {WorkflowNodeKind.CAPABILITY.value, WorkflowNodeKind.AGENT.value}:
            return self._run_capability_node(execution, graph, node, ctx)

        execution.state = WorkflowExecutionState.FAILED
        execution.error = f"WORKFLOW_INVALID: unsupported node kind {kind}"
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _execution_context(self, execution: WorkflowExecution, variables: list[Any]) -> dict[str, Any]:
        var_map = dict(execution.input_snapshot or {})
        for var in variables:
            var_map.setdefault(var.name, var.default)
        nodes_out: dict[str, Any] = {}
        for receipt in execution.node_results:
            nid = str(receipt.get("node_id") or receipt.get("step_id") or "")
            if not nid:
                continue
            nodes_out[nid] = {
                "output": receipt.get("output")
                if "output" in receipt
                else (receipt.get("result") or {}),
                "status": receipt.get("status"),
            }
        return build_execution_context(
            inputs=dict(execution.input_snapshot or {}),
            variables=var_map,
            nodes=nodes_out,
            trigger={"source": execution.trigger_source},
            execution={"execution_id": execution.execution_id, "workflow_id": execution.workflow_id},
        )

    def _run_condition(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        node: WorkflowNodeDef,
        ctx: dict[str, Any],
    ) -> WorkflowRecord:
        cfg = dict(node.config or {})
        predicate = cfg.get("predicate")
        if not isinstance(predicate, dict):
            # Allow shorthand op/left/right at config root.
            predicate = {k: cfg[k] for k in ("op", "left", "right", "path", "args", "predicates") if k in cfg}
        try:
            result = bool(eval_predicate(predicate, ctx))
        except ValueError as exc:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = str(exc)
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        handle = "true" if result else "false"
        self._append_node_result(execution, node, status="COMPLETED", output={"result": result, "handle": handle})
        moved = self._move_to_next(execution, graph, handle=handle)
        if not moved:
            execution.state = WorkflowExecutionState.COMPLETED
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _run_loop(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        node: WorkflowNodeDef,
        ctx: dict[str, Any],
    ) -> WorkflowRecord:
        """Loop semantics — max_iterations is a safety ceiling when while/until would continue."""
        cfg = dict(node.config or {})
        max_iterations = int(cfg.get("max_iterations") or 0)
        if max_iterations < 1:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "LOOP_LIMIT_EXCEEDED"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        cursor = dict(execution.cursor or {})
        counters = dict(cursor.get("loop_counters") or {})
        count = int(counters.get(node.node_id) or 0)

        terminate = cfg.get("until") or cfg.get("while")
        has_predicate = isinstance(terminate, dict)
        predicate_continue = True
        if has_predicate:
            try:
                pred = eval_predicate(terminate, ctx)
            except ValueError as exc:
                execution.state = WorkflowExecutionState.FAILED
                execution.error = str(exc)
                self.store.save_execution(execution)
                return self.store.get(execution.execution_id)  # type: ignore[return-value]
            if cfg.get("until"):
                predicate_continue = not bool(pred)
            else:
                predicate_continue = bool(pred)

        def _exit_done(*, reason: str) -> WorkflowRecord:
            self._append_node_result(
                execution,
                node,
                status="COMPLETED",
                output={
                    "iteration": count,
                    "max_iterations": max_iterations,
                    "done": True,
                    "exit_reason": reason,
                },
            )
            moved = self._move_to_next(execution, graph, handle="done")
            if not moved:
                moved = self._move_to_next(execution, graph, handle="false")
            if not moved:
                execution.state = WorkflowExecutionState.COMPLETED
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        if has_predicate and not predicate_continue:
            return _exit_done(reason="predicate_false")

        if count >= max_iterations:
            if has_predicate and predicate_continue:
                execution.state = WorkflowExecutionState.FAILED
                execution.error = "LOOP_LIMIT_EXCEEDED"
                self._append_node_result(
                    execution,
                    node,
                    status="FAILED",
                    output={
                        "iteration": count,
                        "max_iterations": max_iterations,
                        "error": "LOOP_LIMIT_EXCEEDED",
                    },
                )
                self.store.save_execution(execution)
                return self.store.get(execution.execution_id)  # type: ignore[return-value]
            return _exit_done(reason="max_iterations_reached")

        counters[node.node_id] = count + 1
        cursor["loop_counters"] = counters
        execution.cursor = cursor
        self._append_node_result(
            execution,
            node,
            status="RUNNING",
            output={"iteration": count + 1, "max_iterations": max_iterations},
        )
        moved = self._move_to_next(execution, graph, handle="body")
        if not moved:
            moved = self._move_to_next(execution, graph, handle=None)
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _run_delay(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        node: WorkflowNodeDef,
    ) -> WorkflowRecord:
        cfg = dict(node.config or {})
        try:
            delay_seconds = float(cfg.get("delay_seconds") or 0)
        except (TypeError, ValueError):
            delay_seconds = -1
        if delay_seconds < 0:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "WORKFLOW_INVALID: delay_seconds"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        if delay_seconds == 0:
            self._append_node_result(execution, node, status="COMPLETED", output={"delayed_seconds": 0})
            moved = self._move_to_next(execution, graph, handle=None)
            if not moved:
                execution.state = WorkflowExecutionState.COMPLETED
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        resume_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat(
            timespec="seconds"
        )
        delay_i = max(1, int(delay_seconds))

        # Foreground test helper (no job_runtime): complete delay inline.
        if self.schedule_store is None and self.job_runtime is None:
            self._append_node_result(
                execution,
                node,
                status="COMPLETED",
                output={"delay_seconds": delay_seconds, "resume_at": resume_at, "foreground": True},
            )
            moved = self._move_to_next(execution, graph, handle=None)
            if not moved:
                execution.state = WorkflowExecutionState.COMPLETED
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        if self.schedule_store is None:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "DELAY_WAKEUP_UNAVAILABLE: schedule_store not bound"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        try:
            from Data.modules.schedules.types import ScheduleTargetKind

            sched = self.schedule_store.create(
                name=f"wf-delay:{execution.execution_id}:{node.node_id}",
                target_kind=ScheduleTargetKind.JOB,
                target_ref="workflow.advance",
                interval_seconds=max(delay_i, 86_400 * 365),
                start_after_seconds=delay_i,
                target_payload={"workflow_id": execution.execution_id},
                metadata={
                    "one_shot": True,
                    "workflow_execution_id": execution.execution_id,
                    "delay_node_id": node.node_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            execution.state = WorkflowExecutionState.FAILED
            execution.error = f"DELAY_WAKEUP_UNAVAILABLE: {exc}"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        meta = dict(execution.metadata or {})
        meta["wait_reason"] = "WAITING_DELAY"
        meta["delay_resume_at"] = resume_at
        meta["delay_node_id"] = node.node_id
        meta["delay_schedule_id"] = sched.schedule_id
        execution.metadata = meta
        execution.state = WorkflowExecutionState.WAITING
        self._append_node_result(
            execution,
            node,
            status="WAITING",
            output={
                "delay_seconds": delay_seconds,
                "resume_at": resume_at,
                "schedule_id": sched.schedule_id,
            },
        )
        try:
            self.store.save_execution(execution)
        except Exception:
            try:
                from Data.modules.schedules.types import ScheduleStatus

                self.schedule_store.set_status(sched.schedule_id, ScheduleStatus.DISABLED)
            except Exception:  # noqa: BLE001
                pass
            raise
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _run_capability_node(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        node: WorkflowNodeDef,
        ctx: dict[str, Any],
    ) -> WorkflowRecord:
        cfg = dict(node.config or {})
        capability_id = str(cfg.get("capability_id") or "").strip()
        if not capability_id:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "WORKFLOW_INVALID: missing capability_id"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        arguments = resolve_value(dict(cfg.get("arguments") or {}), ctx)
        meta = dict(execution.metadata or {})
        approval_id = meta.get("resume_approval_id") or cfg.get("approval_id")

        cap_meta = None
        try:
            definition = self.gateway.catalog.get(capability_id)
            cap_meta = getattr(definition, "metadata", None) if definition else None
        except Exception:  # noqa: BLE001
            cap_meta = None
        workload = classify_capability(
            capability_id,
            metadata=cap_meta if isinstance(cap_meta, dict) else None,
        )
        external = workload == ExecutionWorkloadClass.EXTERNAL_REQUIRED or is_external_required(
            capability_id,
            metadata=cap_meta if isinstance(cap_meta, dict) else None,
        )

        if external and self.job_runtime is not None:
            existing = meta.get("pending_child_job_id")
            if existing:
                meta["wait_reason"] = "WAITING_CHILD"
                execution.metadata = meta
                execution.state = WorkflowExecutionState.WAITING
                self.store.save_execution(execution)
                return self.store.get(execution.execution_id)  # type: ignore[return-value]
            idem = f"workflow:child:{execution.execution_id}:{node.node_id}:{execution.cursor.get('current_step')}"
            try:
                from Data.modules.workers.pools import pool_for_capability

                pool = pool_for_capability(capability_id)
            except Exception:  # noqa: BLE001
                pool = None
            child = self.job_runtime.enqueue(
                capability_id=capability_id,
                arguments=dict(arguments or {}),
                approval_id=approval_id,
                run_id=execution.run_id,
                requested_by="workflow",
                idempotency_key=idem,
                domain="workflows",
                domain_entity_type="workflow_execution",
                domain_entity_id=execution.execution_id,
                worker_pool=pool,
                latency_class="background",
                metadata={
                    "workflow_id": execution.workflow_id,
                    "execution_id": execution.execution_id,
                    "node_id": node.node_id,
                },
            )
            meta["pending_child_job_id"] = child.job_id
            meta["wait_reason"] = "WAITING_CHILD"
            execution.metadata = meta
            execution.state = WorkflowExecutionState.WAITING
            child_ids = list(execution.child_job_ids or [])
            child_ids.append(child.job_id)
            execution.child_job_ids = child_ids
            if execution.root_job_id is None:
                execution.root_job_id = child.job_id
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=dict(arguments or {}),
                approval_id=approval_id,
                run_id=execution.run_id,
                requested_by="workflow",
                request_id=f"{execution.execution_id}:{node.node_id}",
            )
        )
        status_value = getattr(result.status, "value", str(result.status))
        if (
            result.status == CapabilityStatus.APPROVAL_REQUIRED
            or status_value in {"PENDING_APPROVAL", "APPROVAL_REQUIRED", "WAITING_APPROVAL"}
            or (
                result.status == CapabilityStatus.REJECTED
                and (result.telemetry or {}).get("reason") == "approval_required"
            )
        ):
            fingerprint = _args_fingerprint(dict(arguments or {}))
            meta["wait_reason"] = "WAITING_APPROVAL"
            meta["pending_approval"] = {
                "node_id": node.node_id,
                "capability_id": capability_id,
                "args_fingerprint": fingerprint,
                "requested_at": utc_now(),
                "gateway_request_id": result.request_id,
                "gateway_reason": (result.telemetry or {}).get("reason") or "approval_required",
            }
            meta.pop("resume_approval_id", None)
            execution.metadata = meta
            execution.state = WorkflowExecutionState.WAITING_APPROVAL
            self._append_node_result(
                execution,
                node,
                status="WAITING_APPROVAL",
                output={"result": result.public_dict(), "args_fingerprint": fingerprint},
            )
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        if meta.get("resume_approval_id"):
            meta.pop("resume_approval_id", None)
            meta.pop("pending_approval", None)
            execution.metadata = meta

        # Bounded receipt — avoid stuffing giant payloads into workflow JSON.
        public = result.public_dict()
        bounded = {
            "status": status_value,
            "error": result.error,
            "has_result": public.get("result") is not None,
            "result_preview": _bound_preview(public.get("result")),
        }
        self._append_node_result(
            execution,
            node,
            status=status_value,
            output=bounded,
            capability_id=capability_id,
        )
        if result.status != CapabilityStatus.COMPLETED:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = result.error or result.status.value
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        moved = self._move_to_next(execution, graph, handle=None)
        if not moved:
            execution.state = WorkflowExecutionState.COMPLETED
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _resume_child_execution(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        pending_job_id: str,
    ) -> WorkflowRecord:
        meta = dict(execution.metadata or {})
        if self.job_runtime is None:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "WORKFLOW_CHILD_UNAVAILABLE"
            meta["wait_reason"] = None
            execution.metadata = meta
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        job = self.job_runtime.store.get(pending_job_id)
        if job is None:
            execution.state = WorkflowExecutionState.FAILED
            execution.error = "WORKFLOW_CHILD_UNAVAILABLE"
            meta["wait_reason"] = None
            execution.metadata = meta
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        from Data.modules.jobs.states import JobState

        if job.state not in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
            return self.store.get(execution.execution_id)  # type: ignore[return-value]

        node_id = execution.current_node_id or ""
        already = any(
            r.get("node_id") == node_id and r.get("child_job_id") == pending_job_id
            for r in execution.node_results
        )
        if not already:
            execution.node_results.append(
                {
                    "node_id": node_id,
                    "step_id": node_id,
                    "status": job.state.value,
                    "child_job_id": pending_job_id,
                    "output": {
                        "job_id": pending_job_id,
                        "state": job.state.value,
                        "result_ref": True,
                        "error": job.error,
                        "has_result": job.result is not None,
                    },
                }
            )
        meta["pending_child_job_id"] = None
        meta["wait_reason"] = None
        execution.metadata = meta
        if job.state != JobState.COMPLETED:
            execution.state = (
                WorkflowExecutionState.CANCELLED
                if job.state == JobState.CANCELLED
                else WorkflowExecutionState.FAILED
            )
            execution.error = job.error or "WORKFLOW_CHILD_FAILED"
            self.store.save_execution(execution)
            return self.store.get(execution.execution_id)  # type: ignore[return-value]
        execution.state = WorkflowExecutionState.RUNNING
        moved = self._move_to_next(execution, graph, handle=None)
        if not moved:
            execution.state = WorkflowExecutionState.COMPLETED
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _move_to_next(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
        *,
        handle: str | None,
    ) -> bool:
        current = execution.current_node_id
        if not current:
            return False
        edges = [e for e in graph.edges if e.source == current]
        chosen: WorkflowEdgeDef | None = None
        if handle is not None:
            for edge in edges:
                if (edge.source_handle or "") == handle or (edge.label or "") == handle:
                    chosen = edge
                    break
        if chosen is None:
            # Default: first edge without a handle, else first edge.
            for edge in edges:
                if not edge.source_handle:
                    chosen = edge
                    break
            if chosen is None and edges and handle is None:
                chosen = edges[0]
        cursor = dict(execution.cursor or {})
        visited = list(cursor.get("visited") or [])
        visited.append(current)
        cursor["visited"] = visited
        step_ids = list(cursor.get("step_ids") or [])
        current_step = int(cursor.get("current_step") or 0)
        if current in step_ids:
            current_step = step_ids.index(current) + 1
        else:
            current_step += 1
        cursor["current_step"] = current_step
        if chosen is None:
            execution.current_node_id = None
            cursor["current_node_id"] = None
            execution.cursor = cursor
            return False
        execution.current_node_id = chosen.target
        cursor["current_node_id"] = chosen.target
        execution.cursor = cursor
        meta = dict(execution.metadata or {})
        meta["current_node_id"] = chosen.target
        execution.metadata = meta
        return True

    def _append_node_result(
        self,
        execution: WorkflowExecution,
        node: WorkflowNodeDef,
        *,
        status: str,
        output: dict[str, Any],
        capability_id: str | None = None,
    ) -> None:
        execution.node_results.append(
            {
                "node_id": node.node_id,
                "step_id": node.node_id,
                "kind": node.kind_value,
                "capability_id": capability_id or (node.config or {}).get("capability_id"),
                "status": status,
                "output": output,
                "result": output,
            }
        )

    def _advance_linear_from_execution(
        self,
        execution: WorkflowExecution,
        graph: WorkflowGraph,
    ) -> WorkflowRecord:
        # Bootstrap: set current to trigger or first node.
        trigger = next((n for n in graph.nodes if n.kind_value == "trigger"), None)
        start = trigger.node_id if trigger else (graph.nodes[0].node_id if graph.nodes else None)
        execution.current_node_id = start
        cursor = dict(execution.cursor or {})
        cursor["current_node_id"] = start
        execution.cursor = cursor
        self.store.save_execution(execution)
        return self._advance_execution(execution)

    def _advance_legacy_record(self, workflow_id: str) -> WorkflowRecord:
        """Compat adapter for rare pre-migration rows without an execution projection.\n\n        Production traffic always has ``workflow_executions`` rows. New orchestration\n        features live only on the execution path — do not extend this adapter.\n        """
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            return record
        if record.state != WorkflowState.RUNNING:
            record.state = WorkflowState.RUNNING
            self.store.save(record)
        if record.current_step >= len(record.steps):
            record.state = WorkflowState.COMPLETED
            return self.store.save(record)
        meta = dict(record.metadata or {})
        wait = str(meta.get("wait_reason") or "")
        pending = meta.get("pending_child_job_id")
        if wait == "WAITING_CHILD" and pending:
            return self._resume_child_legacy(record, str(pending))
        if wait == "WAITING_APPROVAL":
            return record
        step = record.steps[record.current_step]
        return self._run_legacy_step(record, step)

    def _run_legacy_step(self, record: WorkflowRecord, step: WorkflowStepDef) -> WorkflowRecord:
        meta = dict(record.metadata or {})
        cap_meta = None
        try:
            definition = self.gateway.catalog.get(step.capability_id)
            cap_meta = getattr(definition, "metadata", None) if definition else None
        except Exception:  # noqa: BLE001
            cap_meta = None
        workload = classify_capability(
            step.capability_id,
            metadata=cap_meta if isinstance(cap_meta, dict) else None,
        )
        external = workload == ExecutionWorkloadClass.EXTERNAL_REQUIRED or is_external_required(
            step.capability_id,
            metadata=cap_meta if isinstance(cap_meta, dict) else None,
        )
        if external and self.job_runtime is not None:
            existing = meta.get("pending_child_job_id")
            if existing:
                meta["wait_reason"] = "WAITING_CHILD"
                record.metadata = meta
                return self.store.save(record)
            idem = f"workflow:child:{record.workflow_id}:{step.step_id}:{record.current_step}"
            try:
                from Data.modules.workers.pools import pool_for_capability

                pool = pool_for_capability(step.capability_id)
            except Exception:  # noqa: BLE001
                pool = None
            child = self.job_runtime.enqueue(
                capability_id=step.capability_id,
                arguments=dict(step.arguments),
                approval_id=step.approval_id,
                run_id=record.run_id,
                requested_by="workflow",
                idempotency_key=idem,
                domain="workflows",
                domain_entity_type="workflow",
                domain_entity_id=record.workflow_id,
                worker_pool=pool,
                latency_class="background",
                metadata={
                    "workflow_id": record.workflow_id,
                    "step_id": step.step_id,
                    "step_index": record.current_step,
                },
            )
            meta["pending_child_job_id"] = child.job_id
            meta["wait_reason"] = "WAITING_CHILD"
            record.metadata = meta
            record.state = WorkflowState.RUNNING
            return self.store.save(record)
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=step.capability_id,
                arguments=step.arguments,
                approval_id=step.approval_id,
                run_id=record.run_id,
                requested_by="workflow",
                request_id=f"{record.workflow_id}:{step.step_id}",
            )
        )
        record.step_results.append(
            {
                "step_id": step.step_id,
                "capability_id": step.capability_id,
                "status": result.status.value,
                "result": result.public_dict(),
            }
        )
        if result.status != CapabilityStatus.COMPLETED:
            record.state = WorkflowState.FAILED
            record.error = result.error or result.status.value
            return self.store.save(record)
        record.current_step += 1
        if record.current_step >= len(record.steps):
            record.state = WorkflowState.COMPLETED
        return self.store.save(record)

    def _resume_child_legacy(self, record: WorkflowRecord, pending_job_id: str) -> WorkflowRecord:
        meta = dict(record.metadata or {})
        if self.job_runtime is None:
            record.state = WorkflowState.FAILED
            record.error = "WORKFLOW_CHILD_UNAVAILABLE"
            meta["wait_reason"] = None
            record.metadata = meta
            return self.store.save(record)
        job = self.job_runtime.store.get(pending_job_id)
        if job is None:
            record.state = WorkflowState.FAILED
            record.error = "WORKFLOW_CHILD_UNAVAILABLE"
            meta["wait_reason"] = None
            record.metadata = meta
            return self.store.save(record)
        from Data.modules.jobs.states import JobState

        if job.state not in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
            return record
        step = record.steps[record.current_step]
        already = any(
            r.get("step_id") == step.step_id and r.get("child_job_id") == pending_job_id
            for r in record.step_results
        )
        if not already:
            record.step_results.append(
                {
                    "step_id": step.step_id,
                    "capability_id": step.capability_id,
                    "status": job.state.value,
                    "child_job_id": pending_job_id,
                    "result": {
                        "job_id": pending_job_id,
                        "state": job.state.value,
                        "result_ref": True,
                        "error": job.error,
                        "has_result": job.result is not None,
                    },
                }
            )
        meta["pending_child_job_id"] = None
        meta["wait_reason"] = None
        record.metadata = meta
        if job.state != JobState.COMPLETED:
            record.state = WorkflowState.FAILED
            record.error = job.error or "WORKFLOW_CHILD_FAILED"
            return self.store.save(record)
        record.current_step += 1
        if record.current_step >= len(record.steps):
            record.state = WorkflowState.COMPLETED
        return self.store.save(record)

    def cancel(self, workflow_id: str) -> WorkflowRecord:
        execution = self.store.get_execution(workflow_id)
        if execution is not None:
            return self._cancel_execution(execution)
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            raise ValueError(f"Workflow already terminal: {record.state.value}")
        meta = dict(record.metadata or {})
        pending = meta.get("pending_child_job_id")
        if pending and self.job_runtime is not None:
            try:
                self.job_runtime.cancel(str(pending))
            except Exception:  # noqa: BLE001
                pass
        meta["wait_reason"] = None
        meta["cancel_requested"] = True
        record.metadata = meta
        record.state = WorkflowState.CANCELLED
        record.error = "Cancelled by request"
        return self.store.save(record)

    def _cancel_execution(self, execution: WorkflowExecution) -> WorkflowRecord:
        if execution.state in {
            WorkflowExecutionState.COMPLETED,
            WorkflowExecutionState.FAILED,
            WorkflowExecutionState.CANCELLED,
        }:
            raise ValueError(f"Workflow already terminal: {execution.state.value}")
        meta = dict(execution.metadata or {})
        meta["cancel_requested"] = True
        pending = meta.get("pending_child_job_id")
        if pending and self.job_runtime is not None:
            try:
                self.job_runtime.cancel(str(pending))
            except Exception:  # noqa: BLE001
                pass
        # Cancel pending workflow.advance jobs when JobRuntime supports listing — best-effort.
        if self.job_runtime is not None:
            try:
                # Cancel root job if tracked.
                if execution.root_job_id:
                    self.job_runtime.cancel(str(execution.root_job_id))
            except Exception:  # noqa: BLE001
                pass
        meta["wait_reason"] = None
        execution.metadata = meta
        execution.state = WorkflowExecutionState.CANCELLED
        execution.error = "Cancelled by request"
        # Disable one-shot delay schedule if present.
        sched_id = meta.get("delay_schedule_id")
        if sched_id and self.schedule_store is not None and str(sched_id) != "foreground":
            try:
                from Data.modules.schedules.types import ScheduleStatus

                self.schedule_store.set_status(str(sched_id), ScheduleStatus.DISABLED)
            except Exception:  # noqa: BLE001
                pass
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]

    def _finalize_cancel(self, execution: WorkflowExecution) -> WorkflowRecord:
        execution.state = WorkflowExecutionState.CANCELLED
        execution.error = execution.error or "Cancelled by request"
        self.store.save_execution(execution)
        return self.store.get(execution.execution_id)  # type: ignore[return-value]


def _bound_preview(value: Any, *, limit: int = 2000) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        if len(text) > limit:
            return text[:limit] + "…"
        return text
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        out = {}
        size = 0
        for key, item in list(value.items())[:40]:
            preview = _bound_preview(item, limit=max(200, limit // 4))
            out[key] = preview
            size += len(str(preview))
            if size > limit:
                out["…"] = "truncated"
                break
        return out
    if isinstance(value, list):
        return [_bound_preview(v, limit=max(200, limit // 4)) for v in value[:20]]
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"
