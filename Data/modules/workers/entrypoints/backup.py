"""Backup pool entrypoint — I/O-heavy backup creation outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.backup.service import BackupService
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    note = args.get("note")
    try:
        settings = ctx["settings"]
        service = BackupService(
            database_path=settings.database_path,
            artifacts_root=settings.artifacts.root,
            backup_root=settings.backup.root,
        )
        manifest = service.create(note=str(note) if note else None)
        ctx["job_store"].transition(
            job.job_id,
            JobState.COMPLETED,
            result=manifest.public_dict() if hasattr(manifest, "public_dict") else {"ok": True},
        )
        return {"backup_id": getattr(manifest, "backup_id", None)}
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("backup", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
