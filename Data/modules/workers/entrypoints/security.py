"""security pool — deep repository/dependency/integrity audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.security.deep_scan import (
        run_deep_audit,
        run_dependency_audit,
        run_repo_scan,
        write_report_artifact,
    )

    cap = str(getattr(job, "capability_id", "") or "")
    args = dict(getattr(job, "arguments", None) or {})
    settings = ctx["settings"]
    # Repo root: parent of Data/ when running from packaged layout.
    data_root = Path(getattr(settings, "repo_root", None) or Path.cwd())
    # Prefer workspace root containing Data/
    if (data_root / "Data").is_dir():
        root = data_root
    elif data_root.name == "Data":
        root = data_root.parent
    else:
        root = Path.cwd()

    try:
        if cap.endswith("dependencies.audit") or cap == "security.dependencies.audit":
            report = run_dependency_audit(root).public_dict()
        elif cap.endswith("repo.scan") or cap == "security.repo.scan":
            report = run_repo_scan(root).public_dict()
        elif cap.endswith("integrity.audit"):
            # Consume evidence pointers — do not duplicate domain integrity owners.
            report = {
                "scanType": "integrity.audit",
                "measurement": "UNMEASURED",
                "note": (
                    "Domain integrity remains owned by maintenance (DB), backup "
                    "(backup sets), and training (artifacts). Security consumes "
                    "their evidence; no silent PASS."
                ),
                "truth": {"missingScannerIsNotPass": True},
            }
        else:
            report = run_deep_audit(root, scope=str(args.get("scope") or "all"))

        art_root = Path(getattr(getattr(settings, "artifacts", None), "root", ".") or ".")
        artifact = write_report_artifact(
            report,
            art_root / "security" / f"{job.job_id}.json",
        )
        result = {
            "report": {
                "measurement": report.get("measurement"),
                "scanType": report.get("scanType") or report.get("scope"),
                "findingsCount": len(report.get("findings") or [])
                if isinstance(report.get("findings"), list)
                else sum(
                    len((sec or {}).get("findings") or [])
                    for sec in (report.get("sections") or {}).values()
                ),
            },
            "artifactRef": str(artifact),
            "summary": report.get("measurement"),
        }
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
            result=result,
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=f"SECURITY_SCAN_FAILED:{exc}"[:500],
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": "SECURITY_SCAN_FAILED"}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("security", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
