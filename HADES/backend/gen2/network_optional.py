"""Network-optional fail-clean helpers + characterization probes (G12).

Internet is optional. Network-gated features must degrade to local behavior
without hang/crash when unavailable or blocked.
"""

from __future__ import annotations

import socket
from typing import Any, Callable


def fail_clean_network_call(
    fn: Callable[[], Any],
    *,
    feature: str,
    local_fallback: Any = None,
    timeout_s: float = 0.05,
) -> dict[str, Any]:
    """Run a network-gated callable; on any failure return local fallback.

    Never raises for transport/DNS/timeouts. Callers remain responsible for
    not marking network success when degraded.
    """
    try:
        # Soft deadline hint for socket defaults inside fn (best-effort).
        previous = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout_s)
        try:
            value = fn()
        finally:
            socket.setdefaulttimeout(previous)
        return {
            "ok": True,
            "degraded": False,
            "feature": feature,
            "value": value,
            "error": None,
            "local_fallback_used": False,
        }
    except Exception as exc:  # noqa: BLE001 — intentional fail-clean
        return {
            "ok": False,
            "degraded": True,
            "feature": feature,
            "value": local_fallback,
            "error": f"{type(exc).__name__}:{exc}"[:500],
            "local_fallback_used": True,
            "note": "Network unavailable/blocked — using local fallback; not a crash.",
        }


def probe_unreachable_host(*, host: str = "240.0.0.1", port: int = 9, timeout_s: float = 0.05) -> dict[str, Any]:
    """Characterization: connecting to a blackhole IP must fail clean, not hang."""

    def _connect() -> str:
        with socket.create_connection((host, port), timeout=timeout_s):
            return "connected"

    return fail_clean_network_call(
        _connect,
        feature="network_probe",
        local_fallback={"status": "offline_local"},
        timeout_s=timeout_s,
    )


def network_optional_feature_matrix() -> dict[str, Any]:
    """Document which Gen2 surfaces are network-optional with local degrade paths."""
    return {
        "version": "network_optional_v1",
        "features": [
            {
                "id": "eval_lab_live_model",
                "network": "optional",
                "degrade": "deterministic_software / blocked live_model without inventing scores",
            },
            {
                "id": "mcp_bridges",
                "network": "optional",
                "degrade": "catalog still lists tools; calls fail with Ready/health errors",
            },
            {
                "id": "finance_live_feeds",
                "network": "optional",
                "degrade": "PAPER fusion from provided articles only; no invented alpha",
            },
            {
                "id": "compute_multi_host",
                "network": "optional",
                "degrade": "single_node_solidity_gate; multi-host deferred",
            },
            {
                "id": "plugin_security_scan",
                "network": "never",
                "degrade": "static checklist only",
            },
        ],
        "rule": "No hang, no crash, no fake network success when offline/blocked.",
    }
