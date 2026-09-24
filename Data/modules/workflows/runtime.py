from __future__ import annotations

from typing import Any

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway

from .store import WorkflowStore
from .types import WorkflowRecord, WorkflowState, WorkflowStepDef


class WorkflowRuntime:
    """Execute ordered capability steps through the shared Execution Gateway.

    Production path: :meth:`enqueue_advance` creates durable ``workflow.advance``
    jobs; workers advance one step and release. :meth:`run` remains a
    synchronous foreground helper for tests/legacy callers.
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
    ) -> Any:
        """Enqueue a durable ``workflow.advance`` job (idempotent per step index)."""
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
        idem = f"workflow:advance:{workflow_id}:{step_index}"
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
            metadata={"workflow_id": workflow_id, "step_index": step_index},
        )

    def run(self, workflow_id: str) -> WorkflowRecord:
        """Foreground helper: run all remaining steps synchronously (tests/legacy)."""
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            return record
        record.state = WorkflowState.RUNNING
        self.store.save(record)

        while record.current_step < len(record.steps):
            record = self.advance_one_step(workflow_id)
            if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
                return record
        return record

    def advance_one_step(self, workflow_id: str) -> WorkflowRecord:
        """Execute exactly one runnable step then persist and return (durable continuation)."""
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

        step = record.steps[record.current_step]
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

    def cancel(self, workflow_id: str) -> WorkflowRecord:
        record = self.store.get(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        if record.state in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
            raise ValueError(f"Workflow already terminal: {record.state.value}")
        record.state = WorkflowState.CANCELLED
        record.error = "Cancelled by request"
        return self.store.save(record)
