"""Communication graph aggregation."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .store import SignalStore


def build_communication_graph(
    store: SignalStore,
    *,
    window_hours: int = 24,
    mission_id: str | None = None,
) -> dict[str, Any]:
    return store.communication_graph(window_hours=window_hours, mission_id=mission_id)
