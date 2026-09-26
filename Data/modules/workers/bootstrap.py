"""LEVIATHAN process bootstrap — API + generic worker supervisor.

``.bat`` is only a launcher. Model-serving subprocesses remain on-demand under
Model Residency (not owned here).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    # bootstrap.py lives at Data/modules/workers/ → parents[3] is the install root.
    return Path(__file__).resolve().parents[3]


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
    try:
        from Data.modules.workers.events import get_worker_event_emitter

        get_worker_event_emitter().control_plane_started()
    except Exception:  # noqa: BLE001
        print("[LEVIATHAN] Control Plane gestart", flush=True)
    uvicorn.run("Data.backend.main:app", host=h, port=p, reload=False)
    return 0


def run_supervisor(*, once: bool = False, tick_seconds: float = 1.0) -> int:
    from Data.backend.config import load_settings
    from Data.modules.workers.console import (
        FabricConsole,
        print_pool_inventory,
        print_startup_banner,
        print_worker_inventory,
    )
    from Data.modules.workers.settings import load_worker_settings
    from Data.modules.workers.supervisor import (
        SupervisorFatalError,
        SupervisorLeaseLost,
        WorkerSupervisor,
    )

    settings = load_settings()
    wsettings = load_worker_settings()
    root = _repo_root()
    if not wsettings.enabled or not wsettings.supervisor_enabled:
        print("[supervisor] disabled by settings", flush=True)
        return 0

    # Force external production posture for this process.
    os.environ.setdefault("LEVIATHAN_WORKERS_EXTERNALIZE_API", "1")
    os.environ.setdefault("LEVIATHAN_DATASET_JOBS_RUNNER", "external")
    os.environ.setdefault("LEVIATHAN_SOURCE_INGESTION_RUNNER", "external")

    print_startup_banner(
        install_root=root,
        database_path=Path(settings.database_path),
        settings=wsettings,
    )
    print_pool_inventory(settings=wsettings)

    restart_count = int(os.environ.get("LEVIATHAN_SUPERVISOR_RESTART_COUNT") or "0")
    supervisor = WorkerSupervisor(
        settings.database_path,
        settings=wsettings,
        repo_root=root,
        restart_count=restart_count,
    )
    stop = {"flag": False}
    exit_code = 0
    fatal_exc: BaseException | None = None
    fabric_console = FabricConsole(settings.database_path)

    def _stop(*_a: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        supervisor.start()
    except RuntimeError as exc:
        msg = str(exc)
        if "WORKER_SUPERVISOR_LEASE_HELD" in msg:
            lease_pid = None
            try:
                from Data.modules.workers.registry import WorkerRegistry

                reg = WorkerRegistry(settings.database_path)
                reg.initialize()
                lease = reg.get_supervisor_lease() or {}
                lease_pid = lease.get("holder_pid")
            except Exception:  # noqa: BLE001
                lease_pid = None
            print(
                f"[WORKER] Supervisor already active"
                + (f": PID {lease_pid}" if lease_pid else "")
                + " — not starting a duplicate fabric.",
                flush=True,
            )
        print(f"[supervisor] {exc}", flush=True)
        return 1
    print(
        f"[supervisor] started holder={supervisor.holder_id} generation={supervisor.generation} "
        f"pid={os.getpid()}",
        flush=True,
    )
    # Allow a brief grace so spawned workers register before inventory.
    time.sleep(0.8 if not once else 0.1)
    try:
        print_worker_inventory(db_path=Path(settings.database_path))
    except Exception as exc:  # noqa: BLE001
        print(f"[FABRIC] worker inventory unavailable: {exc}", flush=True)

    try:
        while not stop["flag"]:
            try:
                status = supervisor.tick()
            except SupervisorLeaseLost as exc:
                fatal_exc = exc
                print(f"[supervisor] lease lost: {exc}", flush=True)
                exit_code = 2
                break
            except SupervisorFatalError as exc:
                fatal_exc = exc
                print(f"[supervisor] fatal: {exc}", flush=True)
                traceback.print_exc()
                exit_code = 3
                break
            except Exception as exc:  # noqa: BLE001 — keep process alive for transient escapes
                print(
                    f"[supervisor] unhandled tick error (continuing): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                traceback.print_exc()
                # Bounded pause before next tick — avoid tight crash loop inside process.
                time.sleep(min(2.0, max(0.2, float(tick_seconds))))
                if once:
                    exit_code = 4
                    fatal_exc = exc
                    break
                continue

            if status.get("fatal") or status.get("reason") == "lost_supervisor_lease":
                print(f"[supervisor] tick stop: {status}", flush=True)
                exit_code = 2 if status.get("reason") == "lost_supervisor_lease" else 3
                break
            if status.get("degraded"):
                print(
                    f"[supervisor] tick degraded: errors={status.get('errors')} "
                    f"health={status.get('health')}",
                    flush=True,
                )
            try:
                fabric_console.maybe_print()
            except Exception:  # noqa: BLE001
                pass
            if once:
                break
            time.sleep(max(0.2, float(tick_seconds)))
    finally:
        # Best-effort stop — never mask the original fatal exception in logs.
        try:
            supervisor.stop()
        except Exception as shut_exc:  # noqa: BLE001
            print(
                f"[supervisor] stop raised (original={type(fatal_exc).__name__ if fatal_exc else None}): "
                f"{type(shut_exc).__name__}: {shut_exc}",
                flush=True,
            )
            traceback.print_exc()
            if fatal_exc is not None:
                print(
                    f"[supervisor] preserving original failure: "
                    f"{type(fatal_exc).__name__}: {fatal_exc}",
                    flush=True,
                )
        print("[supervisor] stopped — fabric shutdown complete", flush=True)
    return exit_code


def _child_env(root: Path, *, supervisor_restart_count: int = 0) -> dict[str, str]:
    """Build a relocatable child env: install root on PYTHONPATH, no stale drive letters required."""
    env = os.environ.copy()
    env.setdefault("LEVIATHAN_WORKERS_EXTERNALIZE_API", "1")
    env.setdefault("LEVIATHAN_DATASET_JOBS_RUNNER", "external")
    env.setdefault("LEVIATHAN_SOURCE_INGESTION_RUNNER", "external")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["LEVIATHAN_SUPERVISOR_RESTART_COUNT"] = str(int(supervisor_restart_count))
    root_s = str(root)
    existing = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    # Prepend install root so -m Data.* resolves even if cwd/PYTHONPATH were stale.
    env["PYTHONPATH"] = os.pathsep.join([root_s, *[p for p in existing if p != root_s]])
    return env


def _spawn_supervisor(root: Path, *, restart_count: int) -> subprocess.Popen[Any]:
    env = _child_env(root, supervisor_restart_count=restart_count)
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "Data.modules.workers.bootstrap", "supervisor"],
        cwd=str(root),
        env=env,
        shell=False,
    )


def run_all() -> int:
    """Spawn API + supervisor as sibling processes (Windows-friendly).

    Supervisor death does NOT kill the API. Parent restarts supervisor with a
    rolling-window budget reused from WorkerSettings restart policy.
    API death terminates the stack (existing launcher policy).
    """
    from Data.backend.config import load_settings
    from Data.modules.workers.registry import WorkerRegistry
    from Data.modules.workers.settings import load_worker_settings

    root = _repo_root()
    wsettings = load_worker_settings()
    settings = load_settings()
    env = _child_env(root)

    api = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "Data.modules.workers.bootstrap", "api"],
        cwd=str(root),
        env=env,
        shell=False,
    )
    supervisor: subprocess.Popen[Any] | None = subprocess.Popen(  # noqa: S603
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
    crash_timestamps: list[float] = []
    restart_count = 0
    next_spawn_at = 0.0
    supervisor_unavailable = False
    registry = WorkerRegistry(settings.database_path)

    try:
        while not stop["flag"]:
            if api.poll() is not None:
                exit_code = int(api.returncode or 0)
                print(f"[bootstrap] API exited code={exit_code}", flush=True)
                break

            if supervisor is not None and supervisor.poll() is None:
                time.sleep(0.5)
                continue

            # Supervisor not running.
            code = int(supervisor.returncode) if supervisor is not None else -1
            now = time.time()
            if supervisor is not None:
                print(
                    f"[bootstrap] supervisor exited code={code} — API remains alive",
                    flush=True,
                )
                crash_timestamps.append(now)
                window = float(wsettings.restart_window_seconds)
                crash_timestamps = [t for t in crash_timestamps if now - t <= window]
                restart_count += 1
                supervisor = None

            if len(crash_timestamps) >= int(wsettings.restart_max_attempts):
                backoff = min(
                    float(wsettings.restart_max_backoff),
                    float(wsettings.restart_base_backoff)
                    * (2 ** max(0, len(crash_timestamps) - 1)),
                )
                if not supervisor_unavailable:
                    reason = (
                        f"SUPERVISOR_RESTART_EXHAUSTED: {len(crash_timestamps)} crashes "
                        f"in {wsettings.restart_window_seconds}s"
                    )
                    print(f"[bootstrap] {reason}; cooldown={backoff:.1f}s", flush=True)
                    try:
                        registry.initialize()
                        registry.write_parent_supervisor_unavailable(
                            reason=reason,
                            restart_count=restart_count,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"[bootstrap] failed to persist DEGRADED: {exc}", flush=True)
                    supervisor_unavailable = True
                next_spawn_at = max(next_spawn_at, now + backoff)
                # After cooldown, allow another attempt (clear window).
                if now < next_spawn_at:
                    time.sleep(0.5)
                    continue
                crash_timestamps.clear()
                supervisor_unavailable = False
                print("[bootstrap] supervisor cooldown elapsed — retrying spawn", flush=True)

            if now < next_spawn_at:
                time.sleep(0.5)
                continue

            # Lease reconcile: do not spawn duplicate while a valid owner holds lease.
            try:
                registry.initialize()
                lease = registry.get_supervisor_lease()
            except Exception as exc:  # noqa: BLE001
                lease = None
                print(f"[bootstrap] lease probe failed: {exc}", flush=True)

            if lease is not None:
                from Data.modules.common.process import pid_is_alive
                from datetime import datetime, timezone

                holder_pid = lease.get("holder_pid")
                expires_at = lease.get("expires_at")
                holder_alive = bool(holder_pid) and pid_is_alive(int(holder_pid))
                lease_valid = False
                if expires_at and holder_alive:
                    try:
                        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                        lease_valid = datetime.now(timezone.utc) < exp
                    except (TypeError, ValueError):
                        lease_valid = False
                if lease_valid and int(holder_pid or 0) != 0:
                    # Another valid supervisor still owns the lease — wait TTL.
                    print(
                        f"[bootstrap] supervisor lease still held by pid={holder_pid}; "
                        "waiting (no duplicate spawn)",
                        flush=True,
                    )
                    next_spawn_at = now + max(1.0, float(wsettings.supervisor_lease_ttl_seconds) / 2)
                    time.sleep(0.5)
                    continue

            backoff = min(
                float(wsettings.restart_max_backoff),
                float(wsettings.restart_base_backoff) * (2 ** max(0, restart_count - 1)),
            )
            print(
                f"[bootstrap] restarting supervisor attempt={restart_count} backoff={backoff:.1f}s",
                flush=True,
            )
            time.sleep(backoff)
            if stop["flag"] or api.poll() is not None:
                continue
            try:
                supervisor = _spawn_supervisor(root, restart_count=restart_count)
                supervisor_unavailable = False
                next_spawn_at = 0.0
            except Exception as exc:  # noqa: BLE001
                print(f"[bootstrap] supervisor spawn failed: {exc}", flush=True)
                next_spawn_at = time.time() + backoff
    finally:
        for proc in (supervisor, api):
            if proc is None:
                continue
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
