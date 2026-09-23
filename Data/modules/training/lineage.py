"""Model lineage edges for the improvement flywheel (U318)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class LineageEdge:
    edge_id: str
    parent_id: str
    child_id: str
    relation: str  # base|tokenizer|mixture|run|adapter|merge|quantization|eval|deployment
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)

    def public_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "relation": self.relation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "truth": {"lineage_is_append_only": True},
        }


class ModelLineageStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_lineage_edges (
                    edge_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_lineage_child "
                "ON model_lineage_edges(child_id, created_at)"
            )

    def add_edge(
        self,
        *,
        parent_id: str,
        child_id: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
    ) -> LineageEdge:
        edge = LineageEdge(
            edge_id=f"lin_{uuid.uuid4().hex[:12]}",
            parent_id=parent_id,
            child_id=child_id,
            relation=relation,
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_lineage_edges(
                    edge_id, parent_id, child_id, relation, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.edge_id,
                    edge.parent_id,
                    edge.child_id,
                    edge.relation,
                    json.dumps(edge.metadata),
                    edge.created_at,
                ),
            )
        return edge

    def list_for_model(self, model_id: str, *, limit: int = 100) -> list[LineageEdge]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM model_lineage_edges
                WHERE parent_id = ? OR child_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (model_id, model_id, limit),
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def _from_row(self, row: sqlite3.Row) -> LineageEdge:
        return LineageEdge(
            edge_id=row["edge_id"],
            parent_id=row["parent_id"],
            child_id=row["child_id"],
            relation=row["relation"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
        )
