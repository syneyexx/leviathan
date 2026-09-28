"""Checkpoint verification — external to FastAPI; streaming hashes only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .types import DurableTrainingJob


_COMPLETE_MARKERS = ("COMPLETE", "complete", "trainer_state.json", "state.json", "adapter_config.json")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _looks_partial(root: Path) -> bool:
    name = root.name.lower()
    if name.endswith(".partial") or name.endswith(".tmp") or ".partial" in name:
        return True
    staging = root / "STAGING"
    if staging.exists():
        return True
    incomplete = root / "INCOMPLETE"
    if incomplete.exists():
        return True
    return False


def verify_checkpoint(
    path: Path,
    *,
    job: DurableTrainingJob | None = None,
) -> dict[str, Any]:
    """Classify a checkpoint as VALID / INCOMPLETE / CORRUPT / UNKNOWN.

    Never selects incomplete checkpoints as resumable.
    """
    root = Path(path)
    if root.is_file():
        root = root.parent
    checks: list[dict[str, Any]] = []
    if not root.exists():
        return {
            "path": str(path),
            "state": "UNKNOWN",
            "resumable": False,
            "checks": [{"name": "exists", "passed": False, "detail": "missing"}],
            "code": "TRAINING_CHECKPOINT_INVALID",
        }
    if _looks_partial(root):
        return {
            "path": str(root),
            "state": "INCOMPLETE",
            "resumable": False,
            "checks": [{"name": "partial_marker", "passed": False, "detail": "partial/staging"}],
            "code": "TRAINING_CHECKPOINT_INCOMPLETE",
        }

    files = [p for p in sorted(root.rglob("*")) if p.is_file()]
    if not files:
        return {
            "path": str(root),
            "state": "INCOMPLETE",
            "resumable": False,
            "checks": [{"name": "files", "passed": False, "detail": "empty directory"}],
            "code": "TRAINING_CHECKPOINT_INCOMPLETE",
        }

    file_hashes: dict[str, str] = {}
    for child in files:
        rel = str(child.relative_to(root)).replace("\\", "/")
        try:
            file_hashes[rel] = _sha256_file(child)
            checks.append({"name": f"hash:{rel}", "passed": True, "detail": file_hashes[rel][:16]})
        except OSError as exc:
            return {
                "path": str(root),
                "state": "CORRUPT",
                "resumable": False,
                "checks": [{"name": f"hash:{rel}", "passed": False, "detail": str(exc)}],
                "code": "TRAINING_CHECKPOINT_VERIFY_FAILED",
            }

    has_marker = any(
        any(marker in p.name for marker in _COMPLETE_MARKERS) for p in files
    ) or (root / "COMPLETE").exists()
    checks.append({"name": "completion_marker", "passed": has_marker, "detail": "present" if has_marker else "absent"})

    compatibility: dict[str, Any] = {"ok": True, "mismatches": []}
    if job is not None:
        cfg = dict(job.config or {})
        manifest_path = root / "checkpoint_manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            for key, expected in (
                ("training_job_id", job.job_id),
                ("config_hash", job.config_hash or cfg.get("config_hash")),
                ("dataset_hash", cfg.get("dataset_content_hash") or cfg.get("dataset_hash")),
                ("method", job.method),
                ("base_model_fingerprint", cfg.get("base_model_fingerprint")),
            ):
                if expected is None:
                    continue
                actual = manifest.get(key)
                if actual is not None and str(actual) != str(expected):
                    compatibility["ok"] = False
                    compatibility["mismatches"].append(
                        {"field": key, "expected": expected, "actual": actual}
                    )
        if not compatibility["ok"]:
            return {
                "path": str(root),
                "state": "STALE",
                "resumable": False,
                "checks": checks,
                "compatibility": compatibility,
                "file_hashes": file_hashes,
                "code": "TRAINING_RESUME_INCOMPATIBLE",
            }

    state = "VALID" if has_marker else "INCOMPLETE"
    return {
        "path": str(root),
        "state": state,
        "resumable": state == "VALID" and compatibility.get("ok", True),
        "checks": checks,
        "compatibility": compatibility,
        "file_hashes": file_hashes,
        "file_count": len(file_hashes),
        "code": None if state == "VALID" else "TRAINING_CHECKPOINT_INCOMPLETE",
    }
