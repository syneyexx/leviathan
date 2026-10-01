"""Dataset transforms with explicit lineage — streaming pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator

from .types import CanonicalRecord, DatasetError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# P1-008: reserved canonical metadata keys — set_metadata must not clobber these.
RESERVED_CANONICAL_METADATA_KEYS = frozenset(
    {
        "source",
        "sourcePath",
        "sourceHash",
        "datasetId",
        "versionId",
        "lineage",
        "trust",
    }
)

# Allowed namespaces for operator/user metadata that would otherwise collide.
OPERATOR_METADATA_NAMESPACES = frozenset({"user", "operator"})

TransformFn = Callable[[CanonicalRecord], CanonicalRecord | None]


@dataclass(frozen=True)
class TransformSpec:
    name: str
    params: dict[str, Any]

    def lineage_entry(
        self,
        *,
        input_count: int,
        output_count: int,
        drop_count: int | None = None,
    ) -> dict[str, Any]:
        entry = {
            "name": self.name,
            "params": dict(self.params),
            "inputCount": input_count,
            "outputCount": output_count,
            "appliedAt": utc_now(),
        }
        if drop_count is not None:
            entry["dropCount"] = drop_count
        return entry


def _strip_whitespace(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    text = rec.text.strip() if params.get("strip", True) else rec.text
    if params.get("collapse_whitespace"):
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    if params.get("drop_empty") and not text.strip() and not rec.messages:
        return None
    return CanonicalRecord(
        id=rec.id,
        text=text,
        messages=rec.messages,
        labels=rec.labels,
        metadata=dict(rec.metadata),
        split=rec.split,
    )


def _lowercase(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    return CanonicalRecord(
        id=rec.id,
        text=rec.text.lower(),
        messages=rec.messages,
        labels=rec.labels,
        metadata={**rec.metadata, "lowercased": True},
        split=rec.split,
    )


def _filter_min_chars(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    minimum = int(params.get("min_chars", 1))
    if len(rec.text) < minimum and not rec.messages:
        return None
    return rec


def _add_prefix(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    prefix = str(params.get("prefix") or "")
    return CanonicalRecord(
        id=rec.id,
        text=f"{prefix}{rec.text}",
        messages=rec.messages,
        labels=rec.labels,
        metadata=dict(rec.metadata),
        split=rec.split,
    )


def _merge_set_metadata(
    existing: dict[str, Any],
    extra: dict[str, Any],
    *,
    namespace: str = "user",
) -> dict[str, Any]:
    """Merge operator metadata without overwriting reserved canonical keys.

    Non-reserved keys are written at the top level. Attempts to set a reserved
    key are redirected into ``namespace`` (default ``user``; ``operator`` also
    allowed) so provenance fields stay intact.
    """
    ns = (namespace or "user").strip() or "user"
    if ns not in OPERATOR_METADATA_NAMESPACES:
        raise DatasetError(
            f"set_metadata.namespace must be one of {sorted(OPERATOR_METADATA_NAMESPACES)}",
            code="invalid_transform",
        )
    merged = dict(existing)
    redirected: dict[str, Any] = {}
    for key, value in extra.items():
        if key in RESERVED_CANONICAL_METADATA_KEYS or key in OPERATOR_METADATA_NAMESPACES:
            redirected[key] = value
        else:
            merged[key] = value
    if redirected:
        bucket = merged.get(ns)
        if isinstance(bucket, dict):
            merged[ns] = {**bucket, **redirected}
        else:
            merged[ns] = dict(redirected)
    return merged


def _set_metadata(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    extra = params.get("metadata") or {}
    if not isinstance(extra, dict):
        raise DatasetError("set_metadata.metadata must be an object", code="invalid_transform")
    namespace = str(params.get("namespace") or "user")
    return CanonicalRecord(
        id=rec.id,
        text=rec.text,
        messages=rec.messages,
        labels=rec.labels,
        metadata=_merge_set_metadata(dict(rec.metadata), extra, namespace=namespace),
        split=rec.split,
    )


TRANSFORM_REGISTRY: dict[str, Callable[[CanonicalRecord, dict[str, Any]], CanonicalRecord | None]] = {
    "strip_whitespace": _strip_whitespace,
    "lowercase": _lowercase,
    "filter_min_chars": _filter_min_chars,
    "add_prefix": _add_prefix,
    "set_metadata": _set_metadata,
}


def _compile_pipeline(
    transforms: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], Callable[[CanonicalRecord, dict[str, Any]], CanonicalRecord | None]]]:
    compiled: list[tuple[str, dict[str, Any], Callable[[CanonicalRecord, dict[str, Any]], CanonicalRecord | None]]] = []
    for spec_raw in transforms:
        name = str(spec_raw.get("name") or "").strip()
        if not name:
            raise DatasetError("Transform missing name", code="invalid_transform")
        if name not in TRANSFORM_REGISTRY:
            raise DatasetError(f"Unknown transform: {name}", code="unknown_transform")
        params = dict(spec_raw.get("params") or {})
        compiled.append((name, params, TRANSFORM_REGISTRY[name]))
    return compiled


def iter_apply_transforms(
    records: Iterable[CanonicalRecord],
    transforms: list[dict[str, Any]],
) -> tuple[Iterator[CanonicalRecord], list[dict[str, Any]]]:
    """Build a streaming transform pipeline.

    Returns (iterator, lineage_holders). Lineage counters are filled while the
    iterator is consumed; call ``finalize_transform_lineage(lineage_holders)``
    after exhaustion, or use ``apply_transforms_to_sink``.
    """
    compiled = _compile_pipeline(transforms)
    # Per-stage counters mutated during iteration
    counters = [{"input": 0, "output": 0, "drop": 0, "name": n, "params": p} for n, p, _ in compiled]
    lineage_refs = counters  # same objects

    def _pipeline() -> Iterator[CanonicalRecord]:
        for rec in records:
            current: CanonicalRecord | None = rec
            for idx, (name, params, fn) in enumerate(compiled):
                counters[idx]["input"] += 1
                if current is None:
                    counters[idx]["drop"] += 1
                    break
                try:
                    current = fn(current, params)
                except DatasetError:
                    raise
                except Exception as exc:  # noqa: BLE001 — surface as transform error
                    raise DatasetError(
                        f"Transform {name} failed on record {rec.id}: {exc}",
                        code="transform_error",
                        details={"recordId": rec.id, "transform": name},
                    ) from exc
                if current is None:
                    counters[idx]["drop"] += 1
                    break
                counters[idx]["output"] += 1
            if current is not None:
                yield current

    return _pipeline(), lineage_refs


def finalize_transform_lineage(lineage_holders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        TransformSpec(name=h["name"], params=h["params"]).lineage_entry(
            input_count=h["input"],
            output_count=h["output"],
            drop_count=h["drop"],
        )
        for h in lineage_holders
    ]


def apply_transforms_streaming(
    records: Iterable[CanonicalRecord],
    transforms: list[dict[str, Any]],
) -> tuple[Iterator[CanonicalRecord], Callable[[], list[dict[str, Any]]]]:
    """Return streaming iterator + callable that builds lineage after consumption."""
    it, holders = iter_apply_transforms(records, transforms)

    def _lineage() -> list[dict[str, Any]]:
        return finalize_transform_lineage(holders)

    return it, _lineage


def apply_transforms(
    records: Iterable[CanonicalRecord],
    transforms: list[dict[str, Any]],
) -> tuple[list[CanonicalRecord], list[dict[str, Any]]]:
    """Compatibility wrapper — materializes output list (for small/tests).

    Production handlers should stream via ``apply_transforms_streaming`` into
    ``write_canonical_jsonl_stream`` instead of calling this for large corpora.
    """
    it, lineage_fn = apply_transforms_streaming(records, transforms)
    out = list(it)
    return out, lineage_fn()
