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


def content_hash(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
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
