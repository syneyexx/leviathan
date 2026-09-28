"""Process-safe Coding worker context — never imports ``Data.backend.main``.

Builds CodingStore / ExecutionGateway / Approvals / Model adapter / loop
so the external coding pool participates in one LEVIATHAN system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_coding_worker_context(
    *,
    settings: Any | None = None,
    job_runtime: Any | None = None,
) -> dict[str, Any]:
    """Return a fully wired CodingControlPlane plus supporting handles."""
    if settings is None:
        from Data.backend.config import load_settings

        settings = load_settings()

    from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
    from Data.modules.coding.llm_adapter import CodingLLMAdapter
    from Data.modules.coding.service import CodingControlPlane
    from Data.modules.common.database_domains import resolve_control_database_path
    from Data.modules.execution import ExecutionGateway, build_default_catalog
    from Data.modules.function_runtime import FunctionRuntime, build_default_registry

    def _settings_path(value: Any, *, fallback: Path) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str) and value.strip():
            return Path(value)
        return fallback

    db_path = _settings_path(
        getattr(settings, "database_path", None),
        fallback=resolve_control_database_path(),
    )

    if job_runtime is None:
        from Data.modules.jobs.resources import ResourceManager
        from Data.modules.jobs.runtime import JobRuntime
        from Data.modules.jobs.store import JobStore

        job_store = JobStore(db_path)
        job_store.initialize()
        gateway_tmp = ExecutionGateway(catalog=build_default_catalog())
        resources = ResourceManager(getattr(getattr(settings, "resources", None), "max_job_concurrency", 4) or 4)
        job_runtime = JobRuntime(job_store, gateway_tmp, resources)

    registry = build_default_registry()
    function_runtime = FunctionRuntime(registry, max_concurrency=2, warm_cache_size=0)
    catalog = build_default_catalog()

    approval_store = ApprovalStore(db_path)
    approval_store.initialize()
    approvals = ApprovalService(approval_store, PolicyEngine())

    gateway = ExecutionGateway(
        catalog=catalog,
        function_runtime=function_runtime,
        approval_checker=approvals,
        filesystem_root=None,
    )

    llm = None
    model_client_error: str | None = None
    try:
        from Data.modules.models.worker_client import build_process_safe_model_caller

        # Prefer a model plane when available; fall back to callable adapter.
        model_caller = build_process_safe_model_caller(settings)
        # CodingLLMAdapter expects a model plane with inference_session.
        # If only a caller is available, leave llm unset — CodingLoop handles FakeLLM/missing.
        llm = model_caller
    except Exception as exc:  # noqa: BLE001
        model_client_error = f"{type(exc).__name__}: {exc}"

    model_plane = None
    coding_llm = None
    try:
        from Data.modules.models.control_plane import ModelControlPlane

        # Best-effort: workers may construct a thin plane when settings allow.
        if hasattr(ModelControlPlane, "from_settings"):
            model_plane = ModelControlPlane.from_settings(settings)  # type: ignore[attr-defined]
            coding_llm = CodingLLMAdapter(model_plane, llm=llm)
    except Exception as exc:  # noqa: BLE001
        if model_client_error is None:
            model_client_error = f"{type(exc).__name__}: {exc}"

    context_builder = None
    try:
        from Data.modules.context import ContextBuilder

        budget = int(getattr(getattr(settings, "coding", None), "token_budget", 4000) or 4000)
        context_builder = ContextBuilder(token_budget=budget)
    except Exception:  # noqa: BLE001
        context_builder = None

    plane = CodingControlPlane.from_settings(
        settings,
        db_path=db_path,
        gateway=gateway,
        approvals=approvals,
        llm=coding_llm or llm,
        context_builder=context_builder,
        job_runtime=job_runtime,
    )

    return {
        "settings": settings,
        "coding_service": plane,
        "coding_store": plane.store,
        "coding_loop": plane.loop,
        "gateway": gateway,
        "approvals": approvals,
        "job_runtime": job_runtime,
        "function_runtime": function_runtime,
        "model_plane": model_plane,
        "model_client_error": model_client_error,
        "db_path": db_path,
    }
