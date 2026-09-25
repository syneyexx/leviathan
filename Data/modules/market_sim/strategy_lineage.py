"""Immutable strategy versions + lineage (P2C / G17)."""

from __future__ import annotations

from typing import Any

from .types import MarketSimError, StrategyVersion


def lineage_chain(
    store: Any,
    strategy_id: str,
    *,
    version: int | None = None,
) -> list[dict[str, Any]]:
    """Return version lineage oldest→newest (parent links via metadata)."""
    versions: list[Any] = []
    if hasattr(store, "list_strategy_versions"):
        versions = store.list_strategy_versions(strategy_id)
    else:
        # Fallback: walk current version metadata parents
        cur = store.get_strategy_version(strategy_id, version)
        while cur is not None:
            versions.append(cur)
            parent = (cur.metadata or {}).get("parent_version")
            if parent is None:
                break
            cur = store.get_strategy_version(strategy_id, int(parent))
        versions.reverse()
        return [v.public_dict() if hasattr(v, "public_dict") else dict(v) for v in versions]

    out = []
    for v in sorted(versions, key=lambda x: int(getattr(x, "version", 0) or (x.get("version") if isinstance(x, dict) else 0))):
        out.append(v.public_dict() if hasattr(v, "public_dict") else dict(v))
    return out


def assert_version_immutable(existing: StrategyVersion | dict[str, Any], new_hash: str) -> None:
    """Sealed/content-addressed versions must not mutate in place."""
    if hasattr(existing, "content_hash"):
        old = existing.content_hash
        meta = dict(existing.metadata or {})
    else:
        old = str(existing.get("content_hash") or "")
        meta = dict(existing.get("metadata") or {})
    if meta.get("immutable", True) and old and old != new_hash:
        raise MarketSimError(
            "STRATEGY_VERSION_IMMUTABLE",
            "strategy version content is immutable; create a new version",
            http_status=409,
        )


def attach_lineage_metadata(
    *,
    parent_version: int | None,
    parent_content_hash: str | None,
    changelog: str,
) -> dict[str, Any]:
    return {
        "immutable": True,
        "parent_version": parent_version,
        "parent_content_hash": parent_content_hash,
        "changelog": changelog,
        "lineage": True,
    }
