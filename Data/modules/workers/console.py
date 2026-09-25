"""Consolidated Worker Fabric terminal console.

Prints startup banner, pool inventory, worker inventory, and periodic
fabric summaries into the single supervisor terminal window.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .dashboard import build_worker_fabric_dashboard
from .pools import POOL_CATALOG
from .settings import WorkerSettings, load_worker_settings


def _out(stream: TextIO[str], line: str = "") -> None:
    print(line, file=stream, flush=True)


def resource_label(classes: tuple[str, ...] | list[str]) -> str:
    mapping = {
        "CPU_LIGHT": "CPU",
        "CPU_HEAVY": "CPU",
        "IO_HEAVY": "IO",
        "MEMORY_HEAVY": "MEM",
        "NETWORK_BOUND": "NETWORK",
        "MODEL_INFERENCE": "MODEL",
        "GPU_SHARED": "GPU",
        "GPU_EXCLUSIVE": "GPU_EXCLUSIVE",
        "DB_SERIAL": "DB_SERIAL",
        "BATCH": "BATCH",
        "MAINTENANCE_EXCLUSIVE": "EXCLUSIVE",
    }
    labels: list[str] = []
    for c in classes:
        lab = mapping.get(str(c), str(c))
        if lab not in labels:
            labels.append(lab)
    return "/".join(labels) if labels else "CPU"


def print_startup_banner(
    *,
    install_root: Path,
    database_path: Path,
    settings: WorkerSettings | None = None,
    stream: TextIO[str] | None = None,
) -> None:
    """Print the consolidated fabric header."""
    s = stream or sys.stdout
    wsettings = settings or load_worker_settings()
    enabled = sum(1 for pid in POOL_CATALOG if wsettings.desired_count(pid) > 0)
    desired = sum(wsettings.desired_count(pid) for pid in POOL_CATALOG)
    _out(s, "=" * 60)
    _out(s, " LEVIATHAN EXTERNAL EXECUTION FABRIC")
    _out(s, "=" * 60)
    _out(s, "")
    _out(s, f"Install root: {install_root}")
    _out(s, f"Database: {database_path}")
    _out(s, "Mode: EXTERNAL")
    _out(s, "Supervisor: STARTING")
    _out(s, "")
    _out(s, f"Pools: {len(POOL_CATALOG)}")
    _out(s, f"Enabled pools: {enabled}")
    _out(s, f"Desired workers: {desired}")
    _out(s, "")
    _out(s, "CONTROL PLANE EXECUTION:")
    _out(s, "  Heavy API runners: EXTERNAL")
    _out(s, "  Dataset: EXTERNAL")
    _out(s, "  Research: EXTERNAL")
    _out(s, "  Source ingestion: EXTERNAL")
    _out(s, "  Coding: EXTERNAL")
    _out(s, "  Agents: EXTERNAL")
    _out(s, "  Knowledge: EXTERNAL")
    _out(s, "")
    _out(s, "=" * 60)
    _out(s, "")


def print_pool_inventory(
    *,
    settings: WorkerSettings | None = None,
    overrides: dict[str, int] | None = None,
    stream: TextIO[str] | None = None,
) -> None:
    """Print dynamic pool catalog inventory (desired/max/resource/purpose)."""
    s = stream or sys.stdout
    wsettings = settings or load_worker_settings()
    ov = overrides or {}
    _out(s, f"{'POOL':<22} {'DESIRED':>7} {'MAX':>5}  {'RESOURCE':<18} PURPOSE")
    _out(s, "-" * 90)
    disabled: list[tuple[str, int, int, str, str]] = []
    for pid, defn in POOL_CATALOG.items():
        desired = int(ov.get(pid, wsettings.desired_count(pid)))
        res = resource_label(defn.resource_classes)
        purpose = (defn.description or "")[:48]
        row = (pid, desired, defn.max_count, res, purpose)
        if desired <= 0:
            disabled.append(row)
        else:
            _out(s, f"{pid:<22} {desired:>7} {defn.max_count:>5}  {res:<18} {purpose}")
    if disabled:
        _out(s, "")
        _out(s, "Disabled/optional:")
        for pid, desired, max_c, res, purpose in disabled:
            _out(s, f"{pid:<22} {desired:>7} {max_c:>5}  {res:<18} {purpose}")
    _out(s, "")


def print_worker_inventory(
    *,
    db_path: Path,
    job_getter: Any = None,
    list_jobs: Any = None,
    stream: TextIO[str] | None = None,
) -> None:
    """Print every registered worker with PID / state / current work."""
    s = stream or sys.stdout
    dash = build_worker_fabric_dashboard(
        db_path=db_path,
        job_getter=job_getter,
        list_jobs=list_jobs,
        include_resources=False,
    )
    _out(s, f"{'WORKER':<28} {'PID':>7}  {'STATE':<10} CURRENT WORK")
    _out(s, "-" * 90)
    workers = sorted(
        dash.get("workers") or [],
        key=lambda w: (str(w.get("pool_id") or ""), int(w.get("slot") or 0)),
    )
    if not workers:
        _out(s, "(no workers registered yet)")
    for w in workers:
        name = str(w.get("display_name") or w.get("worker_id") or "?")
        pid = w.get("pid") or "—"
        state = str(w.get("state") or "UNKNOWN")
        work = str(w.get("current_work") or "—")[:48]
        _out(s, f"{name:<28} {pid:>7}  {state:<10} {work}")
    _out(s, "")
    summary = dash.get("summary") or {}
    _out(
        s,
        f"[FABRIC] pools={summary.get('pools_total')} "
        f"enabled={summary.get('pools_enabled')} "
        f"desired={summary.get('desired_workers')} "
        f"running={summary.get('running_workers')} "
        f"busy={summary.get('busy_workers')} "
        f"idle={summary.get('idle_workers')} "
        f"queue={summary.get('queue_depth')} "
        f"degraded={summary.get('degraded_pools')}",
    )
    _out(s, "")


def print_fabric_summary(
    *,
    db_path: Path,
    job_getter: Any = None,
    list_jobs: Any = None,
    stream: TextIO[str] | None = None,
) -> dict[str, Any]:
    """Print a one-line fabric summary; return the dashboard for change detection."""
    s = stream or sys.stdout
    dash = build_worker_fabric_dashboard(
        db_path=db_path,
        job_getter=job_getter,
        list_jobs=list_jobs,
        include_resources=False,
    )
    summary = dash.get("summary") or {}
    _out(
        s,
        f"[FABRIC] pools={summary.get('pools_total')} "
        f"enabled={summary.get('pools_enabled')} "
        f"desired={summary.get('desired_workers')} "
        f"running={summary.get('running_workers')} "
        f"busy={summary.get('busy_workers')} "
        f"idle={summary.get('idle_workers')} "
        f"queue={summary.get('queue_depth')} "
        f"degraded={summary.get('degraded_pools')}",
    )
    return dash


def summary_interval_seconds() -> float:
    raw = (os.environ.get("LEVIATHAN_WORKERS_TERMINAL_SUMMARY_SECONDS") or "").strip()
    if not raw:
        return 30.0
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 30.0


class FabricConsole:
    """Periodic summary helper owned by the supervisor process."""

    def __init__(
        self,
        db_path: Path,
        *,
        interval_seconds: float | None = None,
        job_getter: Any = None,
        list_jobs: Any = None,
        stream: TextIO[str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.interval = float(interval_seconds if interval_seconds is not None else summary_interval_seconds())
        self.job_getter = job_getter
        self.list_jobs = list_jobs
        self.stream = stream or sys.stdout
        self._next_at = 0.0
        self._last_busy: int | None = None
        self._last_running: int | None = None

    def maybe_print(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_at:
            return
        self._next_at = now + self.interval
        dash = print_fabric_summary(
            db_path=self.db_path,
            job_getter=self.job_getter,
            list_jobs=self.list_jobs,
            stream=self.stream,
        )
        summary = dash.get("summary") or {}
        busy = int(summary.get("busy_workers") or 0)
        running = int(summary.get("running_workers") or 0)
        # On significant state change, reprint worker rows (bounded).
        if (
            self._last_busy is not None
            and (busy != self._last_busy or abs(running - (self._last_running or 0)) >= 2)
        ):
            busy_workers = [
                w
                for w in (dash.get("workers") or [])
                if str(w.get("state") or "").upper() == "BUSY"
            ][:12]
            for w in busy_workers:
                name = w.get("display_name") or w.get("worker_id")
                work = w.get("current_work") or "—"
                _out(self.stream, f"  · {name}: {work}")
        self._last_busy = busy
        self._last_running = running
