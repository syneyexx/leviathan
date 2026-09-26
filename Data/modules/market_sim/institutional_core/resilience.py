"""W64 — Backup/restore + fault-injection test helpers (in-process only).

Does not claim production DR capability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload: Mapping[str, Any] | Sequence[Any] | str | bytes) -> str:
    if isinstance(payload, bytes):
        return hashlib.sha256(payload).hexdigest()
    if isinstance(payload, str):
        raw = payload
    else:
        raw = _canon(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class BackupArtifact:
    artifact_id: str
    kind: str
    digest: str
    bytes_len: int
    created_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "kind": self.kind,
            "digest": self.digest,
            "bytesLen": self.bytes_len,
            "createdAt": self.created_at,
        }


@dataclass
class BackupManifest:
    manifest_id: str
    created_at: str
    artifacts: list[BackupArtifact] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def manifest_hash(self) -> str:
        return content_hash(
            {
                "manifest_id": self.manifest_id,
                "created_at": self.created_at,
                "artifacts": [a.public_dict() for a in self.artifacts],
            }
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "manifestId": self.manifest_id,
            "createdAt": self.created_at,
            "artifacts": [a.public_dict() for a in self.artifacts],
            "manifestHash": self.manifest_hash(),
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "in_process_helper_only": True,
                "not_production_dr_claim": True,
            },
        }


def build_backup_manifest(
    *,
    manifest_id: str,
    created_at: str,
    documents: Mapping[str, Mapping[str, Any]],
) -> BackupManifest:
    artifacts: list[BackupArtifact] = []
    for artifact_id, doc in sorted(documents.items()):
        payload = _canon(dict(doc))
        artifacts.append(
            BackupArtifact(
                artifact_id=artifact_id,
                kind="json_document",
                digest=content_hash(payload),
                bytes_len=len(payload.encode("utf-8")),
                created_at=created_at,
            )
        )
    return BackupManifest(
        manifest_id=manifest_id,
        created_at=created_at,
        artifacts=artifacts,
        notes=["simulated_backup_manifest"],
    )


def verify_restore(
    manifest: BackupManifest | Mapping[str, Any],
    restored_documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify restored docs match expected artifact hashes from the manifest."""
    if isinstance(manifest, Mapping):
        arts = [
            BackupArtifact(
                artifact_id=str(a.get("artifactId") or a.get("artifact_id") or ""),
                kind=str(a.get("kind") or "json_document"),
                digest=str(a.get("digest") or ""),
                bytes_len=int(a.get("bytesLen") or a.get("bytes_len") or 0),
                created_at=str(a.get("createdAt") or a.get("created_at") or ""),
            )
            for a in (manifest.get("artifacts") or [])
        ]
        manifest = BackupManifest(
            manifest_id=str(manifest.get("manifestId") or manifest.get("manifest_id") or ""),
            created_at=str(manifest.get("createdAt") or manifest.get("created_at") or ""),
            artifacts=arts,
        )

    errors: list[str] = []
    expected = {a.artifact_id: a.digest for a in manifest.artifacts}
    for artifact_id, digest in expected.items():
        if artifact_id not in restored_documents:
            errors.append(f"missing:{artifact_id}")
            continue
        actual = content_hash(_canon(dict(restored_documents[artifact_id])))
        if actual != digest:
            errors.append(f"hash_mismatch:{artifact_id}")
    for artifact_id in restored_documents:
        if artifact_id not in expected:
            errors.append(f"unexpected:{artifact_id}")

    ok = not errors
    return {
        "ok": ok,
        "status": MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
        "errors": errors,
        "manifestHash": manifest.manifest_hash(),
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "not_production_dr_claim": True,
            "in_process_verification_only": True,
        },
    }


def fault_inject(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    drop_keys: Sequence[str] = (),
    corrupt_keys: Sequence[str] = (),
) -> dict[str, dict[str, Any]]:
    """Test helper: drop or mutate documents to exercise restore verification."""
    out = {k: dict(v) for k, v in documents.items() if k not in set(drop_keys)}
    for key in corrupt_keys:
        if key in out:
            out[key] = {**out[key], "_corrupted": True}
    return out


# --- W99 local DB backup / restore (extends helper; not production DR claim) ---

def backup_sqlite_database(
    db_path,
    *,
    backup_dir,
    manifest_id=None,
):
    """Copy canonical SQLite DB into an isolated backup directory and hash it."""
    import shutil
    from pathlib import Path as _Path
    from .timeutil import now_canonical

    src = _Path(db_path)
    dest_dir = _Path(backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    created = now_canonical()
    mid = manifest_id or f"bak-{created}"
    dest = dest_dir / f"{mid}.sqlite"
    shutil.copy2(src, dest)
    digest = content_hash(dest.read_bytes())
    artifact = BackupArtifact(
        artifact_id="central_sqlite",
        kind="sqlite",
        digest=digest,
        bytes_len=dest.stat().st_size,
        created_at=created,
    )
    # Attach path via notes/public extension without breaking dataclass
    manifest = BackupManifest(
        manifest_id=mid,
        created_at=created,
        artifacts=[artifact],
        notes=[f"local_sqlite_file_copy path={dest}"],
    )
    manifest._sqlite_path = str(dest)  # type: ignore[attr-defined]
    return manifest


def restore_and_verify_institutional(*, backup_manifest, restore_dir):
    """Restore DB copy into isolated dir and verify institutional integrity."""
    import shutil
    import time
    from pathlib import Path as _Path

    t0 = time.perf_counter()
    restore_dir = _Path(restore_dir)
    restore_dir.mkdir(parents=True, exist_ok=True)
    sqlite_art = next((a for a in backup_manifest.artifacts if a.kind == "sqlite"), None)
    path_note = None
    for note in backup_manifest.notes:
        if "path=" in note:
            path_note = note.split("path=", 1)[1].strip()
    src_path = getattr(backup_manifest, "_sqlite_path", None) or path_note
    if sqlite_art is None or not src_path:
        return {"ok": False, "status": "FAIL", "reason": "no_sqlite_artifact"}
    src = _Path(src_path)
    if not src.exists():
        return {"ok": False, "status": "FAIL", "reason": "backup_file_missing"}
    if content_hash(src.read_bytes()) != sqlite_art.digest:
        return {"ok": False, "status": "FAIL", "reason": "backup_digest_mismatch"}
    dest = restore_dir / "restored.sqlite"
    shutil.copy2(src, dest)
    from .runtime import InstitutionalRuntime

    rt = InstitutionalRuntime(dest)
    audit = rt.repo.verify_audit_chain()
    elapsed = time.perf_counter() - t0
    ok = bool(audit.get("ok"))
    return {
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "restoredPath": str(dest),
        "audit": audit,
        "measuredRtoSec": elapsed,
        "truth": {
            "local_measured_rto_not_guaranteed_production_rto": True,
            "not_production_dr_claim": True,
        },
    }
