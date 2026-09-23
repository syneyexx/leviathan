"""Replaceable sandbox adapters — fixture only in Wave 10 (U348).

Real OS containers remain UNMEASURED; this proves constraint enforcement shape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SandboxLimits:
    cpu_seconds: float = 5.0
    memory_mb: int = 512
    wall_time_seconds: float = 10.0
    network_allowed: bool = False
    writable_roots: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "wall_time_seconds": self.wall_time_seconds,
            "network_allowed": self.network_allowed,
            "writable_roots": list(self.writable_roots),
        }


@dataclass(frozen=True)
class SandboxSession:
    session_id: str
    project_id: str
    workspace_root: str
    limits: SandboxLimits
    created_at_ms: float
    backend: str = "fixture"

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "workspace_root": self.workspace_root,
            "limits": self.limits.public_dict(),
            "created_at_ms": self.created_at_ms,
            "backend": self.backend,
            "truth": {
                "fixture_sandbox_not_os_container": True,
                "real_container_adapter_unmeasured": True,
            },
        }


@dataclass(frozen=True)
class SandboxExecResult:
    ok: bool
    denied_reason: str | None = None
    stdout: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "denied_reason": self.denied_reason,
            "stdout": self.stdout,
            "metadata": self.metadata,
        }


class SandboxBackend(Protocol):
    def open_session(
        self,
        *,
        project_id: str,
        workspace_root: Path,
        limits: SandboxLimits | None = None,
    ) -> SandboxSession: ...

    def check_path(self, session: SandboxSession, path: Path, *, write: bool = False) -> SandboxExecResult: ...


class FixtureSandboxBackend:
    """Workspace-rooted path deny/allow without spawning containers."""

    def __init__(self) -> None:
        self.sessions: dict[str, SandboxSession] = {}
        self.denials = 0

    def open_session(
        self,
        *,
        project_id: str,
        workspace_root: Path,
        limits: SandboxLimits | None = None,
    ) -> SandboxSession:
        root = workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        lim = limits or SandboxLimits(writable_roots=(str(root),))
        session = SandboxSession(
            session_id=f"sbx_{project_id}_{int(time.time() * 1000) % 1_000_000}",
            project_id=project_id,
            workspace_root=str(root),
            limits=lim,
            created_at_ms=time.time() * 1000,
            backend="fixture",
        )
        self.sessions[session.session_id] = session
        return session

    def check_path(self, session: SandboxSession, path: Path, *, write: bool = False) -> SandboxExecResult:
        target = path.resolve()
        root = Path(session.workspace_root).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self.denials += 1
            return SandboxExecResult(
                ok=False,
                denied_reason="path_outside_workspace",
                metadata={"path": str(target), "workspace": str(root)},
            )
        if write:
            allowed = False
            for writable in session.limits.writable_roots:
                try:
                    target.relative_to(Path(writable).resolve())
                    allowed = True
                    break
                except ValueError:
                    continue
            if not allowed:
                self.denials += 1
                return SandboxExecResult(ok=False, denied_reason="write_not_permitted")
        return SandboxExecResult(ok=True, stdout="allowed")

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_count": len(self.sessions),
            "denials": self.denials,
            "truth": {
                "fixture_sandbox_not_os_container": True,
                "real_container_adapter_unmeasured": True,
            },
        }
