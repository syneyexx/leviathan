"""Incremental SQLite FTS5 index for safe plugin documentation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from platform_db import PlatformDatabase, utc_now

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".hades",
        "secrets",
        ".secrets",
    }
)
_SKIP_FILE_NAMES = frozenset({".env", ".env.local", "credentials.json", "secrets.json"})
_TEXT_EXTENSIONS = frozenset({".md", ".mdc", ".txt", ".rst", ".json"})
_SECRET_RE = re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]", re.I)
_MAX_FILE_BYTES = 256_000
_MAX_DOC_CHARS = 48_000


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def ensure_plugin_knowledge_schema(db: PlatformDatabase) -> None:
    with db.connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS plugin_knowledge_docs (
                id TEXT PRIMARY KEY,
                plugin_id TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(plugin_id, rel_path)
            );
            CREATE INDEX IF NOT EXISTS idx_plugin_knowledge_docs_plugin
                ON plugin_knowledge_docs(plugin_id, updated_at DESC);

            CREATE VIRTUAL TABLE IF NOT EXISTS plugin_knowledge_fts USING fts5(
                doc_id UNINDEXED,
                plugin_id UNINDEXED,
                rel_path UNINDEXED,
                title,
                content,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )


def _safe_relative(path: Path, root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except Exception:
        return None
    parts = rel.parts
    if any(part in _SKIP_DIR_NAMES or part.startswith(".") for part in parts[:-1]):
        return None
    if rel.name in _SKIP_FILE_NAMES:
        return None
    return rel.as_posix()


def _iter_doc_paths(plugin: dict[str, Any]) -> Iterable[tuple[str, Path]]:
    root = Path(str(plugin.get("local_path") or "")).expanduser()
    if not root.is_dir():
        return
    manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
    yield ("manifest", root / "hades-plugin.json")
    for pattern in ("README*", "readme*"):
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                rel = _safe_relative(path, root)
                if rel:
                    yield (rel, path)
    for folder in (".cursor/rules", "skills", "rules", "docs"):
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _TEXT_EXTENSIONS and path.suffix:
                continue
            rel = _safe_relative(path, root)
            if rel:
                yield (rel, path)
    knowledge_paths = manifest.get("knowledge_paths") or manifest.get("docs_paths") or []
    if isinstance(knowledge_paths, list):
        for entry in knowledge_paths:
            rel = str(entry or "").strip().replace("\\", "/")
            if not rel or ".." in rel.split("/"):
                continue
            path = root / rel
            if path.is_file():
                safe = _safe_relative(path, root)
                if safe:
                    yield (safe, path)


def _read_doc_text(path: Path) -> str:
    if path.name == "hades-plugin.json" and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            pass
    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    if len(raw) > _MAX_FILE_BYTES:
        raw = raw[:_MAX_FILE_BYTES]
    text = raw.decode("utf-8", errors="replace")
    if _SECRET_RE.search(text):
        return ""
    return text[:_MAX_DOC_CHARS]


def reindex_plugin(db: PlatformDatabase, plugin: dict[str, Any]) -> dict[str, Any]:
    ensure_plugin_knowledge_schema(db)
    plugin_id = str(plugin.get("id") or "")
    if not plugin_id:
        return {"indexed": 0, "removed": 0}
    indexed = 0
    removed = 0
    seen_paths: set[str] = set()
    with db.connection() as conn:
        for rel_path, path in _iter_doc_paths(plugin):
            if not path.is_file():
                continue
            seen_paths.add(rel_path)
            content = _read_doc_text(path)
            if not content.strip():
                continue
            content_hash = _sha256_text(content)
            existing = conn.execute(
                "SELECT id, content_hash FROM plugin_knowledge_docs WHERE plugin_id=? AND rel_path=?",
                (plugin_id, rel_path),
            ).fetchone()
            if existing and str(existing["content_hash"]) == content_hash:
                continue
            doc_id = str(existing["id"]) if existing else f"pkd_{hashlib.sha1(f'{plugin_id}:{rel_path}'.encode()).hexdigest()[:24]}"
            now = utc_now()
            if existing:
                conn.execute("DELETE FROM plugin_knowledge_fts WHERE doc_id=?", (doc_id,))
                removed += 1
            title = rel_path
            conn.execute(
                """
                INSERT INTO plugin_knowledge_docs(id, plugin_id, rel_path, title, content_hash, updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(plugin_id, rel_path) DO UPDATE SET
                    title=excluded.title,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (doc_id, plugin_id, rel_path, title, content_hash, now),
            )
            conn.execute(
                "INSERT INTO plugin_knowledge_fts(doc_id, plugin_id, rel_path, title, content) VALUES(?,?,?,?,?)",
                (doc_id, plugin_id, rel_path, title, content),
            )
            indexed += 1
        stale = conn.execute(
            "SELECT id, rel_path FROM plugin_knowledge_docs WHERE plugin_id=?",
            (plugin_id,),
        ).fetchall()
        for row in stale:
            if row["rel_path"] not in seen_paths:
                conn.execute("DELETE FROM plugin_knowledge_fts WHERE doc_id=?", (row["id"],))
                conn.execute("DELETE FROM plugin_knowledge_docs WHERE id=?", (row["id"],))
                removed += 1
    return {"indexed": indexed, "removed": removed, "plugin_id": plugin_id}


def remove_plugin_index(db: PlatformDatabase, plugin_id: str) -> None:
    ensure_plugin_knowledge_schema(db)
    with db.connection() as conn:
        rows = conn.execute("SELECT id FROM plugin_knowledge_docs WHERE plugin_id=?", (plugin_id,)).fetchall()
        for row in rows:
            conn.execute("DELETE FROM plugin_knowledge_fts WHERE doc_id=?", (row["id"],))
        conn.execute("DELETE FROM plugin_knowledge_docs WHERE plugin_id=?", (plugin_id,))


def _fts_query(query: str) -> str:
    tokens = [re.sub(r"[^\w]+", "", part) for part in query.split() if part.strip()]
    tokens = [part for part in tokens if len(part) >= 2]
    if not tokens:
        return ""
    return " OR ".join(f'"{part}"' for part in tokens[:12])


def search_plugin_knowledge(
    db: PlatformDatabase,
    query: str,
    *,
    plugin_id: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    ensure_plugin_knowledge_schema(db)
    match = _fts_query(query)
    if not match:
        return []
    sql = """
        SELECT d.plugin_id, d.rel_path, d.title, snippet(plugin_knowledge_fts, 4, '[', ']', '…', 24) AS excerpt,
               bm25(plugin_knowledge_fts) AS rank
        FROM plugin_knowledge_fts f
        JOIN plugin_knowledge_docs d ON d.id = f.doc_id
        WHERE plugin_knowledge_fts MATCH ?
    """
    params: list[Any] = [match]
    if plugin_id:
        sql += " AND d.plugin_id = ?"
        params.append(plugin_id)
    sql += " ORDER BY rank LIMIT ?"
    params.append(max(1, min(int(limit), 50)))
    with db.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "plugin_id": row["plugin_id"],
            "path": row["rel_path"],
            "title": row["title"],
            "excerpt": row["excerpt"],
            "rank": row["rank"],
        }
        for row in rows
    ]


def is_static_knowledge_query(arguments: dict[str, Any]) -> str | None:
    if not isinstance(arguments, dict):
        return None
    allowed = {"query", "q", "search", "text", "limit", "offset"}
    if any(key not in allowed for key in arguments):
        return None
    for key in ("query", "q", "search", "text"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def knowledge_fast_path_result(
    db: PlatformDatabase,
    plugin: dict[str, Any],
    tool: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    from runtime.tool_contracts import classify_tool_action

    contract = classify_tool_action(tool)
    if contract.get("mutating"):
        return None
    query = is_static_knowledge_query(arguments)
    if not query:
        return None
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    action = str(contract.get("action") or "").lower()
    if not (
        meta.get("static_knowledge")
        or meta.get("knowledge_fast_path")
        or action in {"search", "query", "read", "help", "docs"}
    ):
        return None
    matches = search_plugin_knowledge(db, query, plugin_id=str(plugin.get("id") or ""), limit=int(arguments.get("limit") or 8))
    if not matches:
        return None
    structured = {
        "source": "plugin_knowledge_index",
        "query": query,
        "matches": matches,
    }
    return {
        "status": "completed",
        "exit_code": 0,
        "output": json.dumps(structured, ensure_ascii=False, indent=2),
        "stdout": "",
        "stderr": "",
        "structured_output": structured,
        "invocation_type": "autonomous",
        "metadata": {"knowledge_fast_path": True, "cacheable": True},
    }
