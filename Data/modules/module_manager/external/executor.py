"""ExecutionGateway ModuleExecutor — routes MODULE provider_kind through external fabric."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from Data.modules.execution.types import CapabilityResult, CapabilityStatus
from Data.modules.function_runtime.types import SideEffect

from ..manager import ModuleManager, ModuleManagerError
from .post_result import queue_or_run_assimilation, resolve_assimilation_mode, run_assimilation_job
from .trading_boundary import annotate_research_only, enforce_trading_boundary, module_trading_flags
from .types import normalize_capability_parts


CancelCheck = Callable[[], bool]
ProgressCb = Callable[[float, str, str], None]


class ExternalModuleExecutor:
    """Gateway adapter: capability_id → module_id + operation via provider_ref.

    provider_ref formats:
      - ``module_id`` (operation from arguments['operation'] or capability suffix)
      - ``module_id:operation``
    """

    def __init__(
        self,
        module_manager: ModuleManager,
        *,
        job_runtime: Any | None = None,
        assimilation_service: Any | None = None,
        evidence_service: Any | None = None,
        observation_store: Any | None = None,
        observability: Any | None = None,
        catalog: Any | None = None,
    ) -> None:
        self.module_manager = module_manager
        self.job_runtime = job_runtime
        self.assimilation_service = assimilation_service
        self.evidence_service = evidence_service
        self.observation_store = observation_store
        self.observability = observability
        self.catalog = catalog

    def execute_module_capability(
        self,
        capability_id: str,
        provider_ref: str,
        arguments: dict[str, Any],
        *,
        request_id: str = "",
        run_id: str | None = None,
        job_id: str | None = None,
        cancel_check: CancelCheck | None = None,
        progress: ProgressCb | None = None,
    ) -> CapabilityResult | dict[str, Any]:
        if capability_id == "external.knowledge.assimilate":
            if self.assimilation_service is None:
                return CapabilityResult(
                    request_id=request_id or "",
                    capability_id=capability_id,
                    status=CapabilityStatus.FAILED,
                    error="assimilation_service unavailable",
                    provider_kind="module",
                    provider_ref=provider_ref,
                )
            try:
                out = run_assimilation_job(arguments, assimilation_service=self.assimilation_service)
                if self.observability is not None:
                    try:
                        self.observability.emit(
                            "external_capability",
                            "knowledge.assimilated",
                            payload={"capability_id": arguments.get("capability_id"), "ok": out.get("ok")},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                return CapabilityResult(
                    request_id=request_id or "",
                    capability_id=capability_id,
                    status=CapabilityStatus.COMPLETED if out.get("ok") else CapabilityStatus.FAILED,
                    output=normalize_capability_parts(summary="assimilation", structured_data=out),
                    provider_kind="module",
                    provider_ref=provider_ref,
                )
            except Exception as exc:  # noqa: BLE001
                return CapabilityResult(
                    request_id=request_id or "",
                    capability_id=capability_id,
                    status=CapabilityStatus.FAILED,
                    error=str(exc),
                    provider_kind="module",
                    provider_ref=provider_ref,
                )

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
                if job_id:
                    self.module_manager.register_job(module_id, job_id)
                managed = self.module_manager.get(module_id)
                inst = managed.instance if managed else None
                if inst is not None and hasattr(inst, "ensure_installed"):
                    result = inst.ensure_installed(progress=progress, cancel_check=cancel_check)
                else:
                    result = self.module_manager.ensure_installed(module_id)
                self._metric("external.modules.installed", {"module_id": module_id})
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
            finally:
                if job_id:
                    try:
                        self.module_manager.unregister_job(module_id, job_id)
                    except Exception:  # noqa: BLE001
                        pass

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
                job_id=job_id,
                cancel_check=cancel_check,
                progress=progress,
            )

        if capability_id in {"external.skills.search", "external.skills.load"}:
            return self._skills_capability(capability_id, arguments, request_id=request_id)

        module_id, operation = _split_ref(provider_ref, capability_id, arguments)
        args = dict(arguments)
        args.pop("operation", None)

        # Trading boundary — before ensure_ready / invoke (MarketSim remains authority).
        managed_pre = self.module_manager.get(module_id)
        flags = module_trading_flags(managed_pre)
        if self.catalog is not None and hasattr(self.catalog, "get"):
            defn = self.catalog.get(capability_id)
            if defn is not None:
                cat_flags = module_trading_flags(defn)
                flags = {
                    "marketsim_bypass_forbidden": flags["marketsim_bypass_forbidden"]
                    or cat_flags["marketsim_bypass_forbidden"],
                    "real_money_blocked": flags["real_money_blocked"] or cat_flags["real_money_blocked"],
                }
        rejected = enforce_trading_boundary(
            flags=flags,
            capability_id=capability_id,
            operation=operation,
            arguments=args,
            request_id=request_id,
            provider_kind="module",
            provider_ref=provider_ref,
        )
        if rejected is not None:
            self._metric(
                "external.failures",
                {"module_id": module_id, "capability_id": capability_id, "status": "TRADING_BOUNDARY"},
            )
            return rejected

        try:
            try:
                self.module_manager.ensure_ready(module_id)
            except ModuleManagerError:
                if hasattr(self.module_manager, "ensure_ready"):
                    raise
            if job_id:
                self.module_manager.register_job(module_id, job_id)

            # Prefer adapter invoke with cancel/progress when available.
            managed = self.module_manager.get(module_id)
            inst = managed.instance if managed else None
            adapter = getattr(inst, "_adapter", None) if inst is not None else None
            if adapter is not None and hasattr(adapter, "invoke") and (cancel_check or progress):
                try:
                    adapter.ensure_ready()
                except Exception:  # noqa: BLE001
                    pass
                result = adapter.invoke(operation, args, progress=progress, cancel_check=cancel_check)
            else:
                result = self.module_manager.execute(module_id, operation, args)
        except ModuleManagerError as exc:
            self._metric("external.failures", {"module_id": module_id, "capability_id": capability_id})
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
        finally:
            if job_id:
                try:
                    self.module_manager.unregister_job(module_id, job_id)
                except Exception:  # noqa: BLE001
                    pass

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
        output = annotate_research_only(output, flags)

        cap_result = CapabilityResult(
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
        self._metric(
            "external.invocations",
            {"module_id": module_id, "capability_id": capability_id, "status": status.value},
        )
        if status != CapabilityStatus.COMPLETED:
            self._metric(
                "external.failures",
                {"module_id": module_id, "capability_id": capability_id, "status": status.value},
            )

        observation_id = None
        try:
            if self.observation_store is not None and hasattr(self.observation_store, "record_execution"):
                obs, _effect = self.observation_store.record_execution(
                    request_id=request_id or capability_id,
                    capability_id=capability_id,
                    status=status.value,
                    side_effects=("READ",),
                    provider_kind="module",
                    provider_ref=provider_ref,
                    run_id=run_id,
                    job_id=job_id,
                    output={
                        "summary": output.get("summary"),
                        "artifact_refs": list(output.get("artifact_refs") or [])[:20],
                        "source_refs": list(output.get("source_refs") or [])[:20],
                        "metadata": {
                            "module_id": module_id,
                            "operation": operation,
                            "source_package": (output.get("metadata") or {}).get("source"),
                            "source_version": (output.get("metadata") or {}).get("version"),
                        },
                    },
                    error=result.error,
                    duration_ms=result.duration_ms,
                    metadata={"module_id": module_id, "external_fabric": True},
                    idempotency_key=(
                        f"ext:{module_id}:{capability_id}:{request_id}" if request_id else None
                    ),
                )
                observation_id = getattr(obs, "observation_id", None)
                if isinstance(cap_result.output, dict) and observation_id:
                    cap_result.output.setdefault("metadata", {})
                    cap_result.output["metadata"]["observation_id"] = observation_id
                if observation_id:
                    cap_result.telemetry = {
                        **dict(cap_result.telemetry or {}),
                        "observation_id": observation_id,
                        "receipt_id": observation_id,
                    }
        except Exception:  # noqa: BLE001 — observations must not fail tool result
            pass

        # Background assimilation — never blocks the capability result path beyond enqueue.
        try:
            meta = {}
            if self.catalog is not None and hasattr(self.catalog, "get"):
                defn = self.catalog.get(capability_id)
                if defn is not None:
                    meta = dict(getattr(defn, "metadata", None) or {})
            mode = resolve_assimilation_mode(meta, output)
            assim = queue_or_run_assimilation(
                mode=mode,
                capability_id=capability_id,
                module_id=module_id,
                request_id=request_id or "",
                run_id=run_id,
                job_id=job_id,
                output=output,
                status=status.value,
                job_runtime=self.job_runtime,
                assimilation_service=self.assimilation_service,
                evidence_service=self.evidence_service,
                observation_id=observation_id,
                observability=self.observability,
            )
            if isinstance(cap_result.output, dict):
                cap_result.output.setdefault("metadata", {})
                cap_result.output["metadata"]["assimilation"] = assim
                if assim.get("queued"):
                    parts = list(cap_result.output.get("parts") or [])
                    parts.append(
                        {
                            "kind": "PROGRESS",
                            "phase": "assimilation",
                            "message": "Knowledge ingestion queued",
                        }
                    )
                    cap_result.output["parts"] = parts
        except Exception:  # noqa: BLE001 — assimilation must not fail the tool result
            pass

        return cap_result

    def _skills_capability(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
    ) -> CapabilityResult:
        store = None
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
            self._metric("skills.indexed", {"count": store.count_skills()})
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
        self._metric("skills.loaded", {"skill_id": skill.get("skill_id")})
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

    def _metric(self, name: str, payload: dict[str, Any]) -> None:
        if self.observability is None:
            return
        try:
            self.observability.emit("external_capability", name, payload=payload)
        except Exception:  # noqa: BLE001
            pass


def _split_ref(provider_ref: str, capability_id: str, arguments: Mapping[str, Any]) -> tuple[str, str]:
    ref = (provider_ref or "").strip()
    if ":" in ref and not ref.startswith("external."):
        module_id, _, operation = ref.partition(":")
        if module_id and operation:
            return module_id, operation
    module_id = ref or capability_id.split(".", 1)[0]
    if module_id.startswith("external."):
        module_id = str(arguments.get("module_id") or capability_id.split(".")[0])
    operation = str(arguments.get("operation") or "")
    if not operation and "." in capability_id:
        operation = capability_id.rsplit(".", 1)[-1]
    if not operation:
        operation = "run"
    return module_id, operation
