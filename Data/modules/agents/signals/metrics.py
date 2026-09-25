"""Signal Fabric metrics helpers."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .store import SignalStore


def collect_metrics(store: SignalStore, *, window_minutes: int = 60) -> dict[str, Any]:
    return store.metrics_snapshot(window_minutes=window_minutes)
