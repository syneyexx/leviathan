"""Market sim pool entrypoint — advances simulations outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState

    try:
        from Data.modules.market_sim.service import MarketSimService

        service = MarketSimService.from_settings(ctx["settings"])
        advanced = False
        if hasattr(service, "worker") and hasattr(service.worker, "process_next"):
            advanced = bool(service.worker.process_next())
        ctx["job_store"].transition(
            job.job_id,
            JobState.COMPLETED,
            result={"advanced": advanced},
        )
        return {"advanced": advanced}
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("market_sim", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
