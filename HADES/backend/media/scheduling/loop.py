
"""Durable media automation loop — leases, budgets, no busy while-True burn."""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MediaScheduler:
    def __init__(
        self,
        store: Any,
        orchestrator: Any,
        *,
        tick_seconds: float = 15.0,
        publish_handler: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.tick_seconds = max(5.0, float(tick_seconds))
        self.publish_handler = publish_handler
        self.owner = f"msched_{secrets.token_hex(3)}"
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="media-scheduler")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
            except Exception:
                # Never die the loop silently forever without backoff.
                await asyncio.sleep(self.tick_seconds)
                continue
            await asyncio.sleep(self.tick_seconds)

    async def tick(self) -> dict[str, Any]:
        if not self.store.claim_scheduler_lease("media_main", self.owner, ttl_seconds=int(self.tick_seconds) + 30):
            return {"ok": True, "skipped": "lease_held"}
        summary: dict[str, Any] = {"advanced": [], "published": [], "spawned": []}
        try:
            # Advance in-flight projects.
            producing = self.store.list_projects(limit=20)
            for project in producing:
                if project["stage"] in {
                    "COMPLETE",
                    "FAILED",
                    "CANCELLED",
                    "WAITING_FOR_APPROVAL",
                    "WAITING_PLATFORM_CONSENT",
                    "READY_TO_PUBLISH",
                    "PUBLISHED",
                    "SCHEDULED",
                }:
                    continue
                result = await self.orchestrator.advance_project(project["id"], max_stages=3)
                summary["advanced"].append({"project_id": project["id"], "ok": result.get("ok"), "stage": (result.get("project") or {}).get("stage")})

            # Spawn autonomous campaigns within budgets.
            for channel in self.store.list_channels(limit=50):
                if not channel.get("enabled"):
                    continue
                if channel.get("autonomy_level") not in {"RESEARCH", "PRODUCE", "QUEUE", "AUTONOMOUS"}:
                    continue
                today = utc_now()[:10]
                producing_count = self.store.count_projects_by_stages(
                    [
                        "DISCOVERING",
                        "INGESTING",
                        "TRANSCRIBING",
                        "ANALYZING_SOURCES",
                        "ANALYZING_TRENDS",
                        "RESEARCHING",
                        "SELECTING_OPPORTUNITY",
                        "DEVELOPING_CONCEPT",
                        "SCRIPTING",
                        "SCRIPT_CRITIQUE",
                        "STORYBOARDING",
                        "GENERATING_VISUALS",
                        "GENERATING_VOICE",
                        "GENERATING_AUDIO",
                        "EDITING",
                        "RENDERING",
                        "QUALITY_CHECK",
                        "PLATFORM_ADAPTATION",
                    ]
                )
                if producing_count >= int(channel.get("max_projects_per_day") or 3):
                    continue
                # Limit spawn rate: at most one new project per channel per tick when under cap.
                existing_today = [
                    p
                    for p in self.store.list_projects(channel_id=channel["id"], limit=50)
                    if str(p.get("created_at") or "").startswith(today)
                ]
                if len(existing_today) >= int(channel.get("max_projects_per_day") or 3):
                    continue
                project = self.store.create_project(
                    {
                        "channel_id": channel["id"],
                        "title": f"Auto {channel.get('niche') or channel.get('name')}",
                        "topic": (channel.get("preferred_topics") or [channel.get("niche") or channel.get("name")])[0],
                        "platforms": channel.get("platforms") or [],
                        "autonomy_level": channel.get("autonomy_level"),
                    }
                )
                summary["spawned"].append(project["id"])

            # Publish approved jobs when handler present.
            if self.publish_handler is not None:
                for job in self.store.list_publish_jobs(status="APPROVED", limit=10):
                    if job.get("platform_consent_state") == "required":
                        # Wait until consent recorded.
                        continue
                    result = self.publish_handler(job)
                    if hasattr(result, "__await__"):
                        result = await result
                    summary["published"].append({"job_id": job["id"], "result": result})
        finally:
            self.store.release_scheduler_lease("media_main", self.owner)
        return {"ok": True, **summary}
