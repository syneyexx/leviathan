"""SQLite Manager HTTP routes — three canonical DB operator surface.

SqliteManager remains the control surface. Heavy READ-ONLY work enqueues
sqlite_ops; mutative exclusive work enqueues maintenance. Tiny bounded
interactive queries may remain inline.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from Data.modules.sqlite_manager import SqliteManager, SqliteManagerError
from Data.modules.sqlite_manager.heavy import (
    classify_checkpoint_mode,
    classify_integrity_kind,
    classify_operator_query,
)


class SqliteQueryRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    sql: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=200, ge=1, le=1000)
    async_: bool = Field(default=False, alias="async")
    export: bool = False


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
    async_: bool = Field(default=False, alias="async")


class SqliteIntegrityRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    kind: str = Field(default="quick_check", max_length=64)
    maxErrors: int = Field(default=100, ge=1, le=1000)


class SqliteCheckpointRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    mode: str = Field(default="PASSIVE", max_length=32)


class SqliteVacuumRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)


class SqliteAnalyzeRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=32)
    confirmDomain: str = Field(min_length=1, max_length=32)
    table: str | None = None
    index: str | None = None


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
    job_runtime: Any | None = None,
    workers_externalize_fn: Callable[[], bool] | None = None,
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

    def _externalize() -> bool:
        if workers_externalize_fn is not None:
            return bool(workers_externalize_fn())
        return job_runtime is not None

    def _enqueue(capability_id: str, arguments: dict[str, Any], *, pool: str, resource: str) -> dict:
        if job_runtime is None or not _externalize():
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "SQLITE_OPS_UNAVAILABLE" if pool == "sqlite_ops" else "MAINTENANCE_UNAVAILABLE",
                    "message": f"{capability_id} requires the {pool} worker",
                },
            )
        try:
            job = job_runtime.enqueue(
                capability_id=capability_id,
                arguments=arguments,
                requested_by="api",
                domain="sqlite_manager",
                worker_pool=pool,
                resource_class=resource,
                latency_class="background" if pool == "sqlite_ops" else "maintenance",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"job": job.public_dict(), "queued": True, "capability": capability_id}

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
            db_path = manager._path_for(domain)  # noqa: SLF001 — shared classifier needs size
            decision = classify_operator_query(
                sql=f"SELECT * FROM {table}",
                domain=domain,
                db_path=db_path,
                limit=payload.limit,
                offset=payload.offset,
                search=payload.search,
                force_async=bool(payload.async_),
                table_scan=True,
            )
            if decision.heavy:
                return _enqueue(
                    decision.capability,
                    {
                        "domain": domain,
                        "table": table,
                        "offset": payload.offset,
                        "limit": payload.limit,
                        "columns": payload.columns,
                        "search": payload.search,
                        "search_columns": payload.columns,
                    },
                    pool="sqlite_ops",
                    resource="IO_HEAVY",
                )
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
            db_path = manager._path_for(payload.domain)  # noqa: SLF001
            decision = classify_operator_query(
                sql=payload.sql,
                domain=payload.domain,
                db_path=db_path,
                limit=payload.limit,
                force_async=bool(payload.async_),
                export=bool(payload.export),
            )
            if decision.heavy:
                return _enqueue(
                    decision.capability,
                    {
                        "domain": payload.domain,
                        "sql": payload.sql,
                        "limit": payload.limit,
                        "format": "jsonl" if payload.export else "json",
                    },
                    pool="sqlite_ops",
                    resource="IO_HEAVY",
                )
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
        try:
            db_path = manager._path_for(payload.domain)  # noqa: SLF001
            decision = classify_integrity_kind(payload.kind, db_path=db_path)
            if decision.heavy:
                return _enqueue(
                    "maintenance.db.integrity",
                    {
                        "domain": payload.domain,
                        "kind": payload.kind,
                        "max_errors": payload.maxErrors,
                    },
                    pool="maintenance",
                    resource="MAINTENANCE_EXCLUSIVE",
                )
            return manager.integrity_check(
                payload.domain,
                kind=payload.kind,
                max_errors=payload.maxErrors,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/wal-checkpoint")
    def wal_checkpoint(payload: SqliteCheckpointRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        decision = classify_checkpoint_mode(payload.mode)
        if decision.heavy:
            return _enqueue(
                "maintenance.db.checkpoint",
                {"domain": payload.domain, "mode": payload.mode},
                pool="maintenance",
                resource="MAINTENANCE_EXCLUSIVE",
            )
        try:
            return manager.wal_checkpoint(
                payload.domain,
                mode=payload.mode,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/vacuum")
    def vacuum(payload: SqliteVacuumRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        if payload.confirmDomain.upper() != payload.domain.upper():
            raise HTTPException(status_code=400, detail="confirmDomain mismatch")
        return _enqueue(
            "maintenance.db.vacuum",
            {"domain": payload.domain},
            pool="maintenance",
            resource="MAINTENANCE_EXCLUSIVE",
        )

    @router.post("/api/sqlite/analyze")
    def analyze(payload: SqliteAnalyzeRequest, request: Request) -> dict[str, Any]:
        _auth(request)
        if payload.confirmDomain.upper() != payload.domain.upper():
            raise HTTPException(status_code=400, detail="confirmDomain mismatch")
        return _enqueue(
            "maintenance.db.analyze",
            {
                "domain": payload.domain,
                "table": payload.table,
                "index": payload.index,
            },
            pool="maintenance",
            resource="MAINTENANCE_EXCLUSIVE",
        )

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
