"""Global derived dataset catalog (recovery / browse aid).

Canonical truth remains DatasetStore. This catalog is derived and must never
corrupt the database on read/write failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from Data.modules.common.atomic import atomic_write_text
from Data.modules.common.corpus import CorpusLayout
from Data.modules.common.paths import normalize_path_key

from .semantic_types import SEMANTIC_SCHEMA_VERSION


CATALOG_FILENAME = "dataset-catalog.json"
CATALOG_SCHEMA_VERSION = 1


class CatalogError(Exception):
    def __init__(self, message: str, *, code: str = "catalog_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def catalog_path(corpus: CorpusLayout | Path) -> Path:
    if isinstance(corpus, CorpusLayout):
        root = Path(corpus.datasets_manifests)
    else:
        root = Path(corpus)
    return root / CATALOG_FILENAME


def _portable_rel(path: str | None, corpus_root: Path | None) -> str | None:
    if not path:
        return None
    try:
        p = Path(path)
        if corpus_root is not None:
            try:
                return str(p.resolve().relative_to(Path(corpus_root).resolve()))
            except (ValueError, OSError):
                pass
        return str(path)
    except OSError:
        return str(path)


def compact_catalog_entry(
    dataset: Mapping[str, Any],
    *,
    corpus_root: Path | None = None,
    versions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a compact catalog row with semantic fields + portable paths."""
    ds_id = str(dataset.get("datasetId") or dataset.get("dataset_id") or "").strip()
    if not ds_id:
        raise CatalogError("catalog entry missing datasetId", code="catalog_missing_id")
    meta = dataset.get("metadata") if isinstance(dataset.get("metadata"), dict) else {}
    semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
    if not semantic and isinstance(dataset.get("semanticProfile"), dict):
        semantic = dict(dataset["semanticProfile"])

    display_name = (
        semantic.get("displayName")
        or meta.get("displayName")
        or dataset.get("displayName")
        or dataset.get("name")
        or ds_id
    )
    entry: dict[str, Any] = {
        "datasetId": ds_id,
        "name": str(dataset.get("name") or display_name),
        "displayName": str(display_name),
        "displayNameSource": semantic.get("displayNameSource")
        or meta.get("displayNameSource")
        or None,
        "sourceType": dataset.get("sourceType") or dataset.get("source_type"),
        "status": dataset.get("status"),
        "contentHash": dataset.get("contentHash") or dataset.get("content_hash"),
        "rowCount": dataset.get("rowCount") if dataset.get("rowCount") is not None else dataset.get("row_count"),
        "byteSize": dataset.get("byteSize") if dataset.get("byteSize") is not None else dataset.get("byte_size"),
        "detectedFormat": dataset.get("detectedFormat") or dataset.get("detected_format"),
        "originalFilename": dataset.get("originalFilename") or dataset.get("original_filename"),
        "rawPath": _portable_rel(
            dataset.get("rawPath") or dataset.get("raw_path"),
            corpus_root,
        ),
        "primaryCategory": semantic.get("primaryCategory") or meta.get("primaryCategory"),
        "secondaryCategory": semantic.get("secondaryCategory") or meta.get("secondaryCategory"),
        "categoryPath": list(semantic.get("categoryPath") or meta.get("categoryPath") or []),
        "tags": list(semantic.get("tags") or meta.get("semanticTags") or meta.get("tags") or []),
        "confidence": semantic.get("confidence"),
        "reviewRequired": semantic.get("reviewRequired")
        if semantic.get("reviewRequired") is not None
        else meta.get("semanticReviewRequired"),
        "updatedAt": dataset.get("updatedAt") or dataset.get("updated_at"),
        "createdAt": dataset.get("createdAt") or dataset.get("created_at"),
    }
    if versions:
        entry["versions"] = [
            {
                "versionId": v.get("versionId") or v.get("version_id"),
                "versionLabel": v.get("versionLabel") or v.get("version_label"),
                "status": v.get("status"),
                "kind": v.get("kind"),
                "contentHash": v.get("contentHash") or v.get("content_hash"),
                "rowCount": v.get("rowCount") if v.get("rowCount") is not None else v.get("row_count"),
                "storagePath": _portable_rel(
                    v.get("storagePath") or v.get("storage_path"),
                    corpus_root,
                ),
            }
            for v in versions[:20]
        ]
    # Strip Nones for compactness
    return {k: v for k, v in entry.items() if v is not None}


def build_catalog_document(
    entries: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": CATALOG_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "entryCount": len(entries),
        "entries": entries,
        "truth": {
            "catalogIsDerived": True,
            "datasetStoreIsCanonical": True,
            "sidecarsAreRecoveryEvidence": True,
            "brainStateMustBeVerified": True,
            "semanticSchemaVersion": SEMANTIC_SCHEMA_VERSION,
        },
    }


def validate_catalog(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CatalogError("catalog must be an object", code="catalog_invalid")
    schema = int(payload.get("schemaVersion") or payload.get("schema_version") or 0)
    if schema != CATALOG_SCHEMA_VERSION:
        raise CatalogError(f"unsupported catalog schemaVersion={schema}", code="catalog_schema")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise CatalogError("catalog.entries must be a list", code="catalog_entries")
    truth = payload.get("truth")
    if truth is not None and not isinstance(truth, dict):
        raise CatalogError("catalog.truth must be an object", code="catalog_truth")
    normalized_entries: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise CatalogError("catalog entry must be an object", code="catalog_entry")
        ds_id = str(item.get("datasetId") or item.get("dataset_id") or "").strip()
        if not ds_id:
            raise CatalogError("catalog entry missing datasetId", code="catalog_missing_id")
        normalized_entries.append(item)
    out = build_catalog_document(
        normalized_entries,
        generated_at=payload.get("generatedAt") or payload.get("generated_at"),
    )
    if isinstance(truth, dict):
        out["truth"] = {
            **out["truth"],
            **{k: v for k, v in truth.items() if k not in {"chain_of_thought", "chainOfThought"}},
        }
    return out


def write_catalog(path: Path, document: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = validate_catalog(dict(document))
    atomic_write_text(path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n")
    return path


def read_catalog(path: Path) -> dict[str, Any]:
    """Read and validate catalog. Raises CatalogError on corruption — never mutates DB."""
    path = Path(path)
    if not path.is_file():
        raise CatalogError("catalog file not found", code="catalog_missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"catalog unreadable: {exc}", code="catalog_corrupt") from exc
    return validate_catalog(raw)


def read_catalog_status(path: Path) -> dict[str, Any]:
    """Soft-read helper: returns validity without raising (still never touches DB)."""
    try:
        doc = read_catalog(path)
        return {"valid": True, "catalog": doc, "path": str(path)}
    except CatalogError as exc:
        return {
            "valid": False,
            "error": exc.message,
            "code": exc.code,
            "path": str(path),
            "truth": {
                "catalogIsDerived": True,
                "datasetStoreIsCanonical": True,
                "corruptCatalogMustNotTouchDb": True,
            },
        }


def build_catalog_from_store(store: Any, corpus: CorpusLayout) -> dict[str, Any]:
    """Snapshot all datasets from DatasetStore into a derived catalog document."""
    from .store import utc_now

    corpus_root = Path(corpus.root)
    entries: list[dict[str, Any]] = []
    datasets = store.list_datasets(limit=10_000)
    for ds in datasets:
        pub = ds.public_dict() if hasattr(ds, "public_dict") else dict(ds)
        versions_raw = store.list_versions(ds.dataset_id) if hasattr(store, "list_versions") else []
        versions = [v.public_dict() if hasattr(v, "public_dict") else dict(v) for v in versions_raw]
        entries.append(compact_catalog_entry(pub, corpus_root=corpus_root, versions=versions))
    # Stable order for diffs
    entries.sort(key=lambda e: str(e.get("datasetId") or ""))
    return build_catalog_document(entries, generated_at=utc_now())


def refresh_catalog_entry(
    corpus: CorpusLayout,
    dataset: Mapping[str, Any],
    *,
    versions: list[Mapping[str, Any]] | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Update one entry in the on-disk catalog (rebuilds full snapshot when needed)."""
    path = catalog_path(corpus)
    corpus_root = Path(corpus.root)
    entry = compact_catalog_entry(dataset, corpus_root=corpus_root, versions=versions)
    if path.is_file():
        status = read_catalog_status(path)
        if status.get("valid"):
            doc = status["catalog"]
            entries = [e for e in doc.get("entries") or [] if e.get("datasetId") != entry["datasetId"]]
            entries.append(entry)
            entries.sort(key=lambda e: str(e.get("datasetId") or ""))
            from .store import utc_now

            document = build_catalog_document(entries, generated_at=utc_now())
            write_catalog(path, document)
            return document
        # Corrupt catalog: rebuild from store when available; else write single-entry catalog.
    if store is not None:
        document = build_catalog_from_store(store, corpus)
        write_catalog(path, document)
        return document
    from .store import utc_now

    document = build_catalog_document([entry], generated_at=utc_now())
    write_catalog(path, document)
    return document


def catalog_public_path_key(path: Path) -> str:
    try:
        return normalize_path_key(str(path.resolve()))
    except OSError:
        return normalize_path_key(str(path))
