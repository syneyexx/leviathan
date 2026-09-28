"""Training-control worker — owns trainer subprocess for its FULL lifetime.

GPU_EXCLUSIVE reservation (held by the worker loop around this handler) covers
the entire supervised trainer execution. Do NOT mark the control job COMPLETED
merely because Popen succeeded.
"""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.training.execution_gate import TrainingExecutionGateError
    from Data.modules.training.service import TrainingError, TrainingService

    cap = str(getattr(job, "capability_id", "") or "training.control")
    args = dict(getattr(job, "arguments", None) or {})
    training_job_id = str(args.get("training_job_id") or args.get("job_id") or "")
    action = str(args.get("action") or "start")
    worker_id = str(ctx.get("worker_id") or "")

    def _cancel_check() -> bool:
        check = ctx.get("job_cancel_check")
        if callable(check):
            try:
                return bool(check())
            except Exception:  # noqa: BLE001
                return True
        if ctx.get("lease_lost") is not None and getattr(ctx["lease_lost"], "is_set", lambda: False)():
            return True
        return False

    try:
        service = TrainingService(ctx["settings"], job_runtime=ctx["job_runtime"])

        if cap == "training.integrity.verify":
            if not training_job_id:
                fenced_transition(
                    ctx["job_store"], job.job_id, JobState.FAILED,
                    error="missing training_job_id", worker_id=worker_id, ctx=ctx,
                )
                return {}
            result = service.execute_integrity_verify(training_job_id)
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.COMPLETED,
                result=result, worker_id=worker_id, ctx=ctx,
            )
            return result

        if cap == "training.checkpoint.verify":
            if not training_job_id:
                fenced_transition(
                    ctx["job_store"], job.job_id, JobState.FAILED,
                    error="missing training_job_id", worker_id=worker_id, ctx=ctx,
                )
                return {}
            result = service.execute_checkpoint_verify(
                training_job_id,
                checkpoint_path=args.get("checkpoint_path"),
            )
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.COMPLETED,
                result=result, worker_id=worker_id, ctx=ctx,
            )
            return result

        if cap == "training.dataset.hash":
            if not training_job_id:
                fenced_transition(
                    ctx["job_store"], job.job_id, JobState.FAILED,
                    error="missing training_job_id", worker_id=worker_id, ctx=ctx,
                )
                return {}
            path = str(args.get("path") or "")
            if not path:
                fenced_transition(
                    ctx["job_store"], job.job_id, JobState.FAILED,
                    error="missing dataset path", worker_id=worker_id, ctx=ctx,
                )
                return {}
            result = service.execute_dataset_hash(training_job_id, path=path)
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.COMPLETED,
                result=result, worker_id=worker_id, ctx=ctx,
            )
            return result

        # training.control — full trainer lifecycle
        if not training_job_id:
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.FAILED,
                error="missing training_job_id", worker_id=worker_id, ctx=ctx,
            )
            return {}
        if action != "start":
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.FAILED,
                error=f"unknown action {action}", worker_id=worker_id, ctx=ctx,
            )
            return {}

        outcome = service.execute_control_start(
            training_job_id,
            cancel_check=_cancel_check,
        )
        training_job = outcome.get("training_job")
        supervision = dict(outcome.get("supervision") or {})
        status = getattr(getattr(training_job, "status", None), "value", None) or supervision.get("status")
        result = {
            "training_job_id": training_job_id,
            "status": status,
            "worker_pid": getattr(training_job, "worker_pid", None) or supervision.get("pid"),
            "supervision": supervision,
            "adopted": bool(outcome.get("adopted")),
            "executed_via": "training_control",
            "lifecycle": "full_trainer_supervision",
        }
        # Control job completes ONLY after trainer terminal supervision.
        terminal = str(supervision.get("terminal") or "")
        if terminal in {"cancelled"} or status == "cancelled":
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.CANCELLED,
                result=result, worker_id=worker_id, ctx=ctx,
            )
        elif status in {"failed"} or terminal in {"trainer_died", "pid_reuse"}:
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.FAILED,
                result=result,
                error=str(supervision.get("error") or f"training status={status}"),
                worker_id=worker_id,
                ctx=ctx,
            )
        else:
            fenced_transition(
                ctx["job_store"], job.job_id, JobState.COMPLETED,
                result=result, worker_id=worker_id, ctx=ctx,
            )
        return result
    except (TrainingError, TrainingExecutionGateError) as exc:
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.FAILED,
            error=str(getattr(exc, "message", exc))[:500],
            worker_id=worker_id,
            ctx=ctx,
        )
        return {"error": str(getattr(exc, "message", exc))}
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.FAILED,
            error=str(exc)[:500], worker_id=worker_id, ctx=ctx,
        )
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("training_control", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
