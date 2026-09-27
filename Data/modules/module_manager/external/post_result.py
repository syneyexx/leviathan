"""Post-result hooks for external capabilities: evidence + background assimilation.

Does not block chat. Large/knowledge work is JobRuntime-queued when a runtime is available.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Any, Mapping

from .types import AssimilationMode


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_assimilation_mode(definition_metadata: Mapping[str, Any] | None, output: Mapping[str, Any] | None) -> AssimilationMode:
    meta = dict(definition_metadata or {})
    raw = meta.get("assimilation_mode")
    if not raw and isinstance(output, Mapping):
        raw = (output.get("metadata") or {}).get("assimilation_mode")
    try:
        return AssimilationMode(str(raw or "NONE").upper())
    except ValueError:
        return AssimilationMode.NONE


def queue_or_run_assimilation(
    *,
    mode: AssimilationMode,
    capability_id: str,
    module_id: str | None,
    request_id: str,
    run_id: str | None,
    job_id: str | None,
    output: Mapping[str, Any] | None,
    status: str,
    job_runtime: Any | None = None,
    assimilation_service: Any | None = None,
    evidence_service: Any | None = None,
    observation_id: str | None = None,
    observability: Any | None = None,
) -> dict[str, Any]:
    """Schedule assimilation according to mode. NEVER blocks on large ingest when JobRuntime available."""
    if mode == AssimilationMode.NONE or str(status).upper() not in {"COMPLETED", "OK", "SUCCESS"}:
        return {"queued": False, "mode": mode.value, "reason": "skipped"}

    # Process-local idempotency for sync/fallback path (JobRuntime key covers queued path).
    idem_key = assimilation_idempotency_key(capability_id, request_id or "")
    if request_id and not mark_assim_seen(idem_key):
        return {"queued": False, "mode": mode.value, "reason": "duplicate_skipped", "idempotency_key": idem_key}

    out = dict(output or {})
    sources = list(out.get("source_refs") or out.get("sources") or [])
    # Prefer earliest source published_at when present — do not strip dynamic-content time.
    published_candidates = []
    available_candidates = []
    for src in sources:
        if isinstance(src, Mapping):
            if src.get("published_at"):
                published_candidates.append(str(src["published_at"]))
            if src.get("available_at"):
                available_candidates.append(str(src["available_at"]))
    meta_out = dict(out.get("metadata") or {})
    retrieved_at = str(meta_out.get("retrieved_at") or utc_now())
    payload = {
        "mode": mode.value,
        "capability_id": capability_id,
        "module_id": module_id,
        "request_id": request_id,
        "run_id": run_id,
        "job_id": job_id,
        "observation_id": observation_id,
        "output": _bounded_output(output),
        "retrieved_at": retrieved_at,
        "published_at": published_candidates[0] if published_candidates else meta_out.get("published_at"),
        "available_at": available_candidates[0] if available_candidates else meta_out.get("available_at"),
        "source_count": len(sources),
        "provenance_retained": True,
    }

    # EVIDENCE-only: claim observation evidence inline (tiny CONTROL_WRITE).
    evidence_id = None
    if mode in {AssimilationMode.EVIDENCE, AssimilationMode.KNOWLEDGE_CANDIDATE, AssimilationMode.AUTO_KNOWLEDGE}:
        if evidence_service is not None and observation_id:
            try:
                record = evidence_service.claim_observation_ref(
                    observation_id=observation_id,
                    claim=f"external capability {capability_id} observation",
                    run_id=run_id,
                )
                evidence_id = getattr(record, "evidence_id", None) or (
                    record.get("evidence_id") if isinstance(record, dict) else None
                )
                payload["evidence_id"] = evidence_id
            except Exception as exc:  # noqa: BLE001
                payload["evidence_error"] = str(exc)

    if mode == AssimilationMode.EVIDENCE:
        _emit(observability, "knowledge.assimilation_queued", {"mode": mode.value, "capability_id": capability_id, "evidence_only": True})
        _emit(observability, "knowledge.assimilated", {"mode": mode.value, "capability_id": capability_id, "evidence_id": evidence_id})
        return {"queued": False, "mode": mode.value, "evidence_id": evidence_id, "completed": True}

    # Knowledge candidate / auto — prefer background job.
    if job_runtime is not None:
        try:
            from Data.modules.execution import CapabilityRequest

            job = job_runtime.enqueue(
                CapabilityRequest(
                    capability_id="external.knowledge.assimilate",
                    arguments=payload,
                    requested_by="external.fabric",
                    run_id=run_id,
                    idempotency_key=f"assim:{capability_id}:{request_id}",
                )
            )
            _emit(
                observability,
                "knowledge.assimilation_queued",
                {"mode": mode.value, "capability_id": capability_id, "job_id": getattr(job, "job_id", None)},
            )
            return {"queued": True, "mode": mode.value, "job_id": getattr(job, "job_id", None), "evidence_id": evidence_id}
        except Exception as exc:  # noqa: BLE001 — fall through to sync best-effort
            payload["enqueue_error"] = str(exc)

    # Sync fallback (tests / no JobRuntime) — still best-effort, never raise to caller.
    if assimilation_service is not None:
        try:
            receipt = assimilation_service.assimilate_external_capability(**payload)
            _emit(
                observability,
                "knowledge.assimilated",
                {
                    "mode": mode.value,
                    "capability_id": capability_id,
                    "receipt_id": getattr(receipt, "receipt_id", None),
                    "ok": getattr(receipt, "ok", False),
                },
            )
            return {
                "queued": False,
                "mode": mode.value,
                "completed": True,
                "receipt": receipt.public_dict() if hasattr(receipt, "public_dict") else receipt,
                "evidence_id": evidence_id,
            }
        except Exception as exc:  # noqa: BLE001
            return {"queued": False, "mode": mode.value, "error": str(exc)}

    return {"queued": False, "mode": mode.value, "reason": "assimilation_service_unavailable", "evidence_id": evidence_id}


def run_assimilation_job(
    arguments: Mapping[str, Any],
    *,
    assimilation_service: Any,
) -> dict[str, Any]:
    receipt = assimilation_service.assimilate_external_capability(**dict(arguments))
    return receipt.public_dict() if hasattr(receipt, "public_dict") else dict(receipt)


def _bounded_output(output: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, Mapping):
        return {}
    out = {
        "summary": output.get("summary"),
        "source_refs": list(output.get("source_refs") or [])[:50],
        "artifact_refs": list(output.get("artifact_refs") or [])[:50],
        "metadata": dict(output.get("metadata") or {}),
    }
    structured = output.get("structured_data")
    if isinstance(structured, dict):
        # Keep bounded structured slice only.
        import json

        encoded = json.dumps(structured, default=str)
        if len(encoded) <= 32_000:
            out["structured_data"] = structured
        else:
            out["structured_data_truncated"] = True
            out["structured_excerpt"] = encoded[:4000]
    return out


def _emit(observability: Any, event: str, payload: dict[str, Any]) -> None:
    if observability is None:
        return
    try:
        observability.emit("external_capability", event, payload=payload)
    except Exception:  # noqa: BLE001
        pass


_idempotency_lock = threading.Lock()
_seen_keys: set[str] = set()


def assimilation_idempotency_key(capability_id: str, request_id: str) -> str:
    return f"assim:{capability_id}:{request_id}"


def mark_assim_seen(key: str) -> bool:
    """Return True if this is the first time seeing the key (should run)."""
    with _idempotency_lock:
        if key in _seen_keys:
            return False
        _seen_keys.add(key)
        if len(_seen_keys) > 10_000:
            # Bound process-local cache.
            _seen_keys.clear()
            _seen_keys.add(key)
        return True


def content_hash_for(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
