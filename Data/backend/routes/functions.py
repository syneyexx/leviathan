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
    job_runtime: Any | None = None,
    filesystem_root: Any = None,
) -> APIRouter:
    router = APIRouter(tags=["functions"])

    capability_aliases = {
        "pdf_parser": "file.parse_pdf",
        "text_file_read": "file.read",
        "csv_inspector": "file.inspect_csv",
        "text_file_write": "file.write",
        "file_hash": "file.hash",
        "file_copy": "file.copy",
        "csv_parse": "file.parse_csv",
        "csv_profile": "file.profile_csv",
        "parquet_process": "file.process_parquet",
        "filesystem_scan": "filesystem.scan",
        "workspace_list": "workspace.list",
        "workspace_search": "workspace.search",
    }

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
        capability_id = capability_aliases.get(function_id, function_id)
        from Data.modules.coding.workspace import confine
        from Data.modules.common.paths import PathEscapeError
        from Data.modules.execution.file_io_dispatch import classify_and_maybe_enqueue
        from Data.modules.execution.file_io_thresholds import FILE_IO_CAPABILITIES
        from Data.modules.execution.workload import (
            ExecutionWorkloadClass,
            api_may_execute_inline,
            classify_request_workload,
        )

        arguments = dict(payload.arguments or {})
        # Path confinement BEFORE classification (security ordering).
        if filesystem_root is not None:
            from pathlib import Path

            root = Path(filesystem_root)
            for key in (
                "path",
                "source_path",
                "dest_path",
                "content_path",
                "workspace_root",
                "cwd",
                "file_path",
                "target",
                "output_path",
            ):
                if key not in arguments or arguments[key] is None:
                    continue
                raw = str(arguments[key]).strip()
                if not raw:
                    continue
                try:
                    arguments[key] = str(confine(root, raw))
                except PathEscapeError as exc:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "error": "PATH_OUTSIDE_ROOT",
                            "reason": "path_escape",
                            "message": str(exc),
                        },
                    ) from exc

        cls = classify_request_workload(
            capability_id,
            arguments,
            filesystem_root=filesystem_root,
        )
        if cls == ExecutionWorkloadClass.EXTERNAL_REQUIRED and not api_may_execute_inline(
            capability_id,
            arguments=arguments,
            filesystem_root=filesystem_root,
        ):
            if capability_id in FILE_IO_CAPABILITIES and job_runtime is not None:
                outcome = classify_and_maybe_enqueue(
                    capability_id=capability_id,
                    arguments=arguments,
                    job_runtime=job_runtime,
                    filesystem_root=filesystem_root,
                    requested_by="api.functions",
                )
                if outcome.get("queued"):
                    job = outcome["job"]
                    return {
                        "status": "QUEUED",
                        "execution_class": outcome["execution_class"],
                        "job_id": getattr(job, "job_id", None),
                        "job": job.public_dict() if hasattr(job, "public_dict") else {"job_id": getattr(job, "job_id", None)},
                        "worker_pool": "file_io",
                    }
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "WORKER_UNAVAILABLE",
                    "reason": "worker_required",
                    "capability_id": capability_id,
                    "function_id": function_id,
                    "execution_class": cls.value,
                    "message": (
                        f"{capability_id} is EXTERNAL_REQUIRED and must run on an external worker"
                    ),
                },
            )
        result = function_runtime.execute(function_id, arguments)
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
        return {"result": result.public_dict(), "execution_class": cls.value}

    @router.post("/api/functions/calls/{call_id}/cancel")
    def cancel_function_call(call_id: str) -> dict:
        cancelled = function_runtime.cancel(call_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Active function call not found")
        return {"cancelled": True, "call_id": call_id}

    return router
