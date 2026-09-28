"""SKILL_PACK adapter — import/index skills; no process."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..install import InstallationService
from ..skills import SkillImporter, load_skill_instructions
from ..types import ExternalFailureCode, ExternalRuntimeState, normalize_capability_parts
from .base import AdapterContext, CancelCheck, ProgressCb, forward_install_kwargs


class SkillPackAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self._state = ExternalRuntimeState.DISCOVERED
        self._install_root: str | None = ctx.install_root
        self._importer = SkillImporter()
        self._skills: list[dict[str, Any]] = []

    def runtime_state(self) -> ExternalRuntimeState:
        return self._state

    def ensure_installed(self, **kwargs: Any) -> dict[str, Any]:
        if self.ctx.data_root:
            service = InstallationService(Path(self.ctx.data_root))
            install_kwargs = forward_install_kwargs(self.ctx, kwargs)
            result = service.ensure_installed(
                module_id=self.ctx.module_id,
                config=self.config,
                **install_kwargs,
            )
            self._install_root = result.install_root
            store = install_kwargs.get("store") or self.ctx.store
            activate = bool(kwargs.get("activate", True))
            if store is not None:
                store.add_version(
                    version_id=result.version_id,
                    module_id=self.ctx.module_id,
                    install_root=result.install_root,
                    source_ref=result.source_ref,
                    resolved_commit=result.resolved_commit,
                    content_hash=result.content_hash,
                    install_strategies=result.strategies,
                    dependency_versions=result.dependency_versions,
                    activate=activate,
                    adapter="SKILL_PACK",
                    name=self.ctx.module_id,
                )
            install_info = result.public_dict()
        else:
            install_info = {"install_root": self._install_root}
        indexed = self._index_skills()
        self._state = ExternalRuntimeState.INSTALLED
        return {**install_info, "skills_indexed": indexed}

    def start(self) -> dict[str, Any]:
        # Enable/activate metadata — no process.
        if not self._skills:
            self._index_skills()
        self._state = ExternalRuntimeState.READY
        if self.ctx.store is not None:
            for skill in self._skills:
                self.ctx.store.set_skill_enabled(skill["skill_id"], True)
            self.ctx.store.set_runtime_state(self.ctx.module_id, ExternalRuntimeState.READY.value, desired_state="ENABLED")
        return {"status": "READY", "skills": len(self._skills)}

    def stop(self) -> dict[str, Any]:
        if self.ctx.store is not None:
            for skill in self._skills:
                self.ctx.store.set_skill_enabled(skill["skill_id"], False)
            self.ctx.store.set_runtime_state(self.ctx.module_id, ExternalRuntimeState.DISABLED.value, desired_state="DISABLED")
        self._state = ExternalRuntimeState.DISABLED
        return {"status": "DISABLED"}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        if self._state in {ExternalRuntimeState.READY, ExternalRuntimeState.INSTALLED}:
            if not self._skills:
                self._index_skills()
            self._state = ExternalRuntimeState.READY
            return {"ready": True, "skills": len(self._skills)}
        installed = self.ensure_installed()
        self.start()
        return {"ready": True, **installed}

    def health(self) -> ModuleHealth:
        # Report truthful lifecycle status — DISCOVERED/DISABLED are not ERROR.
        if self._state == ExternalRuntimeState.READY:
            status = ModuleStatus.READY
        elif self._state == ExternalRuntimeState.INSTALLED:
            status = ModuleStatus.INSTALLED
        elif self._state == ExternalRuntimeState.DISABLED:
            status = ModuleStatus.DISABLED
        elif self._state == ExternalRuntimeState.FAILED:
            status = ModuleStatus.FAILED
        else:
            status = ModuleStatus.DISCOVERED
        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=status,
            detail=f"skills={len(self._skills)}",
            telemetry={"runtime_state": self._state.value, "adapter": "SKILL_PACK"},
        )

    def logs(self, *, limit: int = 200) -> list[str]:
        return [f"skills_indexed={len(self._skills)}"][:limit]

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        self.ensure_ready()
        if operation in {"list", "search"}:
            query = str(arguments.get("query") or "").strip() or None
            skills = self._skills
            if query:
                q = query.lower()
                skills = [
                    s
                    for s in skills
                    if q in s.get("name", "").lower()
                    or q in (s.get("description") or "").lower()
                    or q in (s.get("trigger_description") or "").lower()
                ]
            limit = max(1, min(int(arguments.get("limit") or 20), 100))
            offset = max(0, int(arguments.get("offset") or 0))
            page = skills[offset : offset + limit]
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(
                    summary=f"{len(page)} skills",
                    structured_data={"skills": page, "total": len(skills), "offset": offset, "limit": limit},
                ),
            )
        if operation in {"load", "get"}:
            skill_id = str(arguments.get("skill_id") or arguments.get("name") or "")
            skill = self._find(skill_id)
            if skill is None:
                return ModuleResult(
                    module_id=self.ctx.module_id,
                    operation=operation,
                    status="FAILED",
                    error=ExternalFailureCode.CAPABILITY_NOT_FOUND.value,
                )
            instructions = load_skill_instructions(skill)
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(
                    summary=skill.get("name"),
                    structured_data={**skill, "instructions": instructions},
                    metadata={"on_demand": True},
                ),
            )
        if operation in {"enable", "disable"}:
            skill_id = str(arguments.get("skill_id") or "")
            enabled = operation == "enable"
            if self.ctx.store is not None and skill_id:
                updated = self.ctx.store.set_skill_enabled(skill_id, enabled)
                return ModuleResult(
                    module_id=self.ctx.module_id,
                    operation=operation,
                    status="COMPLETED",
                    output=normalize_capability_parts(summary=operation, structured_data=updated),
                )
        if operation in {"index", "refresh"}:
            n = self._index_skills()
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(summary=f"indexed {n}", structured_data={"count": n}),
            )
        return ModuleResult(
            module_id=self.ctx.module_id,
            operation=operation,
            status="REJECTED",
            error="unknown skill operation",
        )

    def _index_skills(self) -> int:
        root = Path(self._install_root or self.config.source.path or ".")
        globs = self.config.skill_roots or self.config.catalog_globs or ("**/SKILL.md",)
        # skill_roots may be directory names — convert to globs.
        patterns: list[str] = []
        for item in globs:
            if "*" in item or item.endswith(".md"):
                patterns.append(item)
            else:
                patterns.append(f"{item}/**/SKILL.md")
                patterns.append(f"{item}/SKILL.md")
        records = self._importer.import_tree(
            root,
            source_repo=self.config.source.source or None,
            source_ref=self.config.source.ref,
            module_id=self.ctx.module_id,
            globs=tuple(patterns) or ("**/SKILL.md",),
            catalog_only=False,
        )
        self._skills = [r.public_dict(include_instructions=False) for r in records]
        if self.ctx.store is not None:
            for record in records:
                self.ctx.store.upsert_skill(record.public_dict(include_instructions=False))
        return len(records)

    def _find(self, key: str) -> dict[str, Any] | None:
        key_l = key.lower()
        for skill in self._skills:
            if skill.get("skill_id") == key or skill.get("name", "").lower() == key_l:
                return skill
        if self.ctx.store is not None:
            found = self.ctx.store.get_skill(key)
            if found:
                return found
            for skill in self.ctx.store.search_skills(query=key, limit=5):
                if skill.get("name", "").lower() == key_l:
                    return skill
        return None
