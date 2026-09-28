"""sqlite_ops pool — heavy READ-ONLY operator SQLite execution.

NEVER performs INSERT/UPDATE/DELETE/DDL/VACUUM/ANALYZE/wal_checkpoint write
modes/ATTACH/restore/migration. Read-only connections + SQL authorizer +
progress-handler deadlines.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool

_DEFAULT_DEADLINE_S = 60.0
_MAX_ROWS = 10_000
_MAX_CELL_CHARS = 4_096
_MAX_RESULT_BYTES = 8 * 1024 * 1024


class _QueryCancelled(RuntimeError):
    def __init__(self, code: str = "SQLITE_QUERY_CANCELLED") -> None:
        super().__init__(code)
        self.code = code


def _cancel_check(ctx: dict[str, Any], job: Any) -> bool:
    store = ctx.get("job_store")
    if store is None:
        return False
    try:
        current = store.get(job.job_id)
        state = getattr(current, "state", None)
        value = getattr(state, "value", state)
        return str(value).upper() in {"CANCEL_REQUESTED", "CANCELLED"}
    except Exception:  # noqa: BLE001
        return False


def _open_readonly(path: Path) -> sqlite3.Connection:
    from Data.modules.common.sqlite_policy import open_sqlite_connection
    from Data.modules.sqlite_manager.sql_safety import open_readonly_connection

    return open_readonly_connection(str(Path(path).resolve()), open_fn=open_sqlite_connection)


def _install_deadline(conn: sqlite3.Connection, *, deadline: float, cancel_fn) -> None:
    def _progress() -> int:
        if time.monotonic() >= deadline:
            return 1
        if cancel_fn():
            return 1
        return 0

    try:
        conn.set_progress_handler(_progress, 1000)
    except Exception:  # noqa: BLE001
        pass


def _serialize_rows(rows: list[Any], columns: list[str]) -> tuple[list[dict[str, Any]], int, bool]:
    out: list[dict[str, Any]] = []
    nbytes = 0
    truncated = False
    for row in rows:
        item: dict[str, Any] = {}
        if hasattr(row, "keys"):
            for col in columns:
                val = row[col]
                if isinstance(val, (bytes, bytearray)):
                    text = f"<blob:{len(val)}>"
                else:
                    text = val if not isinstance(val, str) else val[:_MAX_CELL_CHARS]
                    if isinstance(val, str) and len(val) > _MAX_CELL_CHARS:
                        truncated = True
                item[col] = text
        else:
            for idx, col in enumerate(columns):
                val = row[idx] if idx < len(row) else None
                item[col] = val
        encoded = json.dumps(item, default=str)
        nbytes += len(encoded)
        if nbytes > _MAX_RESULT_BYTES:
            truncated = True
            break
        out.append(item)
    return out, nbytes, truncated


def _paths_from_settings(settings: Any) -> dict[str, Path]:
    db_paths = getattr(settings, "database_paths", None)
    if db_paths is not None:
        return {
            "CONTROL": Path(db_paths.control),
            "KNOWLEDGE": Path(db_paths.knowledge),
            "MARKET": Path(db_paths.market),
        }
    return {"CONTROL": Path(settings.database_path)}


def _resolve_domain(settings: Any, domain: str) -> Path:
    key = str(domain or "CONTROL").strip().upper()
    paths = _paths_from_settings(settings)
    if key not in paths:
        raise ValueError(f"UNKNOWN_DATABASE_DOMAIN:{domain}")
    # Refuse arbitrary ATTACH / path escape — only canonical DatabasePaths.
    return paths[key]


def _refuse_writes(sql: str) -> None:
    from Data.modules.sqlite_manager.sql_safety import classify_read_sql

    upper = str(sql or "").strip().upper()
    forbidden = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        "VACUUM",
        "ANALYZE",
        "ATTACH",
        "DETACH",
        "CREATE",
        "DROP",
        "ALTER",
        "REINDEX",
        "PRAGMA WRITABLE_SCHEMA",
        "WAL_CHECKPOINT",
    )
    for token in forbidden:
        if token in upper and not upper.startswith("SELECT") and "PRAGMA TABLE_INFO" not in upper:
            # Still let classify_read_sql be authoritative.
            break
    try:
        classify_read_sql(sql)
    except ValueError as exc:
        raise PermissionError(f"SQLITE_QUERY_FORBIDDEN:{exc}") from exc
    if any(
        tok in upper
        for tok in (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "VACUUM",
            "ANALYZE",
            "ATTACH ",
            "WAL_CHECKPOINT",
            "WRITABLE_SCHEMA",
        )
    ):
        # Extra defense for authorizer bypass attempts in text.
        if not upper.lstrip().startswith(("SELECT", "WITH", "PRAGMA")):
            raise PermissionError("SQLITE_QUERY_FORBIDDEN")


def execute_sqlite_ops(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    cap = str(getattr(job, "capability_id", "") or "")
    args = dict(getattr(job, "arguments", None) or {})
    settings = ctx["settings"]
    domain = str(args.get("domain") or "CONTROL")
    deadline_s = float(args.get("deadline_seconds") or _DEFAULT_DEADLINE_S)
    deadline = time.monotonic() + max(1.0, deadline_s)
    sql = str(args.get("sql") or "")
    table = str(args.get("table") or "")
    limit = min(int(args.get("limit") or 200), _MAX_ROWS)
    offset = max(0, int(args.get("offset") or 0))
    search = args.get("search")
    fmt = str(args.get("format") or "json").lower()
    params: list[Any] = []

    try:
        path = _resolve_domain(settings, domain)
        if cap.endswith(".scan") or (not sql and table):
            cols = "*"
            if args.get("columns"):
                cols = ", ".join(str(c) for c in args["columns"])
            search_cols = list(args.get("search_columns") or [])
            where = ""
            if search and search_cols:
                clauses = [f"CAST({c} AS TEXT) LIKE ?" for c in search_cols]
                where = " WHERE (" + " OR ".join(clauses) + ")"
                params = [f"%{search}%"] * len(search_cols)
            elif search and not search_cols:
                raise PermissionError("SQLITE_SEARCH_FAILED:search_columns_required")
            sql = f"SELECT {cols} FROM {table}{where} LIMIT {limit} OFFSET {offset}"

        if cap.endswith(".export") and not sql and table:
            sql = f"SELECT * FROM {table} LIMIT {limit}"

        _refuse_writes(sql)
        conn = _open_readonly(path)
        try:
            _install_deadline(
                conn,
                deadline=deadline,
                cancel_fn=lambda: _cancel_check(ctx, job),
            )
            cur = conn.execute(sql, params)
            columns = [d[0] for d in (cur.description or [])]
            rows_raw = cur.fetchmany(limit + 1)
            more = len(rows_raw) > limit
            rows_raw = rows_raw[:limit]
            rows, nbytes, truncated = _serialize_rows(rows_raw, columns)
        finally:
            conn.close()

        result: dict[str, Any] = {
            "domain": domain.upper(),
            "capability": cap,
            "columns": columns,
            "rowCount": len(rows),
            "bytesEmitted": nbytes,
            "truncated": truncated or more,
            "elapsedSeconds": max(0.0, deadline_s - (deadline - time.monotonic())),
            "rows": rows if not cap.endswith(".export") or nbytes < 256_000 else [],
        }

        if cap.endswith(".export") or nbytes > 256_000:
            art_root = Path(getattr(getattr(settings, "artifacts", None), "root", ".") or ".")
            out = art_root / "sqlite_ops" / f"{job.job_id}.{'csv' if fmt == 'csv' else 'jsonl'}"
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(out.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                if fmt == "csv" and columns:
                    handle.write(",".join(columns) + "\n")
                    for row in rows:
                        handle.write(
                            ",".join(json.dumps(row.get(c), default=str) for c in columns) + "\n"
                        )
                else:
                    for row in rows:
                        handle.write(json.dumps(row, default=str) + "\n")
            tmp.replace(out)
            result["artifactRef"] = str(out)
            result["rows"] = []
            result["exportFormat"] = fmt
            result["provenance"] = {
                "domain": domain.upper(),
                "query": sql[:2000],
                "rowCount": len(rows),
                "generatedAt": time.time(),
            }

        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
            result=result,
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"rowCount": len(rows), "artifactRef": result.get("artifactRef")}
    except PermissionError as exc:
        code = str(exc).split(":")[0] if ":" in str(exc) else "SQLITE_QUERY_FORBIDDEN"
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=code,
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": code}
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "cancelled" in msg.lower() or time.monotonic() >= deadline:
            code = "SQLITE_QUERY_TIMEOUT" if time.monotonic() >= deadline else "SQLITE_QUERY_CANCELLED"
        else:
            code = "SQLITE_OPS_FAILED"
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=f"{code}:{msg}"[:500],
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": code}


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    return execute_sqlite_ops(ctx, job)


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("sqlite_ops", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
