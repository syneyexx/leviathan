"""Bounded deterministic chart render batches for market_sim worker.

Large batches: render a slice → persist manifest → requeue continuation.
No ChartWorker pool. Artifacts go to ArtifactStore.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Sequence

from Data.modules.common.atomic import atomic_write_text, ensure_dir

from .chart_perception import (
    CHART_RENDERER_VERSION,
    MAX_BARS_RENDERED,
    render_chart_snapshot,
    store_chart_artifact,
)


DEFAULT_CHART_BATCH_LIMIT = 25
MAX_CHART_BATCH_LIMIT = 100


def clamp_batch_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_CHART_BATCH_LIMIT
    return max(1, min(int(limit), MAX_CHART_BATCH_LIMIT))


def render_chart_batch_slice(
    specs: Sequence[dict[str, Any]],
    *,
    artifact_store: Any | None = None,
    batch_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    cancel_check: Any | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, Any]:
    """Render a bounded slice of chart specs. Returns progress + artifact refs."""
    batch_id = batch_id or str(uuid.uuid4())
    slice_limit = clamp_batch_limit(limit)
    total = len(specs)
    start = max(0, int(offset))
    end = min(total, start + slice_limit)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    reused = 0

    for idx in range(start, end):
        if cancel_check is not None and callable(cancel_check) and cancel_check():
            return {
                "batch_id": batch_id,
                "status": "cancelled",
                "offset": start,
                "next_offset": idx,
                "total": total,
                "rendered": len(results),
                "failed": len(failures),
                "reused": reused,
                "results": results,
                "failures": failures,
                "complete": False,
                "renderer_version": CHART_RENDERER_VERSION,
            }
        spec = dict(specs[idx] or {})
        try:
            bars = list(spec.get("bars") or [])
            # Bound input — never materialize unbounded history for a small chart.
            if len(bars) > MAX_BARS_RENDERED * 2:
                bars = bars[-(MAX_BARS_RENDERED * 2) :]
            snapshot = render_chart_snapshot(
                bars=bars,
                symbol=str(spec.get("symbol") or ""),
                timeframe=str(spec.get("timeframe") or "1h"),
                as_of=str(spec.get("as_of") or ""),
                start_ts=str(spec.get("start_ts") or ""),
                end_ts=str(spec.get("end_ts") or ""),
                overlays=spec.get("overlays") if isinstance(spec.get("overlays"), dict) else None,
                dataset_id=spec.get("dataset_id"),
                dataset_version=spec.get("dataset_version"),
                dataset_hash=spec.get("dataset_hash"),
                source_id=spec.get("source_id"),
                style_version=str(spec.get("style_version") or "v1"),
            )
            meta = dict(snapshot.metadata or {})
            artifact_id = None
            if artifact_store is not None:
                artifact_id = store_chart_artifact(artifact_store, snapshot)
            results.append(
                {
                    "index": idx,
                    "symbol": meta.get("symbol") or spec.get("symbol"),
                    "render_hash": snapshot.render_spec_hash,
                    "content_hash": meta.get("content_hash") or snapshot.render_spec_hash,
                    "artifact_id": artifact_id,
                    "bar_count": meta.get("bar_count"),
                    "size_bytes": len(snapshot.bytes_data),
                }
            )
        except Exception as exc:  # noqa: BLE001 — one chart failure must not corrupt batch
            failures.append({"index": idx, "error": str(exc)[:400], "symbol": spec.get("symbol")})

    complete = end >= total
    next_offset = end if not complete else None
    manifest = {
        "batch_id": batch_id,
        "status": "completed" if complete else "continue",
        "offset": start,
        "next_offset": next_offset,
        "limit": slice_limit,
        "total": total,
        "rendered": len(results),
        "failed": len(failures),
        "reused": reused,
        "results": results,
        "failures": failures,
        "complete": complete,
        "renderer_version": CHART_RENDERER_VERSION,
        "max_bars_rendered": MAX_BARS_RENDERED,
    }
    if manifest_dir is not None:
        ensure_dir(manifest_dir)
        atomic_write_text(
            Path(manifest_dir) / f"chart_batch_{batch_id}_{start}.json",
            json.dumps(manifest, indent=2, default=str),
        )
    return manifest
