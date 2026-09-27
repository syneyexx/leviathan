"""Canonical cheap host liveness projection.

Intentionally tiny. No LLM, knowledge, product-truth, worker dashboard,
backup, MCP, or database scans. A successful HTTP response from this route
proves the API process is alive and FastAPI lifespan startup completed.
"""

from __future__ import annotations

from typing import Any


def build_host_liveness(*, version: str = "", bootstrapped: bool = True) -> dict[str, Any]:
    """Return the bounded liveness payload for GET /api/host/liveness."""
    return {
        "ok": True,
        "liveness": "alive",
        "bootstrapped": bool(bootstrapped),
        "started": True,
        "version": str(version or ""),
        "truth": {
            "processLivenessOnly": True,
            "noSubsystemAggregation": True,
            "notProductTruth": True,
        },
    }
