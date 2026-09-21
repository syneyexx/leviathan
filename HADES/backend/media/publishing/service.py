
"""Durable idempotent publishing across platform adapters."""

from __future__ import annotations

from typing import Any

from media.models import ProjectStage


class PublishingService:
    def __init__(self, store: Any, adapters: Any, events: Any | None = None) -> None:
        self.store = store
        self.adapters = adapters
        self.events = events

    def approve_jobs(self, job_ids: list[str], *, platform_consent: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out = []
        consent = platform_consent or {}
        for job_id in job_ids:
            job = self.store.get_publish_job(job_id)
            if not job:
                continue
            updates: dict[str, Any] = {"approval_state": "approved", "status": "APPROVED"}
            if job["platform"] in consent:
                updates["platform_consent_state"] = "granted"
                payload = dict(job.get("payload") or {})
                payload["consent"] = consent[job["platform"]]
                updates["payload"] = payload
            elif job.get("platform_consent_state") == "required":
                updates["status"] = "WAITING_PLATFORM_CONSENT"
                updates["platform_consent_state"] = "waiting"
                self.store.update_project(job["project_id"], stage=ProjectStage.WAITING_PLATFORM_CONSENT.value)
            out.append(self.store.update_publish_job(job_id, **updates))
        return out

    def publish_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_publish_job(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        # Idempotency: already published.
        if job.get("status") == "PUBLISHED" and job.get("external_post_id"):
            return {"ok": True, "status": "PUBLISHED", "job": job, "idempotent": True}
        if job.get("external_upload_id") and job.get("status") in {"UPLOADING", "PROCESSING"}:
            return self.reconcile_job(job_id)

        adapter = self.adapters.get(job["platform"]) if self.adapters else None
        if adapter is None:
            return {"ok": False, "status": "UNAVAILABLE", "error": "adapter_missing"}

        if job.get("platform_consent_state") in {"required", "waiting"}:
            updated = self.store.update_publish_job(job_id, status="WAITING_PLATFORM_CONSENT")
            return {"ok": False, "status": "WAITING_PLATFORM_CONSENT", "job": updated}

        variant = self.store.get_variant(job["variant_id"]) if job.get("variant_id") else None
        if not variant:
            return {"ok": False, "error": "variant_missing"}

        attempt = int(job.get("attempt_count") or 0) + 1
        self.store.update_publish_job(
            job_id,
            attempt_count=attempt,
            last_attempt_at=__import__("media.store", fromlist=["utc_now"]).utc_now(),
            status="UPLOADING",
        )
        consent = (job.get("payload") or {}).get("consent")
        try:
            result = adapter.publish(job, variant, consent=consent)
        except Exception as exc:
            updated = self.store.update_publish_job(job_id, status="FAILED", error=str(exc)[:800])
            return {"ok": False, "status": "FAILED", "job": updated, "error": str(exc)}

        if result.get("status") == "WAITING_PLATFORM_CONSENT":
            updated = self.store.update_publish_job(
                job_id,
                status="WAITING_PLATFORM_CONSENT",
                platform_consent_state="waiting",
                error=result.get("detail"),
            )
            self.store.update_project(job["project_id"], stage=ProjectStage.WAITING_PLATFORM_CONSENT.value)
            return {"ok": False, "status": "WAITING_PLATFORM_CONSENT", "job": updated, "result": result}

        if not result.get("ok") and result.get("status") not in {"PROCESSING", "PUBLISHED"}:
            updated = self.store.update_publish_job(job_id, status="FAILED", error=str(result.get("detail") or result.get("status"))[:800])
            self.store.add_publish_record(
                {"job_id": job_id, "platform": job["platform"], "status": "FAILED", "raw": result}
            )
            return {"ok": False, "status": "FAILED", "job": updated, "result": result}

        status = "PUBLISHED" if result.get("status") == "PUBLISHED" else "PROCESSING"
        updated = self.store.update_publish_job(
            job_id,
            status=status,
            external_upload_id=result.get("external_upload_id"),
            external_post_id=result.get("external_post_id"),
            error=None,
        )
        self.store.add_publish_record(
            {
                "job_id": job_id,
                "platform": job["platform"],
                "external_post_id": result.get("external_post_id"),
                "status": status,
                "raw": {k: v for k, v in result.items() if k != "content"},
            }
        )
        if status == "PUBLISHED":
            self._maybe_complete_project(job["project_id"])
        if self.events:
            self.events.emit("media.publish.status", {"job_id": job_id, "status": status, "platform": job["platform"]})
        return {"ok": True, "status": status, "job": updated, "result": result}

    def reconcile_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_publish_job(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        if job.get("status") == "PUBLISHED" and job.get("external_post_id"):
            return {"ok": True, "status": "PUBLISHED", "job": job, "idempotent": True}
        adapter = self.adapters.get(job["platform"]) if self.adapters else None
        if adapter is None or not job.get("external_upload_id"):
            return {"ok": False, "status": job.get("status"), "job": job}
        status = adapter.publish_status(job["external_upload_id"])
        remote = str(status.get("status") or "").upper()
        if remote in {"PUBLISH_COMPLETE", "PUBLISHED", "FINISHED", "SUCCESS"}:
            updated = self.store.update_publish_job(
                job_id,
                status="PUBLISHED",
                external_post_id=status.get("external_post_id") or job.get("external_post_id") or job.get("external_upload_id"),
            )
            self._maybe_complete_project(job["project_id"])
            return {"ok": True, "status": "PUBLISHED", "job": updated, "remote": status}
        if remote in {"FAILED", "ERROR"}:
            updated = self.store.update_publish_job(job_id, status="FAILED", error=str(status)[:800])
            return {"ok": False, "status": "FAILED", "job": updated, "remote": status}
        return {"ok": True, "status": "PROCESSING", "job": job, "remote": status}

    def _maybe_complete_project(self, project_id: str) -> None:
        jobs = self.store.list_publish_jobs(project_id=project_id, limit=50)
        if not jobs:
            return
        # Complete when every non-consent-blocked job is published; blocked platforms don't halt others.
        active = [j for j in jobs if j.get("status") not in {"CANCELLED"}]
        unresolved = [
            j
            for j in active
            if j.get("status") not in {"PUBLISHED", "WAITING_PLATFORM_CONSENT", "FAILED"}
        ]
        if unresolved:
            return
        if any(j.get("status") == "PUBLISHED" for j in active):
            self.store.update_project(project_id, stage=ProjectStage.PUBLISHED.value, progress=1.0)
