"""Durable workflow orchestration — one step per advance; specialist child jobs for EXTERNAL_REQUIRED."""

from __future__ import annotations

from typing import Any

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
    is_external_required,
)

from .store import WorkflowStore
from .types import WorkflowRecord, WorkflowState, WorkflowStepDef


class WorkflowRuntime:
    """Execute ordered capability steps through the shared Execution Gateway.

    Production path: :meth:`enqueue_advance` creates durable ``workflow.advance``
    jobs; workers advance one step and release. :meth:`run` remains a
    synchronous foreground helper for tests/legacy callers only.
    """

    def __init__(
        self,
        store: WorkflowStore,
        gateway: ExecutionGateway,
        *,
        job_runtime: Any | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.job_runtime = job_runtime

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def create(
        self,
        *,
        name: str,
        steps: list[WorkflowStepDef],
        run_id: str | None = None,
    ) -> WorkflowRecord:
        return self.store.create(name=name, steps=steps, run_id=run_id)

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
        if record.state == WorkflowState.CREATED:
            record.state = WorkflowState.RUNNING
            self.store.save(record)
        step_index = int(record.current_step)
        wait = str((record.metadata or {}).get("wait_reason") or "")
        pending = (record.metadata or {}).get("pending_child_job_id") or ""
        gen = generation or f"{step_index}:{wait}:{pending}"
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
        """TEST-ONLY / legacy foreground helper: run all remaining steps synchronously.

        Production control plane must use :meth:`enqueue_advance` instead.
        """
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            return record
        record.state = WorkflowState.RUNNING
        self.store.save(record)

        while record.current_step < len(record.steps):
            record = self.advance_one_step(workflow_id)
            wait = str((record.metadata or {}).get("wait_reason") or "")
            if wait == "WAITING_CHILD":
                # Foreground helper: drain the child once (tests only).
                pending = (record.metadata or {}).get("pending_child_job_id")
                if pending and self.job_runtime is not None:
                    # Do not call process_next in a loop steal — only process until our child is done.
                    # For unit tests without workers, execute the child capability inline via gateway.
                    record = self._consume_or_fail_child_foreground(record)
                    continue
                record.state = WorkflowState.FAILED
                record.error = "WORKFLOW_CHILD_UNAVAILABLE"
                return self.store.save(record)
            if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
                return record
        return record

    def _consume_or_fail_child_foreground(self, record: WorkflowRecord) -> WorkflowRecord:
        """TEST-ONLY: resolve a pending child by gateway execute of the same step."""
        meta = dict(record.metadata or {})
        step = record.steps[record.current_step]
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

        # Resume after child job
        if wait == "WAITING_CHILD" and pending:
            return self._resume_child(record, str(pending))

        if wait == "WAITING_APPROVAL":
            # Still waiting — caller must re-enqueue after approval.
            return record

        step = record.steps[record.current_step]
        if step.approval_id is None:
            # Check if capability requires approval without one → wait, don't fail closed as FAILED
            # unless gateway would reject. Keep current fail-fast for missing approval via gateway.
            pass

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
            # Idempotent child: reuse existing pending if present.
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
            # Do NOT busy-wait — release worker; continuation resumes later.
            return self.store.save(record)

        # INLINE_SAFE (or no job_runtime for tests): execute via gateway in this worker.
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

    def _resume_child(self, record: WorkflowRecord, pending_job_id: str) -> WorkflowRecord:
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
            # Still waiting — leave metadata; do not busy-wait.
            return record

        step = record.steps[record.current_step]
        # Avoid duplicate receipt on retry.
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
                        # Bounded receipt — do not duplicate giant outputs.
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
