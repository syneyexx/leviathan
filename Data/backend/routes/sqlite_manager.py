"""SQLite Manager HTTP routes — three canonical DB operator surface."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from Data.modules.sqlite_manager import SqliteManager, SqliteManagerError


class SqliteQueryRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    sql: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=200, ge=1, le=1000)


class SqliteMutateRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    sql: str = Field(min_length=1, max_length=20_000)


class SqliteRowsQueryRequest(BaseModel):
    offset: int = Field(default=0, ge=0, le=10_000_000)
    limit: int = Field(default=50, ge=1, le=200)
    columns: list[str] | None = None
    filters: list[dict[str, Any]] | None = None
    search: str | None = Field(default=None, max_length=500)
    orderBy: list[str] | None = None


class SqliteIntegrityRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    kind: str = Field(default="quick_check", max_length=64)
    maxErrors: int = Field(default=100, ge=1, le=1000)


class SqliteCheckpointRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    mode: str = Field(default="PASSIVE", max_length=32)


class SqliteRowInsertRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    table: str = Field(min_length=1, max_length=128)
    values: dict[str, Any]


class SqliteRowUpdateRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    table: str = Field(min_length=1, max_length=128)
    identity: dict[str, Any]
    values: dict[str, Any]


class SqliteRowDeleteRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    table: str = Field(min_length=1, max_length=128)
    identity: dict[str, Any]


def build_sqlite_manager_router(
    manager: SqliteManager,
    *,
    assert_mutation_auth: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["sqlite-manager"])

    def _http(exc: SqliteManagerError) -> HTTPException:
        status = 409 if exc.code == "DB_BUSY" else 400
        if exc.code in {"ROW_BOUND_EXCEEDED", "UNBOUNDED_WRITE_FORBIDDEN", "ROWCOUNT_UNAVAILABLE"}:
            status = 400
        return HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc), "domain": exc.domain},
        )

    def _auth(request: Request) -> None:
        if assert_mutation_auth is not None:
            assert_mutation_auth(request)

    @router.get("/api/sqlite/databases")
    def list_databases() -> dict[str, Any]:
        return {"databases": manager.list_databases()}

    @router.get("/api/sqlite/databases/{domain}")
    def database_status(domain: str) -> dict[str, Any]:
        try:
            return {"database": manager.database_status(domain)}
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.get("/api/sqlite/databases/{domain}/tables")
    def list_tables(domain: str) -> dict[str, Any]:
        try:
            return {"domain": domain.upper(), "tables": manager.list_tables(domain)}
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.get("/api/sqlite/databases/{domain}/tables/{table}")
    def table_detail(domain: str, table: str) -> dict[str, Any]:
        try:
            return {"table": manager.table_detail(domain, table)}
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/databases/{domain}/tables/{table}/rows/query")
    def query_rows(domain: str, table: str, payload: SqliteRowsQueryRequest) -> dict[str, Any]:
        try:
            return manager.query_rows(
                domain,
                table,
                offset=payload.offset,
                limit=payload.limit,
                columns=payload.columns,
                filters=payload.filters,
                search=payload.search,
                order_by=payload.orderBy,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/query")
    def query(payload: SqliteQueryRequest) -> dict[str, Any]:
        try:
            return manager.query(payload.domain, payload.sql, limit=payload.limit)
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/mutate")
    def mutate(payload: SqliteMutateRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        try:
            return manager.mutate(
                payload.domain,
                payload.sql,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/rows/insert")
    def insert_row(payload: SqliteRowInsertRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        try:
            return manager.insert_row(
                payload.domain,
                payload.table,
                payload.values,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/rows/update")
    def update_row(payload: SqliteRowUpdateRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        try:
            return manager.update_row(
                payload.domain,
                payload.table,
                payload.identity,
                payload.values,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/rows/delete")
    def delete_row(payload: SqliteRowDeleteRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        try:
            return manager.delete_row(
                payload.domain,
                payload.table,
                payload.identity,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/integrity")
    def integrity(payload: SqliteIntegrityRequest) -> dict[str, Any]:
        # Full integrity_check can freeze the API on large DBs — quick_check only here.
        kind = str(payload.kind or "quick_check").strip().lower()
        if kind == "integrity_check":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "HEAVY_INTEGRITY_EXTERNALIZE",
                    "message": (
                        "PRAGMA integrity_check must not run inline in the API process; "
                        "use kind=quick_check or enqueue a maintenance job"
                    ),
                },
            )
        try:
            return manager.integrity_check(
                payload.domain,
                kind=kind,
                max_errors=payload.maxErrors,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/wal-checkpoint")
    def wal_checkpoint(payload: SqliteCheckpointRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        mode_u = str(payload.mode or "PASSIVE").strip().upper()
        if mode_u in {"FULL", "RESTART", "TRUNCATE"}:
            # Blocking maintenance modes require the same operator boundary as mutations.
            _auth(request)
        try:
            return manager.wal_checkpoint(
                payload.domain,
                mode=payload.mode,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.get("/api/sqlite/ownership-audit")
    def ownership_audit() -> dict[str, Any]:
        try:
            return manager.ownership_audit()
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.get("/api/sqlite/runtime")
    def runtime() -> dict[str, Any]:
        try:
            return manager.runtime_status()
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    return router
