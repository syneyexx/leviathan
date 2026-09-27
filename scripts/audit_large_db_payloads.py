#!/usr/bin/env python3
"""W177 — audit central SQLite TEXT/BLOB columns for large / unbounded payloads.

Scans schema + sampled cell sizes, classifies each column, and writes a JSON
report. Dataset bulk corpora are already file-backed via storage_path; this
script documents that. KnowledgeStore redesign is out of scope — unbounded
document/chunk content is classified and noted, not migrated here.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# Full scan output is ephemeral — do not commit machine-local raw scans.
DEFAULT_OUT = ROOT / "Data" / "backend" / "data" / "artifacts" / "large_payload_db_audit.full.json"
DEFAULT_SUMMARY_OUT = ROOT / "Data" / "backend" / "tests" / "large_payload_db_audit.summary.json"
# Legacy single-DB default — prefer --domains or settings three-DB paths.
DEFAULT_DB = ROOT / "Data" / "backend" / "data" / "leviathan_control.db"
DEFAULT_SAMPLE_LIMIT = 5000
FULL_SCAN_SENTINEL = 10**12

# Classification thresholds (bytes)
METADATA_MAX = 64 * 1024  # typical config/schema JSON
REASONABLE_MAX = 256 * 1024  # embeddings / bounded blobs
LARGE_CELL = 256 * 1024
LARGE_COLUMN_TOTAL = 10 * 1024 * 1024

# Known schema roles — avoid false "fix" recommendations
DATASET_FILE_REF_COLUMNS = {
    ("datasets", "raw_path"),
    ("dataset_versions", "storage_path"),
    ("dataset_files", "path"),
    ("dataset_indexes", "storage_path"),
    ("dataset_jobs", "log_path"),
}

# Bulk content that would require KnowledgeStore redesign to externalize
KNOWLEDGE_UNBOUNDED = {
    ("knowledge_documents", "content"),
    ("knowledge_chunks", "content"),
}

# Intentionally bounded binary vectors
REASONABLE_BY_ROLE = {
    ("knowledge_chunk_embeddings", "embedding"),
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _classify(
    *,
    table: str,
    column: str,
    col_type: str,
    max_len: int,
    total_len: int,
    row_count: int,
    null_count: int,
) -> dict[str, Any]:
    key = (table, column)
    notes: list[str] = []

    if key in DATASET_FILE_REF_COLUMNS:
        return {
            "classification": "metadata_sized",
            "role": "file_ref",
            "notes": [
                "Path reference only — bulk corpus lives on disk under corpus/datasets.",
                "No KnowledgeStore redesign required; already file-backed.",
            ],
            "recommendedAction": "none",
        }

    if key in KNOWLEDGE_UNBOUNDED:
        return {
            "classification": "unbounded",
            "role": "bulk_text_inline",
            "notes": [
                "Inline document/chunk body without schema size bound.",
                "Moving to file refs would redesign KnowledgeStore — out of scope for W177.",
            ],
            "recommendedAction": "document_only",
        }

    if key in REASONABLE_BY_ROLE:
        return {
            "classification": "reasonable",
            "role": "embedding_blob",
            "notes": ["Fixed-dimension embedding vector blob — expected in central DB."],
            "recommendedAction": "none",
        }

    ctype = (col_type or "").upper()
    is_blob = "BLOB" in ctype
    is_text = "TEXT" in ctype or ctype in {"", "CLOB"} or not ctype

    if max_len <= METADATA_MAX and total_len < LARGE_COLUMN_TOTAL:
        classification = "metadata_sized"
        notes.append("Max cell and column total within metadata-sized bounds.")
        action = "none"
    elif max_len <= REASONABLE_MAX and (is_blob or total_len < LARGE_COLUMN_TOTAL * 2):
        classification = "reasonable"
        notes.append("Within reasonable bounds for structured payloads / small blobs.")
        action = "none"
    elif max_len >= LARGE_CELL or total_len >= LARGE_COLUMN_TOTAL:
        classification = "large"
        notes.append("Observed large cells or column total; review if payload belongs on disk.")
        # Dataset JSON metadata columns that grew large — prefer file refs only if clearly bulk corpus
        if table.startswith("dataset_") or table == "datasets":
            if column.endswith("_json") or column in {"result_json", "checkpoint_json", "config_json"}:
                notes.append(
                    "Dataset table JSON — typically job/metadata, not row corpus. "
                    "No clear win to externalize without redesigning job receipts."
                )
                action = "document_only"
            else:
                action = "document_only"
        else:
            action = "document_only"
    else:
        classification = "metadata_sized"
        notes.append("Default metadata-sized classification.")
        action = "none"

    # Schema without NOT NULL size bound + TEXT looking like body storage
    if is_text and column in {"content", "body", "payload", "report_markdown", "patch_text"}:
        if classification != "unbounded":
            classification = "unbounded" if max_len > METADATA_MAX or row_count > 0 else classification
            if classification == "unbounded":
                notes.append("Column name suggests unbounded body storage.")
                action = "document_only"

    if is_blob and classification == "metadata_sized" and max_len > 0:
        classification = "reasonable"
        notes.append("Non-empty BLOB reclassified as reasonable.")

    return {
        "classification": classification,
        "role": "blob" if is_blob else "text",
        "notes": notes,
        "recommendedAction": action,
        "stats": {
            "maxLen": max_len,
            "totalLen": total_len,
            "rowCount": row_count,
            "nullCount": null_count,
        },
    }


def audit_database(
    db_path: Path,
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    full_scan: bool = False,
    domain: str | None = None,
) -> dict[str, Any]:
    if not db_path.is_file():
        return {
            "schemaVersion": 2,
            "generatedAt": _utcnow(),
            "databasePath": str(db_path),
            "databaseDomain": domain,
            "databaseExists": False,
            "boundedMode": not full_scan,
            "columns": [],
            "summary": {
                "metadata_sized": 0,
                "reasonable": 0,
                "large": 0,
                "unbounded": 0,
            },
            "truth": {
                "knowledgeStoreRedesignSkipped": True,
                "datasetBulkAlreadyFileBacked": True,
                "clearWinFixesApplied": [],
                "note": "Database file missing — empty audit; create DB then re-run.",
            },
        }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        columns_out: list[dict[str, Any]] = []
        for table in tables:
            try:
                info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            except sqlite3.Error:
                continue
            for col in info:
                col_name = str(col[1])
                col_type = str(col[2] or "")
                ctype_u = col_type.upper()
                if not (
                    "TEXT" in ctype_u
                    or "BLOB" in ctype_u
                    or "CLOB" in ctype_u
                    or ctype_u in {"", "JSON"}
                ):
                    if col_name not in {
                        "content",
                        "body",
                        "payload",
                        "embedding",
                        "result_json",
                        "config_json",
                        "metadata_json",
                        "schema_json",
                        "provenance_json",
                        "checkpoint_json",
                        "payload_json",
                    } and not col_name.endswith("_json"):
                        continue
                try:
                    # Bounded mode (default): sample only — never force full aggregates.
                    row = conn.execute(
                        f"""
                        SELECT
                          COUNT(*) AS row_count,
                          SUM(CASE WHEN "{col_name}" IS NULL THEN 1 ELSE 0 END) AS null_count,
                          COALESCE(MAX(LENGTH("{col_name}")), 0) AS max_len,
                          COALESCE(SUM(LENGTH("{col_name}")), 0) AS total_len
                        FROM (
                          SELECT "{col_name}" FROM "{table}" LIMIT ?
                        )
                        """,
                        (sample_limit,),
                    ).fetchone()
                    stats_row = row
                    if full_scan:
                        full = conn.execute(
                            f"""
                            SELECT
                              COUNT(*) AS row_count,
                              SUM(CASE WHEN "{col_name}" IS NULL THEN 1 ELSE 0 END) AS null_count,
                              COALESCE(MAX(LENGTH("{col_name}")), 0) AS max_len,
                              COALESCE(SUM(LENGTH("{col_name}")), 0) AS total_len
                            FROM "{table}"
                            """
                        ).fetchone()
                        stats_row = full
                except sqlite3.Error as exc:
                    columns_out.append(
                        {
                            "table": table,
                            "column": col_name,
                            "declaredType": col_type,
                            "classification": "metadata_sized",
                            "error": str(exc),
                            "notes": ["Failed to measure column; defaulted metadata_sized."],
                            "recommendedAction": "none",
                        }
                    )
                    continue

                max_len = int(stats_row["max_len"] or 0)
                total_len = int(stats_row["total_len"] or 0)
                row_count = int(stats_row["row_count"] or 0)
                null_count = int(stats_row["null_count"] or 0)
                classified = _classify(
                    table=table,
                    column=col_name,
                    col_type=col_type,
                    max_len=max_len,
                    total_len=total_len,
                    row_count=row_count,
                    null_count=null_count,
                )
                columns_out.append(
                    {
                        "table": table,
                        "column": col_name,
                        "declaredType": col_type,
                        **classified,
                    }
                )

        summary = {"metadata_sized": 0, "reasonable": 0, "large": 0, "unbounded": 0}
        for item in columns_out:
            key = str(item.get("classification") or "metadata_sized")
            if key not in summary:
                summary[key] = 0
            summary[key] += 1

        clear_wins: list[str] = []
        dataset_unbounded = [
            c
            for c in columns_out
            if c.get("classification") == "unbounded"
            and str(c.get("table") or "").startswith("dataset")
            and c.get("role") == "bulk_text_inline"
        ]
        truth_note = (
            "Dataset bulk payloads already use file refs (storage_path / raw_path). "
            "No clear-win schema move without KnowledgeStore redesign."
        )
        if dataset_unbounded:
            truth_note = (
                "Unexpected unbounded dataset columns found — documented only; "
                "KnowledgeStore-style redesign deferred."
            )

        return {
            "schemaVersion": 2,
            "wave": "W177",
            "generatedAt": _utcnow(),
            "databasePath": str(db_path.resolve()),
            "databaseDomain": domain,
            "databaseExists": True,
            "boundedMode": not full_scan,
            "sampleLimit": sample_limit,
            "fullScan": bool(full_scan),
            "thresholds": {
                "metadataMaxBytes": METADATA_MAX,
                "reasonableMaxBytes": REASONABLE_MAX,
                "largeCellBytes": LARGE_CELL,
                "largeColumnTotalBytes": LARGE_COLUMN_TOTAL,
            },
            "columns": columns_out,
            "summary": summary,
            "truth": {
                "knowledgeStoreRedesignSkipped": True,
                "datasetBulkAlreadyFileBacked": True,
                "clearWinFixesApplied": clear_wins,
                "note": truth_note,
                "notCentralSingleDb": True,
            },
        }
    finally:
        conn.close()


def audit_canonical_domains(
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    full_scan: bool = False,
) -> dict[str, Any]:
    """Audit CONTROL / KNOWLEDGE / MARKET separately — never as one central DB."""
    try:
        from Data.backend.config import load_settings

        settings = load_settings()
        paths = {
            "CONTROL": Path(settings.control_database_path),
            "KNOWLEDGE": Path(settings.knowledge_database_path),
            "MARKET": Path(settings.market_database_path),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schemaVersion": 2,
            "generatedAt": _utcnow(),
            "error": f"settings_unavailable: {exc}",
            "domains": {},
        }
    domains: dict[str, Any] = {}
    for name, path in paths.items():
        domains[name] = audit_database(
            path, sample_limit=sample_limit, full_scan=full_scan, domain=name
        )
    return {
        "schemaVersion": 2,
        "wave": "W177",
        "generatedAt": _utcnow(),
        "mode": "three_database",
        "boundedMode": not full_scan,
        "fullScan": bool(full_scan),
        "domains": domains,
        "truth": {
            "notCentralSingleDb": True,
            "canonicalDomains": ["CONTROL", "KNOWLEDGE", "MARKET"],
            "heavyFullScanOptIn": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional single DB path (legacy). Prefer --domains.",
    )
    parser.add_argument("--domains", action="store_true", default=True,
                        help="Audit CONTROL/KNOWLEDGE/MARKET (default).")
    parser.add_argument("--single-db", action="store_true",
                        help="Force single --db path mode.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="HEAVY: run complete aggregates over every table (opt-in).",
    )
    args = parser.parse_args(argv)
    if args.single_db or args.db is not None:
        db_path = args.db or DEFAULT_DB
        report = audit_database(
            db_path,
            sample_limit=max(100, int(args.sample_limit)),
            full_scan=bool(args.full_scan),
            domain="SINGLE",
        )
    else:
        report = audit_canonical_domains(
            sample_limit=max(100, int(args.sample_limit)),
            full_scan=bool(args.full_scan),
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Always refresh the bounded committed summary (no per-column firehose).
    summary = {
        "program": "large_payload_db_audit",
        "artifactKind": "bounded_summary",
        "schemaVersion": report.get("schemaVersion"),
        "generatedAt": report.get("generatedAt"),
        "mode": report.get("mode") or "single",
        "boundedMode": report.get("boundedMode", True),
        "fullScan": report.get("fullScan", False),
        "truth": {
            **dict(report.get("truth") or {}),
            "rawScanNotCommitted": True,
            "fullReportPath": str(args.out),
        },
        "domains": {},
        "result": "SUMMARY_ONLY",
    }
    for name, body in (report.get("domains") or {}).items():
        if not isinstance(body, dict):
            continue
        cols = body.get("columns") or []
        notable = [
            {
                "table": c.get("table"),
                "column": c.get("column"),
                "classification": c.get("classification"),
                "role": c.get("role"),
            }
            for c in cols
            if c.get("classification") in {"unbounded", "large", "file_ref"}
        ][:32]
        summary["domains"][name] = {
            "databaseExists": body.get("databaseExists"),
            "boundedMode": body.get("boundedMode"),
            "summary": body.get("summary"),
            "columnCount": len(cols),
            "notableColumns": notable,
        }
    if not summary["domains"] and report.get("summary") is not None:
        summary["legacySingleDbSummary"] = report.get("summary")
        summary["columnCount"] = len(report.get("columns") or [])
    DEFAULT_SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_SUMMARY_OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "out": str(args.out),
                "summaryOut": str(DEFAULT_SUMMARY_OUT),
                "mode": report.get("mode") or "single",
                "boundedMode": report.get("boundedMode", True),
                "fullScan": report.get("fullScan", False),
                "summary": report.get("summary")
                or {
                    d: (report.get("domains") or {}).get(d, {}).get("summary")
                    for d in ("CONTROL", "KNOWLEDGE", "MARKET")
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
