"""CATALOG_SOURCE adapter — bounded index/search; materialize skills on demand."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..install import InstallationService
from ..skills import SkillImporter
from ..types import ExternalFailureCode, ExternalRuntimeState, normalize_capability_parts
from .base import AdapterContext, CancelCheck, ProgressCb
from .skill_pack import SkillPackAdapter


class CatalogSourceAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self._state = ExternalRuntimeState.DISCOVERED
        self._install_root: str | None = ctx.install_root
        self._importer = SkillImporter()
        self._entries: list[dict[str, Any]] = []

    def runtime_state(self) -> ExternalRuntimeState:
        return self._state

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]:
        if self.ctx.data_root:
            result = InstallationService(Path(self.ctx.data_root)).ensure_installed(
                module_id=self.ctx.module_id,
                config=self.config,
                progress=progress,
                cancel_check=cancel_check,
            )
            self._install_root = result.install_root
            if self.ctx.store is not None:
                self.ctx.store.add_version(
                    version_id=result.version_id,
                    module_id=self.ctx.module_id,
                    install_root=result.install_root,
                    source_ref=result.source_ref,
                    resolved_commit=result.resolved_commit,
                    content_hash=result.content_hash,
                    install_strategies=result.strategies,
                    activate=True,
                )
            info = result.public_dict()
        else:
            info = {"install_root": self._install_root}
        count = self.refresh_index()
        self._state = ExternalRuntimeState.INSTALLED
        return {**info, "catalog_entries": count}

    def start(self) -> dict[str, Any]:
        if not self._entries:
            self.refresh_index()
        self._state = ExternalRuntimeState.READY
        return {"status": "READY", "entries": len(self._entries)}

    def stop(self) -> dict[str, Any]:
        self._state = ExternalRuntimeState.STOPPED
        return {"status": "STOPPED"}

    def restart(self) -> dict[str, Any]:
        self.refresh_index()
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        if not self._entries:
            if self._install_root or self.config.source.path:
                self.refresh_index()
            else:
                self.ensure_installed()
        self._state = ExternalRuntimeState.READY
        return {"ready": True, "entries": len(self._entries)}

    def health(self) -> ModuleHealth:
        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=ModuleStatus.READY if self._state != ExternalRuntimeState.FAILED else ModuleStatus.ERROR,
            detail=f"catalog_entries={len(self._entries)}",
            telemetry={"runtime_state": self._state.value, "adapter": "CATALOG_SOURCE"},
        )

    def logs(self, *, limit: int = 200) -> list[str]:
        return [f"catalog_entries={len(self._entries)}"][:limit]

    def refresh_index(self) -> int:
        root = Path(self._install_root or self.config.source.path or ".")
        records = self._importer.import_catalog_index(
            root,
            source_repo=self.config.source.source or None,
            module_id=self.ctx.module_id,
            limit=5000,
        )
        self._entries = [r.public_dict(include_instructions=False) for r in records]
        if self.ctx.store is not None:
            for record in records:
                self.ctx.store.upsert_skill(record.public_dict(include_instructions=False))
        return len(records)

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        self.ensure_ready()
        if operation in {"search", "list"}:
            query = str(arguments.get("query") or "").strip().lower()
            limit = max(1, min(int(arguments.get("limit") or 25), 100))
            offset = max(0, int(arguments.get("offset") or 0))
            items = self._entries
            if query:
                items = [
                    e
                    for e in items
                    if query in e.get("name", "").lower()
                    or query in (e.get("description") or "").lower()
                ]
            page = items[offset : offset + limit]
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(
                    summary=f"{len(page)} of {len(items)} catalog skills",
                    structured_data={"skills": page, "total": len(items), "offset": offset, "limit": limit},
                    metadata={"bounded": True, "not_prompt_injected": True},
                ),
            )
        if operation in {"refresh", "index"}:
            n = self.refresh_index()
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(summary=f"refreshed {n}", structured_data={"count": n}),
            )
        if operation in {"materialize", "install_skill"}:
            # Materialize means: locate catalog entry and import as enabled non-catalog skill if SKILL.md exists.
            skill_id = str(arguments.get("skill_id") or arguments.get("name") or "")
            entry = next((e for e in self._entries if e.get("skill_id") == skill_id or e.get("name") == skill_id), None)
            if entry is None:
                return ModuleResult(
                    module_id=self.ctx.module_id,
                    operation=operation,
                    status="FAILED",
                    error=ExternalFailureCode.CAPABILITY_NOT_FOUND.value,
                )
            # If source_path points at a real SKILL.md, re-import via SkillPack.
            path = entry.get("source_path")
            if path and Path(path).name == "SKILL.md":
                pack = SkillPackAdapter(self.ctx)
                pack._install_root = str(Path(path).parent)  # type: ignore[attr-defined]
                pack.start()
                loaded = pack.invoke("load", {"skill_id": entry.get("name") or skill_id})
                if self.ctx.store is not None:
                    self.ctx.store.set_skill_enabled(entry["skill_id"], True)
                return loaded
            # Catalog link-only entry — mark enabled metadata; actual clone is a separate install job.
            if self.ctx.store is not None:
                updated = dict(entry)
                updated["catalog_only"] = False
                updated["enabled"] = True
                self.ctx.store.upsert_skill(updated)
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(
                    summary=f"materialized metadata for {entry.get('name')}",
                    structured_data=entry,
                    metadata={"requires_source_fetch": True},
                ),
            )
        return ModuleResult(
            module_id=self.ctx.module_id,
            operation=operation,
            status="REJECTED",
            error="unknown catalog operation",
        )
