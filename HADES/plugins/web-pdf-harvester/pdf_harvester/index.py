"""Persistent resource index (SQLite canonical + JSONL/txt exports)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .models import ResourceRecord, utc_now_iso
from .storage import StoragePaths, atomic_write_text


class ResourceIndex:
    def __init__(self, paths: StoragePaths) -> None:
        self.paths = paths.ensure()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.paths.resources_sqlite), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS resources (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                status TEXT NOT NULL,
                download_status TEXT NOT NULL,
                hostname TEXT,
                title TEXT,
                sha256 TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(status);
            CREATE INDEX IF NOT EXISTS idx_resources_download ON resources(download_status);
            CREATE INDEX IF NOT EXISTS idx_resources_host ON resources(hostname);
            CREATE INDEX IF NOT EXISTS idx_resources_sha ON resources(sha256);
            CREATE INDEX IF NOT EXISTS idx_resources_url ON resources(normalized_url);
            """
        )
        self._conn.commit()

    def upsert(self, record: ResourceRecord) -> ResourceRecord:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM resources WHERE id=?", (record.id,)).fetchone()
            existing = ResourceRecord.from_dict(json.loads(row["payload"])) if row else None
            if existing:
                # Preserve download fields unless new record has fresher download info
                if record.download_status == "not_downloaded" and existing.download_status != "not_downloaded":
                    record.download_status = existing.download_status
                    record.local_path = existing.local_path or record.local_path
                    record.sha256 = existing.sha256 or record.sha256
                if not record.title and existing.title:
                    record.title = existing.title
                if not record.click_path and existing.click_path:
                    record.click_path = existing.click_path
            payload = json.dumps(record.to_dict(), ensure_ascii=False)
            self._conn.execute(
                """
                INSERT INTO resources(id, payload, normalized_url, status, download_status, hostname, title, sha256, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    normalized_url=excluded.normalized_url,
                    status=excluded.status,
                    download_status=excluded.download_status,
                    hostname=excluded.hostname,
                    title=excluded.title,
                    sha256=excluded.sha256,
                    updated_at=excluded.updated_at
                """,
                (
                    record.id,
                    payload,
                    record.normalized_url,
                    record.status,
                    record.download_status,
                    record.hostname,
                    record.title,
                    record.sha256,
                    utc_now_iso(),
                ),
            )
            self._conn.commit()
            return record

    def get(self, resource_id: str) -> ResourceRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM resources WHERE id=?", (resource_id,)).fetchone()
        if not row:
            return None
        return ResourceRecord.from_dict(json.loads(row["payload"]))

    def get_by_normalized_url(self, normalized_url: str) -> ResourceRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM resources WHERE normalized_url=? LIMIT 1",
                (normalized_url,),
            ).fetchone()
        if not row:
            return None
        return ResourceRecord.from_dict(json.loads(row["payload"]))

    def find_by_sha256(self, sha256: str) -> ResourceRecord | None:
        if not sha256:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM resources WHERE sha256=? AND download_status='downloaded' LIMIT 1",
                (sha256,),
            ).fetchone()
        if not row:
            return None
        return ResourceRecord.from_dict(json.loads(row["payload"]))

    def list(
        self,
        *,
        status: str | None = None,
        download_status: str | None = None,
        hostname: str | None = None,
        category: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if download_status:
            clauses.append("download_status=?")
            params.append(download_status)
        if hostname:
            clauses.append("hostname=?")
            params.append(hostname.lower())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT payload FROM resources{where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        items: list[dict[str, Any]] = []
        search_l = (search or "").strip().lower()
        category_l = (category or "").strip().lower()
        for row in rows:
            data = json.loads(row["payload"])
            if category_l and category_l not in str(data.get("category") or "").lower():
                continue
            if search_l:
                hay = " ".join(
                    str(data.get(k) or "")
                    for k in ("title", "author", "description", "filename", "normalized_url", "anchor_text", "category")
                ).lower()
                if search_l not in hay:
                    continue
            items.append(data)
        total = len(items)
        page = items[offset : offset + max(1, limit)]
        return {"total": total, "offset": offset, "limit": limit, "items": page}

    def all_confirmed(self) -> list[ResourceRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM resources WHERE status='confirmed'"
            ).fetchall()
        return [ResourceRecord.from_dict(json.loads(r["payload"])) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS c FROM resources").fetchone()["c"]
            confirmed = self._conn.execute(
                "SELECT COUNT(*) AS c FROM resources WHERE status='confirmed'"
            ).fetchone()["c"]
            candidates = self._conn.execute(
                "SELECT COUNT(*) AS c FROM resources WHERE status='candidate'"
            ).fetchone()["c"]
            downloaded = self._conn.execute(
                "SELECT COUNT(*) AS c FROM resources WHERE download_status='downloaded'"
            ).fetchone()["c"]
            failed = self._conn.execute(
                "SELECT COUNT(*) AS c FROM resources WHERE download_status='failed'"
            ).fetchone()["c"]
            partial = self._conn.execute(
                "SELECT COUNT(*) AS c FROM resources WHERE download_status='partial'"
            ).fetchone()["c"]
        return {
            "total": int(total),
            "confirmed": int(confirmed),
            "candidates": int(candidates),
            "downloaded": int(downloaded),
            "failed": int(failed),
            "partial": int(partial),
        }

    def size_estimate(self) -> dict[str, Any]:
        confirmed = self.all_confirmed()
        known = 0
        unknown = 0
        pending = 0
        for item in confirmed:
            if item.download_status == "downloaded" and item.local_path and Path(item.local_path).exists():
                continue
            pending += 1
            if item.content_length and item.content_length > 0:
                known += int(item.content_length)
            else:
                unknown += 1
        return {
            "pending_count": pending,
            "known_total_bytes": known,
            "unknown_size_count": unknown,
            "known_total_human": _human_bytes(known),
        }

    def export_jsonl_and_links(self) -> dict[str, str]:
        confirmed = [r for r in self.all_confirmed()]
        # Also export candidates for debugging but links file is confirmed only
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM resources ORDER BY updated_at ASC").fetchall()
        lines = [row["payload"] for row in rows]
        atomic_write_text(self.paths.resources_jsonl, "\n".join(lines) + ("\n" if lines else ""))
        link_lines = []
        seen: set[str] = set()
        for record in confirmed:
            url = record.final_url or record.normalized_url or record.discovered_url
            if url and url not in seen:
                seen.add(url)
                link_lines.append(url)
        atomic_write_text(self.paths.pdf_links_txt, "\n".join(link_lines) + ("\n" if link_lines else ""))
        return {
            "index_path": str(self.paths.resources_jsonl),
            "sqlite_path": str(self.paths.resources_sqlite),
            "links_export_path": str(self.paths.pdf_links_txt),
        }

    def upsert_many(self, records: Iterable[ResourceRecord]) -> int:
        count = 0
        for record in records:
            self.upsert(record)
            count += 1
        return count


def _human_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num} B"
