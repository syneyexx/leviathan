"""DB Commit Coordinator worker entrypoint — desired_count=1, max_count=1.

Owns durable spool + IPC and serializes COMMIT_WRITE. Also claims legacy
``knowledge.commit`` jobs and converts them into CommitIntents (no dual writer).
"""

from __future__ import annotations

import argparse
import os
import signal
import time
from typing import Any

from Data.modules.workers.events import get_worker_event_emitter
from Data.modules.workers.loop import build_minimal_job_context
from Data.modules.workers.protocol import (
    WORKER_PROTOCOL_VERSION,
    WorkerInstanceState,
    WorkerRegistration,
)
from Data.modules.workers.registry import utc_now


def _register(ctx: dict[str, Any], worker_id: str, slot: int) -> None:
    from Data.modules.workers.process import process_start_identity_for

    registry = ctx["registry"]
    generation = os.environ.get("LEVIATHAN_WORKER_SUPERVISOR_GENERATION")
    registry.upsert(
        WorkerRegistration(
            worker_id=worker_id,
            pool_id="db_commit",
            slot=slot,
            pid=os.getpid(),
            process_start_identity=process_start_identity_for(os.getpid()),
            protocol_version=WORKER_PROTOCOL_VERSION,
            supported_job_kinds=("db_commit.", "knowledge.commit"),
            started_at=utc_now(),
            last_heartbeat_at=utc_now(),
            state=WorkerInstanceState.READY,
            supervisor_generation=generation,
        )
    )


def _ingest_knowledge_commit_job(ctx: dict[str, Any], job: Any, coordinator: Any) -> None:
    """Convert a legacy knowledge.commit job into a CommitIntent (same writer PID)."""
    from Data.modules.db_commit.producer import CommitProducer
    from Data.modules.db_commit.types import CommitPriority
    from Data.modules.jobs.states import JobState

    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    artifact = args.get("artifact") or {}
    if hasattr(artifact, "public_dict"):
        artifact = artifact.public_dict()
    idem = args.get("idempotency_key") or getattr(job, "idempotency_key", None)
    title = str((artifact or {}).get("title") or "")[:120] if isinstance(artifact, dict) else ""

    if hasattr(store, "update_progress"):
        store.update_progress(job.job_id, phase="COMMIT_QUEUED", message="ingested by db_commit")

    producer = CommitProducer(
        ctx["settings"].database_path,
        settings=coordinator.settings,
        spool=coordinator.spool,
        receipts=coordinator.receipts,
    )
    result = producer.submit(
        operation="knowledge.commit_prepared",
        domain="knowledge",
        payload={"artifact": artifact},
        idempotency_key=str(idem) if idem else None,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="knowledge_artifact",
        entity_id=str(
            (artifact.get("artifact_id") if isinstance(artifact, dict) else "")
            or getattr(job, "job_id", "")
        ),
        safe_human_title=title,
        source_job_id=str(getattr(job, "job_id", "") or ""),
        producer_worker_id=str(ctx.get("worker_id") or ""),
        record_count_hint=1,
    )
    # Process immediately in this writer so the job can complete.
    coordinator.process_until_idle(max_items=32)
    receipt = coordinator.receipts.get_by_commit_id(result.commit_id)
    if receipt is None and idem:
        receipt = coordinator.receipts.get_by_idempotency_key(str(idem))
    if receipt is not None:
        store.transition(
            job.job_id,
            JobState.COMPLETED,
            result=receipt.to_dict(),
            metadata_update={"commit_phase": "COMPLETED", "via": "db_commit"},
        )
    elif not result.accepted:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=f"{result.ack_status}: {result.message}"[:500],
        )
    else:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error="COMMIT_FAILED: receipt missing after db_commit ingest",
        )


def run_db_commit_worker(*, once: bool = False, max_commits: int | None = None) -> int:
    from Data.modules.db_commit.writer import DbCommitCoordinator

    ctx = build_minimal_job_context()
    worker_id = os.environ.get("LEVIATHAN_WORKER_ID") or f"db_commit-{os.getpid()}"
    slot = int(os.environ.get("LEVIATHAN_WORKER_SLOT") or "0")
    ctx["worker_id"] = worker_id
    _register(ctx, worker_id, slot)

    emitter = get_worker_event_emitter()
    emitter.pool_started(pool="db_commit", worker_count=1)
    emitter.worker_ready(pool="db_commit", worker_id=worker_id, worker_pid=os.getpid())
    print("[WORKER] DB Commit pool gestart — 1 worker", flush=True)

    coordinator = DbCommitCoordinator.from_env(ctx)
    stop = {"flag": False}

    def _stop(*_a: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    coordinator.startup()
    registry = ctx["registry"]
    store = ctx["job_store"]
    wsettings = ctx["worker_settings"]
    hb_every = float(wsettings.heartbeat_seconds)
    lease_ttl = float(wsettings.lease_ttl_seconds)
    last_hb = 0.0
    processed = 0

    try:
        while not stop["flag"]:
            now = time.time()
            if now - last_hb >= hb_every:
                reg = registry.heartbeat(worker_id, state=WorkerInstanceState.READY)
                last_hb = now
                if reg is None:
                    print("[DB-WRITER] lost registry — exiting", flush=True)
                    break

            # Claim legacy knowledge.commit jobs into this single writer.
            job = None
            try:
                if hasattr(store, "claim_next_for_pool"):
                    job = store.claim_next_for_pool(
                        pool_id="db_commit",
                        worker_id=worker_id,
                        lease_ttl_seconds=lease_ttl,
                    )
                if job is None:
                    job = store.claim_next_queued(
                        worker_id=worker_id,
                        lease_ttl_seconds=lease_ttl,
                        capability_ids={"knowledge.commit"},
                    )
            except Exception:  # noqa: BLE001
                job = None
            if job is not None and str(getattr(job, "capability_id", "")) == "knowledge.commit":
                try:
                    _ingest_knowledge_commit_job(ctx, job, coordinator)
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    from Data.modules.jobs.states import JobState

                    store.transition(job.job_id, JobState.FAILED, error=str(exc)[:500])

            did = coordinator.process_one()
            if did:
                processed += 1
            if max_commits is not None and processed >= max_commits:
                break
            if once and not did and job is None:
                break
            if not did and job is None:
                time.sleep(float(coordinator.settings.poll_seconds))
    finally:
        coordinator.shutdown()
        emitter.worker_stopping(pool="db_commit", worker_id=worker_id)

    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leviathan db_commit worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-commits", type=int, default=None)
    args = parser.parse_args(argv)
    count = run_db_commit_worker(once=args.once, max_commits=args.max_commits)
    print(f"[db_commit-worker] processed={count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
