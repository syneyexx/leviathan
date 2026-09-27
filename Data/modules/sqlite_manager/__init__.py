"""SQLite Manager — operator control plane over the three canonical LEVIATHAN databases.

Extends (does not replace) platform operator surfaces. Writes require an explicit
database domain and never silently fall back to Control.

This module is NOT a second persistence layer, migration engine, or DB writer.
Canonical owners remain: DatabasePaths, table_ownership, sqlite_policy,
MigrationRunner / db_upgrade, and the DB Commit Coordinator.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from Data.backend.db_upgrade import domain_schema_version
from Data.backend.table_ownership import is_fts_shadow_table
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.common.sqlite_policy import (
    WriteClass,
    ControlWriteSpec,
    control_write,
    is_transient_sqlite_error,
    open_sqlite_connection,
    sqlite_metrics_snapshot,
    write_transaction,
)

from .ownership_audit import (
    classify_table_in_domain,
    domain_ownership_description,
    ownership_audit_for_tables,
)
from .sql_safety import (
    classify_read_sql,
    classify_write_sql,
    disable_extension_loading,
    install_mutate_authorizer,
    open_readonly_connection,
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_QUERY_LIMIT = 1000
_MAX_PAGE_SIZE = 200
_DEFAULT_PAGE_SIZE = 50
_MAX_CELL_CHARS_DEFAULT = 4_096
_MAX_FILTER_CLAUSES = 16
_INTEGRITY_MAX_ERRORS = 100

# Operator mutations are tiny admin CONTROL_WRITE operations — never COMMIT_WRITE
# fallbacks and never arbitrary coordinator SQL. expected_max_rows is enforced.
_MUTATE_SPEC = ControlWriteSpec(
    operation="sqlite_manager.mutate",
    expected_max_rows=32,
    expected_max_ms=2_000.0,
)


class SqliteManagerError(RuntimeError):
    def __init__(self, code: str, message: str, *, domain: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.domain = domain


@dataclass
class SqliteManagerRuntimeDeps:
    """Optional runtime adapters — never invent metrics when absent."""

    backup_list: Callable[[], list[dict[str, Any]]] | None = None
    db_commit_settings: Callable[[], dict[str, Any]] | None = None
    db_commit_spool_stats: Callable[[], dict[str, Any]] | None = None


@dataclass(frozen=True)
class SqliteManager:
    paths: DatabasePaths
    allow_writes: bool = True
    runtime: SqliteManagerRuntimeDeps = field(default_factory=SqliteManagerRuntimeDeps)

    # --- domain helpers -------------------------------------------------

    def _domain(self, domain: DatabaseDomain | str) -> DatabaseDomain:
        if isinstance(domain, DatabaseDomain):
            return domain
        try:
            return DatabaseDomain(str(domain).upper())
        except ValueError as exc:
            raise SqliteManagerError(
                "UNKNOWN_DATABASE_DOMAIN",
                f"Unknown database domain: {domain!r}",
            ) from exc

    def _path_for(self, domain: DatabaseDomain | str) -> Path:
        key = self._domain(domain)
        return self.paths.path_for(key)

    def _require_file(self, key: DatabaseDomain) -> Path:
        path = self.paths.path_for(key)
        if not path.is_file():
            raise SqliteManagerError(
                "DATABASE_MISSING",
                f"{key.value} database file does not exist: {path}",
                domain=key.value,
            )
        return path

    def _quote_ident(self, name: str, *, domain: str) -> str:
        if not _IDENT.match(name):
            raise SqliteManagerError(
                "TABLE_NOT_FOUND",
                f"Invalid identifier: {name!r}",
                domain=domain,
            )
        return f'"{name}"'

    # --- A. overview ----------------------------------------------------

    def list_databases(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for domain, path in self.paths:
            out.append(self._status_for(domain, path))
        return out

    def database_status(self, domain: DatabaseDomain | str) -> dict[str, Any]:
        key = self._domain(domain)
        path = self.paths.path_for(key)
        return self._status_for(key, path)

    def _status_for(self, domain: DatabaseDomain, path: Path) -> dict[str, Any]:
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        wal = path.with_suffix(path.suffix + "-wal")
        shm = path.with_suffix(path.suffix + "-shm")
        schema = domain_schema_version(path) if exists else 0
        table_count: int | str = "UNMEASURED"
        journal_mode: str = "UNMEASURED"
        page_count: int | str = "UNMEASURED"
        page_size: int | str = "UNMEASURED"
        health = "MISSING" if not exists else "UNKNOWN"
        readiness = "MISSING" if not exists else "UNKNOWN"
        if exists:
            try:
                conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
                try:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
                    ).fetchone()
                    table_count = int(row[0] if row is not None else 0)
                    jm = conn.execute("PRAGMA journal_mode").fetchone()
                    journal_mode = str(jm[0] if jm is not None else "UNMEASURED")
                    pc = conn.execute("PRAGMA page_count").fetchone()
                    page_count = int(pc[0]) if pc is not None else "UNMEASURED"
                    ps = conn.execute("PRAGMA page_size").fetchone()
                    page_size = int(ps[0]) if ps is not None else "UNMEASURED"
                    health = "OK"
                    readiness = "READY"
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                if is_transient_sqlite_error(exc):
                    health = "BUSY"
                    readiness = "BUSY"
                else:
                    health = "ERROR"
                    readiness = "ERROR"
        return {
            "domain": domain.value,
            "path": str(path),
            "exists": exists,
            "sizeBytes": size,
            "walExists": wal.is_file(),
            "walSizeBytes": wal.stat().st_size if wal.is_file() else 0,
            "shmExists": shm.is_file(),
            "schemaVersion": schema,
            "tableCount": table_count,
            "journalMode": journal_mode,
            "pageCount": page_count,
            "pageSize": page_size,
            "health": health,
            "readiness": readiness,
            "ownershipDescription": domain_ownership_description(domain),
        }

    # --- C. table browser -----------------------------------------------

    def list_tables(self, domain: DatabaseDomain | str) -> list[dict[str, Any]]:
        key = self._domain(domain)
        path = self._require_file(key)
        conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
        try:
            rows = conn.execute(
                "SELECT name, type, sql FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                name = str(row[0] if not isinstance(row, sqlite3.Row) else row["name"])
                typ = str(row[1] if not isinstance(row, sqlite3.Row) else row["type"])
                create_sql = row[2] if not isinstance(row, sqlite3.Row) else row["sql"]
                ownership = classify_table_in_domain(name, key)
                out.append(
                    {
                        "name": name,
                        "type": typ,
                        "owningDomain": ownership.get("declaredOwner"),
                        "ownershipState": ownership["ownershipState"],
                        "presentDomain": key.value,
                        "isVirtual": bool(
                            create_sql
                            and "VIRTUAL TABLE" in str(create_sql).upper()
                        )
                        or is_fts_shadow_table(name)
                        or (name.endswith("_fts")),
                        "columnCount": None,  # filled cheaply below
                        "indexCount": None,
                    }
                )
                # Lightweight column/index counts without full detail payload.
                cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
                idxs = conn.execute(f'PRAGMA index_list("{name}")').fetchall()
                out[-1]["columnCount"] = len(cols)
                out[-1]["indexCount"] = len(idxs)
                out[-1]["columns"] = [
                    {
                        "name": r[1] if not isinstance(r, sqlite3.Row) else r["name"],
                        "type": r[2] if not isinstance(r, sqlite3.Row) else r["type"],
                        "notnull": bool(r[3] if not isinstance(r, sqlite3.Row) else r["notnull"]),
                        "pk": int(r[5] if not isinstance(r, sqlite3.Row) else r["pk"] or 0),
                    }
                    for r in cols
                ]
                out[-1]["indexes"] = [
                    {
                        "name": r[1] if not isinstance(r, sqlite3.Row) else r["name"],
                        "unique": bool(r[2] if not isinstance(r, sqlite3.Row) else r["unique"]),
                    }
                    for r in idxs
                ]
            return out
        finally:
            conn.close()

    def table_detail(self, domain: DatabaseDomain | str, table: str) -> dict[str, Any]:
        key = self._domain(domain)
        path = self._require_file(key)
        if not _IDENT.match(table):
            raise SqliteManagerError(
                "TABLE_NOT_FOUND",
                f"Invalid table name: {table!r}",
                domain=key.value,
            )
        conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
        try:
            master = conn.execute(
                "SELECT name, type, sql FROM sqlite_master "
                "WHERE name = ? AND type IN ('table','view')",
                (table,),
            ).fetchone()
            if master is None:
                raise SqliteManagerError(
                    "TABLE_NOT_FOUND",
                    f"Table {table!r} not found in {key.value}",
                    domain=key.value,
                )
            name = str(master[0] if not isinstance(master, sqlite3.Row) else master["name"])
            typ = str(master[1] if not isinstance(master, sqlite3.Row) else master["type"])
            create_sql = master[2] if not isinstance(master, sqlite3.Row) else master["sql"]
            cols = [
                {
                    "name": r[1] if not isinstance(r, sqlite3.Row) else r["name"],
                    "type": (r[2] if not isinstance(r, sqlite3.Row) else r["type"]) or "",
                    "notnull": bool(r[3] if not isinstance(r, sqlite3.Row) else r["notnull"]),
                    "defaultValue": r[4] if not isinstance(r, sqlite3.Row) else r["dflt_value"],
                    "pk": int(r[5] if not isinstance(r, sqlite3.Row) else r["pk"] or 0),
                }
                for r in conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            ]
            indexes: list[dict[str, Any]] = []
            for r in conn.execute(f'PRAGMA index_list("{name}")').fetchall():
                idx_name = r[1] if not isinstance(r, sqlite3.Row) else r["name"]
                unique = bool(r[2] if not isinstance(r, sqlite3.Row) else r["unique"])
                origin = r[3] if not isinstance(r, sqlite3.Row) else r["origin"]
                cols_idx = [
                    {
                        "seq": c[0] if not isinstance(c, sqlite3.Row) else c["seqno"],
                        "name": c[2] if not isinstance(c, sqlite3.Row) else c["name"],
                    }
                    for c in conn.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                ]
                indexes.append(
                    {
                        "name": idx_name,
                        "unique": unique,
                        "origin": origin,
                        "columns": cols_idx,
                    }
                )
            fks = [
                {
                    "id": r[0] if not isinstance(r, sqlite3.Row) else r["id"],
                    "seq": r[1] if not isinstance(r, sqlite3.Row) else r["seq"],
                    "table": r[2] if not isinstance(r, sqlite3.Row) else r["table"],
                    "from": r[3] if not isinstance(r, sqlite3.Row) else r["from"],
                    "to": r[4] if not isinstance(r, sqlite3.Row) else r["to"],
                    "onUpdate": r[5] if not isinstance(r, sqlite3.Row) else r["on_update"],
                    "onDelete": r[6] if not isinstance(r, sqlite3.Row) else r["on_delete"],
                }
                for r in conn.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
            ]
            ownership = classify_table_in_domain(name, key)
            pk_cols = [c["name"] for c in sorted(cols, key=lambda c: c["pk"]) if c["pk"] > 0]
            unique_indexes = [i for i in indexes if i["unique"]]
            row_count_state = "UNMEASURED"
            row_count: int | None = None
            # Bounded estimate via sqlite_stat1 when present; never full scan.
            try:
                stat = conn.execute(
                    "SELECT stat FROM sqlite_stat1 WHERE tbl = ? LIMIT 1",
                    (name,),
                ).fetchone()
                if stat is not None:
                    raw = str(stat[0] if not isinstance(stat, sqlite3.Row) else stat["stat"])
                    # sqlite_stat1.stat starts with approximate row count.
                    approx = int(str(raw).split()[0])
                    row_count = approx
                    row_count_state = "ESTIMATED"
            except sqlite3.Error:
                pass
            return {
                "domain": key.value,
                "name": name,
                "type": typ,
                "createSql": create_sql,
                "columns": cols,
                "indexes": indexes,
                "uniqueIndexes": unique_indexes,
                "foreignKeys": fks,
                "primaryKey": pk_cols,
                "owningDomain": ownership.get("declaredOwner"),
                "ownershipState": ownership["ownershipState"],
                "presentDomain": key.value,
                "isVirtual": bool(
                    create_sql and "VIRTUAL TABLE" in str(create_sql).upper()
                )
                or name.endswith("_fts")
                or is_fts_shadow_table(name),
                "rowCount": row_count,
                "rowCountState": row_count_state,
                "rowEditAvailable": bool(pk_cols) and typ == "table" and not (
                    create_sql and "VIRTUAL TABLE" in str(create_sql).upper()
                ),
            }
        finally:
            conn.close()

    # --- D. data browser ------------------------------------------------

    def query_rows(
        self,
        domain: DatabaseDomain | str,
        table: str,
        *,
        offset: int = 0,
        limit: int = _DEFAULT_PAGE_SIZE,
        columns: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        search: str | None = None,
        order_by: list[str] | None = None,
    ) -> dict[str, Any]:
        key = self._domain(domain)
        path = self._require_file(key)
        detail = self.table_detail(key, table)
        col_meta = {c["name"]: c for c in detail["columns"]}
        if not col_meta:
            raise SqliteManagerError(
                "TABLE_NOT_FOUND",
                f"No columns for {table!r}",
                domain=key.value,
            )
        if columns:
            select_cols = []
            for c in columns:
                if c not in col_meta:
                    raise SqliteManagerError(
                        "QUERY_FAILED",
                        f"Unknown column {c!r}",
                        domain=key.value,
                    )
                select_cols.append(c)
        else:
            select_cols = list(col_meta.keys())
        capped = max(1, min(int(limit), _MAX_PAGE_SIZE))
        off = max(0, int(offset))
        where_parts: list[str] = []
        params: list[Any] = []
        for clause in (filters or [])[:_MAX_FILTER_CLAUSES]:
            col = str(clause.get("column") or "")
            op = str(clause.get("op") or "=").upper()
            if col not in col_meta:
                raise SqliteManagerError(
                    "QUERY_FAILED",
                    f"Unknown filter column {col!r}",
                    domain=key.value,
                )
            qcol = self._quote_ident(col, domain=key.value)
            if op == "IS NULL":
                where_parts.append(f"{qcol} IS NULL")
            elif op == "IS NOT NULL":
                where_parts.append(f"{qcol} IS NOT NULL")
            elif op in {"=", "!=", "<>", ">", "<", ">=", "<="}:
                where_parts.append(f"{qcol} {op} ?")
                params.append(clause.get("value"))
            elif op == "LIKE":
                where_parts.append(f"{qcol} LIKE ?")
                params.append(clause.get("value"))
            else:
                raise SqliteManagerError(
                    "QUERY_FAILED",
                    f"Filter operator not allowed: {op}",
                    domain=key.value,
                )
        if search:
            text_cols = [
                c
                for c, meta in col_meta.items()
                if str(meta.get("type") or "").upper() in {"", "TEXT", "VARCHAR", "CHAR", "CLOB", "JSON"}
                or "CHAR" in str(meta.get("type") or "").upper()
                or "TEXT" in str(meta.get("type") or "").upper()
            ]
            if text_cols:
                like = f"%{search}%"
                ors = " OR ".join(f'{self._quote_ident(c, domain=key.value)} LIKE ?' for c in text_cols)
                where_parts.append(f"({ors})")
                params.extend([like] * len(text_cols))
        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        pk = detail["primaryKey"]
        order_cols: list[str] = []
        if order_by:
            for c in order_by:
                raw = c.strip()
                parts = raw.split()
                name = parts[0]
                direction = "DESC" if len(parts) > 1 and parts[1].upper() == "DESC" else "ASC"
                if name not in col_meta:
                    raise SqliteManagerError(
                        "QUERY_FAILED",
                        f"Unknown order column {name!r}",
                        domain=key.value,
                    )
                order_cols.append(f"{self._quote_ident(name, domain=key.value)} {direction}")
        elif pk:
            order_cols = [self._quote_ident(c, domain=key.value) for c in pk]
        else:
            order_cols = [self._quote_ident(select_cols[0], domain=key.value)]
        order_sql = " ORDER BY " + ", ".join(order_cols)
        qtable = self._quote_ident(table, domain=key.value)
        select_sql = ", ".join(self._quote_ident(c, domain=key.value) for c in select_cols)
        sql = (
            f"SELECT {select_sql} FROM {qtable}{where_sql}{order_sql} "
            f"LIMIT ? OFFSET ?"
        )
        conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
        started = time.perf_counter()
        try:
            cur = conn.execute(sql, [*params, capped + 1, off])
            rows_raw = cur.fetchall()
            truncated = len(rows_raw) > capped
            rows_raw = rows_raw[:capped]
            rows: list[dict[str, Any]] = []
            for r in rows_raw:
                values = list(r)
                cell_map: dict[str, Any] = {}
                identity: dict[str, Any] | None = {}
                for idx, col in enumerate(select_cols):
                    val = values[idx]
                    cell_map[col] = self._serialize_cell(val)
                    if col in pk:
                        identity[col] = val
                if not pk:
                    identity = None
                rows.append({"values": cell_map, "identity": identity})
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "domain": key.value,
                "table": table,
                "columns": select_cols,
                "primaryKey": pk,
                "rows": rows,
                "rowCount": len(rows),
                "offset": off,
                "limit": capped,
                "truncated": truncated,
                "rowEditAvailable": bool(detail["rowEditAvailable"]),
                "elapsedMs": round(elapsed_ms, 3),
            }
        except sqlite3.Error as exc:
            code = "DB_BUSY" if is_transient_sqlite_error(exc) else "QUERY_FAILED"
            raise SqliteManagerError(code, f"{key.value}: {exc}", domain=key.value) from exc
        finally:
            conn.close()

    def _serialize_cell(self, value: Any, *, max_chars: int = _MAX_CELL_CHARS_DEFAULT) -> dict[str, Any]:
        if value is None:
            return {"kind": "null", "value": None, "truncated": False}
        if isinstance(value, (bytes, memoryview)):
            raw = bytes(value)
            preview = raw[:64].hex()
            return {
                "kind": "blob",
                "value": preview,
                "byteLength": len(raw),
                "truncated": len(raw) > 64,
            }
        if isinstance(value, (int, float)):
            return {"kind": "number", "value": value, "truncated": False}
        text = str(value)
        truncated = len(text) > max_chars
        return {
            "kind": "text",
            "value": text[:max_chars] if truncated else text,
            "truncated": truncated,
            "fullLength": len(text),
        }

    # --- E/F. SQL console -----------------------------------------------

    def query(
        self,
        domain: DatabaseDomain | str,
        sql: str,
        *,
        limit: int = 200,
    ) -> dict[str, Any]:
        key = self._domain(domain)
        path = self._require_file(key)
        try:
            classify_read_sql(sql)
        except ValueError as exc:
            code = str(exc)
            if code not in {
                "EMPTY_SQL",
                "READ_ONLY_QUERY",
                "MULTI_STATEMENT_FORBIDDEN",
                "SCHEMA_MUTATION_FORBIDDEN",
            }:
                code = "READ_ONLY_QUERY"
            raise SqliteManagerError(
                code,
                f"{key.value}: query rejected ({code})",
                domain=key.value,
            ) from exc
        from .sql_safety import normalize_sql

        text = normalize_sql(sql)
        capped = max(1, min(int(limit), _MAX_QUERY_LIMIT))
        conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
        started = time.perf_counter()
        try:
            cursor = conn.execute(text)
            colnames = [d[0] for d in (cursor.description or [])]
            rows = cursor.fetchmany(capped + 1)
            truncated = len(rows) > capped
            rows = rows[:capped]
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "domain": key.value,
                "columns": colnames,
                "rows": [list(r) for r in rows],
                "rowCount": len(rows),
                "truncated": truncated,
                "limit": capped,
                "elapsedMs": round(elapsed_ms, 3),
                "mode": "READ",
            }
        except sqlite3.Error as exc:
            code = "DB_BUSY" if is_transient_sqlite_error(exc) else "QUERY_FAILED"
            raise SqliteManagerError(code, f"{key.value}: {exc}", domain=key.value) from exc
        finally:
            conn.close()

    def mutate(
        self,
        domain: DatabaseDomain | str,
        sql: str,
        *,
        confirm_domain: str,
    ) -> dict[str, Any]:
        key = self._domain(domain)
        if not self.allow_writes:
            raise SqliteManagerError(
                "WRITES_DISABLED",
                f"{key.value}: writes are disabled",
                domain=key.value,
            )
        if str(confirm_domain).upper() != key.value:
            raise SqliteManagerError(
                "DOMAIN_CONFIRM_MISMATCH",
                f"confirmDomain {confirm_domain!r} does not match selected domain {key.value}",
                domain=key.value,
            )
        try:
            classify_write_sql(sql)
        except ValueError as exc:
            code = str(exc)
            if code not in {
                "EMPTY_SQL",
                "WRITE_NOT_ALLOWLISTED",
                "MULTI_STATEMENT_FORBIDDEN",
                "SCHEMA_MUTATION_FORBIDDEN",
                "UNBOUNDED_WRITE_FORBIDDEN",
            }:
                code = "WRITE_NOT_ALLOWLISTED"
            raise SqliteManagerError(
                code,
                f"{key.value}: mutation rejected ({code})",
                domain=key.value,
            ) from exc
        from .sql_safety import assert_write_row_bound, normalize_sql

        text = normalize_sql(sql)
        path = self._require_file(key)
        started = time.perf_counter()
        max_rows = int(_MUTATE_SPEC.expected_max_rows)

        def _run(conn: sqlite3.Connection) -> int:
            disable_extension_loading(conn)
            install_mutate_authorizer(conn)
            with write_transaction(
                conn,
                immediate=True,
                store="sqlite_manager",
                operation="sqlite_manager.mutate",
                write_class=WriteClass.CONTROL_WRITE,
            ):
                # Re-install authorizer after BEGIN (authorizer persists on conn).
                cur = conn.execute(text)
                rowcount = int(cur.rowcount if cur.rowcount is not None else -1)
                if rowcount < 0:
                    # Prefer changes() when rowcount is unavailable.
                    try:
                        rowcount = int(conn.execute("SELECT changes()").fetchone()[0])
                    except sqlite3.Error:
                        rowcount = -1
                try:
                    assert_write_row_bound(rowcount, max_rows=max_rows)
                except ValueError as bound_exc:
                    # Abort transaction — do not commit unbounded CONTROL_WRITE.
                    raise SqliteManagerError(
                        str(bound_exc),
                        f"{key.value}: raw mutation affected {rowcount} rows "
                        f"(max {max_rows}); use structured row edit or DB Commit",
                        domain=key.value,
                    ) from bound_exc
                return rowcount

        try:
            rowcount = control_write(path, _run, spec=_MUTATE_SPEC)
        except SqliteManagerError:
            raise
        except sqlite3.Error as exc:
            code = "DB_BUSY" if is_transient_sqlite_error(exc) else "MUTATION_FAILED"
            raise SqliteManagerError(code, f"{key.value}: {exc}", domain=key.value) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "domain": key.value,
            "rowcount": rowcount,
            "ok": True,
            "elapsedMs": round(elapsed_ms, 3),
            "writeClass": WriteClass.CONTROL_WRITE.value,
            "mode": "WRITE",
            "expectedMaxRows": max_rows,
        }

    # --- G. structured row editing --------------------------------------

    def insert_row(
        self,
        domain: DatabaseDomain | str,
        table: str,
        values: dict[str, Any],
        *,
        confirm_domain: str,
    ) -> dict[str, Any]:
        key = self._require_mutate_domain(domain, confirm_domain)
        detail = self.table_detail(key, table)
        if detail["type"] != "table" or detail["isVirtual"]:
            raise SqliteManagerError(
                "ROW_IDENTITY_UNAVAILABLE",
                f"{table}: inserts require a concrete table",
                domain=key.value,
            )
        col_meta = {c["name"]: c for c in detail["columns"]}
        unknown = [c for c in values if c not in col_meta]
        if unknown:
            raise SqliteManagerError(
                "MUTATION_FAILED",
                f"Unknown columns: {unknown}",
                domain=key.value,
            )
        if not values:
            raise SqliteManagerError("EMPTY_SQL", "No values provided", domain=key.value)
        cols = list(values.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(self._quote_ident(c, domain=key.value) for c in cols)
        qtable = self._quote_ident(table, domain=key.value)
        sql = f"INSERT INTO {qtable} ({col_sql}) VALUES ({placeholders})"
        params = [values[c] for c in cols]
        return self._exec_params(key, sql, params, operation="sqlite_manager.insert_row")

    def update_row(
        self,
        domain: DatabaseDomain | str,
        table: str,
        identity: dict[str, Any],
        values: dict[str, Any],
        *,
        confirm_domain: str,
    ) -> dict[str, Any]:
        key = self._require_mutate_domain(domain, confirm_domain)
        detail = self.table_detail(key, table)
        pk = detail["primaryKey"]
        if not detail["rowEditAvailable"] or not pk:
            raise SqliteManagerError(
                "ROW_IDENTITY_UNAVAILABLE",
                f"{table}: ROW_EDIT_UNAVAILABLE (no deterministic primary key)",
                domain=key.value,
            )
        if set(identity.keys()) != set(pk):
            raise SqliteManagerError(
                "ROW_IDENTITY_UNAVAILABLE",
                f"{table}: identity must include primary key columns {pk}",
                domain=key.value,
            )
        col_meta = {c["name"]: c for c in detail["columns"]}
        unknown = [c for c in values if c not in col_meta]
        if unknown:
            raise SqliteManagerError(
                "MUTATION_FAILED",
                f"Unknown columns: {unknown}",
                domain=key.value,
            )
        # Do not allow silently changing PK via values without identity update semantics.
        for pk_col in pk:
            if pk_col in values and values[pk_col] != identity[pk_col]:
                raise SqliteManagerError(
                    "MUTATION_FAILED",
                    f"Primary key column {pk_col!r} cannot be changed via update_row",
                    domain=key.value,
                )
        if not values:
            raise SqliteManagerError("EMPTY_SQL", "No values provided", domain=key.value)
        set_cols = [c for c in values if c not in pk]
        if not set_cols:
            raise SqliteManagerError("EMPTY_SQL", "No updatable values provided", domain=key.value)
        set_sql = ", ".join(f"{self._quote_ident(c, domain=key.value)} = ?" for c in set_cols)
        where_sql = " AND ".join(f"{self._quote_ident(c, domain=key.value)} = ?" for c in pk)
        qtable = self._quote_ident(table, domain=key.value)
        sql = f"UPDATE {qtable} SET {set_sql} WHERE {where_sql}"
        params = [values[c] for c in set_cols] + [identity[c] for c in pk]
        return self._exec_params(key, sql, params, operation="sqlite_manager.update_row")

    def delete_row(
        self,
        domain: DatabaseDomain | str,
        table: str,
        identity: dict[str, Any],
        *,
        confirm_domain: str,
    ) -> dict[str, Any]:
        key = self._require_mutate_domain(domain, confirm_domain)
        detail = self.table_detail(key, table)
        pk = detail["primaryKey"]
        if not detail["rowEditAvailable"] or not pk:
            raise SqliteManagerError(
                "ROW_IDENTITY_UNAVAILABLE",
                f"{table}: ROW_EDIT_UNAVAILABLE (no deterministic primary key)",
                domain=key.value,
            )
        if set(identity.keys()) != set(pk):
            raise SqliteManagerError(
                "ROW_IDENTITY_UNAVAILABLE",
                f"{table}: identity must include primary key columns {pk}",
                domain=key.value,
            )
        where_sql = " AND ".join(f"{self._quote_ident(c, domain=key.value)} = ?" for c in pk)
        qtable = self._quote_ident(table, domain=key.value)
        sql = f"DELETE FROM {qtable} WHERE {where_sql}"
        params = [identity[c] for c in pk]
        return self._exec_params(key, sql, params, operation="sqlite_manager.delete_row")

    def _require_mutate_domain(
        self, domain: DatabaseDomain | str, confirm_domain: str
    ) -> DatabaseDomain:
        key = self._domain(domain)
        if not self.allow_writes:
            raise SqliteManagerError(
                "WRITES_DISABLED",
                f"{key.value}: writes are disabled",
                domain=key.value,
            )
        if str(confirm_domain).upper() != key.value:
            raise SqliteManagerError(
                "DOMAIN_CONFIRM_MISMATCH",
                f"confirmDomain {confirm_domain!r} does not match selected domain {key.value}",
                domain=key.value,
            )
        self._require_file(key)
        return key

    def _exec_params(
        self,
        key: DatabaseDomain,
        sql: str,
        params: list[Any],
        *,
        operation: str,
    ) -> dict[str, Any]:
        path = self.paths.path_for(key)
        started = time.perf_counter()
        spec = ControlWriteSpec(operation=operation, expected_max_rows=8, expected_max_ms=500.0)

        def _run(conn: sqlite3.Connection) -> int:
            disable_extension_loading(conn)
            install_mutate_authorizer(conn)
            with write_transaction(
                conn,
                immediate=True,
                store="sqlite_manager",
                operation=operation,
                write_class=WriteClass.CONTROL_WRITE,
            ):
                cur = conn.execute(sql, params)
                return int(cur.rowcount if cur.rowcount is not None else 0)

        try:
            rowcount = control_write(path, _run, spec=spec)
        except sqlite3.Error as exc:
            code = "DB_BUSY" if is_transient_sqlite_error(exc) else "MUTATION_FAILED"
            raise SqliteManagerError(code, f"{key.value}: {exc}", domain=key.value) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "domain": key.value,
            "rowcount": rowcount,
            "ok": True,
            "elapsedMs": round(elapsed_ms, 3),
            "writeClass": WriteClass.CONTROL_WRITE.value,
            "mode": "WRITE",
            "operation": operation,
        }

    # --- J/K. integrity + WAL -------------------------------------------

    def integrity_check(
        self,
        domain: DatabaseDomain | str,
        *,
        kind: str = "quick_check",
        max_errors: int = _INTEGRITY_MAX_ERRORS,
    ) -> dict[str, Any]:
        key = self._domain(domain)
        path = self._require_file(key)
        kind_norm = str(kind).strip().lower()
        if kind_norm not in {"quick_check", "integrity_check", "foreign_key_check"}:
            raise SqliteManagerError(
                "QUERY_FAILED",
                f"Unknown integrity kind: {kind!r}",
                domain=key.value,
            )
        capped = max(1, min(int(max_errors), 1000))
        conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
        started = time.perf_counter()
        try:
            if kind_norm == "foreign_key_check":
                rows = conn.execute("PRAGMA foreign_key_check").fetchmany(capped + 1)
                truncated = len(rows) > capped
                rows = rows[:capped]
                issues = [list(r) for r in rows]
                ok = len(issues) == 0
                result = "ok" if ok else "issues"
            elif kind_norm == "quick_check":
                rows = conn.execute(f"PRAGMA quick_check({capped})").fetchall()
                messages = [str(r[0]) for r in rows]
                ok = messages == ["ok"]
                result = messages[0] if len(messages) == 1 else messages
                issues = [] if ok else messages
                truncated = False
            else:
                rows = conn.execute(f"PRAGMA integrity_check({capped})").fetchall()
                messages = [str(r[0]) for r in rows]
                ok = messages == ["ok"]
                result = messages[0] if len(messages) == 1 else messages
                issues = [] if ok else messages
                truncated = (not ok) and len(messages) >= capped
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "domain": key.value,
                "kind": kind_norm,
                "ok": ok,
                "result": result,
                "issues": issues,
                "truncated": truncated,
                "elapsedMs": round(elapsed_ms, 3),
            }
        except sqlite3.Error as exc:
            code = "DB_BUSY" if is_transient_sqlite_error(exc) else "QUERY_FAILED"
            raise SqliteManagerError(code, f"{key.value}: {exc}", domain=key.value) from exc
        finally:
            conn.close()

    def wal_checkpoint(
        self,
        domain: DatabaseDomain | str,
        *,
        mode: str = "PASSIVE",
        confirm_domain: str,
    ) -> dict[str, Any]:
        key = self._require_mutate_domain(domain, confirm_domain)
        mode_u = str(mode).strip().upper()
        if mode_u not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise SqliteManagerError(
                "WRITE_NOT_ALLOWLISTED",
                f"Unsupported checkpoint mode: {mode!r}",
                domain=key.value,
            )
        path = self.paths.path_for(key)
        started = time.perf_counter()
        conn = open_sqlite_connection(path)
        try:
            disable_extension_loading(conn)
            # Checkpoint is MAINTENANCE_WRITE — explicit operator action only.
            row = conn.execute(f"PRAGMA wal_checkpoint({mode_u})").fetchone()
            busy = int(row[0]) if row is not None else 0
            log = int(row[1]) if row is not None else 0
            checkpointed = int(row[2]) if row is not None else 0
            conn.commit()
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            code = "DB_BUSY" if is_transient_sqlite_error(exc) else "MUTATION_FAILED"
            raise SqliteManagerError(code, f"{key.value}: {exc}", domain=key.value) from exc
        finally:
            conn.close()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "domain": key.value,
            "mode": mode_u,
            "busy": busy,
            "log": log,
            "checkpointed": checkpointed,
            "ok": True,
            "elapsedMs": round(elapsed_ms, 3),
            "writeClass": WriteClass.MAINTENANCE_WRITE.value,
        }

    # --- L/M. ownership audit -------------------------------------------

    def ownership_audit(self) -> dict[str, Any]:
        present: dict[str, set[str]] = {}
        db_status: list[dict[str, Any]] = []
        for domain, path in self.paths:
            status = self._status_for(domain, path)
            db_status.append(
                {
                    "domain": domain.value,
                    "exists": status["exists"],
                    "schemaVersion": status["schemaVersion"],
                    "path": status["path"],
                }
            )
            if not path.is_file():
                continue
            conn = open_readonly_connection(str(path), open_fn=open_sqlite_connection)
            try:
                names = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                }
                present[domain.value] = names
            finally:
                conn.close()
        audit = ownership_audit_for_tables(present_by_domain=present)
        schema_versions = {d["domain"]: d["schemaVersion"] for d in db_status if d["exists"]}
        schema_inconsistent = len(set(schema_versions.values())) > 1 if schema_versions else False
        if schema_inconsistent:
            audit["findings"].append(
                {
                    "kind": "SCHEMA_VERSION_INCONSISTENCY",
                    "schemaVersions": schema_versions,
                }
            )
            audit["ok"] = False
        for d in db_status:
            if not d["exists"]:
                audit["findings"].append(
                    {
                        "kind": "DATABASE_ABSENT",
                        "domain": d["domain"],
                        "path": d["path"],
                    }
                )
                audit["ok"] = False
        audit["databases"] = db_status
        audit["schemaVersions"] = schema_versions
        return audit

    # --- N/O. runtime ---------------------------------------------------

    def runtime_status(self) -> dict[str, Any]:
        metrics = sqlite_metrics_snapshot()
        backup: dict[str, Any] = {"available": False, "status": "UNMEASURED"}
        if self.runtime.backup_list is not None:
            try:
                items = self.runtime.backup_list()
                latest = items[0] if items else None
                backup = {
                    "available": True,
                    "count": len(items),
                    "latest": latest,
                    "canonicalCoverage": (
                        latest.get("backupSetComplete")
                        if isinstance(latest, dict)
                        else "UNMEASURED"
                    ),
                    "restoreImplication": (
                        "Restore requires explicit confirm via BackupService; "
                        "SQLite Manager never copies live DB files directly."
                    ),
                }
            except Exception as exc:  # noqa: BLE001 — surface honestly
                backup = {"available": False, "status": "ERROR", "error": str(exc)}

        db_commit: dict[str, Any] = {"status": "UNMEASURED"}
        if self.runtime.db_commit_settings is not None:
            try:
                settings = self.runtime.db_commit_settings()
                db_commit = {
                    "settings": settings,
                    "enabled": bool(settings.get("enabled", True)),
                    "workerState": "UNMEASURED",
                    "note": (
                        "Coordinator runs in the db_commit worker process; "
                        "API process reports settings + spool truth only."
                    ),
                }
            except Exception as exc:  # noqa: BLE001
                db_commit = {"status": "ERROR", "error": str(exc)}
        if self.runtime.db_commit_spool_stats is not None:
            try:
                db_commit["spool"] = self.runtime.db_commit_spool_stats()
            except Exception as exc:  # noqa: BLE001
                db_commit["spool"] = {"status": "ERROR", "error": str(exc)}

        return {
            "sqliteMetrics": metrics,
            "contention": {
                "busyCount": metrics.get("sqlite_busy_count", "UNMEASURED"),
                "busyRetrySuccess": metrics.get("sqlite_busy_retry_success", "UNMEASURED"),
                "busyRetryExhausted": metrics.get("sqlite_busy_retry_exhausted", "UNMEASURED"),
                "slowTransactionCount": metrics.get("slow_transaction_count", "UNMEASURED"),
            },
            "dbCommit": db_commit,
            "backup": backup,
            "writePolicy": {
                "operatorMutations": WriteClass.CONTROL_WRITE.value,
                "substantialDomainWrites": WriteClass.COMMIT_WRITE.value,
                "maintenance": WriteClass.MAINTENANCE_WRITE.value,
                "note": (
                    "SQLite Manager allowlisted mutations use CONTROL_WRITE with "
                    "domain confirmation. Substantial product writes remain owned by "
                    "the DB Commit Coordinator. Schema changes remain owned by migrations."
                ),
            },
            "databases": self.list_databases(),
        }
