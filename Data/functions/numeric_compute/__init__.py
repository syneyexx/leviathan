from __future__ import annotations

from typing import Any


def run(
    operation: str,
    *,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deterministic Tier-0 numeric/statistics compute."""
    from Data.modules.compute.numeric import NumericComputeEngine

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    return NumericComputeEngine().dispatch(str(operation), payload).public_dict()
