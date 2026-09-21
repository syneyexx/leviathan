"""Preflight helpers for large offline Dataset Brain imports.

Hugging Face's Dataset Viewer can expose a complete per-split size estimate.  HADES
uses that estimate only when the server explicitly reports ``partial=false``.  A
partial/unavailable estimate never becomes a fabricated capacity guarantee; the
worker's incremental free-space checks remain the fallback safety boundary.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx

from training_service import HF_DATASET_SERVER

MIN_FREE_RESERVE_BYTES = 5 * 1024 * 1024 * 1024


class DatasetBrainStorageError(OSError):
    """Raised when a complete HF size estimate proves local storage is insufficient."""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def estimate_hf_split_size(
    dataset: dict[str, Any],
    *,
    token: str | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Return a best-effort complete HF split-size estimate without guessing.

    ``known`` is true only when Dataset Viewer returns ``partial=false`` and the
    requested config/split has a positive byte measurement. Network/API failures
    deliberately degrade to ``known=false`` so the normal streaming path can still
    proceed under the worker's incremental disk reserve checks.
    """

    source = dict(dataset.get("source") or {})
    dataset_name = str(source.get("dataset_id") or "").strip()
    config = str(source.get("config") or "").strip()
    split = str(source.get("split") or "").strip()
    if not dataset_name or not config or not split:
        return {"checked": False, "known": False, "reason": "missing_source_metadata"}

    headers = {"Authorization": f"Bearer {token.strip()}"} if token and token.strip() else {}
    try:
        with httpx.Client(
            timeout=httpx.Timeout(max(5.0, min(float(timeout_seconds), 60.0))),
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = client.get(f"{HF_DATASET_SERVER}/size", params={"dataset": dataset_name})
            if response.status_code >= 400:
                return {
                    "checked": True,
                    "known": False,
                    "reason": f"http_{response.status_code}",
                }
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return {"checked": True, "known": False, "reason": "size_endpoint_unavailable"}

    if not isinstance(payload, dict):
        return {"checked": True, "known": False, "reason": "invalid_size_payload"}
    if payload.get("partial") is True:
        return {"checked": True, "known": False, "reason": "partial_size"}

    size = payload.get("size")
    split_rows = size.get("splits") if isinstance(size, dict) else None
    if not isinstance(split_rows, list):
        return {"checked": True, "known": False, "reason": "split_size_missing"}

    selected: dict[str, Any] | None = None
    for item in split_rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("config") or "") == config and str(item.get("split") or "") == split:
            selected = item
            break
    if selected is None:
        return {"checked": True, "known": False, "reason": "requested_split_missing"}

    memory_bytes = _positive_int(selected.get("num_bytes_memory"))
    parquet_bytes = _positive_int(selected.get("num_bytes_parquet_files"))
    estimated_bytes = max(memory_bytes or 0, parquet_bytes or 0)
    if estimated_bytes <= 0:
        return {"checked": True, "known": False, "reason": "split_bytes_unknown"}

    return {
        "checked": True,
        "known": True,
        "dataset": dataset_name,
        "config": config,
        "split": split,
        "estimated_bytes": estimated_bytes,
        "num_bytes_memory": memory_bytes,
        "num_bytes_parquet_files": parquet_bytes,
        "num_rows": _positive_int(selected.get("num_rows")),
        "partial": False,
    }


def preflight_hf_disk(
    target_root: str | Path,
    dataset: dict[str, Any],
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Reject only imports that a complete HF estimate proves cannot fit safely."""

    root = Path(target_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    free_bytes = int(shutil.disk_usage(root).free)
    estimate = estimate_hf_split_size(dataset, token=token)
    result = {**estimate, "free_bytes": free_bytes, "reserve_bytes": MIN_FREE_RESERVE_BYTES}
    if not estimate.get("known"):
        result["required_bytes"] = None
        return result

    estimated_bytes = int(estimate["estimated_bytes"])
    required_bytes = estimated_bytes + MIN_FREE_RESERVE_BYTES
    result["required_bytes"] = required_bytes
    if free_bytes < required_bytes:
        required_gib = required_bytes / (1024**3)
        free_gib = free_bytes / (1024**3)
        estimate_gib = estimated_bytes / (1024**3)
        raise DatasetBrainStorageError(
            "Onvoldoende vrije schijfruimte voor deze Hugging Face split: "
            f"geschatte dataset {estimate_gib:.1f} GiB + 5.0 GiB veiligheidsreserve "
            f"vereist circa {required_gib:.1f} GiB; beschikbaar {free_gib:.1f} GiB."
        )
    return result
