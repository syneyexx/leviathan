"""Subprocess entrypoint for training workers — argv-only, no shell."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leviathan-training-worker")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--events-path", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Ensure repo root on path when launched as python -m ...
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from Data.modules.common.atomic import atomic_write_text, ensure_dir
    from Data.modules.common.process import write_pid_file
    from Data.modules.common.secrets import redact_secrets
    from Data.modules.training.config import TrainingConfig
    from Data.modules.training.events import TrainingEventLog
    from Data.modules.training.store import TrainingStore, utc_now
    from Data.modules.training.types import DurableTrainingStatus
    from Data.modules.training.worker.trainer_loop import format_worker_error, run_training_loop

    job_id = args.job_id
    db_path = Path(args.db_path)
    config_path = Path(args.config_path)
    output_dir = Path(args.output_dir)
    log_path = Path(args.log_path)
    events_path = Path(args.events_path)

    ensure_dir(output_dir)
    ensure_dir(log_path.parent)
    ensure_dir(events_path.parent)

    store = TrainingStore(db_path)
    events = TrainingEventLog(events_path)
    pid_path = output_dir / "worker.pid"
    write_pid_file(pid_path, os.getpid())

    def log(line: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(redact_secrets(line.rstrip()) + "\n")

    try:
        raw = config_path.read_text(encoding="utf-8")
        import json

        config = TrainingConfig.from_dict(json.loads(raw))
        store.update_job(
            job_id,
            status=DurableTrainingStatus.RUNNING,
            phase="running",
            worker_pid=os.getpid(),
            started_at=utc_now(),
            log_path=str(log_path),
        )
        events.emit("state_changed", status="running", pid=os.getpid())
        log(f"worker start pid={os.getpid()} job_id={job_id} method={config.method}")

        def cancel_check() -> bool:
            job = store.get_job(job_id)
            return bool(job and job.cancel_requested)

        result = run_training_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
        )
        log(f"worker finished: {result}")
        atomic_write_text(output_dir / "result.json", redact_secrets(json.dumps(result, indent=2)))
        return 0 if result.get("status") in {"completed", "cancelled"} else 1
    except Exception as exc:  # noqa: BLE001 — persist failure, exit non-zero
        err = format_worker_error(exc)
        log(err)
        events.emit("failed", error=str(exc))
        try:
            store.update_job(
                job_id,
                status=DurableTrainingStatus.FAILED,
                phase="failed",
                error=redact_secrets(str(exc))[:2000],
                finished_at=utc_now(),
            )
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
