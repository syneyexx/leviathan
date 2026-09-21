"""Typed contracts for the Media Intelligence domain."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MediaPlatform(str, Enum):
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"


class AutonomyLevel(str, Enum):
    OFF = "OFF"
    RESEARCH = "RESEARCH"
    PRODUCE = "PRODUCE"
    QUEUE = "QUEUE"
    AUTONOMOUS = "AUTONOMOUS"


class CapabilityTruth(str, Enum):
    READY = "READY"
    SETUP_REQUIRED = "SETUP_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    APP_REVIEW_REQUIRED = "APP_REVIEW_REQUIRED"
    PLATFORM_AUDIT_REQUIRED = "PLATFORM_AUDIT_REQUIRED"
    PRIVATE_ONLY = "PRIVATE_ONLY"
    PAGE_REQUIRED = "PAGE_REQUIRED"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED_ON_HOST = "UNVERIFIED_ON_HOST"
    FAILED = "FAILED"
    PLATFORM_LIMITATION = "PLATFORM_LIMITATION"


class ProjectStage(str, Enum):
    CREATED = "CREATED"
    DISCOVERING = "DISCOVERING"
    INGESTING = "INGESTING"
    TRANSCRIBING = "TRANSCRIBING"
    ANALYZING_SOURCES = "ANALYZING_SOURCES"
    ANALYZING_TRENDS = "ANALYZING_TRENDS"
    RESEARCHING = "RESEARCHING"
    SELECTING_OPPORTUNITY = "SELECTING_OPPORTUNITY"
    DEVELOPING_CONCEPT = "DEVELOPING_CONCEPT"
    SCRIPTING = "SCRIPTING"
    SCRIPT_CRITIQUE = "SCRIPT_CRITIQUE"
    STORYBOARDING = "STORYBOARDING"
    GENERATING_VISUALS = "GENERATING_VISUALS"
    GENERATING_VOICE = "GENERATING_VOICE"
    GENERATING_AUDIO = "GENERATING_AUDIO"
    EDITING = "EDITING"
    RENDERING = "RENDERING"
    QUALITY_CHECK = "QUALITY_CHECK"
    PLATFORM_ADAPTATION = "PLATFORM_ADAPTATION"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_PLATFORM_CONSENT = "WAITING_PLATFORM_CONSENT"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    COLLECTING_METRICS = "COLLECTING_METRICS"
    LEARNING = "LEARNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LicenseState(str, Enum):
    GENERATED = "GENERATED"
    USER_OWNED = "USER_OWNED"
    LICENSED = "LICENSED"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    UNKNOWN = "UNKNOWN"


class AssetStrategy(str, Enum):
    GENERATED_IMAGE = "GENERATED_IMAGE"
    GENERATED_VIDEO = "GENERATED_VIDEO"
    AUTHORIZED_STOCK = "AUTHORIZED_STOCK"
    USER_ASSET = "USER_ASSET"
    MOTION_GRAPHICS = "MOTION_GRAPHICS"
    TEXT_GRAPHICS = "TEXT_GRAPHICS"
    SCREENSHOT_WHERE_ALLOWED = "SCREENSHOT_WHERE_ALLOWED"


class ContentFormat(str, Enum):
    SHORT_VERTICAL = "SHORT_VERTICAL"
    LONG_HORIZONTAL = "LONG_HORIZONTAL"
    YOUTUBE_SHORT = "YOUTUBE_SHORT"
    YOUTUBE_LONG = "YOUTUBE_LONG"
    TIKTOK_VIDEO = "TIKTOK_VIDEO"
    INSTAGRAM_REEL = "INSTAGRAM_REEL"
    FACEBOOK_REEL = "FACEBOOK_REEL"
    FACEBOOK_PAGE_VIDEO = "FACEBOOK_PAGE_VIDEO"


class PublishJobStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    WAITING_PLATFORM_CONSENT = "WAITING_PLATFORM_CONSENT"
    SCHEDULED = "SCHEDULED"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# Ordered production pipeline (excludes terminal / wait states used as branches).
PIPELINE_STAGES: tuple[ProjectStage, ...] = (
    ProjectStage.CREATED,
    ProjectStage.DISCOVERING,
    ProjectStage.INGESTING,
    ProjectStage.TRANSCRIBING,
    ProjectStage.ANALYZING_SOURCES,
    ProjectStage.ANALYZING_TRENDS,
    ProjectStage.RESEARCHING,
    ProjectStage.SELECTING_OPPORTUNITY,
    ProjectStage.DEVELOPING_CONCEPT,
    ProjectStage.SCRIPTING,
    ProjectStage.SCRIPT_CRITIQUE,
    ProjectStage.STORYBOARDING,
    ProjectStage.GENERATING_VISUALS,
    ProjectStage.GENERATING_VOICE,
    ProjectStage.GENERATING_AUDIO,
    ProjectStage.EDITING,
    ProjectStage.RENDERING,
    ProjectStage.QUALITY_CHECK,
    ProjectStage.PLATFORM_ADAPTATION,
    ProjectStage.READY_TO_PUBLISH,
)

TERMINAL_STAGES = frozenset(
    {
        ProjectStage.COMPLETE,
        ProjectStage.FAILED,
        ProjectStage.CANCELLED,
    }
)

ALLOWED_PLATFORMS = frozenset(p.value for p in MediaPlatform)
ALLOWED_AUTONOMY = frozenset(a.value for a in AutonomyLevel)


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    niche: str = Field(default="", max_length=200)
    sub_niches: list[str] = Field(default_factory=list, max_length=40)
    language: str = Field(default="en", max_length=16)
    target_region: str = Field(default="", max_length=80)
    target_audience: str = Field(default="", max_length=400)
    platforms: list[str] = Field(default_factory=list, min_length=1, max_length=8)
    content_formats: list[str] = Field(default_factory=lambda: [ContentFormat.SHORT_VERTICAL.value])
    posting_frequency: str = Field(default="1/day", max_length=64)
    schedule_windows: list[dict[str, Any]] = Field(default_factory=list)
    timezone: str = Field(default="UTC", max_length=64)
    autonomy_level: str = Field(default=AutonomyLevel.OFF.value, max_length=32)
    voice_persona: dict[str, Any] = Field(default_factory=dict)
    visual_persona: dict[str, Any] = Field(default_factory=dict)
    tone: str = Field(default="", max_length=200)
    content_length: str = Field(default="short", max_length=64)
    preferred_topics: list[str] = Field(default_factory=list, max_length=80)
    excluded_topics: list[str] = Field(default_factory=list, max_length=80)
    fact_strictness: str = Field(default="high", max_length=32)
    cta_strategy: str = Field(default="", max_length=400)
    music_policy: str = Field(default="generated_or_licensed", max_length=64)
    asset_policy: str = Field(default="generated_or_user", max_length=64)
    ai_disclosure_policy: str = Field(default="disclose", max_length=64)
    budget: dict[str, Any] = Field(default_factory=dict)
    experiment_policy: dict[str, Any] = Field(default_factory=dict)
    account_mappings: dict[str, Any] = Field(default_factory=dict)
    max_projects_per_day: int = Field(default=3, ge=0, le=100)
    max_published_per_day: int = Field(default=3, ge=0, le=100)
    max_llm_calls: int = Field(default=200, ge=0, le=100_000)
    max_image_generations: int = Field(default=40, ge=0, le=10_000)
    max_video_generations: int = Field(default=5, ge=0, le=1000)
    max_voice_generations: int = Field(default=40, ge=0, le=10_000)
    max_retries: int = Field(default=3, ge=0, le=20)
    exploration_rate: float = Field(default=0.2, ge=0.0, le=1.0)

    @field_validator("platforms")
    @classmethod
    def _platforms(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            key = str(item or "").strip().lower()
            if key not in ALLOWED_PLATFORMS:
                raise ValueError(f"Unsupported platform: {item}")
            if key not in cleaned:
                cleaned.append(key)
        if not cleaned:
            raise ValueError("At least one platform is required")
        return cleaned

    @field_validator("autonomy_level")
    @classmethod
    def _autonomy(cls, value: str) -> str:
        key = str(value or "").strip().upper()
        if key not in ALLOWED_AUTONOMY:
            raise ValueError(f"Unsupported autonomy_level: {value}")
        return key


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    niche: str | None = Field(default=None, max_length=200)
    sub_niches: list[str] | None = None
    language: str | None = Field(default=None, max_length=16)
    target_region: str | None = Field(default=None, max_length=80)
    target_audience: str | None = Field(default=None, max_length=400)
    platforms: list[str] | None = None
    content_formats: list[str] | None = None
    posting_frequency: str | None = Field(default=None, max_length=64)
    schedule_windows: list[dict[str, Any]] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    autonomy_level: str | None = Field(default=None, max_length=32)
    voice_persona: dict[str, Any] | None = None
    visual_persona: dict[str, Any] | None = None
    tone: str | None = Field(default=None, max_length=200)
    content_length: str | None = Field(default=None, max_length=64)
    preferred_topics: list[str] | None = None
    excluded_topics: list[str] | None = None
    fact_strictness: str | None = Field(default=None, max_length=32)
    cta_strategy: str | None = Field(default=None, max_length=400)
    music_policy: str | None = Field(default=None, max_length=64)
    asset_policy: str | None = Field(default=None, max_length=64)
    ai_disclosure_policy: str | None = Field(default=None, max_length=64)
    budget: dict[str, Any] | None = None
    experiment_policy: dict[str, Any] | None = None
    account_mappings: dict[str, Any] | None = None
    max_projects_per_day: int | None = Field(default=None, ge=0, le=100)
    max_published_per_day: int | None = Field(default=None, ge=0, le=100)
    max_llm_calls: int | None = Field(default=None, ge=0, le=100_000)
    max_image_generations: int | None = Field(default=None, ge=0, le=10_000)
    max_video_generations: int | None = Field(default=None, ge=0, le=1000)
    max_voice_generations: int | None = Field(default=None, ge=0, le=10_000)
    max_retries: int | None = Field(default=None, ge=0, le=20)
    exploration_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool | None = None

    @field_validator("platforms")
    @classmethod
    def _platforms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return ChannelCreate.model_validate({"name": "x", "platforms": value}).platforms

    @field_validator("autonomy_level")
    @classmethod
    def _autonomy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ChannelCreate.model_validate(
            {"name": "x", "platforms": ["youtube"], "autonomy_level": value}
        ).autonomy_level


class ProjectCreate(BaseModel):
    channel_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=300)
    topic: str = Field(default="", max_length=400)
    platforms: list[str] | None = None
    seed_source: dict[str, Any] = Field(default_factory=dict)
    autonomy_override: str | None = Field(default=None, max_length=32)

    @field_validator("platforms")
    @classmethod
    def _platforms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return ChannelCreate.model_validate({"name": "x", "platforms": value}).platforms


class SourceIngest(BaseModel):
    channel_id: str | None = Field(default=None, max_length=80)
    project_id: str | None = Field(default=None, max_length=80)
    source_kind: str = Field(min_length=1, max_length=64)  # local_video|local_audio|url|document|transcript|topic
    uri: str = Field(default="", max_length=4000)
    text: str = Field(default="", max_length=200_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    approved_network: bool = False
    approved_file_read: bool = False


class PublishApprove(BaseModel):
    job_ids: list[str] = Field(default_factory=list, max_length=50)
    platform_consent: dict[str, Any] = Field(default_factory=dict)


class CapabilityItem(BaseModel):
    id: str
    label: str
    status: CapabilityTruth
    detail: str = ""
    remediation: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class OverviewResponse(BaseModel):
    engine_status: str
    channels: int
    trend_signals: int
    opportunities: int
    projects_producing: int
    ready_to_publish: int
    published_today: int
    failures: int
    platforms: dict[str, CapabilityItem]
    campaigns: list[dict[str, Any]] = Field(default_factory=list)
    active_generation: list[dict[str, Any]] = Field(default_factory=list)
    publish_queue: list[dict[str, Any]] = Field(default_factory=list)
    trending_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    experiments: list[dict[str, Any]] = Field(default_factory=list)
    learning_findings: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    recent_failures: list[dict[str, Any]] = Field(default_factory=list)
