"""Knowledge Library read projections — bounded list/overview helpers.

Canonical ownership remains KnowledgeStore. This module holds library-type
normalization, summary projection, and query parameter validation so the
operator Library UI never becomes a second Knowledge authority.
"""

from __future__ import annotations

import re
from typing import Any

# Canonical library type ids used for filters / sidebar counts.
# Labels are presentation; ids are durable filter keys.
LIBRARY_TYPE_IDS: tuple[str, ...] = (
    "document",
    "book",
    "research_paper",
    "market_data",
    "financial_data",
    "code",
    "web",
    "note",
    "conversation",
    "image",
    "table",
    "other",
)

LIBRARY_TYPE_LABELS: dict[str, str] = {
    "document": "Documenten",
    "book": "Boeken",
    "research_paper": "Research Papers",
    "market_data": "Markt Data",
    "financial_data": "Financiële Data",
    "code": "Code",
    "web": "Web Content",
    "note": "Notities",
    "conversation": "Gesprekken",
    "image": "Afbeeldingen",
    "table": "Tabellen",
    "other": "Overige",
}

# Map SourceIngestion SourceKind / chunk source_type / parsers → library type.
_KIND_TO_LIBRARY: dict[str, str] = {
    "document": "document",
    "office": "document",
    "plain_text": "document",
    "book": "book",
    "research_paper": "research_paper",
    "paper": "research_paper",
    "market_data": "market_data",
    "financial_data": "financial_data",
    "dataset": "table",
    "structured": "table",
    "table": "table",
    "source_code": "code",
    "code": "code",
    "web": "web",
    "web_content": "web",
    "note": "note",
    "notes": "note",
    "manual": "note",
    "conversation": "conversation",
    "chat": "conversation",
    "image": "image",
    "binary": "other",
    "archive": "other",
    "secret": "other",
    "unknown": "other",
    "file": "document",
    "research_upload": "document",
}

_MIME_TO_LIBRARY: dict[str, str] = {
    "application/pdf": "document",
    "text/markdown": "document",
    "text/plain": "document",
    "text/csv": "table",
    "application/json": "table",
    "application/x-parquet": "table",
    "application/vnd.apache.parquet": "table",
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/gif": "image",
    "text/x-python": "code",
    "text/javascript": "code",
    "application/typescript": "code",
}

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,63}$")

LIBRARY_SORTS = frozenset(
    {
        "updated_desc",
        "updated_asc",
        "created_desc",
        "created_asc",
        "title_asc",
        "title_desc",
        "size_desc",
        "size_asc",
        "relevance",
    }
)

LIBRARY_MAX_LIMIT = 100
LIBRARY_DEFAULT_LIMIT = 50


def normalize_library_type(raw: str | None) -> str:
    """Map a provenance/kind/parser hint to a canonical library type id."""
    if not raw:
        return "other"
    key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if key in LIBRARY_TYPE_LABELS:
        return key
    return _KIND_TO_LIBRARY.get(key, "other")


def infer_library_type(
    *,
    explicit: str | None = None,
    source: str | None = None,
    parser: str | None = None,
    mime_type: str | None = None,
    trust_metadata: dict[str, Any] | None = None,
    chunk_source_type: str | None = None,
) -> str:
    """Deterministic library type from canonical provenance — never invents books/papers.

    Order:
      1. explicit library_type column / trust_metadata.library_type
      2. trust_metadata.detection.kind (SourceIngestion)
      3. mime_type
      4. chunk/document source_type when typed
      5. parser family
      6. source string prefixes (manual/note/research_upload/…)
      7. other
    """
    trust = trust_metadata if isinstance(trust_metadata, dict) else {}
    candidates: list[str | None] = [
        explicit,
        trust.get("library_type") if isinstance(trust.get("library_type"), str) else None,
    ]
    detection = trust.get("detection") if isinstance(trust.get("detection"), dict) else {}
    if detection.get("kind"):
        candidates.append(str(detection.get("kind")))
    mime = mime_type or (str(trust.get("mime_type")) if trust.get("mime_type") else None)
    if mime:
        mime_key = mime.split(";")[0].strip().lower()
        candidates.append(_MIME_TO_LIBRARY.get(mime_key))
        if mime_key.startswith("image/"):
            candidates.append("image")
        elif mime_key.startswith("text/x-") or mime_key in {"text/javascript", "application/typescript"}:
            candidates.append("code")
    if chunk_source_type:
        candidates.append(chunk_source_type)
    if parser:
        p = parser.lower()
        if "pdf" in p or "office" in p or "document" in p:
            candidates.append("document")
        elif "code" in p:
            candidates.append("code")
        elif "parquet" in p or "csv" in p or "structured" in p:
            candidates.append("table")
        elif "image" in p or "ocr" in p:
            candidates.append("image")
        else:
            candidates.append(parser)
    if source:
        s = source.lower()
        if s in {"manual", "note", "notes"} or s.startswith("note:"):
            candidates.append("note")
        elif s.startswith("upload:") or s == "research_upload":
            # Uploads are typed by detection/mime above; fall through to document only
            # when no stronger signal exists.
            candidates.append("document")
        elif "conversation" in s or s.startswith("chat"):
            candidates.append("conversation")
        elif s.startswith("web") or "http" in s:
            candidates.append("web")
        else:
            candidates.append(source)

    for cand in candidates:
        if not cand:
            continue
        normalized = normalize_library_type(cand)
        # Prefer concrete types over generic "other" when earlier signals exist.
        if normalized != "other":
            return normalized
    return "other"


def normalize_tag(raw: str) -> str | None:
    """Normalize a single tag token. Returns None when invalid."""
    token = str(raw or "").strip().lower().lstrip("#")
    if not token:
        return None
    token = token.replace(" ", "-")
    if not _TAG_RE.match(token):
        # Soft-sanitize: keep alnum/._/-
        cleaned = re.sub(r"[^a-z0-9._/-]+", "-", token).strip("-")
        if not cleaned or not _TAG_RE.match(cleaned):
            return None
        token = cleaned
    return token[:64]


def extract_tags(trust_metadata: dict[str, Any] | None) -> list[str]:
    """Pull tags from canonical trust_metadata without inventing values."""
    if not isinstance(trust_metadata, dict):
        return []
    raw = trust_metadata.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p for p in re.split(r"[,;\s]+", raw) if p]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = normalize_tag(part)
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def validate_library_sort(sort: str | None, *, has_query: bool) -> str:
    """Return a safe sort key. Relevance only when q is present."""
    key = (sort or "").strip().lower() or ("relevance" if has_query else "updated_desc")
    if key == "relevantie":
        key = "relevance"
    if key not in LIBRARY_SORTS:
        raise ValueError(f"Invalid library sort: {sort}")
    if key == "relevance" and not has_query:
        return "updated_desc"
    return key


def clamp_library_limit(limit: int | None) -> int:
    if limit is None:
        return LIBRARY_DEFAULT_LIMIT
    return max(1, min(int(limit), LIBRARY_MAX_LIMIT))


def document_summary_dict(
    *,
    document_id: str,
    title: str,
    source: str,
    status: str,
    size_bytes: int | None,
    created_at: str,
    updated_at: str,
    library_type: str,
    tags: list[str],
    parser: str | None = None,
    content_hash: str | None = None,
    trust_metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Lightweight library row — never includes content/chunks/embeddings."""
    trust = trust_metadata if isinstance(trust_metadata, dict) else {}
    page_count = trust.get("page_count")
    if page_count is not None:
        try:
            page_count = int(page_count)
        except (TypeError, ValueError):
            page_count = None
    mime = trust.get("mime_type")
    return {
        "id": document_id,
        "title": title,
        "source": source,
        "status": status,
        "library_type": normalize_library_type(library_type),
        "library_type_label": LIBRARY_TYPE_LABELS.get(
            normalize_library_type(library_type), LIBRARY_TYPE_LABELS["other"]
        ),
        "size_bytes": size_bytes,
        "size_measured": size_bytes is not None,
        "created_at": created_at,
        "updated_at": updated_at,
        "tags": list(tags),
        "parser": parser,
        "content_hash": content_hash,
        "mime_type": mime if isinstance(mime, str) else None,
        "page_count": page_count,
        "error": error,
        "truth": {
            "summary_excludes_content": True,
            "summary_excludes_chunks": True,
            "unmeasured_size_is_not_zero": size_bytes is None,
        },
    }
