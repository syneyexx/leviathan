"""Normalized capability metadata — discoverable fields without authority (U161–U164)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


METADATA_SCHEMA_VERSION = 1

# Canonical keys retained after normalization.
_CANONICAL_KEYS = (
    "tags",
    "domains",
    "aliases",
    "cacheable",
    "idempotent",
    "schema_version",
    "worker_kind",
    "isolation",
    "risk_tier",
    "docs_url",
    "execution_class",
    "workload_class",
)


def schema_hash(input_schema: dict[str, Any], output_schema: dict[str, Any] | None = None) -> str:
    payload = json.dumps(
        {"input": input_schema or {}, "output": output_schema or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize_capability_metadata(
    metadata: dict[str, Any] | None,
    *,
    capability_id: str = "",
    name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Normalize free-form metadata into a stable catalog shape.

    Unknown keys are preserved under ``extra`` so providers can attach
    non-authoritative hints without inventing parallel registries.
    """
    raw = dict(metadata or {})
    tags = _as_str_tuple(raw.pop("tags", ()) or ())
    domains = _as_str_tuple(raw.pop("domains", ()) or ())
    aliases = _as_str_tuple(raw.pop("aliases", ()) or ())
    # Derive soft aliases from id/name tokens when none provided.
    if not aliases and capability_id:
        aliases = tuple(
            part
            for part in capability_id.replace(".", " ").replace("_", " ").split()
            if part and part not in {"mcp", "file", "git"}
        )
    cacheable = bool(raw.pop("cacheable", False))
    idempotent = bool(raw.pop("idempotent", cacheable))
    schema_version = int(raw.pop("schema_version", METADATA_SCHEMA_VERSION) or METADATA_SCHEMA_VERSION)
    worker_kind = str(raw.pop("worker_kind", "") or "") or None
    isolation = str(raw.pop("isolation", "") or "") or None
    risk_tier = str(raw.pop("risk_tier", "") or "standard")
    docs_url = str(raw.pop("docs_url", "") or "") or None
    # Workload classification (W2) — authoritative hint for control-plane vs worker.
    raw_execution = raw.pop("execution_class", None)
    raw_workload = raw.pop("workload_class", None)
    execution_class = _normalize_execution_class(
        raw_execution if raw_execution is not None else raw_workload,
        capability_id=capability_id,
        worker_kind=worker_kind,
    )

    # Soft domain inference from capability id prefix.
    if not domains and "." in capability_id:
        domains = (capability_id.split(".", 1)[0].lower(),)

    extra = {k: v for k, v in raw.items() if k not in _CANONICAL_KEYS}
    return {
        "schema_version": schema_version,
        "tags": list(tags),
        "domains": list(domains),
        "aliases": list(aliases),
        "cacheable": cacheable,
        "idempotent": idempotent,
        "worker_kind": worker_kind,
        "isolation": isolation,
        "risk_tier": risk_tier,
        "docs_url": docs_url,
        "execution_class": execution_class,
        "search_text": " ".join(
            filter(
                None,
                [
                    capability_id,
                    name,
                    description,
                    " ".join(tags),
                    " ".join(domains),
                    " ".join(aliases),
                    execution_class or "",
                ],
            )
        ).lower(),
        "extra": extra,
        "truth": {
            "metadata_is_not_authorization": True,
            "discoverable_is_not_approved": True,
            "execution_class_is_not_authorization": True,
        },
    }


def _normalize_execution_class(
    value: Any,
    *,
    capability_id: str = "",
    worker_kind: str | None = None,
) -> str:
    from .workload import classify_capability

    meta: dict[str, Any] = {}
    if value is not None and str(value).strip():
        meta["execution_class"] = value
    if worker_kind:
        meta["worker_kind"] = worker_kind
    return classify_capability(capability_id, metadata=meta).value


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(",", " ").split() if p.strip()]
        return tuple(parts)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()
