from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

BACKEND_LIVENESS_URL = "http://127.0.0.1:8000/openapi.json"
BACKEND_IDENTITY = "HADES Local Bridge"
FRONTEND_URL = "http://127.0.0.1:3000/"
FRONTEND_IDENTITY = "HADES — Local AI Workspace"
DEFAULT_TARGETS = (
    (BACKEND_LIVENESS_URL, BACKEND_IDENTITY),
    (FRONTEND_URL, FRONTEND_IDENTITY),
)


def is_url_ready(
    url: str,
    *,
    expected_text: str | None = None,
    timeout: float = 0.5,
    opener: Callable[..., Any] | None = None,
) -> bool:
    """Return True only for a successful HTTP response matching HADES identity."""

    open_url = opener or urllib.request.urlopen
    try:
        with open_url(url, timeout=timeout) as response:
            status = int(getattr(response, "status", 0))
            if not 200 <= status < 400:
                return False
            if expected_text is None:
                return True
            body = response.read(256_000)
            if isinstance(body, bytes):
                rendered = body.decode("utf-8", errors="replace")
            else:
                rendered = str(body)
            return expected_text in rendered
    except Exception:
        return False


def wait_for_local_hades(
    targets: Iterable[tuple[str, str | None]] = DEFAULT_TARGETS,
    *,
    attempts: int = 60,
    interval: float = 0.5,
    request_timeout: float = 0.5,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> bool:
    """Wait until the expected local HADES backend and frontend are reachable.

    Startup readiness deliberately probes lightweight identity-bearing endpoints
    rather than ``/api/health``. The health route performs provider/database/plugin
    diagnostics and may legitimately wait on LM Studio; launcher liveness must not
    turn optional/provider health into a startup dependency. Identity markers also
    prevent unrelated processes on ports 8000/3000 from being mistaken for HADES.
    """

    required = tuple(targets)
    if not required:
        return True
    if attempts <= 0:
        return False

    sleeper = sleep_fn or time.sleep
    for attempt in range(attempts):
        if all(
            is_url_ready(
                url,
                expected_text=expected_text,
                timeout=request_timeout,
                opener=opener,
            )
            for url, expected_text in required
        ):
            return True
        if attempt + 1 < attempts:
            sleeper(interval)
    return False


def main() -> int:
    if wait_for_local_hades():
        print("[OK] HADES backend en frontend zijn bereikbaar en geidentificeerd.")
        return 0
    print("[FOUT] HADES backend en/of frontend werd niet binnen de starttimeout herkend.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
