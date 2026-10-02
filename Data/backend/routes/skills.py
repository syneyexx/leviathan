"""Skills HTTP routes — installed + catalog skills over ExternalCapabilityStore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityStatus
from Data.modules.execution.http_status import gateway_status_http_code


class SkillEnableRequest(BaseModel):
    enabled: bool = True


class SkillExecuteRequest(BaseModel):
    """Invoke a required capability mapped from the skill — never arbitrary shell."""

    capability_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    requested_by: str = "skills_page"
    trace_id: str | None = None
    idempotency_key: str | None = None


def build_skills_router(
    *,
    external_store: Any,
    observability: Any = None,
    capability_catalog: Any = None,
    execution_gateway: Any = None,
    module_manager: Any = None,
) -> APIRouter:
    router = APIRouter(tags=["skills"])

    def _totals() -> dict[str, Any]:
        if hasattr(external_store, "skill_totals_projection"):
            return external_store.skill_totals_projection()
        installed = external_store.count_skills(catalog_only=False)
        catalog = external_store.count_skills(catalog_only=True)
        return {
            "installed": installed,
            "catalog": catalog,
            "total": installed + catalog,
            "available": installed,
            "external_packs": None,
            "tools": None,
            "issues": None,
            "agent_skills": None,
            "updates_available": None,
            "classifications": {
                "all": installed + catalog,
                "core": installed,
                "external": catalog,
                "tools": None,
                "agent": None,
            },
            "truth": {
                "agent_skills_unmeasured": True,
                "updates_available_unmeasured": True,
            },
        }

    def _enrich_skill(skill: dict[str, Any], *, include_instructions: bool = False) -> dict[str, Any]:
        from Data.modules.module_manager.external.skills import (
            load_skill_instructions,
            parse_skill_declarations,
        )

        out = dict(skill)
        declarations = parse_skill_declarations(skill)
        out["declarations"] = declarations
        out["compatibility"] = _compatibility_projection(skill)
        out["classification"] = _classify_skill(skill)
        if include_instructions:
            out["instructions"] = load_skill_instructions(skill)
        return out

    def _classify_skill(skill: dict[str, Any]) -> str:
        if skill.get("catalog_only"):
            return "external"
        scripts = skill.get("script_refs") or []
        if isinstance(scripts, list) and len(scripts) > 0:
            return "tools"
        return "core"

    def _module_snapshot(module_id: str) -> dict[str, Any] | None:
        if module_manager is None:
            return None
        try:
            if hasattr(module_manager, "get_module"):
                snap = module_manager.get_module(str(module_id))
                if isinstance(snap, dict):
                    return snap
            if hasattr(module_manager, "get"):
                managed = module_manager.get(str(module_id))
                if managed is not None and hasattr(managed, "public_dict"):
                    return managed.public_dict()
            if hasattr(module_manager, "snapshot"):
                snap_all = module_manager.snapshot()
            elif hasattr(module_manager, "public_snapshot"):
                snap_all = module_manager.public_snapshot()
            else:
                return None
            modules = (snap_all.get("modules") if isinstance(snap_all, dict) else None) or []
            for row in modules:
                mid = (row.get("manifest") or {}).get("module_id") or row.get("module_id")
                if mid == module_id:
                    return row if isinstance(row, dict) else None
        except Exception:  # noqa: BLE001
            return None
        return None

    def _compatibility_projection(skill: dict[str, Any]) -> dict[str, Any]:
        required = [str(x) for x in (skill.get("required_capabilities") or []) if str(x).strip()]
        if not required:
            return {
                "status": "UNMEASURED",
                "reason": "No required_capabilities declared on skill record",
                "capabilities": [],
                "agents": [],
                "runtimes": [],
            }
        if capability_catalog is None and execution_gateway is None:
            return {
                "status": "UNMEASURED",
                "reason": "Capability catalog unavailable",
                "capabilities": [{"id": c, "status": "UNMEASURED"} for c in required],
                "agents": [],
                "runtimes": [],
            }

        known: set[str] = set()
        available_map: dict[str, bool] = {}
        enabled_map: dict[str, bool] = {}
        if capability_catalog is not None:
            try:
                for item in list(capability_catalog.search("", limit=500) or []):
                    cid = str(getattr(item, "id", "") or "")
                    if cid:
                        known.add(cid)
                        available_map[cid] = bool(getattr(item, "available", True))
                        enabled_map[cid] = bool(getattr(item, "enabled", True))
            except Exception:  # noqa: BLE001
                known = set()
        if not known and execution_gateway is not None:
            try:
                for item in list(execution_gateway.list_capabilities() or [])[:500]:
                    cid = str(getattr(item, "id", "") or getattr(item, "capability_id", "") or "")
                    if cid:
                        known.add(cid)
                        available_map[cid] = bool(getattr(item, "available", True))
                        enabled_map[cid] = bool(getattr(item, "enabled", True))
            except Exception:  # noqa: BLE001
                known = set()

        cap_rows = []
        present = 0
        for cap_id in required:
            ok = cap_id in known
            if ok:
                present += 1
            row_status = "COMPATIBLE" if ok else "INCOMPATIBLE"
            if ok and (not available_map.get(cap_id, True) or not enabled_map.get(cap_id, True)):
                row_status = "INCOMPATIBLE"
                present -= 1
            cap_rows.append(
                {
                    "id": cap_id,
                    "status": row_status,
                    "available": available_map.get(cap_id) if ok else False,
                    "enabled": enabled_map.get(cap_id) if ok else False,
                }
            )
        if present == len(required) and present > 0:
            status = "COMPATIBLE"
        elif present == 0:
            status = "INCOMPATIBLE"
        else:
            status = "PARTIAL"

        # Runtimes: derive from owning module adapter when module_manager is available.
        runtimes: list[dict[str, Any]] = []
        module_id = skill.get("module_id")
        if module_id:
            snap = _module_snapshot(str(module_id))
            if isinstance(snap, dict):
                adapter = (
                    (snap.get("adapter") or "")
                    or ((snap.get("manifest") or {}).get("external") or {}).get("adapter")
                    or ""
                )
                status_s = str(snap.get("status") or snap.get("runtime_state") or "")
                runtimes.append(
                    {
                        "id": str(module_id),
                        "adapter": str(adapter) if adapter else None,
                        "status": "Required",
                        "module_status": status_s or None,
                    }
                )
            else:
                runtimes.append(
                    {
                        "id": str(module_id),
                        "adapter": None,
                        "status": "Required",
                        "module_status": None,
                    }
                )

        return {
            "status": status,
            "reason": None,
            "capabilities": cap_rows,
            "agents": [],  # No agent-policy ranking surface on this API.
            "runtimes": runtimes,
            "truth": {
                "recommended_agents_unsupported": True,
                "compatibility_from_required_capabilities": True,
                "partial_or_unmeasured_is_not_pass": True,
            },
        }

    def _test_skill(skill: dict[str, Any]) -> dict[str, Any]:
        """Fail-closed skill readiness test.

        COMPATIBLE = pass. PARTIAL / UNMEASURED / INCOMPATIBLE = not pass.
        ModuleManager required but unavailable → not pass.
        Disabled/unavailable capability → not pass.
        Unhealthy module → not pass for execution-readiness.
        Never ok=true from incomplete evidence.
        """
        from Data.modules.module_manager.external.skills import load_skill_instructions

        checks: list[dict[str, Any]] = []
        ok = True

        def add(name: str, passed: bool, detail: str) -> None:
            nonlocal ok
            if not passed:
                ok = False
            checks.append({"name": name, "passed": passed, "detail": detail})

        add("record_present", True, f"skill_id={skill.get('skill_id')}")
        add(
            "name_present",
            bool(str(skill.get("name") or "").strip()),
            str(skill.get("name") or ""),
        )
        add(
            "content_hash_present",
            bool(str(skill.get("content_hash") or "").strip()),
            str(skill.get("content_hash") or "")[:16],
        )
        add(
            "skill_enabled",
            bool(skill.get("enabled")),
            "enabled" if skill.get("enabled") else "disabled — not execution-ready",
        )

        catalog_only = bool(skill.get("catalog_only"))
        source_path = str(skill.get("source_path") or "").strip()
        if catalog_only:
            add(
                "catalog_metadata",
                True,
                "Catalog-only entry — instructions are not prompt-injected",
            )
            # Catalog-only is not execution-ready.
            add(
                "execution_readiness",
                False,
                "Catalog-only skill has no executable surface",
            )
        else:
            path_ok = bool(source_path) and Path(source_path).is_file()
            add(
                "instruction_artifact_resolvable",
                path_ok,
                source_path or "missing source_path",
            )
            if path_ok:
                body = load_skill_instructions(skill)
                add(
                    "instructions_loadable",
                    bool(body.strip()),
                    f"{len(body)} chars" if body else "empty body",
                )

        required = [str(x) for x in (skill.get("required_capabilities") or []) if str(x).strip()]
        if not required:
            # Incomplete evidence for execution-readiness — not a pass.
            add(
                "required_capabilities",
                False,
                "none declared — UNMEASURED is not pass",
            )
        else:
            compat = _compatibility_projection(skill)
            compat_status = str(compat.get("status") or "UNMEASURED").upper()
            # Fail-closed: only COMPATIBLE passes.
            add(
                "required_capabilities",
                compat_status == "COMPATIBLE",
                f"status={compat_status} (COMPATIBLE required; PARTIAL/UNMEASURED/INCOMPATIBLE != pass)",
            )
            for cap_row in compat.get("capabilities") or []:
                if not isinstance(cap_row, dict):
                    continue
                if cap_row.get("available") is False or cap_row.get("enabled") is False:
                    add(
                        f"capability_{cap_row.get('id')}_enabled_available",
                        False,
                        "disabled or unavailable capability is not pass",
                    )

        module_id = skill.get("module_id")
        if module_id:
            if module_manager is None:
                add(
                    "owning_module_available",
                    False,
                    f"{module_id} — ModuleManager required but unavailable (not pass)",
                )
            else:
                snap = _module_snapshot(str(module_id))
                found = snap is not None
                add("owning_module_available", found, str(module_id))
                if found and isinstance(snap, dict):
                    module_status = str(snap.get("status") or snap.get("runtime_state") or "").upper()
                    healthy = module_status in {
                        "READY",
                        "RUNNING",
                        "INSTALLED",
                        "INITIALIZED",
                        "BUSY",
                        "EXECUTING",
                        "DEGRADED",
                    }
                    add(
                        "owning_module_healthy",
                        healthy,
                        f"module_status={module_status or 'UNMEASURED'}",
                    )
                    # Prefer live health when present on snapshot.
                    health = snap.get("health") if isinstance(snap.get("health"), dict) else None
                    if health is not None:
                        h_status = str(health.get("status") or "").upper()
                        freshness = str(health.get("freshness") or snap.get("health_freshness") or "")
                        health_ok = h_status not in {"ERROR", "FAILED", "UNHEALTHY", "STALE"} and freshness != "UNMEASURED"
                        if freshness == "UNMEASURED":
                            health_ok = False
                        add(
                            "owning_module_health_evidence",
                            health_ok,
                            f"health={h_status or 'UNMEASURED'} freshness={freshness or 'UNMEASURED'}",
                        )
        else:
            add("owning_module_available", True, "no module_id on record")

        return {
            "ok": ok,
            "skill_id": skill.get("skill_id"),
            "checks": checks,
            "truth": {
                "not_mocked_pass": True,
                "skills_are_not_shell_authority": True,
                "fail_closed": True,
                "compatible_only_is_pass": True,
                "unmeasured_is_not_pass": True,
                "incomplete_evidence_is_not_ok": True,
            },
        }

    @router.get("/api/skills")
    def list_skills(
        query: str | None = None,
        include_catalog: bool = Query(default=False),
        enabled_only: bool = Query(default=False),
        classification: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        class_key = (classification or "").strip().lower() or None
        if class_key in {None, "all"}:
            # "all" always spans installed + catalog metadata (no instruction bodies).
            effective_include = True if class_key == "all" else include_catalog
            effective_class = None
        elif class_key in {"external", "catalog"}:
            effective_include = True
            effective_class = "external"
        elif class_key == "tools":
            effective_include = True if include_catalog else include_catalog
            # Tools across installed+catalog when include_catalog is true (default for UI).
            effective_include = include_catalog if include_catalog else True
            effective_class = "tools"
        else:
            effective_include = include_catalog
            effective_class = class_key

        rows = external_store.search_skills(
            query=query,
            enabled_only=enabled_only,
            include_catalog=effective_include,
            classification=effective_class,
            limit=limit,
            offset=offset,
        )
        enriched = [_enrich_skill(r, include_instructions=False) for r in rows]
        for row in enriched:
            row.pop("instructions", None)
        return {
            "skills": enriched,
            "count": len(enriched),
            "offset": offset,
            "limit": limit,
            "totals": _totals(),
            "truth": {
                "skills_are_not_shell_authority": True,
                "instructions_load_on_demand": True,
                "catalog_not_prompt_injected": True,
            },
        }

    @router.get("/api/skills/{skill_id}")
    def get_skill(skill_id: str, include_instructions: bool = Query(default=False)) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        skill = external_store.get_skill(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        return {"skill": _enrich_skill(skill, include_instructions=include_instructions)}

    @router.post("/api/skills/{skill_id}/enable")
    def enable_skill(skill_id: str, payload: SkillEnableRequest | None = None) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        payload = payload or SkillEnableRequest(enabled=True)
        updated = external_store.set_skill_enabled(skill_id, bool(payload.enabled))
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        if observability is not None:
            observability.emit(
                "external_capability",
                "skills.enabled" if payload.enabled else "skills.disabled",
                payload={"skill_id": skill_id},
            )
        return {"skill": _enrich_skill(updated, include_instructions=False)}

    @router.post("/api/skills/{skill_id}/test")
    def test_skill(skill_id: str) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        skill = external_store.get_skill(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        result = _test_skill(skill)
        if observability is not None:
            observability.emit(
                "external_capability",
                "skills.tested",
                payload={"skill_id": skill_id, "ok": result.get("ok")},
            )
        return {"result": result, "skill": _enrich_skill(skill, include_instructions=False)}

    @router.post("/api/skills/{skill_id}/execute")
    def execute_skill(skill_id: str, payload: SkillExecuteRequest | None = None) -> dict:
        """Execute only via a declared required capability through ExecutionGateway.

        Instruction-only skills are rejected — skills are not shell authority.
        HTTP 200 must not mean success when result is REJECTED/FAILED/TIMEOUT/CANCELLED.
        """
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        skill = external_store.get_skill(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        if not skill.get("enabled"):
            raise HTTPException(status_code=403, detail="Skill is disabled")
        if skill.get("catalog_only"):
            raise HTTPException(
                status_code=422,
                detail="Catalog-only skill has no executable capability surface",
            )
        payload = payload or SkillExecuteRequest()
        required = [str(x) for x in (skill.get("required_capabilities") or []) if str(x).strip()]
        capability_id = (payload.capability_id or "").strip() or (required[0] if required else "")
        if not capability_id:
            raise HTTPException(
                status_code=422,
                detail="Instruction-only skill; no executable capability",
            )
        if required and capability_id not in required:
            raise HTTPException(
                status_code=422,
                detail=f"Capability {capability_id} is not declared on this skill",
            )
        if execution_gateway is None:
            raise HTTPException(status_code=503, detail="Execution gateway unavailable")
        if capability_catalog is not None:
            if capability_id not in capability_catalog:
                raise HTTPException(status_code=404, detail=f"Unknown capability: {capability_id}")
            definition = capability_catalog.get(capability_id)
            if definition is not None:
                if not bool(getattr(definition, "enabled", True)):
                    raise HTTPException(status_code=403, detail=f"Capability disabled: {capability_id}")
                if not bool(getattr(definition, "available", True)):
                    raise HTTPException(
                        status_code=503,
                        detail=f"Capability unavailable: {capability_id}",
                    )

        from Data.modules.execution import CapabilityRequest

        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=dict(payload.arguments or {}),
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                job_id=payload.job_id,
                requested_by=payload.requested_by or "skills_page",
                trace_id=payload.trace_id,
                idempotency_key=payload.idempotency_key,
            )
        )
        status_value = getattr(getattr(result, "status", None), "value", None) or str(
            getattr(result, "status", "")
        )
        if observability is not None:
            observability.emit(
                "external_capability",
                "skills.execute",
                payload={
                    "skill_id": skill_id,
                    "capability_id": capability_id,
                    "status": status_value,
                    "request_id": getattr(result, "request_id", None),
                },
            )
        body = {
            "skill_id": skill_id,
            "capability_id": capability_id,
            "result": result.public_dict() if hasattr(result, "public_dict") else {"status": status_value},
            "truth": {
                "skills_are_not_shell_authority": True,
                "execution_via_gateway": True,
                "http_200_is_not_rejected_or_failed": True,
                "provenance_via_gateway_receipt": True,
            },
        }
        # Align with capabilities route: non-success gateway statuses are not HTTP 200.
        if isinstance(getattr(result, "status", None), CapabilityStatus):
            status_enum = result.status
        else:
            try:
                status_enum = CapabilityStatus(str(status_value).upper())
            except ValueError:
                status_enum = None
        if status_enum is not None:
            reason = (getattr(result, "telemetry", None) or {}).get("reason")
            code = gateway_status_http_code(
                status_enum, reject_reason=str(reason) if reason else None
            )
            if code is not None:
                if code == 202:
                    return body
                raise HTTPException(status_code=code, detail=body)
        return body

    return router
