"""Bounded model artifact verification — owned by model_download semantically.

Streaming hash reuses file_io.hash_file. GGUF/safetensors validation inspects
headers only — never loads tensor payloads.
"""

from __future__ import annotations

import json
import struct
from enum import Enum
from pathlib import Path
from typing import Any, Callable

CancelCheck = Callable[[], bool]
ProgressCb = Callable[[dict[str, Any]], None]


class VerificationLevel(str, Enum):
    FILE_PRESENT = "FILE_PRESENT"
    HEADER_VALID = "HEADER_VALID"
    SIZE_VERIFIED = "SIZE_VERIFIED"
    HASH_VERIFIED = "HASH_VERIFIED"
    MANIFEST_VERIFIED = "MANIFEST_VERIFIED"
    DEEP_MODEL_TESTED = "DEEP_MODEL_TESTED"


GGUF_MAGIC = b"GGUF"


def verify_file_present(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    present = target.is_file()
    size = int(target.stat().st_size) if present else None
    return {
        "path": str(target),
        "level": VerificationLevel.FILE_PRESENT.value,
        "ok": present,
        "sizeBytes": size,
    }


def stream_hash_artifact(
    path: str | Path,
    *,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Canonical streaming SHA-256 via file_io — cancellable, mutation-aware."""
    from Data.modules.file_io.ops import hash_file

    result = hash_file(
        path,
        algorithm="sha256",
        cancel_check=cancel_check,
        progress=progress,
        chunk_size=chunk_size,
    )
    changed = result.get("status") == "CHANGED_DURING_READ"
    levels = [VerificationLevel.FILE_PRESENT.value, VerificationLevel.SIZE_VERIFIED.value]
    if not changed and result.get("hash"):
        levels.append(VerificationLevel.HASH_VERIFIED.value)
    return {
        **result,
        "levels": levels,
        "level": (
            VerificationLevel.HASH_VERIFIED.value
            if not changed and result.get("hash")
            else VerificationLevel.SIZE_VERIFIED.value
        ),
        "ok": bool(result.get("hash")) and not changed,
        "artifactChanged": changed,
        "truth": {
            "streaming_hash": True,
            "no_fake_progress": True,
            "partial_digest_not_final": True,
            **dict(result.get("truth") or {}),
        },
    }


def validate_gguf_header(
    path: str | Path,
    *,
    cancel_check: CancelCheck | None = None,
    max_metadata_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Bounded GGUF validation — magic + version + metadata bounds. No tensor load."""
    target = Path(path).expanduser()
    if not target.is_file():
        return {
            "ok": False,
            "level": VerificationLevel.FILE_PRESENT.value,
            "error": "file_not_found",
            "path": str(target),
        }
    size = target.stat().st_size
    if cancel_check and cancel_check():
        return {"ok": False, "cancelled": True, "level": VerificationLevel.FILE_PRESENT.value}
    with target.open("rb") as handle:
        magic = handle.read(4)
        if magic != GGUF_MAGIC:
            return {
                "ok": False,
                "level": VerificationLevel.FILE_PRESENT.value,
                "error": "invalid_magic",
                "magic": magic.hex() if magic else None,
                "sizeBytes": size,
            }
        version_raw = handle.read(4)
        if len(version_raw) < 4:
            return {
                "ok": False,
                "level": VerificationLevel.FILE_PRESENT.value,
                "error": "truncated_header",
                "sizeBytes": size,
            }
        version = struct.unpack("<I", version_raw)[0]
        # tensor_count + metadata_kv_count (uint64 each) — version >= 2 layout
        counts = handle.read(16)
        if len(counts) < 16:
            return {
                "ok": False,
                "level": VerificationLevel.HEADER_VALID.value,
                "error": "truncated_counts",
                "version": version,
                "sizeBytes": size,
            }
        tensor_count, metadata_kv_count = struct.unpack("<QQ", counts)
        header_bytes_read = 4 + 4 + 16
        if header_bytes_read > size:
            return {
                "ok": False,
                "level": VerificationLevel.HEADER_VALID.value,
                "error": "header_exceeds_file",
                "version": version,
                "sizeBytes": size,
            }
        # Do not walk all metadata — bound check only.
        remaining = size - header_bytes_read
        if metadata_kv_count > 1_000_000:
            return {
                "ok": False,
                "level": VerificationLevel.HEADER_VALID.value,
                "error": "oversized_metadata_count",
                "version": version,
                "metadataKvCount": metadata_kv_count,
                "sizeBytes": size,
            }
        if remaining < 0 or (metadata_kv_count > 0 and remaining > max_metadata_bytes * 4 and size < 64):
            # Tiny file claiming huge metadata is invalid.
            pass
    if cancel_check and cancel_check():
        return {"ok": False, "cancelled": True, "level": VerificationLevel.HEADER_VALID.value}
    return {
        "ok": True,
        "level": VerificationLevel.HEADER_VALID.value,
        "levels": [
            VerificationLevel.FILE_PRESENT.value,
            VerificationLevel.SIZE_VERIFIED.value,
            VerificationLevel.HEADER_VALID.value,
        ],
        "version": version,
        "tensorCount": tensor_count,
        "metadataKvCount": metadata_kv_count,
        "sizeBytes": size,
        "path": str(target),
        "truth": {"no_tensor_load": True, "bounded_header_only": True},
    }


def validate_safetensors_header(
    path: str | Path,
    *,
    cancel_check: CancelCheck | None = None,
    max_header_bytes: int = 100 * 1024 * 1024,
) -> dict[str, Any]:
    """Bounded safetensors header validation — no tensor payload load."""
    target = Path(path).expanduser()
    if not target.is_file():
        return {
            "ok": False,
            "level": VerificationLevel.FILE_PRESENT.value,
            "error": "file_not_found",
            "path": str(target),
        }
    size = target.stat().st_size
    if cancel_check and cancel_check():
        return {"ok": False, "cancelled": True, "level": VerificationLevel.FILE_PRESENT.value}
    with target.open("rb") as handle:
        header_len_raw = handle.read(8)
        if len(header_len_raw) < 8:
            return {
                "ok": False,
                "level": VerificationLevel.FILE_PRESENT.value,
                "error": "truncated_header_len",
                "sizeBytes": size,
            }
        header_len = struct.unpack("<Q", header_len_raw)[0]
        if header_len <= 0 or header_len > max_header_bytes:
            return {
                "ok": False,
                "level": VerificationLevel.HEADER_VALID.value,
                "error": "invalid_header_size",
                "headerLen": header_len,
                "sizeBytes": size,
            }
        if 8 + header_len > size:
            return {
                "ok": False,
                "level": VerificationLevel.HEADER_VALID.value,
                "error": "header_exceeds_file",
                "headerLen": header_len,
                "sizeBytes": size,
            }
        raw = handle.read(header_len)
        if len(raw) < header_len:
            return {
                "ok": False,
                "level": VerificationLevel.HEADER_VALID.value,
                "error": "truncated_header",
                "headerLen": header_len,
                "sizeBytes": size,
            }
    if cancel_check and cancel_check():
        return {"ok": False, "cancelled": True, "level": VerificationLevel.HEADER_VALID.value}
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "level": VerificationLevel.HEADER_VALID.value,
            "error": f"invalid_header_json:{exc}",
            "headerLen": header_len,
            "sizeBytes": size,
        }
    if not isinstance(header, dict):
        return {
            "ok": False,
            "level": VerificationLevel.HEADER_VALID.value,
            "error": "header_not_object",
            "sizeBytes": size,
        }
    tensor_keys = [k for k in header.keys() if k != "__metadata__"]
    return {
        "ok": True,
        "level": VerificationLevel.HEADER_VALID.value,
        "levels": [
            VerificationLevel.FILE_PRESENT.value,
            VerificationLevel.SIZE_VERIFIED.value,
            VerificationLevel.HEADER_VALID.value,
        ],
        "headerLen": header_len,
        "tensorCount": len(tensor_keys),
        "sizeBytes": size,
        "path": str(target),
        "truth": {"no_tensor_load": True, "bounded_header_only": True},
    }


def validate_safetensors_index(
    index_path: str | Path,
    *,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Validate safetensors shard index + required shard presence (no tensor load)."""
    target = Path(index_path).expanduser()
    if not target.is_file():
        return {
            "ok": False,
            "level": VerificationLevel.FILE_PRESENT.value,
            "error": "index_not_found",
        }
    if cancel_check and cancel_check():
        return {"ok": False, "cancelled": True}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "level": VerificationLevel.HEADER_VALID.value}
    weight_map = payload.get("weight_map") if isinstance(payload, dict) else None
    if not isinstance(weight_map, dict):
        return {
            "ok": False,
            "error": "missing_weight_map",
            "level": VerificationLevel.HEADER_VALID.value,
        }
    shards = sorted({str(v) for v in weight_map.values()})
    missing: list[str] = []
    for name in shards:
        if cancel_check and cancel_check():
            return {"ok": False, "cancelled": True}
        shard_path = target.parent / name
        if not shard_path.is_file():
            missing.append(name)
    ok = not missing
    return {
        "ok": ok,
        "level": (
            VerificationLevel.MANIFEST_VERIFIED.value
            if ok
            else VerificationLevel.HEADER_VALID.value
        ),
        "shardCount": len(shards),
        "missingShards": missing,
        "path": str(target),
        "truth": {"no_tensor_load": True},
    }


def verify_model_artifact(
    path: str | Path,
    *,
    expect_hash: str | None = None,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    hash_large: bool = True,
) -> dict[str, Any]:
    """Dispatch bounded verification by artifact kind."""
    target = Path(path).expanduser()
    present = verify_file_present(target)
    if not present["ok"]:
        return present
    suffix = target.suffix.lower()
    header: dict[str, Any] = {"ok": True, "level": VerificationLevel.FILE_PRESENT.value}
    if suffix == ".gguf":
        header = validate_gguf_header(target, cancel_check=cancel_check)
    elif suffix == ".safetensors":
        header = validate_safetensors_header(target, cancel_check=cancel_check)
    elif target.name.endswith(".index.json") or target.name == "model.safetensors.index.json":
        header = validate_safetensors_index(target, cancel_check=cancel_check)

    hash_result: dict[str, Any] | None = None
    if hash_large and expect_hash:
        hash_result = stream_hash_artifact(
            target, cancel_check=cancel_check, progress=progress
        )
        if hash_result.get("artifactChanged"):
            return {
                "ok": False,
                "error": "MODEL_ARTIFACT_CHANGED",
                "level": VerificationLevel.SIZE_VERIFIED.value,
                "header": header,
                "hash": hash_result,
            }
        digest = str(hash_result.get("hash") or "")
        if digest and digest.lower() != str(expect_hash).lower():
            return {
                "ok": False,
                "error": "MODEL_ARTIFACT_VERIFY_FAILED",
                "level": VerificationLevel.HASH_VERIFIED.value,
                "header": header,
                "hash": hash_result,
                "expected": expect_hash,
            }
    return {
        "ok": bool(header.get("ok")),
        "level": header.get("level"),
        "header": header,
        "hash": hash_result,
        "path": str(target),
    }
