"""HTTP error handlers that attach ``trace_id`` to every 5xx (T16/F-33)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from errors.correlation import (
    CorrelationContext,
    bind_correlation,
    ensure_correlation,
    new_trace_id,
    reset_correlation,
)
from errors.taxonomy import ErrorCode, HadesError

_LOG = logging.getLogger("hades.api")


def _header_trace_id(request: Request) -> str | None:
    for key in ("x-trace-id", "x-request-id"):
        raw = request.headers.get(key)
        if raw and 8 <= len(raw.strip()) <= 120:
            return raw.strip()
    return None


def resolve_request_trace_id(request: Request | None = None) -> str:
    """Prefer request-scoped id (survives BaseHTTPMiddleware task hops)."""
    if request is not None:
        existing = getattr(request.state, "trace_id", None)
        if existing:
            return str(existing)
    ctx = ensure_correlation()
    if request is not None and not getattr(request.state, "trace_id", None):
        request.state.trace_id = ctx.trace_id
    return ctx.trace_id


def detail_with_trace(detail: Any, trace_id: str) -> Any:
    """Ensure a 5xx body carries ``trace_id`` without inventing success."""
    if isinstance(detail, dict):
        body = dict(detail)
        body.setdefault("trace_id", trace_id)
        return body
    return {"message": detail, "trace_id": trace_id}


def response_body_for_5xx(*, detail: Any, trace_id: str, error_code: str = ErrorCode.INTERNAL_ERROR.value) -> dict[str, Any]:
    enriched = detail_with_trace(detail, trace_id)
    if isinstance(enriched, dict):
        body = dict(enriched)
        body.setdefault("trace_id", trace_id)
        body.setdefault("error_code", error_code)
        # Preserve FastAPI-shaped ``detail`` for clients that only read that key.
        if "detail" not in body:
            message = body.get("message")
            body["detail"] = message if message is not None else body
        return body
    return {"detail": enriched, "trace_id": trace_id, "error_code": error_code}


class TraceCorrelationMiddleware(BaseHTTPMiddleware):
    """Bind a per-request correlation context and echo ``X-Trace-Id``.

    ``request.state.trace_id`` is the durable carrier: BaseHTTPMiddleware may run
    ``call_next`` in a different task where contextvars do not propagate.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        incoming = _header_trace_id(request)
        trace_id = incoming or new_trace_id()
        request.state.trace_id = trace_id
        ctx = CorrelationContext(trace_id=trace_id, request_id=trace_id)
        token = bind_correlation(ctx)
        try:
            response = await call_next(request)
            response.headers.setdefault("X-Trace-Id", trace_id)
            if response.status_code >= 500:
                _LOG.error(
                    "http_5xx status=%s method=%s path=%s trace_id=%s",
                    response.status_code,
                    request.method,
                    request.url.path,
                    trace_id,
                )
            return response
        finally:
            reset_correlation(token)


def install_api_error_handlers(app: FastAPI) -> None:
    """Register handlers so every 5xx JSON body includes ``trace_id`` and is logged."""

    @app.exception_handler(HadesError)
    async def hades_error_handler(request: Request, exc: HadesError) -> JSONResponse:
        trace_id = resolve_request_trace_id(request)
        bind_correlation(CorrelationContext(trace_id=trace_id, request_id=trace_id))
        if not exc.trace_id:
            exc.trace_id = trace_id
        status = exc.http_status()
        body = exc.as_dict()
        body.setdefault("trace_id", trace_id)
        if status >= 500:
            _LOG.error(
                "hades_error code=%s status=%s path=%s trace_id=%s message=%s",
                exc.code.value,
                status,
                request.url.path,
                trace_id,
                exc.message,
            )
        return JSONResponse(status_code=status, content=body, headers={"X-Trace-Id": trace_id})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        trace_id = resolve_request_trace_id(request)
        bind_correlation(CorrelationContext(trace_id=trace_id, request_id=trace_id))
        headers = {"X-Trace-Id": trace_id}
        if isinstance(exc.headers, dict):
            headers.update({str(k): str(v) for k, v in exc.headers.items()})
        if exc.status_code >= 500:
            _LOG.error(
                "http_exception status=%s path=%s trace_id=%s detail=%s",
                exc.status_code,
                request.url.path,
                trace_id,
                exc.detail,
            )
            body = response_body_for_5xx(detail=exc.detail, trace_id=trace_id)
            return JSONResponse(status_code=exc.status_code, content=body, headers=headers)
        # Keep FastAPI default shape for non-5xx.
        if isinstance(exc.detail, (dict, list)):
            content: Any = exc.detail
        else:
            content = {"detail": exc.detail}
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        trace_id = resolve_request_trace_id(request)
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "trace_id": trace_id},
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = resolve_request_trace_id(request)
        bind_correlation(CorrelationContext(trace_id=trace_id, request_id=trace_id))
        _LOG.exception(
            "unhandled_exception path=%s trace_id=%s error_type=%s",
            request.url.path,
            trace_id,
            type(exc).__name__,
        )
        body = response_body_for_5xx(
            detail="Internal server error",
            trace_id=trace_id,
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
        return JSONResponse(status_code=500, content=body, headers={"X-Trace-Id": trace_id})
