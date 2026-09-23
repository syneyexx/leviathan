"""Atomic change plans + transactional workspace snapshots (U204–U205)."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .patch import PatchApplyError, apply_unified_diff


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChangeRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: str  # create | patch | delete | rewrite
    unified_diff: str | None = None
    content: str | None = None
    rationale: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "unified_diff": self.unified_diff,
            "content_len": len(self.content or ""),
            "rationale": self.rationale,
        }


@dataclass
class ChangePlan:
    plan_id: str
    goal: str
    affected_files: list[str]
    changes: list[FileChange]
    invariants: list[str] = field(default_factory=list)
    expected_tests: list[str] = field(default_factory=list)
    risk: ChangeRisk = ChangeRisk.LOW
    rollback_boundary: str = "workspace_snapshot"
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "affected_files": list(self.affected_files),
            "changes": [c.public_dict() for c in self.changes],
            "invariants": list(self.invariants),
            "expected_tests": list(self.expected_tests),
            "risk": self.risk.value,
            "rollback_boundary": self.rollback_boundary,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "plan_is_not_authorization": True,
                "failed_verification_restores_snapshot": True,
            },
        }


def build_change_plan(
    *,
    goal: str,
    changes: list[FileChange],
    invariants: list[str] | None = None,
    expected_tests: list[str] | None = None,
    risk: ChangeRisk | str | None = None,
) -> ChangePlan:
    files = [c.path for c in changes]
    risk_enum = (
        risk
        if isinstance(risk, ChangeRisk)
        else ChangeRisk((risk or "low").lower())
        if risk
        else (ChangeRisk.HIGH if len(files) > 3 else ChangeRisk.MEDIUM if len(files) > 1 else ChangeRisk.LOW)
    )
    return ChangePlan(
        plan_id=f"chg_{uuid.uuid4().hex[:12]}",
        goal=goal,
        affected_files=files,
        changes=list(changes),
        invariants=list(invariants or ["workspace remains readable", "no path escape"]),
        expected_tests=list(expected_tests or []),
        risk=risk_enum,
        metadata={"change_count": len(changes)},
    )


@dataclass
class SnapshotResult:
    snapshot_id: str
    snapshot_dir: str
    file_hashes: dict[str, str]
    created_at: str
    restored: bool = False
    applied_files: list[str] = field(default_factory=list)
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_dir": self.snapshot_dir,
            "file_hashes": dict(self.file_hashes),
            "created_at": self.created_at,
            "restored": self.restored,
            "applied_files": list(self.applied_files),
            "error": self.error,
            "truth": {"exact_pre_change_tree_restorable": True},
        }


class WorkspaceTransaction:
    """Apply a ChangePlan under a snapshot; restore on failure (U205)."""

    def __init__(self, workspace_root: Path, *, snapshots_root: Path | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.snapshots_root = Path(snapshots_root or (self.workspace_root / ".leviathan_snapshots"))

    def snapshot_files(self, paths: list[str]) -> SnapshotResult:
        snap_id = f"snap_{uuid.uuid4().hex[:12]}"
        dest = self.snapshots_root / snap_id
        dest.mkdir(parents=True, exist_ok=True)
        hashes: dict[str, str] = {}
        for rel in paths:
            src = self._confine(rel)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.exists() and src.is_file():
                shutil.copy2(src, target)
                hashes[rel] = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
            else:
                # Record absence so restore can delete created files.
                marker = target.with_suffix(target.suffix + ".absent")
                marker.write_text("absent", encoding="utf-8")
                hashes[rel] = "absent"
        meta = {"paths": paths, "created_at": _utc_now()}
        (dest / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return SnapshotResult(
            snapshot_id=snap_id,
            snapshot_dir=str(dest),
            file_hashes=hashes,
            created_at=meta["created_at"],
        )

    def apply_plan(self, plan: ChangePlan, *, auto_rollback_on_error: bool = True) -> SnapshotResult:
        snap = self.snapshot_files(plan.affected_files)
        applied: list[str] = []
        try:
            for change in plan.changes:
                path = self._confine(change.path)
                if change.kind == "delete":
                    if path.exists():
                        path.unlink()
                    applied.append(change.path)
                    continue
                if change.kind == "patch":
                    if not change.unified_diff:
                        raise PatchApplyError("patch change missing unified_diff", reason="empty_diff")
                    original = path.read_text(encoding="utf-8") if path.exists() else ""
                    updated = apply_unified_diff(original, change.unified_diff)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(updated, encoding="utf-8")
                    applied.append(change.path)
                    continue
                # create / rewrite
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(change.content or "", encoding="utf-8")
                applied.append(change.path)
            snap.applied_files = applied
            return snap
        except Exception as exc:  # noqa: BLE001
            snap.error = str(exc)
            snap.applied_files = applied
            if auto_rollback_on_error:
                self.restore(snap)
                snap.restored = True
            raise

    def restore(self, snapshot: SnapshotResult) -> SnapshotResult:
        dest = Path(snapshot.snapshot_dir)
        for rel, digest in snapshot.file_hashes.items():
            target = self._confine(rel)
            backup = dest / rel
            absent = backup.with_suffix(backup.suffix + ".absent")
            if digest == "absent" or absent.exists():
                if target.exists():
                    target.unlink()
                continue
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
        snapshot.restored = True
        return snapshot

    def _confine(self, rel: str) -> Path:
        candidate = (self.workspace_root / rel).resolve()
        if not str(candidate).startswith(str(self.workspace_root)):
            raise PermissionError(f"Path escape blocked: {rel}")
        return candidate
