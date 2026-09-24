"""LEVIATHAN process bootstrap — API + generic worker supervisor.

``.bat`` is only a launcher. Model-serving subprocesses remain on-demand under
Model Residency (not owned here).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_api(*, host: str | None = None, port: int | None = None) -> int:
    from Data.backend.config import load_settings

    settings = load_settings()
    h = host or settings.runtime.host
    p = int(port or settings.runtime.port)
    if settings.runtime.loopback_only and h not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"LEVIATHAN_LOOPBACK_ONLY=true requires loopback host (got {h!r})",
            file=sys.stderr,
        )
        return 2
    import uvicorn

    # Externalize API runners when supervisor owns pools (production default).
    os.environ.setdefault("LEVIATHAN_WORKERS_EXTERNALIZE_API", "1")
    os.environ.setdefault("LEVIATHAN_DATASET_JOBS_RUNNER", "external")
    os.environ.setdefault("LEVIATHAN_SOURCE_INGESTION_RUNNER", "external")
    uvicorn.run("Data.backend.main:app", host=h, port=p, reload=False)
    return 0


def run_supervisor(*, once: bool = False, tick_seconds: float = 1.0) -> int:
    from Data.backend.config import load_settings
    from Data.modules.workers.settings import load_worker_settings
    from Data.modules.workers.supervisor import WorkerSupervisor

    settings = load_settings()
    wsettings = load_worker_settings()
    if not wsettings.enabled or not wsettings.supervisor_enabled:
        print("[supervisor] disabled by settings", flush=True)
        return 0
    supervisor = WorkerSupervisor(settings.database_path, settings=wsettings, repo_root=_repo_root())
    stop = {"flag": False}

    def _stop(*_a: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        supervisor.start()
    except RuntimeError as exc:
        print(f"[supervisor] {exc}", flush=True)
        return 1
    print(
        f"[supervisor] started holder={supervisor.holder_id} generation={supervisor.generation}",
        flush=True,
    )
    try:
        while not stop["flag"]:
            status = supervisor.tick()
            if not status.get("ok"):
                print(f"[supervisor] tick stop: {status}", flush=True)
                break
            if once:
                break
            time.sleep(max(0.2, float(tick_seconds)))
    finally:
        supervisor.stop()
        print("[supervisor] stopped", flush=True)
    return 0


def run_all() -> int:
    """Spawn API + supervisor as sibling processes (Windows-friendly)."""
    root = _repo_root()
    env = os.environ.copy()
    env.setdefault("LEVIATHAN_WORKERS_EXTERNALIZE_API", "1")
    env.setdefault("LEVIATHAN_DATASET_JOBS_RUNNER", "external")
    env.setdefault("LEVIATHAN_SOURCE_INGESTION_RUNNER", "external")
    env.setdefault("PYTHONUNBUFFERED", "1")

    api = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "Data.modules.workers.bootstrap", "api"],
        cwd=str(root),
        env=env,
        shell=False,
    )
    supervisor = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "Data.modules.workers.bootstrap", "supervisor"],
        cwd=str(root),
        env=env,
        shell=False,
    )
    stop = {"flag": False}

    def _stop(*_a: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    exit_code = 0
    try:
        while not stop["flag"]:
            if api.poll() is not None:
                exit_code = int(api.returncode or 0)
                break
            if supervisor.poll() is not None:
                # Supervisor death is non-fatal for API but should restart in production;
                # here we exit so the launcher can respawn both cleanly.
                exit_code = int(supervisor.returncode or 1)
                break
            time.sleep(0.5)
    finally:
        for proc in (supervisor, api):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except Exception:  # noqa: BLE001
                    proc.kill()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leviathan bootstrap")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_api = sub.add_parser("api", help="Run FastAPI only")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)
    p_sup = sub.add_parser("supervisor", help="Run generic worker supervisor")
    p_sup.add_argument("--once", action="store_true")
    p_sup.add_argument("--tick", type=float, default=1.0)
    sub.add_parser("all", help="Run API + supervisor")
    args = parser.parse_args(argv)
    if args.cmd == "api":
        return run_api(host=args.host, port=args.port)
    if args.cmd == "supervisor":
        return run_supervisor(once=args.once, tick_seconds=args.tick)
    if args.cmd == "all":
        return run_all()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
