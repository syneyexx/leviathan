"""Integrity gates before publishing trained artifacts to the model registry (U294).

Canonical artifact manifests hash every protected file. Mutating any protected
weight/adapter/tokenizer/config file invalidates the manifest hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import ArtifactRecord, DurableTrainingJob

# Files that must be covered by the canonical integrity manifest when present.
_PROTECTED_NAME_HINTS = (
    ".safetensors",
    ".bin",
    ".pt",
    ".pth",
    ".gguf",
    ".ggml",
    "adapter_config.json",
    "adapter_model",
    "tokenizer",
    "vocab",
    "merges.txt",
    "special_tokens",
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "leviathan_adapter.json",
    "manifest.json",
)


@dataclass
class IntegrityCheck:
    name: str
    passed: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class IntegrityReport:
    artifact_id: str
    passed: bool
    checks: list[IntegrityCheck] = field(default_factory=list)
    manifest_hash: str | None = None
    file_hashes: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "passed": self.passed,
            "checks": [c.public_dict() for c in self.checks],
            "manifest_hash": self.manifest_hash,
            "file_hashes": dict(self.file_hashes),
            "truth": {
                "registry_publish_requires_integrity": True,
                "no_silent_production_replace": True,
                "mutation_invalidates_manifest": True,
            },
        }


def _is_protected(rel: str) -> bool:
    low = rel.lower().replace("\\", "/")
    name = Path(low).name
    if name.startswith(".") and name not in {".gitattributes"}:
        return False
    return any(hint in low for hint in _PROTECTED_NAME_HINTS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(root: Path) -> dict[str, Any]:
    """Build a canonical per-file hash manifest for an artifact directory/file."""
    root = Path(root)
    files: dict[str, str] = {}
    if root.is_file():
        files[root.name] = _sha256_file(root)
    elif root.is_dir():
            for child in sorted(root.rglob("*")):
                if not child.is_file():
                    continue
                rel = str(child.relative_to(root)).replace("\\", "/")
                if rel.endswith("integrity_manifest.json"):
                    continue
                files[rel] = _sha256_file(child)
    else:
        return {"files": {}, "manifest_hash": None, "root": str(root)}

    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    manifest_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "files": files,
        "manifest_hash": manifest_hash,
        "root": str(root),
        "file_count": len(files),
    }


def verify_artifact_integrity(
    artifact: ArtifactRecord,
    *,
    job: DurableTrainingJob | None = None,
    require_mixture_hash: bool = False,
) -> IntegrityReport:
    checks: list[IntegrityCheck] = []
    path = Path(artifact.path) if artifact.path else None
    exists = bool(path and path.exists())
    checks.append(
        IntegrityCheck(
            name="artifact_path_exists",
            passed=exists,
            detail=str(path) if exists else f"missing path: {artifact.path}",
        )
    )

    file_hashes: dict[str, str] = {}
    manifest_hash: str | None = None
    hash_ok = False

    if exists and path is not None:
        manifest = build_artifact_manifest(path)
        file_hashes = dict(manifest.get("files") or {})
        manifest_hash = manifest.get("manifest_hash")
        checks.append(
            IntegrityCheck(
                name="canonical_manifest_built",
                passed=bool(manifest_hash) and bool(file_hashes),
                detail=f"files={len(file_hashes)} manifest={str(manifest_hash)[:16] if manifest_hash else None}",
            )
        )

        if artifact.content_hash:
            # Accept either: exact file match, or exact canonical manifest hash.
            digests = set(file_hashes.values())
            digests.add(manifest_hash or "")
            if path.is_file():
                digests.add(_sha256_file(path))
            hash_ok = artifact.content_hash in digests
            # Also accept stored manifest hash on the artifact metadata if present.
            stored_manifest = (artifact.evaluation or {}).get("manifest_hash") if artifact.evaluation else None
            if not hash_ok and stored_manifest:
                hash_ok = stored_manifest == manifest_hash
            checks.append(
                IntegrityCheck(
                    name="content_hash_matches",
                    passed=hash_ok,
                    detail="ok" if hash_ok else "content_hash not found among artifact files/manifest",
                )
            )
            if stored_manifest:
                checks.append(
                    IntegrityCheck(
                        name="manifest_hash_matches_stored",
                        passed=stored_manifest == manifest_hash,
                        detail="ok" if stored_manifest == manifest_hash else "manifest mutated",
                    )
                )
        else:
            checks.append(
                IntegrityCheck(
                    name="content_hash_matches",
                    passed=False,
                    detail="artifact content_hash missing",
                )
            )
    elif not artifact.content_hash:
        checks.append(
            IntegrityCheck(
                name="content_hash_matches",
                passed=False,
                detail="artifact content_hash missing",
            )
        )
    else:
        checks.append(
            IntegrityCheck(
                name="content_hash_matches",
                passed=False,
                detail="cannot hash missing path",
            )
        )

    if job is not None and job.config_hash and artifact.config_hash:
        config_ok = job.config_hash == artifact.config_hash
        checks.append(
            IntegrityCheck(
                name="config_hash_matches_job",
                passed=config_ok,
                detail="ok" if config_ok else "job/artifact config_hash mismatch",
            )
        )

    if require_mixture_hash or (job and (job.config or {}).get("mixture_id")):
        mixture_hash = (job.config or {}).get("mixture_content_hash") if job else None
        if not mixture_hash:
            checks.append(
                IntegrityCheck(
                    name="mixture_hash_present",
                    passed=False,
                    detail="training job missing mixture_content_hash",
                )
            )
        else:
            checks.append(
                IntegrityCheck(
                    name="mixture_hash_present",
                    passed=True,
                    detail=str(mixture_hash)[:16],
                )
            )

    passed = all(c.passed for c in checks)
    return IntegrityReport(
        artifact_id=artifact.artifact_id,
        passed=passed,
        checks=checks,
        manifest_hash=manifest_hash,
        file_hashes=file_hashes,
    )
