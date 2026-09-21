"""Managed artifact registry for uploads, generated files, logs and evidence."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any

from database import new_id, utc_now

ARTIFACT_KINDS = frozenset({"upload", "generated", "log", "evidence", "attachment"})
ARTIFACT_STATUSES = frozenset({"partial", "ready", "failed", "deleted"})
SUPPORTED_GENERATED_EXTENSIONS = frozenset({
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv",
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp",
    ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".sql", ".sh", ".bat", ".ps1",
})
TEXT_PREVIEW_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def guess_mime(name: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(name)
    return guessed or fallback



def can_generate_format(name: str, mime: str | None = None) -> tuple[bool, str]:
    suffix = Path(name).suffix.lower()
    resolved_mime = mime or guess_mime(name)
    if suffix in {".pdf", ".xlsx", ".xls", ".docx", ".pptx"}:
        return False, f"Formaat {suffix or resolved_mime} kan niet worden gegenereerd zonder een echte generator of plugin."
    if suffix and suffix not in SUPPORTED_GENERATED_EXTENSIONS:
        return False, f"Formaat {suffix} wordt niet ondersteund voor gegenereerde resultaten."
    if resolved_mime.startswith("image/") or resolved_mime.startswith("audio/") or resolved_mime.startswith("video/"):
        return False, f"MIME-type {resolved_mime} wordt niet ondersteund zonder generator."
    return True, ""


def is_safe_preview(mime: str) -> bool:
    if mime in {"application/json", "application/xml", "application/javascript"}:
        return True
    return mime.startswith("text/")


class ArtifactService:
    """Filesystem-backed artifact registry with atomic writes and verification."""

    def __init__(self, db: Any, root: Path) -> None:
        self.db = db
        self.root = Path(root).expanduser().resolve()
        self.store = self.root / "artifacts"
        self.store.mkdir(parents=True, exist_ok=True)

    def _path_for(self, artifact_id: str, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "._-+" else "_" for ch in Path(name).name)[:120] or "artifact.bin"
        folder = self.store / artifact_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder / safe

    def create(
        self,
        *,
        name: str,
        kind: str,
        data: bytes | None = None,
        source_path: Path | None = None,
        mime_type: str | None = None,
        status: str = "ready",
        version: int = 1,
        parent_artifact_id: str | None = None,
        creator_run_id: str | None = None,
        creator_toolcall_id: str | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        verify_format: bool = True,
    ) -> dict[str, Any]:
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"Onbekend artifact-kind: {kind}")
        if status not in ARTIFACT_STATUSES:
            raise ValueError(f"Onbekende artifact-status: {status}")
        mime = mime_type or guess_mime(name)
        if kind == "generated" and verify_format and status == "ready":
            ok, reason = can_generate_format(name, mime)
            if not ok:
                raise ValueError(reason)

        artifact_id = new_id("art")
        payload: bytes
        if data is not None:
            payload = data
        elif source_path is not None:
            payload = Path(source_path).read_bytes()
        else:
            payload = b""
            if status == "ready":
                status = "partial"

        target = self._path_for(artifact_id, name)
        if status == "ready":
            self._atomic_write(target, payload)
            if not target.is_file() or not os.access(target, os.R_OK):
                raise RuntimeError("Artifact kon niet worden geverifieerd na schrijven.")
            checksum = sha256_file(target)
            size = target.stat().st_size
            if size != len(payload) or checksum != sha256_bytes(payload):
                raise RuntimeError("Artifact-checksum kwam niet overeen na atomisch schrijven.")
        else:
            # Keep partial/failed material recognizable without claiming readiness.
            partial = target.with_suffix(target.suffix + ".partial")
            self._atomic_write(partial, payload)
            target = partial
            checksum = sha256_bytes(payload) if payload else ""
            size = len(payload)

        record = {
            "id": artifact_id,
            "name": Path(name).name,
            "kind": kind,
            "mime_type": mime,
            "size_bytes": size,
            "checksum_sha256": checksum,
            "version": version,
            "parent_artifact_id": parent_artifact_id,
            "status": status,
            "storage_path": str(target),
            "creator_run_id": creator_run_id,
            "creator_toolcall_id": creator_toolcall_id,
            "conversation_id": conversation_id,
            "project_id": project_id,
            "task_id": task_id,
            "metadata": metadata or {},
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        return self.db.insert_artifact(record)

    def _atomic_write(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def create_text_result(
        self,
        *,
        name: str,
        text: str,
        kind: str = "generated",
        mime_type: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        mime = mime_type or guess_mime(name, "text/plain")
        ok, reason = can_generate_format(name, mime)
        if not ok:
            self.create(
                name=name,
                kind=kind,
                data=text.encode("utf-8"),
                mime_type=mime,
                status="failed",
                verify_format=False,
                metadata={**(kwargs.get("metadata") or {}), "error": reason},
                **{k: v for k, v in kwargs.items() if k != "metadata"},
            )
            raise ValueError(reason)
        return self.create(
            name=name,
            kind=kind,
            data=text.encode("utf-8"),
            mime_type=mime,
            status="ready",
            **kwargs,
        )

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        item = self.db.get_artifact(artifact_id)
        if not item or item.get("status") == "deleted":
            return None
        return item

    def list(
        self,
        *,
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.db.list_artifacts(
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            kind=kind,
            limit=limit,
        )

    def preview(self, artifact_id: str, max_chars: int = 20_000) -> dict[str, Any]:
        item = self.get(artifact_id)
        if not item:
            raise KeyError(artifact_id)
        if item["status"] != "ready":
            raise ValueError(f"Artifact is niet gereed (status={item['status']}).")
        path = Path(item["storage_path"])
        if not path.is_file():
            raise FileNotFoundError("Artifactbestand ontbreekt op schijf.")
        mime = item["mime_type"]
        if not is_safe_preview(mime):
            return {
                "artifact": item,
                "previewable": False,
                "reason": "Dit formaat wordt niet automatisch uitgevoerd of gerenderd als actieve HTML/JS.",
                "text": None,
            }
        text = path.read_text(encoding="utf-8", errors="replace")
        return {
            "artifact": item,
            "previewable": True,
            "reason": None,
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    def read_bytes(self, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        item = self.get(artifact_id)
        if not item:
            raise KeyError(artifact_id)
        if item["status"] != "ready":
            raise ValueError(f"Artifact is niet gereed (status={item['status']}).")
        path = Path(item["storage_path"])
        if not path.is_file():
            raise FileNotFoundError("Artifactbestand ontbreekt op schijf.")
        data = path.read_bytes()
        if item["checksum_sha256"] and sha256_bytes(data) != item["checksum_sha256"]:
            raise RuntimeError("Checksum-mismatch bij lezen van artifact.")
        return item, data

    def new_version(self, artifact_id: str, data: bytes, name: str | None = None, **kwargs: Any) -> dict[str, Any]:
        parent = self.get(artifact_id)
        if not parent:
            raise KeyError(artifact_id)
        return self.create(
            name=name or parent["name"],
            kind=parent["kind"],
            data=data,
            mime_type=parent["mime_type"],
            version=int(parent.get("version") or 1) + 1,
            parent_artifact_id=parent["id"],
            conversation_id=parent.get("conversation_id"),
            project_id=parent.get("project_id"),
            task_id=parent.get("task_id"),
            **kwargs,
        )

    def soft_delete(self, artifact_id: str) -> bool:
        item = self.get(artifact_id)
        if not item:
            return False
        return self.db.update_artifact(artifact_id, status="deleted", updated_at=utc_now())

    def verify_ready(self, artifact_id: str) -> dict[str, Any]:
        item = self.get(artifact_id)
        if not item:
            raise KeyError(artifact_id)
        path = Path(item["storage_path"])
        size = path.stat().st_size if path.is_file() else 0
        checks = {
            "exists": path.is_file(),
            "readable": path.is_file() and os.access(path, os.R_OK),
            "checksum_ok": False,
            "status_ready": item["status"] == "ready",
            "non_empty": path.is_file() and size > 0,
            "size_bytes": size,
        }
        if checks["exists"]:
            checks["checksum_ok"] = sha256_file(path) == item.get("checksum_sha256")
        # Empty artifacts must not count as verification-ready even if checksum matches.
        checks["ok"] = all(
            checks[key] for key in ("exists", "readable", "checksum_ok", "status_ready", "non_empty")
        )
        return {"artifact": item, "checks": checks}

    def summarize_result(
        self,
        artifact_id: str,
        *,
        verification: dict[str, Any] | None = None,
        uncertainties: list[str] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """User-facing result card: what/where/checked/uncertain/next — not internals."""
        item = self.get(artifact_id)
        if not item:
            raise KeyError(artifact_id)
        ready = self.verify_ready(artifact_id)
        checks = dict(ready.get("checks") or {})
        ver = dict(verification or {})
        uncertain = list(uncertainties or [])
        if not checks.get("ok"):
            uncertain.append("Artifact failed readiness verification.")
        if item.get("status") != "ready":
            uncertain.append(f"Status is {item.get('status')}, not ready.")
        checked = [
            name
            for name, ok in checks.items()
            if name != "ok" and name != "size_bytes" and ok is True
        ]
        failed_checks = [
            name
            for name, ok in checks.items()
            if name not in {"ok", "size_bytes"} and ok is False
        ]
        return {
            "artifact_id": item.get("id"),
            "name": item.get("name"),
            "what": {
                "kind": item.get("kind"),
                "mime_type": item.get("mime_type"),
                "version": item.get("version"),
                "size_bytes": checks.get("size_bytes") or item.get("size_bytes"),
            },
            "where": {
                "storage_path": item.get("storage_path"),
                "task_id": item.get("task_id"),
                "project_id": item.get("project_id"),
                "conversation_id": item.get("conversation_id"),
                "parent_artifact_id": item.get("parent_artifact_id"),
            },
            "checked": {
                "ready": bool(checks.get("ok")),
                "passed": checked,
                "failed": failed_checks,
                "verification_status": ver.get("status"),
            },
            "uncertain": uncertain,
            "inputs": list(inputs or []),
            "sources": list(sources or []),
            "next_actions": [
                "preview" if is_safe_preview(str(item.get("mime_type") or "")) else "download",
                "new_version",
                "reverify",
            ],
            "summary_version": "artifact_result_v1",
        }

    def export_for_backup(self, artifact_ids: list[str] | None = None) -> list[dict[str, Any]]:
        items = self.list(limit=10_000) if not artifact_ids else [self.get(i) for i in artifact_ids]
        out = []
        for item in items:
            if not item or item.get("status") == "deleted":
                continue
            out.append({
                **item,
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            })
        return out
