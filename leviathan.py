from __future__ import annotations

import uvicorn


def main() -> None:
    from Data.backend.config import settings

    host = settings.runtime.host
    port = settings.runtime.port
    if settings.runtime.loopback_only and host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "LEVIATHAN_LOOPBACK_ONLY=true requires a loopback LEVIATHAN_HOST "
            f"(got {host!r})"
        )
    uvicorn.run("Data.backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
