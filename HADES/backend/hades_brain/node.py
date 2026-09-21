"""Local node advertisement. No speculative distributed infrastructure."""

from __future__ import annotations

from typing import Any


def advertise_local_node(*, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    host: dict[str, Any] = {}
    fabric: dict[str, Any] = {}
    try:
        from host_capability import check_host_capabilities

        host = check_host_capabilities()
    except Exception as exc:
        host = {"error": type(exc).__name__, "available": False}
    try:
        from compute_fabric import LocalExecutor

        fabric = LocalExecutor().capabilities()
    except Exception as extra_exc:
        fabric = {"error": type(extra_exc).__name__, "distributed": False, "node": "local"}
    payload = {
        "node_id": "local",
        "distributed": False,
        "cpu": host.get("cpu") or "unknown",
        "ram": host.get("ram") or "unknown",
        "gpu": host.get("gpu") or "unknown",
        "vram": host.get("vram") or "unknown",
        "models": list((extras or {}).get("models") or []),
        "datasets": list((extras or {}).get("datasets") or []),
        "repositories": list((extras or {}).get("repositories") or []),
        "plugins": list((extras or {}).get("plugins") or []),
        "mcp_providers": list((extras or {}).get("mcp_providers") or []),
        "software": host,
        "health": "available" if host.get("error") is None else "unknown",
        "capabilities": fabric,
        "data_locality": "local",
        "note": "HADES advertises this process only. Remote peering is not implemented.",
    }
    return payload


def prefer_local_data(resource_kind: str, *, local_present: bool, remote_compute_better: bool) -> str:
    """Prefer execution where large data already lives."""
    if local_present:
        return "local"
    if remote_compute_better:
        return "remote_if_safe"
    return "local"
