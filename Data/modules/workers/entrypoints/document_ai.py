"""document_ai worker pool entrypoint — OCR / Document AI execution owner.

Honest readiness: when no real OCR backend is configured the handler fails
closed with typed OCR_UNAVAILABLE. Never fabricates extracted text.
"""
from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool

# Capability ids owned by this pool (must stay EXTERNAL_REQUIRED).
OCR_CAPABILITIES = frozenset(
    {
        "ocr.extract",
        "document_ai.ocr",
        "document_ai.extract",
        "document_ai.process",
    }
)


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """Execute OCR/document-AI jobs — currently no configured backend.

    Returns a typed unavailable receipt. Job is failed (not SUCCESS) so callers
    never treat missing OCR as completed extraction.
    """
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.source_ingestion.types import (
        ERROR_DOCUMENT_AI_UNAVAILABLE,
        ERROR_OCR_UNAVAILABLE,
    )

    capability = str(getattr(job, "capability_id", "") or "")
    args = dict(getattr(job, "arguments", None) or {})
    source_id = str(args.get("source_id") or "")
    worker_id = str(ctx.get("worker_id") or "")
    receipt = {
        "capability_id": capability,
        "source_id": source_id,
        "project_id": args.get("project_id"),
        "relative_path": args.get("relative_path"),
        "status": ERROR_OCR_UNAVAILABLE,
        "error_code": ERROR_OCR_UNAVAILABLE,
        "reason": "OCR backend missing",
        "extracted_text": None,
        "extracted_chars": 0,
        "truth": {
            "ocr_backend": "missing",
            "fabricated": False,
            "executed_inline": False,
            "pool": "document_ai",
            "parent_job_id": getattr(job, "parent_job_id", None),
            "root_job_id": getattr(job, "root_job_id", None),
        },
    }
    # Prefer DOCUMENT_AI_UNAVAILABLE when the capability is under document_ai.*
    if capability.startswith("document_ai."):
        receipt["status"] = ERROR_DOCUMENT_AI_UNAVAILABLE
        receipt["error_code"] = ERROR_DOCUMENT_AI_UNAVAILABLE
        receipt["reason"] = "Document AI backend missing"

    store = ctx["job_store"]
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            error=f"{receipt['error_code']}: {receipt['reason']}",
            result=receipt,
        )
    except Exception:
        # Lease may have been reclaimed — do not fabricate SUCCESS.
        pass
    return receipt


def main(argv=None):
    return main_for_pool("document_ai", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
