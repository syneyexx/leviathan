
"""High-level MediaService facade used by routes and app lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from media.analytics.engine import AnalyticsEngine
from media.capabilities import MediaCapabilityDoctor
from media.creative.pipeline import CreativePipeline
from media.events import MediaEventBus
from media.experiments.engine import ExperimentEngine
from media.learning.engine import LearningEngine
from media.models import AutonomyLevel, ChannelCreate, ChannelUpdate, ProjectCreate, ProjectStage, SourceIngest
from media.orchestrator import MediaOrchestrator
from media.paths import MediaPaths, content_hash_bytes
from media.platforms.registry import build_adapter_registry
from media.publishing.service import PublishingService
from media.rendering.ffmpeg_renderer import FFmpegRenderer
from media.research.engine import ResearchEngine
from media.scheduling.loop import MediaScheduler
from media.store import MediaStore
from media.transcription.engine import TranscriptionEngine
from media.trends.engine import TrendEngine
from media.trends.providers import HistoricalPerformanceTrendProvider, StaticSeedTrendProvider


class MediaService:
    def __init__(
        self,
        *,
        database_path: str | Path,
        data_root: str | Path,
        get_setting: Callable[[str], Any] | None = None,
        secrets: dict[str, str] | None = None,
        platform_config: dict[str, Any] | None = None,
        event_emitter: Callable[[str, dict[str, Any]], None] | None = None,
        research_retrieve: Callable[..., Any] | None = None,
        http: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.store = MediaStore(database_path)
        self.paths = MediaPaths(data_root)
        self.get_setting = get_setting or (lambda _k: None)
        self.secrets = dict(secrets or {})
        self.platform_config = dict(platform_config or {})
        self.events = MediaEventBus(event_emitter)
        self.adapters = build_adapter_registry(secrets=self.secrets, config=self.platform_config, http=http)
        self.trends = TrendEngine(
            self.store,
            providers=[
                StaticSeedTrendProvider(
                    [
                        {"topic": "Roman concrete self-healing", "platform": "web", "velocity": 72, "freshness": 80, "competition": 45, "confidence": 0.5},
                        {"topic": "Strange historical maps", "platform": "youtube", "velocity": 64, "freshness": 70, "competition": 55, "confidence": 0.45},
                        {"topic": "Lost engineering techniques", "platform": "web", "velocity": 58, "freshness": 66, "competition": 50, "confidence": 0.42},
                    ]
                ),
                HistoricalPerformanceTrendProvider(self.store),
            ],
        )
        self.research = ResearchEngine(self.store, retrieve=research_retrieve)
        self.creative = CreativePipeline(self.store)
        self.transcription = TranscriptionEngine(self.store)
        self.renderer = FFmpegRenderer()
        self.orchestrator = MediaOrchestrator(
            self.store,
            data_root=data_root,
            events=self.events,
            trend_engine=self.trends,
            research_engine=self.research,
            creative=self.creative,
            transcription=self.transcription,
            renderer=self.renderer,
            adapters=self.adapters,
        )
        self.publishing = PublishingService(self.store, self.adapters, events=self.events)
        self.analytics = AnalyticsEngine(self.store)
        self.learning = LearningEngine(self.store)
        self.experiments = ExperimentEngine(self.store)
        self.scheduler = MediaScheduler(self.store, self.orchestrator, publish_handler=self._publish_approved)

    async def start(self) -> None:
        await self.scheduler.start()

    async def stop(self) -> None:
        await self.scheduler.stop()

    def capabilities(self) -> dict[str, Any]:
        accounts = self.store.list_accounts()
        platform_auth = {}
        for name, adapter in self.adapters.all().items():
            platform_auth[name] = adapter.auth_status()
        doctor = MediaCapabilityDoctor(
            data_root=self.paths.root.parent,
            get_setting=self.get_setting,
            accounts=accounts,
            platform_auth=platform_auth,
        )
        return doctor.snapshot()

    def overview(self) -> dict[str, Any]:
        caps = self.capabilities()
        today = datetime.now(UTC).isoformat(timespec="seconds")[:10]
        producing_stages = [
            s.value
            for s in ProjectStage
            if s.value
            not in {
                "CREATED",
                "READY_TO_PUBLISH",
                "WAITING_FOR_APPROVAL",
                "WAITING_PLATFORM_CONSENT",
                "SCHEDULED",
                "PUBLISHED",
                "COLLECTING_METRICS",
                "LEARNING",
                "COMPLETE",
                "FAILED",
                "CANCELLED",
            }
        ]
        platforms = {
            k: v
            for k, v in (caps.get("platforms") or {}).items()
        }
        return {
            "engine_status": "ACTIVE",
            "channels": self.store.count_channels(),
            "trend_signals": self.store.count_trend_signals(),
            "opportunities": self.store.count_opportunities(),
            "projects_producing": self.store.count_projects_by_stages(producing_stages),
            "ready_to_publish": self.store.count_projects_by_stages(["READY_TO_PUBLISH", "WAITING_FOR_APPROVAL"]),
            "published_today": self.store.count_published_since(today),
            "failures": self.store.count_projects_by_stages(["FAILED"]),
            "platforms": platforms,
            "campaigns": self.store.list_channels(limit=20),
            "active_generation": self.store.list_projects(limit=20),
            "publish_queue": self.store.list_publish_jobs(limit=20),
            "trending_opportunities": self.store.list_opportunities(limit=12),
            "experiments": self.store.list_experiments(limit=10),
            "learning_findings": self.store.list_learning_findings(limit=10),
            "blockers": self._blockers(caps),
            "budget": {},
            "recent_failures": [p for p in self.store.list_projects(stage="FAILED", limit=10)],
            "capabilities": caps,
        }

    def _blockers(self, caps: dict[str, Any]) -> list[dict[str, Any]]:
        blockers = []
        for section in ("generation", "platforms", "automation"):
            for item in (caps.get(section) or {}).values():
                status = item.get("status")
                if status in {"READY", "PARTIAL", "DEGRADED", "UNVERIFIED_ON_HOST", "PRIVATE_ONLY"}:
                    continue
                blockers.append(item)
        return blockers

    def create_channel(self, payload: ChannelCreate | dict[str, Any]) -> dict[str, Any]:
        data = payload.model_dump() if isinstance(payload, ChannelCreate) else dict(payload)
        return self.store.create_channel(data)

    def update_channel(self, channel_id: str, payload: ChannelUpdate | dict[str, Any]) -> dict[str, Any] | None:
        data = payload.model_dump(exclude_unset=True) if isinstance(payload, ChannelUpdate) else dict(payload)
        return self.store.update_channel(channel_id, data)

    def create_project(self, payload: ProjectCreate | dict[str, Any]) -> dict[str, Any]:
        data = payload.model_dump() if isinstance(payload, ProjectCreate) else dict(payload)
        channel = self.store.get_channel(data["channel_id"])
        if not channel:
            raise ValueError("channel_not_found")
        platforms = data.get("platforms") or channel.get("platforms") or []
        autonomy = data.get("autonomy_override") or channel.get("autonomy_level") or AutonomyLevel.OFF.value
        project = self.store.create_project(
            {
                "channel_id": data["channel_id"],
                "title": data.get("title") or data.get("topic") or "Untitled",
                "topic": data.get("topic") or "",
                "platforms": platforms,
                "autonomy_level": autonomy,
                "artifacts": {"seed_source": data.get("seed_source") or {}},
            }
        )
        return project

    async def run_project(self, project_id: str, *, max_stages: int = 30) -> dict[str, Any]:
        return await self.orchestrator.advance_project(project_id, max_stages=max_stages)

    def ingest_source(self, payload: SourceIngest | dict[str, Any]) -> dict[str, Any]:
        data = payload.model_dump() if isinstance(payload, SourceIngest) else dict(payload)
        text = data.get("text") or ""
        content_hash = content_hash_bytes(text.encode("utf-8")) if text else content_hash_bytes(str(data.get("uri") or "").encode("utf-8"))
        return self.store.create_source(
            {
                "channel_id": data.get("channel_id"),
                "project_id": data.get("project_id"),
                "source_kind": data["source_kind"],
                "uri": data.get("uri") or "",
                "content_hash": content_hash,
                "text_excerpt": text[:4000],
                "metadata": data.get("metadata") or {},
            }
        )

    async def discover_trends(self, *, query: str = "", channel_id: str | None = None) -> dict[str, Any]:
        channel = self.store.get_channel(channel_id) if channel_id else None
        result = await self.trends.discover(query=query or ((channel or {}).get("niche") or ""), language=(channel or {}).get("language") or "en")
        opportunities = []
        for trend in result.get("trends") or []:
            opportunities.append(self.trends.create_opportunity_for_trend(trend, channel))
        result["opportunities"] = opportunities
        return result

    def _publish_approved(self, job: dict[str, Any]) -> dict[str, Any]:
        return self.publishing.publish_job(job["id"])

    def setup_checklist(self) -> dict[str, Any]:
        caps = self.capabilities()
        return {
            "capabilities": caps,
            "external_actions": [
                {"id": "ffmpeg", "needed": caps["generation"]["ffmpeg"]["status"] != "READY", "action": "Install FFmpeg on PATH"},
                {"id": "youtube", "needed": caps["platforms"]["youtube"]["status"] == "AUTH_REQUIRED", "action": "Google Cloud OAuth + YouTube Data API"},
                {"id": "tiktok", "needed": caps["platforms"]["tiktok"]["status"] in {"AUTH_REQUIRED", "PLATFORM_AUDIT_REQUIRED", "PRIVATE_ONLY"}, "action": "TikTok developer app + Content Posting API + audit for public posts"},
                {"id": "instagram", "needed": caps["platforms"]["instagram"]["status"] in {"AUTH_REQUIRED", "APP_REVIEW_REQUIRED"}, "action": "Meta app + Instagram professional account OAuth / App Review"},
                {"id": "facebook", "needed": caps["platforms"]["facebook"]["status"] in {"AUTH_REQUIRED", "PAGE_REQUIRED"}, "action": "Meta app + Facebook Page token with pages_manage_posts"},
                {"id": "comfyui", "needed": caps["generation"]["image"]["status"] == "SETUP_REQUIRED", "action": "Optional: configure ComfyUI endpoint"},
            ],
        }
