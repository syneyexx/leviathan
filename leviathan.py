from __future__ import annotations

"""Leviathan entrypoint — prefers bootstrap (API + supervisor) when workers enabled."""


def main() -> None:
    import os

    from Data.modules.workers.settings import load_worker_settings

    settings = load_worker_settings()
    mode = (os.environ.get("LEVIATHAN_BOOTSTRAP_MODE") or "").strip().lower()
    if mode in {"api", "supervisor", "all"}:
        from Data.modules.workers.bootstrap import main as bootstrap_main

        raise SystemExit(bootstrap_main([mode]))

    if settings.enabled and settings.supervisor_enabled:
        # Production default: API + generic worker supervisor.
        from Data.modules.workers.bootstrap import run_all

        raise SystemExit(run_all())

    # Legacy: API-only (in-process domain runners).
    import uvicorn
    from Data.backend.config import settings as app_settings

    host = app_settings.runtime.host
    port = app_settings.runtime.port
    if app_settings.runtime.loopback_only and host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "LEVIATHAN_LOOPBACK_ONLY=true requires a loopback LEVIATHAN_HOST "
            f"(got {host!r})"
        )
    uvicorn.run("Data.backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
