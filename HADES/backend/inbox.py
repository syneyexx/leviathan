"""Persistent in-app inbox for results, failures and required input."""

from __future__ import annotations

from typing import Any

from database import new_id, utc_now


class InboxService:
    def __init__(self, db: Any) -> None:
        self.db = db

    def create(
        self,
        *,
        kind: str,
        title: str,
        body: str = "",
        ref_type: str | None = None,
        ref_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        conversation_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        if dedupe_key:
            existing = self.db.get_inbox_by_dedupe(dedupe_key)
            if existing and existing.get("status") != "archived":
                return existing
            if existing and existing.get("status") == "archived":
                # Archived history must not reserve a live dedupe key forever.
                # Releasing only the key preserves the historical row while the
                # database unique index still serializes concurrent re-creates.
                self.db.update_inbox_item(existing["id"], dedupe_key=None, updated_at=utc_now())
        record = {
            "id": new_id("inbox"),
            "kind": kind,
            "title": title[:200],
            "body": body[:4000],
            "ref_type": ref_type,
            "ref_id": ref_id,
            "project_id": project_id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "status": "unread",
            "dedupe_key": dedupe_key,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        return self.db.insert_inbox_item(record)

    def list(self, *, status: str | None = None, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.list_inbox_items(status=status, kind=kind, limit=limit)

    def mark_read(self, item_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.db.connection() as db:
            db.execute(
                "UPDATE inbox_items SET status='read', updated_at=? WHERE id=? AND status!='archived'",
                (now, item_id),
            )
            row = db.execute("SELECT * FROM inbox_items WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def mark_refs_read(self, ref_type: str, ref_id: str) -> int:
        return self.db.mark_inbox_refs(ref_type, ref_id, status="read")

    def archive(self, item_id: str) -> dict[str, Any] | None:
        return self.db.update_inbox_item(item_id, status="archived", updated_at=utc_now())
