"""Trading → Research bridge (W128).

Orchestra / paper decisions may identify a knowledge gap and request Research
via ResearchService + JobRuntime. Never runs synchronous web research inside
an order-critical section.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request_trading_research(
    research_service: Any,
    *,
    question: str,
    instrument: str | None = None,
    strategy_id: str | None = None,
    urgency: str = "deferred",
    allow_web: bool = True,
) -> dict[str, Any]:
    """Create a research project for a trading knowledge gap.

    Returns WAITING / INSUFFICIENT_EVIDENCE semantics for urgent decisions.
    Does not block the order path — caller decides HOLD vs defer.
    """
    q = (question or "").strip()
    if not q:
        return {
            "status": "REJECTED",
            "error_code": "VALIDATION_ERROR",
            "error": "question is required",
        }
    urgent = str(urgency or "").lower() in {"urgent", "immediate", "blocking"}
    topic = q
    if instrument:
        topic = f"{q} (instrument={instrument})"
    if strategy_id:
        topic = f"{topic} (strategy={strategy_id})"
    try:
        project = research_service.create_project(
            title=f"Trading research gap — {instrument or strategy_id or 'general'}",
            topic=topic[:500],
            objective=(
                "Evidence-seeking research requested by Trading Orchestra. "
                "Distinguish search hits from fetched sources from evidence from claims."
            ),
            depth="standard",
            allow_web=bool(allow_web),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "FAILED",
            "error_code": "RESEARCH_CREATE_FAILED",
            "error": str(exc)[:400],
            "urgency": urgency,
            "decisionHint": "HOLD" if urgent else "DEFER",
        }
    project_id = getattr(project, "project_id", None) or (
        project.get("project_id") if isinstance(project, dict) else None
    )
    # Kick off asynchronously when possible — never sync-crawl in order path.
    queued = False
    try:
        if hasattr(research_service, "run"):
            research_service.run(project_id, background=True)
            queued = True
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "WAITING",
            "error_code": "RESEARCH_QUEUE_FAILED",
            "error": str(exc)[:400],
            "projectId": project_id,
            "queued": False,
            "decisionHint": "HOLD" if urgent else "DEFER",
            "createdAt": _utc_now(),
        }
    return {
        "status": "WAITING" if urgent else "QUEUED",
        "projectId": project_id,
        "queued": queued,
        "urgency": urgency,
        "decisionHint": "HOLD" if urgent else "DEFER",
        "decisionCode": "INSUFFICIENT_EVIDENCE" if urgent else "RESEARCH_DEFERRED",
        "createdAt": _utc_now(),
        "truth": {
            "not_order_critical_path": True,
            "synchronous_web_research_forbidden_here": True,
            "live_trading_blocked": True,
        },
    }
