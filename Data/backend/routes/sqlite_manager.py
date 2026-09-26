"""SQLite Manager HTTP routes — three canonical DB operator surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
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


def build_sqlite_manager_router(manager: SqliteManager) -> APIRouter:
    router = APIRouter(tags=["sqlite-manager"])

    def _http(exc: SqliteManagerError) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc), "domain": exc.domain},
        )

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

    @router.post("/api/sqlite/query")
    def query(payload: SqliteQueryRequest) -> dict[str, Any]:
        try:
            return manager.query(payload.domain, payload.sql, limit=payload.limit)
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    @router.post("/api/sqlite/mutate")
    def mutate(payload: SqliteMutateRequest) -> dict[str, Any]:
        try:
            return manager.mutate(
                payload.domain,
                payload.sql,
                confirm_domain=payload.confirmDomain,
            )
        except SqliteManagerError as exc:
            raise _http(exc) from exc

    return router
