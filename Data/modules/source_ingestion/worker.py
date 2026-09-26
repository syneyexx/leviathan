"""External source-ingestion worker — claims JobStore source_ingestion.* jobs.

Uses the same jobs table and KnowledgeStore as the API process.
Set ``LEVIATHAN_SOURCE_INGESTION_RUNNER=external`` before starting the API so the
in-process runner does not compete with this worker.

  python scripts/source_ingestion_worker.py
  python scripts/source_ingestion_worker.py --once
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

RUNNER_ENV = "LEVIATHAN_SOURCE_INGESTION_RUNNER"
LOCK_ENV = "LEVIATHAN_SOURCE_INGESTION_WORKER_LOCK"


def resolve_runner_mode(settings: Any | None = None) -> str:
    """Return ``inprocess``, ``external``, or ``none``.

    Production default is ``external``. ``inprocess`` is TEST/LEGACY only.
    """
    raw = (os.environ.get(RUNNER_ENV) or "").strip().lower()
    if not raw and settings is not None:
        ri = getattr(settings, "research_integration", None)
        raw = str(getattr(ri, "source_ingestion_runner", "") or "").strip().lower()
    if raw in {"inprocess", "in-process", "internal", "thread"}:
        return "inprocess"
    if raw in {"external", "worker", "process"}:
        return "external"
    if raw in {"none", "off", "disabled"}:
        return "none"
    return "external"


def should_start_inprocess_runner(settings: Any | None = None) -> bool:
    return resolve_runner_mode(settings) == "inprocess"


def _default_lock_path(db_path: Path) -> Path:
    override = (os.environ.get(LOCK_ENV) or "").strip()
    if override:
        return Path(override)
    return Path(db_path).with_suffix(Path(db_path).suffix + ".source-ingestion-worker.lock")


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
    lock_path = _default_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            existing = int(lock_path.read_text(encoding="utf-8").strip().splitlines()[0])
        except (OSError, ValueError, IndexError):
            existing = -1
        if existing > 0 and existing != os.getpid() and _pid_alive(existing):
            raise RuntimeError(
                f"Another source-ingestion worker holds the lock (pid={existing}, path={lock_path}). "
                f"Stop it or set {RUNNER_ENV}=none before starting a second executor."
            )
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
    from Data.modules.common.corpus import build_corpus_layout
    from Data.modules.execution import build_default_catalog
    from Data.modules.execution.gateway import ExecutionGateway
    from Data.modules.jobs.resources import ResourceManager
    from Data.modules.jobs.runtime import JobRuntime
    from Data.modules.jobs.store import JobStore
    from Data.modules.knowledge import KnowledgeStore
    from Data.modules.knowledge.embeddings import build_embedding_provider
    from Data.modules.research.store import ResearchStore
    from Data.modules.source_ingestion.service import SourceIngestionService
    from Data.modules.source_ingestion.settings import load_source_ingestion_settings

    settings = load_settings()
    corpus = build_corpus_layout(settings).ensure()
    research = ResearchStore(settings.database_path)
    research.initialize()
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
    job_store = JobStore(settings.database_path)
    job_store.initialize()
    catalog = build_default_catalog()
    gateway = ExecutionGateway(catalog=catalog)
    resources = ResourceManager(settings.resources.max_job_concurrency)
    job_runtime = JobRuntime(job_store, gateway, resources)
    si_settings = load_source_ingestion_settings(research_integration=settings.research_integration)
    service = SourceIngestionService.from_corpus(
        research_store=research,
        corpus=corpus,
        database_path=settings.database_path,
        knowledge=knowledge,
        job_runtime=job_runtime,
        settings=si_settings,
    )
    return service, settings


def run_worker_loop(
    *,
    poll_seconds: float = 0.5,
    max_jobs: int | None = None,
    once: bool = False,
) -> int:
    service, settings = build_service_from_env()
    lock_path = acquire_worker_lock(settings.database_path)
    stop = {"flag": False}
    worker_id = f"source-ingestion-ext-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    def _stop(*_args: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    processed = 0
    print(f"[source-ingestion-worker] start worker_id={worker_id} pid={os.getpid()}", flush=True)
    try:
        while not stop["flag"]:
            job_id = service.process_next()
            if job_id is None:
                if once:
                    break
                time.sleep(max(0.1, float(poll_seconds)))
                continue
            processed += 1
            print(f"[source-ingestion-worker] completed job={job_id}", flush=True)
            if max_jobs is not None and processed >= max_jobs:
                break
            if once:
                break
    finally:
        release_worker_lock(lock_path)
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leviathan source ingestion worker (shared JobStore)")
    parser.add_argument("--poll", type=float, default=0.5, help="Idle poll interval seconds")
    parser.add_argument("--max-jobs", type=int, default=None, help="Stop after N jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one job then exit")
    args = parser.parse_args(argv)
    os.environ.setdefault(RUNNER_ENV, "external")
    count = run_worker_loop(poll_seconds=args.poll, max_jobs=args.max_jobs, once=args.once)
    print(f"[source-ingestion-worker] processed={count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
