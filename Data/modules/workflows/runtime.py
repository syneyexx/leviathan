from __future__ import annotations

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway

from .store import WorkflowStore
from .types import WorkflowRecord, WorkflowState, WorkflowStepDef


class WorkflowRuntime:
    """Execute ordered capability steps through the shared Execution Gateway."""

    def __init__(self, store: WorkflowStore, gateway: ExecutionGateway) -> None:
        self.store = store
        self.gateway = gateway

    def create(
        self,
        *,
        name: str,
        steps: list[WorkflowStepDef],
        run_id: str | None = None,
    ) -> WorkflowRecord:
        return self.store.create(name=name, steps=steps, run_id=run_id)

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
