"""ExecutionGateway ModuleExecutor — routes MODULE provider_kind through external fabric."""

from __future__ import annotations

from typing import Any, Mapping

from Data.modules.execution.types import CapabilityResult, CapabilityStatus
from Data.modules.function_runtime.types import SideEffect

from ..manager import ModuleManager, ModuleManagerError
from .types import normalize_capability_parts


class ExternalModuleExecutor:
    """Gateway adapter: capability_id → module_id + operation via provider_ref.

    provider_ref formats:
      - ``module_id`` (operation from arguments['operation'] or capability suffix)
      - ``module_id:operation``
    """

    def __init__(self, module_manager: ModuleManager) -> None:
        self.module_manager = module_manager

    def execute_module_capability(
        self,
        capability_id: str,
        provider_ref: str,
        arguments: dict[str, Any],
        *,
        request_id: str = "",
        run_id: str | None = None,
    ) -> CapabilityResult | dict[str, Any]:
        # Control-plane external fabric capabilities.
        if capability_id == "external.module.install":
            module_id = str(arguments.get("module_id") or "")
            if not module_id:
                return CapabilityResult(
                    request_id=request_id or "",
                    capability_id=capability_id,
                    status=CapabilityStatus.REJECTED,
                    error="module_id required",
                    provider_kind="module",
                    provider_ref=provider_ref,
                )
            try:
                result = self.module_manager.ensure_installed(module_id)
                return CapabilityResult(
                    request_id=request_id or "",
                    capability_id=capability_id,
                    status=CapabilityStatus.COMPLETED,
                    output=normalize_capability_parts(summary=f"installed {module_id}", structured_data=result),
                    provider_kind="module",
                    provider_ref=provider_ref,
                )
            except ModuleManagerError as exc:
                return CapabilityResult(
                    request_id=request_id or "",
                    capability_id=capability_id,
                    status=CapabilityStatus.FAILED,
                    error=str(exc),
                    provider_kind="module",
                    provider_ref=provider_ref,
                )
        if capability_id == "external.module.invoke":
            module_id = str(arguments.get("module_id") or "")
            operation = str(arguments.get("operation") or "run")
            inner = dict(arguments.get("arguments") or {})
            return self.execute_module_capability(
                f"{module_id}.{operation}",
                f"{module_id}:{operation}",
                inner,
                request_id=request_id,
                run_id=run_id,
            )
        if capability_id in {"external.skills.search", "external.skills.load"}:
            return self._skills_capability(capability_id, arguments, request_id=request_id)

        module_id, operation = _split_ref(provider_ref, capability_id, arguments)
        args = dict(arguments)
        args.pop("operation", None)
        try:
            # Lazy start when needed.
            try:
                self.module_manager.ensure_ready(module_id)
            except ModuleManagerError:
                # ensure_ready may not exist on older managers — fall through to execute.
                if hasattr(self.module_manager, "ensure_ready"):
                    raise
            result = self.module_manager.execute(module_id, operation, args)
        except ModuleManagerError as exc:
            return CapabilityResult(
                request_id=request_id or "",
                capability_id=capability_id,
                status=CapabilityStatus.FAILED,
                error=str(exc),
                output=normalize_capability_parts(
                    summary=str(exc),
                    error={"code": "MODULE_ERROR", "detail": str(exc)},
                    metadata={"module_id": module_id, "operation": operation, "run_id": run_id},
                ),
                provider_kind="module",
                provider_ref=provider_ref,
            )

        status_map = {
            "COMPLETED": CapabilityStatus.COMPLETED,
            "OK": CapabilityStatus.COMPLETED,
            "SUCCESS": CapabilityStatus.COMPLETED,
            "FAILED": CapabilityStatus.FAILED,
            "REJECTED": CapabilityStatus.REJECTED,
            "CANCELLED": CapabilityStatus.CANCELLED,
            "TIMEOUT": CapabilityStatus.TIMEOUT,
        }
        status = status_map.get(str(result.status).upper(), CapabilityStatus.FAILED)
        output = result.output if isinstance(result.output, dict) else {"result": result.output}
        if "parts" not in output:
            output = normalize_capability_parts(
                summary=str((output or {}).get("summary") or result.status),
                structured_data=output,
                metadata={"module_id": module_id, "operation": operation, "run_id": run_id},
            )
        else:
            output = {
                **output,
                "metadata": {
                    **dict(output.get("metadata") or {}),
                    "module_id": module_id,
                    "operation": operation,
                    "run_id": run_id,
                },
            }
        return CapabilityResult(
            request_id=request_id or "",
            capability_id=capability_id,
            status=status,
            output=output,
            error=result.error,
            side_effects=(SideEffect.READ,),
            provider_kind="module",
            provider_ref=provider_ref,
            telemetry={
                "duration_ms": result.duration_ms,
                "module_id": module_id,
                "operation": operation,
            },
        )

    def _skills_capability(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
    ) -> CapabilityResult:
        store = None
        # Prefer CONTROL store via any external module instance metadata.
        for managed in self.module_manager.list():
            inst = managed.instance
            if inst is not None and getattr(inst, "_store", None) is not None:
                store = inst._store
                break
        if store is None:
            return CapabilityResult(
                request_id=request_id or "",
                capability_id=capability_id,
                status=CapabilityStatus.FAILED,
                error="skill store unavailable",
                provider_kind="module",
                provider_ref="external.skills",
            )
        if capability_id == "external.skills.search":
            rows = store.search_skills(
                query=str(arguments.get("query") or "") or None,
                enabled_only=bool(arguments.get("enabled_only", True)),
                include_catalog=bool(arguments.get("include_catalog", True)),
                limit=int(arguments.get("limit") or 25),
                offset=int(arguments.get("offset") or 0),
            )
            return CapabilityResult(
                request_id=request_id or "",
                capability_id=capability_id,
                status=CapabilityStatus.COMPLETED,
                output=normalize_capability_parts(
                    summary=f"{len(rows)} skills",
                    structured_data={"skills": rows, "count": len(rows)},
                    metadata={"bounded": True, "not_prompt_injected": True},
                ),
                provider_kind="module",
                provider_ref="external.skills",
            )
        skill_id = str(arguments.get("skill_id") or arguments.get("name") or "")
        skill = store.get_skill(skill_id)
        if skill is None:
            matches = store.search_skills(query=skill_id, limit=1)
            skill = matches[0] if matches else None
        if skill is None:
            return CapabilityResult(
                request_id=request_id or "",
                capability_id=capability_id,
                status=CapabilityStatus.FAILED,
                error="skill not found",
                provider_kind="module",
                provider_ref="external.skills",
            )
        from .skills import load_skill_instructions

        instructions = load_skill_instructions(skill)
        return CapabilityResult(
            request_id=request_id or "",
            capability_id=capability_id,
            status=CapabilityStatus.COMPLETED,
            output=normalize_capability_parts(
                summary=skill.get("name"),
                structured_data={**skill, "instructions": instructions},
                metadata={"on_demand": True},
            ),
            provider_kind="module",
            provider_ref="external.skills",
        )


def _split_ref(provider_ref: str, capability_id: str, arguments: Mapping[str, Any]) -> tuple[str, str]:
    ref = (provider_ref or "").strip()
    if ":" in ref and not ref.startswith("external."):
        module_id, _, operation = ref.partition(":")
        if module_id and operation:
            return module_id, operation
    module_id = ref or capability_id.split(".", 1)[0]
    # Prefer explicit module_id in external.* provider refs like "external.invoke"
    if module_id.startswith("external."):
        module_id = str(arguments.get("module_id") or capability_id.split(".")[0])
    operation = str(arguments.get("operation") or "")
    if not operation and "." in capability_id:
        operation = capability_id.rsplit(".", 1)[-1]
    if not operation:
        operation = "run"
    return module_id, operation
