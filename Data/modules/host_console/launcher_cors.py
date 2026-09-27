"""Narrow CORS contract for the native launcher WebView read projections.

CORS is a browser policy, not authorization. Mutation routes remain gated by
existing loopback/token owners. This middleware only grants read access to an
exact allowlist of local launcher origins on an exact allowlist of GET paths.
"""

from __future__ import annotations

from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Production Tauri 2 origins (verified against Tauri asset protocol):
# - Windows/Android custom protocol default: http://tauri.localhost
# - Optional https scheme: https://tauri.localhost
# - macOS/Linux custom protocol: tauri://localhost
# Dev Vite (tauri.conf.json build.devUrl): http://127.0.0.1:1420
LAUNCHER_ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://[::1]:1420",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    }
)

LAUNCHER_READ_PATHS: frozenset[str] = frozenset(
    {
        "/api/host/liveness",
        "/api/health",
        "/api/workers/dashboard",
        "/api/performance/snapshot",
        "/api/host/overview",
        "/api/host/source-ingestion",
        "/api/host/native-operations",
        "/api/models/status",
        "/api/events/stream",
    }
)

_ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def origin_is_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin.strip() in LAUNCHER_ALLOWED_ORIGINS


def path_is_launcher_read(path: str) -> bool:
    if path in LAUNCHER_READ_PATHS:
        return True
    # Allow query-bearing SSE path normalization already handled by ASGI path.
    return False


def cors_headers_for(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Accept, Last-Event-ID, Content-Type",
        "Access-Control-Expose-Headers": "Content-Type",
        "Vary": "Origin",
    }


class LauncherReadCorsMiddleware(BaseHTTPMiddleware):
    """Add CORS headers only for allowlisted launcher origins + read paths."""

    def __init__(
        self,
        app,
        *,
        allowed_origins: Iterable[str] | None = None,
        allowed_paths: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._origins = frozenset(allowed_origins) if allowed_origins is not None else LAUNCHER_ALLOWED_ORIGINS
        self._paths = frozenset(allowed_paths) if allowed_paths is not None else LAUNCHER_READ_PATHS

    async def dispatch(self, request: Request, call_next) -> Response:
        origin = request.headers.get("origin")
        path = request.url.path
        method = request.method.upper()
        eligible = (
            origin in self._origins
            and path in self._paths
            and method in _ALLOWED_METHODS
        )

        if method == "OPTIONS" and eligible:
            response = Response(status_code=204)
            response.headers.update(cors_headers_for(origin))  # type: ignore[arg-type]
            # Explicitly do not grant credentialed CORS.
            if "access-control-allow-credentials" in response.headers:
                del response.headers["access-control-allow-credentials"]
            return response

        response = await call_next(request)
        if eligible and origin:
            for key, value in cors_headers_for(origin).items():
                response.headers[key] = value
            if "access-control-allow-credentials" in response.headers:
                del response.headers["access-control-allow-credentials"]
        return response
