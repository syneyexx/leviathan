"""Skills HTTP routes — installed + catalog skills over ExternalCapabilityStore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class SkillEnableRequest(BaseModel):
    enabled: bool = True


class SkillExecuteRequest(BaseModel):
    """Invoke a required capability mapped from the skill — never arbitrary shell."""

    capability_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


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
        if capability_catalog is not None:
            try:
                for item in list(capability_catalog.search("", limit=500) or []):
                    cid = str(getattr(item, "id", "") or "")
                    if cid:
                        known.add(cid)
            except Exception:  # noqa: BLE001
                known = set()
        if not known and execution_gateway is not None:
            try:
                for item in list(execution_gateway.list_capabilities() or [])[:500]:
                    cid = str(getattr(item, "id", "") or getattr(item, "capability_id", "") or "")
                    if cid:
                        known.add(cid)
            except Exception:  # noqa: BLE001
                known = set()

        cap_rows = []
        present = 0
        for cap_id in required:
            ok = cap_id in known
            if ok:
                present += 1
            cap_rows.append(
                {
                    "id": cap_id,
                    "status": "COMPATIBLE" if ok else "INCOMPATIBLE",
                }
            )
        if present == len(required):
            status = "COMPATIBLE"
        elif present == 0:
            status = "INCOMPATIBLE"
        else:
            status = "PARTIAL"

        # Runtimes: derive from owning module adapter when module_manager is available.
        runtimes: list[dict[str, Any]] = []
        module_id = skill.get("module_id")
        if module_id and module_manager is not None:
            try:
                snap = module_manager.get_module(str(module_id)) if hasattr(module_manager, "get_module") else None
                if snap is None and hasattr(module_manager, "snapshot"):
                    # Fallback: scan snapshot list.
                    modules = []
                    snap_all = module_manager.snapshot()
                    if isinstance(snap_all, dict):
                        modules = snap_all.get("modules") or []
                    for row in modules:
                        mid = (row.get("manifest") or {}).get("module_id") or row.get("module_id")
                        if mid == module_id:
                            snap = row
                            break
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
            except Exception:  # noqa: BLE001
                runtimes = []

        if not runtimes and module_id:
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
            },
        }

    def _test_skill(skill: dict[str, Any]) -> dict[str, Any]:
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

        catalog_only = bool(skill.get("catalog_only"))
        source_path = str(skill.get("source_path") or "").strip()
        if catalog_only:
            add(
                "catalog_metadata",
                True,
                "Catalog-only entry — instructions are not prompt-injected",
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
            add("required_capabilities", True, "none declared")
        else:
            compat = _compatibility_projection(skill)
            add(
                "required_capabilities",
                compat.get("status") in {"COMPATIBLE", "PARTIAL", "UNMEASURED"},
                f"status={compat.get('status')}",
            )
            if compat.get("status") == "INCOMPATIBLE":
                ok = False

        module_id = skill.get("module_id")
        if module_id and module_manager is not None:
            try:
                found = False
                if hasattr(module_manager, "get_module"):
                    found = module_manager.get_module(str(module_id)) is not None
                elif hasattr(module_manager, "snapshot"):
                    snap = module_manager.snapshot()
                    modules = (snap.get("modules") if isinstance(snap, dict) else None) or []
                    found = any(
                        ((m.get("manifest") or {}).get("module_id") or m.get("module_id")) == module_id
                        for m in modules
                    )
                add("owning_module_available", found, str(module_id))
            except Exception as exc:  # noqa: BLE001
                add("owning_module_available", False, str(exc))
        elif module_id:
            add("owning_module_available", True, f"{module_id} (module manager not wired — presence unchecked)")
        else:
            add("owning_module_available", True, "no module_id on record")

        return {
            "ok": ok,
            "skill_id": skill.get("skill_id"),
            "checks": checks,
            "truth": {
                "not_mocked_pass": True,
                "skills_are_not_shell_authority": True,
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
        """
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        skill = external_store.get_skill(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
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
        if capability_catalog is not None and capability_id not in capability_catalog:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {capability_id}")

        from Data.modules.execution import CapabilityRequest

        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=dict(payload.arguments or {}),
                requested_by="skills_page",
            )
        )
        if observability is not None:
            observability.emit(
                "external_capability",
                "skills.execute",
                payload={
                    "skill_id": skill_id,
                    "capability_id": capability_id,
                    "status": getattr(getattr(result, "status", None), "value", None),
                },
            )
        status_value = getattr(getattr(result, "status", None), "value", None) or str(
            getattr(result, "status", "")
        )
        return {
            "skill_id": skill_id,
            "capability_id": capability_id,
            "result": result.public_dict() if hasattr(result, "public_dict") else {"status": status_value},
            "truth": {
                "skills_are_not_shell_authority": True,
                "execution_via_gateway": True,
            },
        }

    return router
