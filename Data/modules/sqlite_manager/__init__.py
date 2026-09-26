"""SQLite Manager — operator tooling for the three canonical LEVIATHAN databases.

Extends (does not replace) platform operator surfaces. Writes require an explicit
database domain and never silently fall back to Control.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Data.backend.db_upgrade import domain_schema_version
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.common.sqlite_policy import open_sqlite_connection

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_WRITE_PREFIXES = ("INSERT ", "UPDATE ", "DELETE ")


class SqliteManagerError(RuntimeError):
    def __init__(self, code: str, message: str, *, domain: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.domain = domain


@dataclass(frozen=True)
class SqliteManager:
    paths: DatabasePaths
    allow_writes: bool = True

    def _path_for(self, domain: DatabaseDomain | str) -> Path:
        if isinstance(domain, DatabaseDomain):
            key = domain
        else:
            try:
                key = DatabaseDomain(str(domain).upper())
            except ValueError as exc:
                raise SqliteManagerError(
                    "UNKNOWN_DATABASE_DOMAIN",
                    f"Unknown database domain: {domain!r}",
                ) from exc
        return self.paths.path_for(key)

    def list_databases(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for domain, path in self.paths:
            exists = path.is_file()
            size = path.stat().st_size if exists else 0
            wal = path.with_suffix(path.suffix + "-wal")
            shm = path.with_suffix(path.suffix + "-shm")
            schema = domain_schema_version(path) if exists else 0
            out.append(
                {
                    "domain": domain.value,
                    "path": str(path),
                    "exists": exists,
                    "sizeBytes": size,
                    "walExists": wal.is_file(),
                    "walSizeBytes": wal.stat().st_size if wal.is_file() else 0,
                    "shmExists": shm.is_file(),
                    "schemaVersion": schema,
                }
            )
        return out

    def database_status(self, domain: DatabaseDomain | str) -> dict[str, Any]:
        key = DatabaseDomain(str(domain).upper())
        for item in self.list_databases():
            if item["domain"] == key.value:
                return item
        raise SqliteManagerError("DATABASE_NOT_FOUND", f"{key.value} not configured", domain=key.value)

    def list_tables(self, domain: DatabaseDomain | str) -> list[dict[str, Any]]:
        path = self._path_for(domain)
        key = DatabaseDomain(str(domain).upper())
        if not path.is_file():
            raise SqliteManagerError(
                "DATABASE_MISSING",
                f"{key.value} database file does not exist: {path}",
                domain=key.value,
            )
        conn = open_sqlite_connection(path)
        try:
            rows = conn.execute(
                "SELECT name, type, sql FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                name = str(row[0] if not isinstance(row, sqlite3.Row) else row["name"])
                typ = str(row[1] if not isinstance(row, sqlite3.Row) else row["type"])
                cols = [
                    {
                        "name": r[1] if not isinstance(r, sqlite3.Row) else r["name"],
                        "type": r[2] if not isinstance(r, sqlite3.Row) else r["type"],
                        "notnull": bool(r[3] if not isinstance(r, sqlite3.Row) else r["notnull"]),
                        "pk": bool(r[5] if not isinstance(r, sqlite3.Row) else r["pk"]),
                    }
                    for r in conn.execute(f'PRAGMA table_info("{name}")').fetchall()
                ]
                indexes = [
                    {
                        "name": r[1] if not isinstance(r, sqlite3.Row) else r["name"],
                        "unique": bool(r[2] if not isinstance(r, sqlite3.Row) else r["unique"]),
                    }
                    for r in conn.execute(f'PRAGMA index_list("{name}")').fetchall()
                ]
                out.append(
                    {
                        "name": name,
                        "type": typ,
                        "columns": cols,
                        "indexes": indexes,
                    }
                )
            return out
        finally:
            conn.close()

    def query(
        self,
        domain: DatabaseDomain | str,
        sql: str,
        *,
        limit: int = 200,
    ) -> dict[str, Any]:
        key = DatabaseDomain(str(domain).upper())
        path = self._path_for(key)
        text = (sql or "").strip()
        if not text:
            raise SqliteManagerError("EMPTY_SQL", "SQL is required", domain=key.value)
        lowered = text.lower()
        if not lowered.startswith("select") and not lowered.startswith("pragma"):
            raise SqliteManagerError(
                "READ_ONLY_QUERY",
                f"{key.value}: only SELECT/PRAGMA allowed on query endpoint",
                domain=key.value,
            )
        if ";" in text.rstrip(";"):
            raise SqliteManagerError(
                "MULTI_STATEMENT_FORBIDDEN",
                f"{key.value}: multiple SQL statements are forbidden",
                domain=key.value,
            )
        if not path.is_file():
            raise SqliteManagerError(
                "DATABASE_MISSING",
                f"{key.value} database file does not exist",
                domain=key.value,
            )
        conn = open_sqlite_connection(path)
        try:
            capped = max(1, min(int(limit), 1000))
            cursor = conn.execute(text)
            colnames = [d[0] for d in (cursor.description or [])]
            rows = cursor.fetchmany(capped + 1)
            truncated = len(rows) > capped
            rows = rows[:capped]
            return {
                "domain": key.value,
                "columns": colnames,
                "rows": [list(r) for r in rows],
                "rowCount": len(rows),
                "truncated": truncated,
                "limit": capped,
            }
        except sqlite3.Error as exc:
            raise SqliteManagerError(
                "QUERY_FAILED",
                f"{key.value}: {exc}",
                domain=key.value,
            ) from exc
        finally:
            conn.close()

    def mutate(
        self,
        domain: DatabaseDomain | str,
        sql: str,
        *,
        confirm_domain: str,
    ) -> dict[str, Any]:
        if isinstance(domain, DatabaseDomain):
            key = domain
        else:
            try:
                key = DatabaseDomain(str(domain).upper())
            except ValueError as exc:
                raise SqliteManagerError(
                    "UNKNOWN_DATABASE_DOMAIN",
                    f"Unknown database domain: {domain!r}",
                ) from exc
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
        path = self._path_for(key)
        text = (sql or "").strip()
        if not text:
            raise SqliteManagerError("EMPTY_SQL", "SQL is required", domain=key.value)
        upper = text.lstrip().upper()
        if not any(upper.startswith(prefix) for prefix in _ALLOWED_WRITE_PREFIXES):
            raise SqliteManagerError(
                "WRITE_NOT_ALLOWLISTED",
                f"{key.value}: only INSERT/UPDATE/DELETE are allowed",
                domain=key.value,
            )
        if ";" in text.rstrip(";"):
            raise SqliteManagerError(
                "MULTI_STATEMENT_FORBIDDEN",
                f"{key.value}: multiple SQL statements are forbidden",
                domain=key.value,
            )
        if not path.is_file():
            raise SqliteManagerError(
                "DATABASE_MISSING",
                f"{key.value} database file does not exist",
                domain=key.value,
            )
        conn = open_sqlite_connection(path)
        try:
            cur = conn.execute(text)
            conn.commit()
            return {
                "domain": key.value,
                "rowcount": int(cur.rowcount if cur.rowcount is not None else 0),
                "ok": True,
            }
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise SqliteManagerError(
                "MUTATION_FAILED",
                f"{key.value}: {exc}",
                domain=key.value,
            ) from exc
        finally:
            conn.close()
