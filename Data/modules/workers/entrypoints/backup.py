"""Backup pool entrypoint — I/O-heavy backup creation outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.backup.service import BackupService
    from Data.modules.common.corpus import resolve_corpus_root
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    note = args.get("note")
    include_corpus = bool(args.get("include_corpus") or args.get("includeCorpus"))
    try:
        settings = ctx["settings"]
        try:
            corpus_root = resolve_corpus_root(settings)
        except Exception:  # noqa: BLE001
            corpus_root = None
        service = BackupService(
            database_path=settings.database_path,
            artifacts_root=settings.artifacts.root,
            backup_root=settings.backup.root,
            corpus_root=corpus_root,
            database_paths=getattr(settings, "database_paths", None),
        )
        manifest = service.create(
            note=str(note) if note else None,
            include_corpus=include_corpus,
        )
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
            result=manifest.public_dict() if hasattr(manifest, "public_dict") else {"ok": True},
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"backup_id": getattr(manifest, "backup_id", None)}
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("backup", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
