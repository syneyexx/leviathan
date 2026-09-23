"""Content-addressed object storage backends (U365).

Canonical metadata stays in the control-plane DB; bytes live behind this
protocol. Fixture backend enforces project scoping to prove no cross-project leak.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ObjectRef:
    object_id: str
    content_hash: str
    size_bytes: int
    project_id: str | None = None
    key: str | None = None
    backend: str = "local_fs"

    def public_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "project_id": self.project_id,
            "key": self.key,
            "backend": self.backend,
        }


class ObjectStore(Protocol):
    def put(
        self,
        data: bytes,
        *,
        key: str,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObjectRef: ...

    def get(self, object_id: str, *, project_id: str | None = None) -> bytes: ...

    def exists(self, object_id: str, *, project_id: str | None = None) -> bool: ...

    def list_for_project(self, project_id: str, *, limit: int = 100) -> list[ObjectRef]: ...


@dataclass
class LocalFsObjectStore:
    """Hash-addressed files under a root directory."""

    root: Path
    backend_name: str = "local_fs"

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        data: bytes,
        *,
        key: str,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObjectRef:
        digest = sha256_bytes(data)
        object_id = digest
        rel = Path(project_id or "_shared") / digest[:2] / digest
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(data)
        return ObjectRef(
            object_id=object_id,
            content_hash=digest,
            size_bytes=len(data),
            project_id=project_id,
            key=key,
            backend=self.backend_name,
        )

    def get(self, object_id: str, *, project_id: str | None = None) -> bytes:
        candidates = []
        if project_id:
            candidates.append(self.root / project_id / object_id[:2] / object_id)
        candidates.append(self.root / "_shared" / object_id[:2] / object_id)
        for path in candidates:
            if path.is_file():
                return path.read_bytes()
        raise FileNotFoundError(f"Object not found: {object_id}")

    def exists(self, object_id: str, *, project_id: str | None = None) -> bool:
        try:
            self.get(object_id, project_id=project_id)
            return True
        except FileNotFoundError:
            return False

    def list_for_project(self, project_id: str, *, limit: int = 100) -> list[ObjectRef]:
        base = self.root / project_id
        refs: list[ObjectRef] = []
        if not base.is_dir():
            return refs
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            digest = path.name
            refs.append(
                ObjectRef(
                    object_id=digest,
                    content_hash=digest,
                    size_bytes=path.stat().st_size,
                    project_id=project_id,
                    backend=self.backend_name,
                )
            )
            if len(refs) >= limit:
                break
        return refs


@dataclass
class FixtureObjectStore:
    """In-memory object store with hard project isolation (CI fixture)."""

    backend_name: str = "fixture"
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _objects: dict[str, tuple[bytes, ObjectRef]] = field(default_factory=dict)
    _by_project: dict[str, set[str]] = field(default_factory=dict)

    def put(
        self,
        data: bytes,
        *,
        key: str,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObjectRef:
        if not project_id:
            raise ValueError("FixtureObjectStore requires project_id for isolation")
        digest = sha256_bytes(data)
        object_id = f"{project_id}:{digest}"
        ref = ObjectRef(
            object_id=object_id,
            content_hash=digest,
            size_bytes=len(data),
            project_id=project_id,
            key=key,
            backend=self.backend_name,
        )
        with self._lock:
            self._objects[object_id] = (data, ref)
            self._by_project.setdefault(project_id, set()).add(object_id)
        return ref

    def get(self, object_id: str, *, project_id: str | None = None) -> bytes:
        with self._lock:
            item = self._objects.get(object_id)
            if item is None:
                raise FileNotFoundError(f"Object not found: {object_id}")
            data, ref = item
            if project_id is not None and ref.project_id != project_id:
                raise PermissionError(
                    f"Cross-project object access denied: {object_id} not in {project_id}"
                )
            return data

    def exists(self, object_id: str, *, project_id: str | None = None) -> bool:
        try:
            self.get(object_id, project_id=project_id)
            return True
        except (FileNotFoundError, PermissionError):
            return False

    def list_for_project(self, project_id: str, *, limit: int = 100) -> list[ObjectRef]:
        with self._lock:
            ids = list(self._by_project.get(project_id, set()))
            refs = [self._objects[i][1] for i in ids if i in self._objects]
        return refs[: max(1, min(limit, 500))]

    def public_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend": self.backend_name,
                "object_count": len(self._objects),
                "projects": sorted(self._by_project.keys()),
                "truth": {
                    "fixture_object_store_not_s3": True,
                    "cross_project_access_denied": True,
                },
            }
