"""Function runtime HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.function_runtime import FunctionCallStatus


class FunctionExecuteRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


def build_functions_router(
    *,
    function_registry: Any,
    function_runtime: Any,
) -> APIRouter:
    router = APIRouter(tags=["functions"])

    @router.get("/api/functions")
    def list_functions() -> dict:
        return {
            "functions": [item.public_dict() for item in function_registry.list()],
            "loaded": sorted(function_runtime.loaded_function_ids()),
            "telemetry": dict(function_runtime.telemetry),
        }

    @router.get("/api/functions/{function_id}")
    def get_function(function_id: str) -> dict:
        definition = function_registry.get(function_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Function not found")
        return {
            "function": definition.public_dict(),
            "loaded": function_id in function_runtime.loaded_function_ids(),
        }

    @router.post("/api/functions/{function_id}/execute")
    def execute_function(function_id: str, payload: FunctionExecuteRequest) -> dict:
        if function_id not in function_registry:
            raise HTTPException(status_code=404, detail="Function not found")
        # Map FunctionRuntime ids to catalog capabilities when present (e.g. pdf_parser → file.parse_pdf).
        capability_aliases = {
            "pdf_parser": "file.parse_pdf",
            "text_file_read": "file.read",
            "csv_inspector": "file.inspect_csv",
            "text_file_write": "file.write",
        }
        capability_id = capability_aliases.get(function_id, function_id)
        from Data.modules.execution.workload import api_may_execute_inline, is_external_required

        if is_external_required(capability_id) and not api_may_execute_inline(capability_id):
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "WORKER_UNAVAILABLE",
                    "reason": "worker_required",
                    "capability_id": capability_id,
                    "function_id": function_id,
                    "message": (
                        f"{capability_id} is EXTERNAL_REQUIRED and must run on an external worker"
                    ),
                },
            )
        result = function_runtime.execute(function_id, payload.arguments)
        status_code = 200
        if result.status == FunctionCallStatus.REJECTED:
            status_code = 422
        elif result.status == FunctionCallStatus.TIMEOUT:
            status_code = 504
        elif result.status == FunctionCallStatus.CANCELLED:
            status_code = 409
        elif result.status == FunctionCallStatus.FAILED:
            status_code = 500
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.public_dict())
        return {"result": result.public_dict()}

    @router.post("/api/functions/calls/{call_id}/cancel")
    def cancel_function_call(call_id: str) -> dict:
        cancelled = function_runtime.cancel(call_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Active function call not found")
        return {"cancelled": True, "call_id": call_id}

    return router
