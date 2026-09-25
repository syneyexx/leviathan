"""Knowledge commit pool entrypoint — compatibility shim onto DB Commit Coordinator.

Bulk Knowledge mutations are owned by the ``db_commit`` worker. This entrypoint
submits a CommitIntent and waits for the durable receipt (no direct heavy write).
"""

from __future__ import annotations

import time
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.db_commit.producer import CommitProducer
    from Data.modules.db_commit.receipts import CommitReceiptStore
    from Data.modules.db_commit.types import CommitPriority
    from Data.modules.jobs.states import JobState

    store = ctx["job_store"]
    settings = ctx["settings"]
    args = dict(getattr(job, "arguments", None) or {})
    artifact = args.get("artifact") or {}
    if hasattr(artifact, "public_dict"):
        artifact = artifact.public_dict()
    idem = args.get("idempotency_key") or getattr(job, "idempotency_key", None)
    title = ""
    if isinstance(artifact, dict):
        title = str(artifact.get("title") or "")[:120]

    def _phase(phase: str, message: str = "") -> None:
        if hasattr(store, "update_progress"):
            store.update_progress(job.job_id, phase=phase, message=message)
        else:
            store.transition(
                job.job_id,
                JobState.RUNNING,
                metadata_update={"commit_phase": phase, "commit_message": message},
            )

    try:
        _phase("COMMIT_QUEUED", "awaiting db_commit receipt")
    except Exception:  # noqa: BLE001
        pass

    producer = CommitProducer(settings.database_path)
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

    if not result.accepted:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=f"{result.ack_status}: {result.message}"[:500],
            metadata_update={"commit_phase": "COMMIT_FAILED"},
        )
        return result.public_dict()

    if result.committed and result.receipt is not None:
        store.transition(
            job.job_id,
            JobState.COMPLETED,
            result=result.receipt.to_dict(),
            metadata_update={"commit_phase": "COMPLETED"},
        )
        return result.receipt.to_dict()

    receipts = CommitReceiptStore(settings.database_path)
    deadline = time.time() + 600.0
    while time.time() < deadline:
        receipt = receipts.get_by_commit_id(result.commit_id)
        if receipt is None and idem:
            receipt = receipts.get_by_idempotency_key(str(idem))
        if receipt is not None:
            store.transition(
                job.job_id,
                JobState.COMPLETED,
                result=receipt.to_dict(),
                metadata_update={"commit_phase": "COMPLETED"},
            )
            return receipt.to_dict()
        try:
            _phase("COMMITTING", f"commit_id={result.commit_id[:8]}")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)

    store.transition(
        job.job_id,
        JobState.FAILED,
        error="COMMIT_TIMEOUT waiting for db_commit receipt",
        metadata_update={"commit_phase": "COMMIT_FAILED"},
    )
    return {"error": "COMMIT_TIMEOUT", "commit_id": result.commit_id}


def main(argv=None):
    return main_for_pool("knowledge_commit", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
