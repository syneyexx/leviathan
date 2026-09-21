"""Local plugin marketplace — catalog bundled `plugins/*/hades-plugin.json` sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SKIP_DIRS = {"_shared", "dist", "__pycache__", ".git"}


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("id") else None


def scan_local_marketplace(
    plugins_root: Path,
    *,
    installed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """List installable local plugin sources with honest install/health status."""
    root = plugins_root.resolve()
    installed_by_id = {
        str(item.get("id")): item
        for item in (installed or [])
        if isinstance(item, dict) and item.get("id")
    }
    items: list[dict[str, Any]] = []

    if not root.is_dir():
        return {
            "items": [],
            "count": 0,
            "plugins_root": str(root),
            "note": "Lokale plugins-map ontbreekt.",
        }

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        manifest_path = child / "hades-plugin.json"
        if not manifest_path.is_file():
            continue
        manifest = _load_manifest(manifest_path)
        if not manifest:
            continue
        plugin_id = str(manifest["id"])
        tools = manifest.get("tools") if isinstance(manifest.get("tools"), list) else []
        labels = manifest.get("labels") if isinstance(manifest.get("labels"), list) else []
        permissions = manifest.get("permissions") if isinstance(manifest.get("permissions"), list) else []
        runtime = str(manifest.get("runtime_type") or manifest.get("runtime") or "unknown")
        tags_blob = " ".join(str(x).lower() for x in [*labels, *permissions, runtime, plugin_id])
        is_mcp = "mcp" in tags_blob or any("mcp" in str(t.get("name") or "").lower() for t in tools if isinstance(t, dict))
        current = installed_by_id.get(plugin_id)
        health = None
        status = "available"
        enabled = False
        if current:
            status = "installed"
            health = current.get("health") or current.get("status") or "unknown"
            enabled = bool(current.get("enabled"))
            # Prefer Ready/health proof over mere presence.
            if str(current.get("status") or "").lower() not in {"ready"} and str(health).lower() not in {"healthy", "ready", "ok"}:
                status = "installed_needs_attention"

        items.append(
            {
                "id": plugin_id,
                "name": manifest.get("name") or plugin_id,
                "version": manifest.get("version") or "0.0.0",
                "description": manifest.get("description") or "",
                "category": manifest.get("category") or "General",
                "labels": [str(x) for x in labels],
                "runtime_type": runtime,
                "permissions": [str(x) for x in permissions],
                "tool_count": len([t for t in tools if isinstance(t, dict)]),
                "mcp": is_mcp or isinstance(manifest.get("mcp"), dict),
                "autonomous": bool(manifest.get("autonomous")),
                "isolation": manifest.get("isolation") or "plugin_cwd",
                "trust_default": manifest.get("trust_default") or "untrusted",
                "capabilities": manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {},
                "marketplace": manifest.get("marketplace") if isinstance(manifest.get("marketplace"), dict) else {},
                "source_path": str(child),
                "relative_path": f"plugins/{child.name}",
                "package_path": str(next(iter(sorted((child / "dist").glob("*.HadesPlugin"), reverse=True)), "") or ""),
                "status": status,
                "installed": current is not None,
                "enabled": enabled,
                "health": health,
                "trust": (current or {}).get("trust"),
                "failure_state": (current or {}).get("failure_state"),
                "installed_status": current.get("status") if current else None,
            }
        )

    return {
        "items": items,
        "count": len(items),
        "installed_count": sum(1 for item in items if item["installed"]),
        "mcp_count": sum(1 for item in items if item["mcp"]),
        "plugins_root": str(root),
        "note": (
            "Lokale marketplace: .HadesPlugin-bronnen uit de repo. "
            "Installatie kopieert + inspecteert; Ready/health volgt na Repair indien nodig. "
            "Catalogus is geen goedkeuring."
        ),
    }
