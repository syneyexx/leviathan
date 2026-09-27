"""Version update / activate / rollback for external capability modules.

Does not mutate the active runtime underneath a running execution.
Install → verify → activate; old versions remain until no active jobs depend on them.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .install import InstallationService, InstallError
from .types import ExternalFailureCode, ExternalRuntimeState


class VersionError(RuntimeError):
    def __init__(self, code: ExternalFailureCode, message: str) -> None:
        code_value = code.value if hasattr(code, "value") else str(code)
        super().__init__(f"{code_value}: {message}")
        self.code = code
        self.message = message


def check_update(
    *,
    module_id: str,
    config: Any,
    store: Any,
) -> dict[str, Any]:
    """Compare configured desired ref against active/installed versions (no silent upgrade)."""
    active = store.get_active_version(module_id) if store is not None else None
    versions = store.list_versions(module_id) if store is not None else []
    desired_ref = getattr(getattr(config, "source", None), "ref", None) or "main"
    active_ref = (active or {}).get("source_ref")
    active_commit = (active or {}).get("resolved_commit")
    newer_installed = [
        v
        for v in versions
        if v.get("version_id") != (active or {}).get("version_id")
        and v.get("status") in {"INSTALLED", "ACTIVE"}
        and v.get("source_ref") == desired_ref
        and v.get("version_id") != (active or {}).get("version_id")
    ]
    update_available = False
    reason = "current"
    if active is None:
        update_available = True
        reason = "not_installed"
    elif active_ref and desired_ref and active_ref != desired_ref:
        update_available = True
        reason = "ref_mismatch"
    elif newer_installed:
        update_available = True
        reason = "inactive_version_present"
    return {
        "module_id": module_id,
        "desired_ref": desired_ref,
        "active_version_id": (active or {}).get("version_id"),
        "active_source_ref": active_ref,
        "active_resolved_commit": active_commit,
        "installed_versions": len(versions),
        "update_available": update_available,
        "reason": reason,
        "candidate_version_ids": [v.get("version_id") for v in newer_installed],
        "truth": {
            "check_update_does_not_install": True,
            "network_remote_compare_not_required": True,
        },
    }


def install_version(
    *,
    module_id: str,
    config: Any,
    data_root: str | Path,
    store: Any,
    ref: str | None = None,
    activate: bool = False,
    active_jobs: list[str] | None = None,
    progress: Any = None,
    cancel_check: Any = None,
) -> dict[str, Any]:
    """Install a pinned version without mutating the active runtime by default."""
    if activate and active_jobs:
        raise VersionError(
            ExternalFailureCode.UPDATE_BLOCKED_ACTIVE,
            f"cannot activate while jobs active: {', '.join(active_jobs[:5])}",
        )
    desired_ref = ref or getattr(getattr(config, "source", None), "ref", None) or "main"
    new_source = replace(config.source, ref=desired_ref)
    new_config = replace(config, source=new_source)
    service = InstallationService(Path(data_root))
    result = service.ensure_installed(
        module_id=module_id,
        config=new_config,
        progress=progress,
        cancel_check=cancel_check,
    )
    if store is not None:
        store.add_version(
            version_id=result.version_id,
            module_id=module_id,
            install_root=result.install_root,
            source_ref=result.source_ref or desired_ref,
            resolved_commit=result.resolved_commit,
            content_hash=result.content_hash,
            install_strategies=result.strategies,
            dependency_versions=result.dependency_versions,
            activate=activate,
            status="ACTIVE" if activate else "INSTALLED",
        )
        if not activate:
            store.set_runtime_state(module_id, ExternalRuntimeState.INSTALLED.value)
    out = result.public_dict()
    out["activated"] = bool(activate)
    out["desired_ref"] = desired_ref
    return out


def activate_version(
    *,
    module_id: str,
    version_id: str,
    store: Any,
    active_jobs: list[str] | None = None,
    adapter: Any = None,
) -> dict[str, Any]:
    """Switch active version only when no jobs depend on the current runtime."""
    if active_jobs:
        raise VersionError(
            ExternalFailureCode.UPDATE_BLOCKED_ACTIVE,
            f"cannot activate while jobs active: {', '.join(active_jobs[:5])}",
        )
    if store is None:
        raise VersionError(ExternalFailureCode.NOT_INSTALLED, "store unavailable")
    version = store.get_version(version_id)
    if version is None or version.get("module_id") != module_id:
        raise VersionError(ExternalFailureCode.NOT_INSTALLED, f"unknown version: {version_id}")
    root = Path(str(version.get("install_root") or ""))
    if not root.exists():
        raise VersionError(ExternalFailureCode.NOT_INSTALLED, f"install root missing: {root}")
    # Demote previous active markers.
    for v in store.list_versions(module_id):
        if v.get("version_id") != version_id and v.get("status") == "ACTIVE":
            # best-effort status demotion via re-add metadata path
            store.add_version(
                version_id=v["version_id"],
                module_id=module_id,
                install_root=v["install_root"],
                source_ref=v.get("source_ref"),
                resolved_commit=v.get("resolved_commit"),
                content_hash=v.get("content_hash"),
                install_strategies=v.get("install_strategies") or [],
                dependency_versions=v.get("dependency_versions") or {},
                status="INSTALLED",
                activate=False,
                metadata=v.get("metadata") or {},
            )
    store.activate_version(module_id, version_id)
    if adapter is not None and hasattr(adapter, "_install_root"):
        adapter._install_root = version["install_root"]
    return {
        "module_id": module_id,
        "version_id": version_id,
        "install_root": version["install_root"],
        "status": "ACTIVE",
        "truth": {"active_runtime_not_mutated_under_jobs": True},
    }


def rollback_version(
    *,
    module_id: str,
    store: Any,
    active_jobs: list[str] | None = None,
    adapter: Any = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    """Activate a previous installed version (explicit id or previous-by-install time)."""
    if store is None:
        raise VersionError(ExternalFailureCode.NOT_INSTALLED, "store unavailable")
    versions = store.list_versions(module_id)
    if not versions:
        raise VersionError(ExternalFailureCode.NOT_INSTALLED, "no versions installed")
    active = store.get_active_version(module_id)
    target_id = version_id
    if target_id is None:
        for v in versions:
            if active and v.get("version_id") == active.get("version_id"):
                continue
            target_id = v.get("version_id")
            break
    if not target_id:
        raise VersionError(ExternalFailureCode.NOT_INSTALLED, "no rollback candidate")
    return activate_version(
        module_id=module_id,
        version_id=str(target_id),
        store=store,
        active_jobs=active_jobs,
        adapter=adapter,
    )
