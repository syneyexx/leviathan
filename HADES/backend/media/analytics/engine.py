
"""Metric snapshots over time — unsupported != zero."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AnalyticsEngine:
    def __init__(self, store: Any) -> None:
        self.store = store

    def record_snapshot(
        self,
        *,
        platform: str,
        external_post_id: str,
        metrics: dict[str, Any] | None,
        project_id: str | None = None,
        hours_since_publish: float | None = None,
        raw: dict[str, Any] | None = None,
        unsupported: bool = False,
    ) -> dict[str, Any]:
        # Persist even when unsupported so callers can see honest gaps.
        payload_metrics = None if unsupported else (metrics or {})
        return self.store.add_metric_snapshot(
            {
                "project_id": project_id,
                "platform": platform,
                "external_post_id": external_post_id,
                "captured_at": utc_now(),
                "hours_since_publish": hours_since_publish,
                "metrics": payload_metrics if payload_metrics is not None else {"_unsupported": True},
                "raw": raw or {},
            }
        )

    def history(self, *, platform: str, external_post_id: str) -> list[dict[str, Any]]:
        return self.store.list_metric_snapshots(platform=platform, external_post_id=external_post_id, limit=200)

    def value_at_or_after(self, snapshots: list[dict[str, Any]], hours: float, metric: str) -> Any:
        for snap in snapshots:
            hs = snap.get("hours_since_publish")
            if hs is None:
                continue
            if float(hs) + 1e-6 >= float(hours):
                metrics = snap.get("metrics") or {}
                if metrics.get("_unsupported"):
                    return None
                return metrics.get(metric)
        return None
