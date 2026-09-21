"""Short-lived read-only deterministic tool result cache."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from runtime.tool_contracts import classify_tool_action

DEFAULT_TTL_SECONDS = 30.0
_MAX_ENTRIES = 256

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _canonical_args(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cache_key(plugin_id: str, tool_name: str, arguments: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        f"{plugin_id}\0{tool_name}\0{_canonical_args(arguments)}".encode("utf-8")
    ).hexdigest()
    return digest


def tool_invocation_cacheable(plugin: dict[str, Any], tool: dict[str, Any]) -> bool:
    contract = classify_tool_action(tool)
    if contract.get("mutating"):
        return False
    if not contract.get("idempotent", True):
        return False
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    if meta.get("cache") is False or meta.get("no_cache"):
        return False
    caps = plugin.get("capabilities") if isinstance(plugin.get("capabilities"), dict) else {}
    effects = {str(item).lower() for item in (caps.get("effects") or plugin.get("permissions") or [])}
    if effects & {"network", "write_files", "service", "mcp"}:
        return False
    action = str(contract.get("action") or "").lower()
    if action in {"start", "stop", "serve", "dev", "logs"}:
        return False
    return True


def get_cached_result(key: str) -> dict[str, Any] | None:
    row = _cache.get(key)
    if not row:
        return None
    expires_at, payload = row
    if time.monotonic() >= expires_at:
        _cache.pop(key, None)
        return None
    return dict(payload)


def store_cached_result(key: str, result: dict[str, Any], *, ttl: float = DEFAULT_TTL_SECONDS) -> None:
    status = str(result.get("status") or "").lower()
    if status not in {"completed", "succeeded", "success", "ok"}:
        return
    if result.get("error"):
        return
    if len(_cache) >= _MAX_ENTRIES:
        oldest = min(_cache.items(), key=lambda item: item[1][0])[0]
        _cache.pop(oldest, None)
    stamped = {**result, "_tool_result_cache": {"hit": False, "stored_at": time.time()}}
    _cache[key] = (time.monotonic() + float(ttl), stamped)


def attach_cache_hit_metadata(result: dict[str, Any]) -> dict[str, Any]:
    meta = dict(result.get("_tool_result_cache") or {})
    meta["hit"] = True
    return {**result, "_tool_result_cache": meta}


def clear_tool_result_cache() -> None:
    _cache.clear()
