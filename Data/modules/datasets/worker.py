"""External dataset job worker — executes the same ``dataset_jobs`` against the same store.

Does **not** introduce a second queue. Use either the in-process runner *or*
this external worker, never both concurrently.

Windows-compatible: plain Python process, no fork required.

  LEVIATHAN_DATASET_JOBS_RUNNER=inprocess|external|none

Start (Windows / Unix)::

  python -m Data.modules.datasets.worker
  python scripts/dataset_worker.py
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any


RUNNER_ENV = "LEVIATHAN_DATASET_JOBS_RUNNER"
LOCK_ENV = "LEVIATHAN_DATASET_WORKER_LOCK"


def resolve_runner_mode(settings: Any | None = None) -> str:
    """Return ``inprocess``, ``external``, or ``none``."""
    raw = (os.environ.get(RUNNER_ENV) or "").strip().lower()
    if not raw and settings is not None:
        ri = getattr(settings, "research_integration", None)
        raw = str(getattr(ri, "dataset_jobs_runner", "") or "").strip().lower()
    if raw in {"inprocess", "in-process", "internal", "thread"}:
        return "inprocess"
    if raw in {"external", "worker", "process"}:
        return "external"
    if raw in {"none", "off", "disabled"}:
        return "none"
    return "inprocess"


def should_start_inprocess_runner(settings: Any | None = None) -> bool:
    return resolve_runner_mode(settings) == "inprocess"


def _default_lock_path(db_path: Path) -> Path:
    override = (os.environ.get(LOCK_ENV) or "").strip()
    if override:
        return Path(override)
    return Path(db_path).with_suffix(Path(db_path).suffix + ".dataset-worker.lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        from Data.modules.common.process import pid_is_alive

        return bool(pid_is_alive(pid))
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def acquire_worker_lock(db_path: Path) -> Path:
    """Exclusive lock so only one dataset job executor runs against this DB."""
    lock_path = _default_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            existing = int(lock_path.read_text(encoding="utf-8").strip().splitlines()[0])
        except (OSError, ValueError, IndexError):
            existing = -1
        if existing > 0 and existing != os.getpid() and _pid_alive(existing):
            raise RuntimeError(
                f"Another dataset job runner holds the lock (pid={existing}, path={lock_path}). "
                f"Stop it or set {RUNNER_ENV}=none before starting a second executor."
            )
    # Atomic-ish replace is good enough; claim_next_queued remains the real CAS.
    from Data.modules.common.atomic import atomic_write_text

    atomic_write_text(lock_path, f"{os.getpid()}\n")
    return lock_path


def release_worker_lock(lock_path: Path | None) -> None:
    if lock_path is None:
        return
    try:
        if lock_path.exists():
            text = lock_path.read_text(encoding="utf-8").strip()
            if text.startswith(str(os.getpid())):
                lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def build_service_from_env():
    from Data.backend.config import load_settings
    from Data.modules.datasets.service import DatasetService
    from Data.modules.knowledge import KnowledgeStore
    from Data.modules.knowledge.embeddings import build_embedding_provider

    settings = load_settings()
    provider = build_embedding_provider(
        kind=settings.knowledge.embedding_provider,
        model_name=settings.knowledge.embedding_model,
        hash_dimensions=getattr(settings.knowledge, "hash_dimensions", 256),
    )
    knowledge = KnowledgeStore(
        settings.database_path,
        data_root=Path(settings.knowledge.data_root),
        embedding_provider=provider,
    )
    knowledge.initialize()
    return DatasetService.from_settings(settings, knowledge=knowledge), settings


def run_worker_loop(
    *,
    poll_seconds: float = 0.5,
    max_jobs: int | None = None,
    once: bool = False,
) -> int:
    service, _settings = build_service_from_env()
    lock_path = acquire_worker_lock(service.store.db_path)
    stop = {"flag": False}

    def _stop(*_args: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    processed = 0
    try:
        service.reconcile()
        # Sidecar catalog recovery on worker boot (same store as API).
        try:
            service.reconcile_sidecars()
        except Exception as exc:  # noqa: BLE001 — never block job loop
            print(f"[dataset-worker] sidecar reconcile skipped: {exc}", file=sys.stderr)
        while not stop["flag"]:
            job = service.runner.process_next()
            if job is None:
                if once:
                    break
                time.sleep(max(0.1, float(poll_seconds)))
                continue
            processed += 1
            print(
                f"[dataset-worker] job={job.job_id} type={job.job_type.value} "
                f"status={job.status.value} phase={job.phase}",
                flush=True,
            )
            if max_jobs is not None and processed >= max_jobs:
                break
            if once:
                break
    finally:
        release_worker_lock(lock_path)
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leviathan dataset job worker (shared store)")
    parser.add_argument("--poll", type=float, default=0.5, help="Idle poll interval seconds")
    parser.add_argument("--max-jobs", type=int, default=None, help="Stop after N jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one job then exit")
    args = parser.parse_args(argv)
    # Force external mode semantics for lock/docs; API should set RUNNER=external.
    os.environ.setdefault(RUNNER_ENV, "external")
    count = run_worker_loop(poll_seconds=args.poll, max_jobs=args.max_jobs, once=args.once)
    print(f"[dataset-worker] processed={count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
