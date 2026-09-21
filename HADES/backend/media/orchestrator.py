
"""Durable MediaOrchestrator — blackboard stages, leases, resumable checkpoints."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from media.creative.pipeline import CreativePipeline
from media.events import MediaEventBus
from media.intelligence.patterns import analyze_transcript_pattern
from media.models import AutonomyLevel, PIPELINE_STAGES, ProjectStage, TERMINAL_STAGES
from media.paths import MediaPaths, content_hash_bytes
from media.qa.gate import QualityGate
from media.rendering.ffmpeg_renderer import FFmpegRenderer
from media.research.engine import ResearchEngine
from media.transcription.engine import TranscriptionEngine
from media.trends.engine import TrendEngine


STAGE_INDEX = {stage: idx for idx, stage in enumerate(PIPELINE_STAGES)}


class MediaOrchestrator:
    def __init__(
        self,
        store: Any,
        *,
        data_root: str | Path,
        events: MediaEventBus | None = None,
        trend_engine: TrendEngine | None = None,
        research_engine: ResearchEngine | None = None,
        creative: CreativePipeline | None = None,
        transcription: TranscriptionEngine | None = None,
        renderer: FFmpegRenderer | None = None,
        adapters: Any | None = None,
        quality_gate: QualityGate | None = None,
    ) -> None:
        self.store = store
        self.paths = MediaPaths(data_root)
        self.events = events or MediaEventBus()
        self.trends = trend_engine
        self.research = research_engine or ResearchEngine(store)
        self.creative = creative or CreativePipeline(store)
        self.transcription = transcription or TranscriptionEngine(store)
        self.renderer = renderer or FFmpegRenderer()
        self.adapters = adapters
        self.quality_gate = quality_gate or QualityGate()
        self.owner = f"orch_{secrets.token_hex(4)}"

    async def advance_project(self, project_id: str, *, max_stages: int = 8) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project:
            return {"ok": False, "error": "project_not_found"}
        if project["stage"] in {s.value for s in TERMINAL_STAGES}:
            return {"ok": True, "project": project, "stopped": "terminal"}
        if project.get("cancel_requested"):
            project = self.store.update_project(project_id, stage=ProjectStage.CANCELLED.value, error="cancelled")
            return {"ok": True, "project": project, "stopped": "cancelled"}
        if not self.store.claim_project_lease(project_id, self.owner, ttl_seconds=180):
            return {"ok": False, "error": "lease_held", "project": project}

        try:
            steps = 0
            while steps < max_stages:
                project = self.store.get_project(project_id)
                assert project is not None
                if project.get("cancel_requested"):
                    project = self.store.update_project(project_id, stage=ProjectStage.CANCELLED.value, error="cancelled")
                    break
                stage = ProjectStage(project["stage"])
                if stage in TERMINAL_STAGES or stage == ProjectStage.READY_TO_PUBLISH:
                    break
                if stage in {ProjectStage.WAITING_FOR_APPROVAL, ProjectStage.WAITING_PLATFORM_CONSENT, ProjectStage.SCHEDULED}:
                    break
                result = await self._run_stage(project, stage)
                steps += 1
                if not result.get("ok"):
                    self.store.update_project(
                        project_id,
                        stage=ProjectStage.FAILED.value,
                        error=str(result.get("error") or result.get("detail") or "stage_failed")[:1000],
                    )
                    self.store.append_project_event(
                        project_id,
                        stage=stage.value,
                        event_type="stage_failed",
                        detail=str(result.get("error") or ""),
                        payload=result,
                    )
                    break
                if result.get("wait"):
                    break
                next_stage = result.get("next_stage")
                if next_stage:
                    progress = (STAGE_INDEX.get(ProjectStage(next_stage), 0) + 1) / max(1, len(PIPELINE_STAGES))
                    artifacts = {**(project.get("artifacts") or {}), **(result.get("artifacts") or {})}
                    checkpoint = {**(project.get("stage_checkpoint") or {}), stage.value: result.get("checkpoint") or {"done": True}}
                    project = self.store.update_project(
                        project_id,
                        stage=next_stage,
                        progress=progress,
                        artifacts=artifacts,
                        stage_checkpoint=checkpoint,
                        content_dna={**(project.get("content_dna") or {}), **(result.get("content_dna") or {})},
                        error=None,
                    )
                    self.store.append_project_event(
                        project_id,
                        stage=next_stage,
                        event_type="stage_completed",
                        detail=stage.value,
                        payload={"from": stage.value, "to": next_stage},
                    )
                    self.events.project_stage(project_id, next_stage)
            return {"ok": True, "project": self.store.get_project(project_id), "steps": steps}
        finally:
            self.store.release_project_lease(project_id, self.owner)

    async def _run_stage(self, project: dict[str, Any], stage: ProjectStage) -> dict[str, Any]:
        checkpoint = (project.get("stage_checkpoint") or {}).get(stage.value) or {}
        if checkpoint.get("done") and stage not in {ProjectStage.CREATED}:
            # Already completed this stage — skip forward.
            nxt = self._next_after(stage)
            return {"ok": True, "next_stage": nxt.value if nxt else stage.value, "checkpoint": checkpoint}

        channel = self.store.get_channel(project["channel_id"]) or {}
        handlers = {
            ProjectStage.CREATED: self._stage_created,
            ProjectStage.DISCOVERING: self._stage_discovering,
            ProjectStage.INGESTING: self._stage_ingesting,
            ProjectStage.TRANSCRIBING: self._stage_transcribing,
            ProjectStage.ANALYZING_SOURCES: self._stage_analyzing_sources,
            ProjectStage.ANALYZING_TRENDS: self._stage_analyzing_trends,
            ProjectStage.RESEARCHING: self._stage_researching,
            ProjectStage.SELECTING_OPPORTUNITY: self._stage_selecting_opportunity,
            ProjectStage.DEVELOPING_CONCEPT: self._stage_developing_concept,
            ProjectStage.SCRIPTING: self._stage_scripting,
            ProjectStage.SCRIPT_CRITIQUE: self._stage_script_critique,
            ProjectStage.STORYBOARDING: self._stage_storyboarding,
            ProjectStage.GENERATING_VISUALS: self._stage_generating_visuals,
            ProjectStage.GENERATING_VOICE: self._stage_generating_voice,
            ProjectStage.GENERATING_AUDIO: self._stage_generating_audio,
            ProjectStage.EDITING: self._stage_editing,
            ProjectStage.RENDERING: self._stage_rendering,
            ProjectStage.QUALITY_CHECK: self._stage_quality_check,
            ProjectStage.PLATFORM_ADAPTATION: self._stage_platform_adaptation,
        }
        handler = handlers.get(stage)
        if handler is None:
            return {"ok": False, "error": f"no_handler_for_{stage.value}"}
        return await handler(project, channel)

    def _next_after(self, stage: ProjectStage) -> ProjectStage | None:
        idx = STAGE_INDEX.get(stage)
        if idx is None:
            return None
        if idx + 1 >= len(PIPELINE_STAGES):
            return None
        return PIPELINE_STAGES[idx + 1]

    async def _stage_created(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "next_stage": ProjectStage.DISCOVERING.value, "checkpoint": {"done": True}}

    async def _stage_discovering(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        query = project.get("topic") or channel.get("niche") or ""
        trends_payload = {"trends": [], "signals": []}
        if self.trends is not None:
            trends_payload = await self.trends.discover(query=query, language=channel.get("language") or "en", limit=10)
        return {
            "ok": True,
            "next_stage": ProjectStage.INGESTING.value,
            "artifacts": {"discover": {"trend_count": len(trends_payload.get("trends") or []), "providers": trends_payload.get("providers")}},
            "checkpoint": {"done": True},
        }

    async def _stage_ingesting(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        artifacts = project.get("artifacts") or {}
        seed = artifacts.get("seed_source") or {}
        if seed:
            text = str(seed.get("text") or seed.get("topic") or project.get("topic") or "")
            content_hash = content_hash_bytes(text.encode("utf-8")) if text else ""
            source = self.store.create_source(
                {
                    "channel_id": channel.get("id"),
                    "project_id": project["id"],
                    "source_kind": seed.get("source_kind") or "topic",
                    "uri": seed.get("uri") or "",
                    "content_hash": content_hash,
                    "text_excerpt": text[:4000],
                    "metadata": seed.get("metadata") or {},
                }
            )
        else:
            text = project.get("topic") or channel.get("niche") or "general topic"
            source = self.store.create_source(
                {
                    "channel_id": channel.get("id"),
                    "project_id": project["id"],
                    "source_kind": "topic",
                    "uri": "",
                    "content_hash": content_hash_bytes(text.encode("utf-8")),
                    "text_excerpt": text,
                    "metadata": {},
                }
            )
        return {
            "ok": True,
            "next_stage": ProjectStage.TRANSCRIBING.value,
            "artifacts": {"source_id": source["id"]},
            "checkpoint": {"done": True, "source_id": source["id"]},
        }

    async def _stage_transcribing(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        source_id = (project.get("artifacts") or {}).get("source_id")
        source = self.store.get_source(source_id) if source_id else None
        text = (source or {}).get("text_excerpt") or project.get("topic") or ""
        result = self.transcription.transcribe_source(
            source_id=source_id or "unknown",
            official_transcript=text,
            language=channel.get("language") or "en",
            tmp_dir=self.paths.tmp_dir(project["id"]),
        )
        if not result.get("ok"):
            # Topic/text sources can proceed with official text even if ASR unavailable.
            if text:
                result = {
                    "ok": True,
                    "transcript": {
                        "id": None,
                        "full_text": text,
                        "provider": "official_captions",
                        "segments": [{"start": 0.0, "end": None, "text": text}],
                    },
                }
            else:
                return result
        transcript = result["transcript"]
        return {
            "ok": True,
            "next_stage": ProjectStage.ANALYZING_SOURCES.value,
            "artifacts": {"transcript_id": transcript.get("id"), "transcript_text": transcript.get("full_text")},
            "checkpoint": {"done": True, "cached": result.get("cached")},
        }

    async def _stage_analyzing_sources(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        text = (project.get("artifacts") or {}).get("transcript_text") or project.get("topic") or ""
        pattern = analyze_transcript_pattern(text)
        saved = self.store.save_pattern({"project_id": project["id"], "source_id": (project.get("artifacts") or {}).get("source_id"), "pattern": pattern})
        return {
            "ok": True,
            "next_stage": ProjectStage.ANALYZING_TRENDS.value,
            "artifacts": {"pattern_id": saved["id"], "pattern": pattern},
            "checkpoint": {"done": True},
        }

    async def _stage_analyzing_trends(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        trends = self.store.list_trends(limit=10)
        opportunity = None
        if trends and self.trends is not None:
            opportunity = self.trends.create_opportunity_for_trend(trends[0], channel)
        elif trends:
            from media.trends.engine import score_opportunity

            scored = score_opportunity(trend=trends[0], channel=channel)
            opportunity = self.store.create_opportunity(
                {
                    "channel_id": channel.get("id"),
                    "trend_id": trends[0]["id"],
                    "score": scored["score"],
                    "components": scored["components"],
                    "explanation": scored["explanation"],
                }
            )
        else:
            # Synthetic opportunity from topic — still evidence-explained as local-only.
            opportunity = self.store.create_opportunity(
                {
                    "channel_id": channel.get("id"),
                    "trend_id": None,
                    "score": 55,
                    "components": {"audience_fit": 60, "evidence_quality": 20, "freshness": 40},
                    "explanation": "Opportunity 55/100 from channel topic only (no external trend evidence yet).",
                }
            )
        return {
            "ok": True,
            "next_stage": ProjectStage.RESEARCHING.value,
            "artifacts": {"opportunity_id": opportunity["id"]},
            "checkpoint": {"done": True},
        }

    async def _stage_researching(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        topic = project.get("topic") or channel.get("niche") or "topic"
        claims = await self.research.research_topic(project_id=project["id"], topic=topic, channel=channel)
        return {
            "ok": True,
            "next_stage": ProjectStage.SELECTING_OPPORTUNITY.value,
            "artifacts": {"research_claim_ids": [c["id"] for c in claims]},
            "checkpoint": {"done": True},
        }

    async def _stage_selecting_opportunity(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        opp_id = (project.get("artifacts") or {}).get("opportunity_id")
        opportunity = self.store.get_opportunity(opp_id) if opp_id else None
        if not opportunity:
            opps = self.store.list_opportunities(channel_id=channel.get("id"), limit=1)
            opportunity = opps[0] if opps else None
        if not opportunity:
            return {"ok": False, "error": "no_opportunity"}
        ideas = self.creative.generate_ideas(channel=channel, opportunity=opportunity)
        if not ideas:
            return {"ok": False, "error": "no_ideas"}
        return {
            "ok": True,
            "next_stage": ProjectStage.DEVELOPING_CONCEPT.value,
            "artifacts": {"idea_id": ideas[0]["id"], "idea_ids": [i["id"] for i in ideas]},
            "checkpoint": {"done": True},
        }

    async def _stage_developing_concept(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        idea_id = (project.get("artifacts") or {}).get("idea_id")
        ideas = self.store.list_ideas(channel_id=channel.get("id"), limit=20)
        idea = next((i for i in ideas if i["id"] == idea_id), ideas[0] if ideas else None)
        if not idea:
            return {"ok": False, "error": "idea_missing"}
        hyp = self.creative.form_hypothesis(project_id=project["id"], channel=channel, idea=idea)
        return {
            "ok": True,
            "next_stage": ProjectStage.SCRIPTING.value,
            "artifacts": {"hypothesis_id": hyp["id"]},
            "content_dna": {
                "topic": (idea.get("payload") or {}).get("topic"),
                "hook_type": (idea.get("payload") or {}).get("hook_type"),
                "format": (idea.get("payload") or {}).get("format"),
                "hypothesis_id": hyp["id"],
            },
            "checkpoint": {"done": True},
        }

    async def _stage_scripting(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        idea_id = (project.get("artifacts") or {}).get("idea_id")
        ideas = self.store.list_ideas(channel_id=channel.get("id"), limit=20)
        idea = next((i for i in ideas if i["id"] == idea_id), ideas[0] if ideas else {"payload": {}})
        claims = self.store.list_research_claims(project["id"])
        prior = []
        for p in self.store.list_projects(channel_id=channel.get("id"), limit=10):
            if p["id"] == project["id"]:
                continue
            script = self.store.latest_script(p["id"])
            if script:
                prior.append(script["body"])
        source_text = [(project.get("artifacts") or {}).get("transcript_text") or ""]
        script = self.creative.write_script(
            project_id=project["id"],
            channel=channel,
            idea=idea,
            research_claims=claims,
            prior_scripts=prior,
            source_transcripts=source_text,
        )
        return {
            "ok": True,
            "next_stage": ProjectStage.SCRIPT_CRITIQUE.value,
            "artifacts": {"script_id": script["id"], "script_version": script["version"]},
            "content_dna": {
                "script_length": len(script.get("body") or ""),
                "hook_text": ((script.get("body") or "").splitlines() or [""])[0][:200],
            },
            "checkpoint": {"done": True},
        }

    async def _stage_script_critique(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        # Critiques already applied in write_script bounded loops.
        script = self.store.latest_script(project["id"])
        if not script:
            return {"ok": False, "error": "script_missing"}
        return {
            "ok": True,
            "next_stage": ProjectStage.STORYBOARDING.value,
            "artifacts": {"critiques": script.get("critiques") or []},
            "checkpoint": {"done": True},
        }

    async def _stage_storyboarding(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        script = self.store.latest_script(project["id"])
        if not script:
            return {"ok": False, "error": "script_missing"}
        board = self.creative.storyboard_from_script(project_id=project["id"], script=script["body"], target_duration=45.0)
        return {
            "ok": True,
            "next_stage": ProjectStage.GENERATING_VISUALS.value,
            "artifacts": {"storyboard_id": board["id"], "scene_count": len(board.get("scenes") or [])},
            "content_dna": {
                "scene_count": len(board.get("scenes") or []),
                "duration": (board.get("scenes") or [{}])[-1].get("end") if board.get("scenes") else None,
                "average_scene_duration": (
                    ((board.get("scenes") or [{}])[-1].get("end") or 0) / max(1, len(board.get("scenes") or []))
                ),
            },
            "checkpoint": {"done": True},
        }

    async def _stage_generating_visuals(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        board = self.store.latest_storyboard(project["id"])
        scenes = (board or {}).get("scenes") or []
        assets = []
        for scene in scenes:
            strategy = scene.get("asset_strategy") or "TEXT_GRAPHICS"
            asset = self.store.create_asset(
                {
                    "project_id": project["id"],
                    "channel_id": channel.get("id"),
                    "asset_type": "image_plan",
                    "origin": strategy,
                    "provider": "text_graphics_ffmpeg",
                    "license_state": "GENERATED",
                    "prompt_hash": content_hash_bytes(str(scene.get("image_prompt") or "").encode("utf-8")),
                    "metadata": {"scene_id": scene.get("scene_id"), "prompt": scene.get("image_prompt")},
                }
            )
            assets.append(asset["id"])
        return {
            "ok": True,
            "next_stage": ProjectStage.GENERATING_VOICE.value,
            "artifacts": {"visual_asset_ids": assets},
            "content_dna": {"visual_style": "text_graphics_motion"},
            "checkpoint": {"done": True, "count": len(assets)},
        }

    async def _stage_generating_voice(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        script = self.store.latest_script(project["id"])
        persona = channel.get("voice_persona") or {}
        # Without bound TTS, persist narration plan honestly.
        asset = self.store.create_asset(
            {
                "project_id": project["id"],
                "channel_id": channel.get("id"),
                "asset_type": "voice_plan",
                "origin": "GENERATED",
                "provider": persona.get("provider") or "hades_voice",
                "license_state": "GENERATED",
                "metadata": {
                    "text": (script or {}).get("body") or "",
                    "persona": persona,
                    "status": "PLAN_ONLY_IF_TTS_UNBOUND",
                },
            }
        )
        return {
            "ok": True,
            "next_stage": ProjectStage.GENERATING_AUDIO.value,
            "artifacts": {"voice_asset_id": asset["id"]},
            "content_dna": {"voice": persona.get("voice_id") or persona.get("provider") or "default"},
            "checkpoint": {"done": True},
        }

    async def _stage_generating_audio(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        policy = channel.get("music_policy") or "generated_or_licensed"
        if policy not in {"generated_or_licensed", "generated", "user_owned", "licensed", "public_domain", "none"}:
            return {"ok": False, "error": "music_policy_blocks_unknown_rights"}
        asset = self.store.create_asset(
            {
                "project_id": project["id"],
                "channel_id": channel.get("id"),
                "asset_type": "music_plan",
                "origin": "GENERATED",
                "provider": "none" if policy == "none" else "generated_bed",
                "license_state": "GENERATED" if policy != "none" else "PUBLIC_DOMAIN",
                "metadata": {"policy": policy, "note": "No copyrighted platform audio ripping."},
            }
        )
        return {
            "ok": True,
            "next_stage": ProjectStage.EDITING.value,
            "artifacts": {"music_asset_id": asset["id"]},
            "content_dna": {"music_style": policy},
            "checkpoint": {"done": True},
        }

    async def _stage_editing(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        board = self.store.latest_storyboard(project["id"])
        plan = self.renderer.build_edit_plan(scenes=(board or {}).get("scenes") or [], width=1080, height=1920)
        return {
            "ok": True,
            "next_stage": ProjectStage.RENDERING.value,
            "artifacts": {"edit_plan": plan},
            "checkpoint": {"done": True},
        }

    async def _stage_rendering(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        plan = (project.get("artifacts") or {}).get("edit_plan")
        if not plan:
            board = self.store.latest_storyboard(project["id"])
            plan = self.renderer.build_edit_plan(scenes=(board or {}).get("scenes") or [])
        out = self.paths.project_dir(project["id"]) / "renders" / "master_9x16.mp4"
        result = self.renderer.render(plan, out, work_dir=self.paths.tmp_dir(project["id"]))
        if not result.get("ok"):
            return result
        asset = self.store.create_asset(
            {
                "project_id": project["id"],
                "channel_id": channel.get("id"),
                "asset_type": "render",
                "origin": "GENERATED",
                "provider": "ffmpeg",
                "license_state": "GENERATED",
                "storage_path": result["path"],
                "content_hash": content_hash_bytes(Path(result["path"]).read_bytes()),
                "metadata": {"probe": result.get("probe"), "aspect": "9:16"},
            }
        )
        return {
            "ok": True,
            "next_stage": ProjectStage.QUALITY_CHECK.value,
            "artifacts": {"render_asset_id": asset["id"], "render_path": result["path"]},
            "checkpoint": {"done": True},
        }

    async def _stage_quality_check(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        # Variants created in next stage; provisional list empty until then — run adaptation first? Spec says QA before publish; we QA master then adapt.
        assets = self.store.list_assets(project_id=project["id"])
        claims = self.store.list_research_claims(project["id"])
        script = self.store.latest_script(project["id"])
        render_path = (project.get("artifacts") or {}).get("render_path")
        report = self.quality_gate.evaluate(
            project=project,
            render_path=render_path,
            assets=assets,
            variants=[{"metadata": {"title": project.get("title") or project.get("topic") or "Media"}}],
            research_claims=claims,
            script=script,
        )
        if not report.get("ok"):
            return {"ok": False, "error": "quality_gate_failed", "report": report}
        return {
            "ok": True,
            "next_stage": ProjectStage.PLATFORM_ADAPTATION.value,
            "artifacts": {"qa_report": report},
            "checkpoint": {"done": True},
        }

    async def _stage_platform_adaptation(self, project: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
        platforms = project.get("platforms") or channel.get("platforms") or []
        render_path = (project.get("artifacts") or {}).get("render_path")
        script = self.store.latest_script(project["id"])
        title = project.get("title") or project.get("topic") or "HADES Media"
        hook = ((script or {}).get("body") or title).splitlines()[0][:100]
        variants = []
        for platform in platforms:
            format_key = {
                "tiktok": "TIKTOK_VIDEO",
                "youtube": "YOUTUBE_SHORT",
                "instagram": "INSTAGRAM_REEL",
                "facebook": "FACEBOOK_REEL",
            }.get(platform, "SHORT_VERTICAL")
            metadata = {
                "title": title[:100],
                "caption": hook,
                "description": (script or {}).get("body") or "",
                "hashtags": [],
                "render_path": render_path,
                "ai_disclosure": True,
                "format_key": format_key,
            }
            variant = self.store.upsert_variant(
                {
                    "project_id": project["id"],
                    "platform": platform,
                    "format_key": format_key,
                    "render_asset_id": (project.get("artifacts") or {}).get("render_asset_id"),
                    "metadata": metadata,
                    "status": "ready",
                }
            )
            variants.append(variant)
            # Create durable publish jobs (approval depends on autonomy).
            autonomy = project.get("autonomy_level") or channel.get("autonomy_level") or AutonomyLevel.OFF.value
            approval = "approved" if autonomy == AutonomyLevel.AUTONOMOUS.value else "pending"
            status = "APPROVED" if autonomy in {AutonomyLevel.QUEUE.value, AutonomyLevel.AUTONOMOUS.value} else "PENDING"
            if autonomy in {AutonomyLevel.OFF.value, AutonomyLevel.RESEARCH.value, AutonomyLevel.PRODUCE.value}:
                status = "PENDING"
                approval = "pending"
            self.store.create_publish_job(
                {
                    "project_id": project["id"],
                    "variant_id": variant["id"],
                    "platform": platform,
                    "approval_state": approval,
                    "platform_consent_state": "required" if platform == "tiktok" else "not_required",
                    "status": status,
                    "payload": {"ai_disclosure": True},
                }
            )
        next_stage = ProjectStage.READY_TO_PUBLISH.value
        if (project.get("autonomy_level") or channel.get("autonomy_level")) in {
            AutonomyLevel.PRODUCE.value,
            AutonomyLevel.RESEARCH.value,
            AutonomyLevel.OFF.value,
        }:
            next_stage = ProjectStage.WAITING_FOR_APPROVAL.value
        return {
            "ok": True,
            "next_stage": next_stage,
            "artifacts": {"variant_ids": [v["id"] for v in variants]},
            "content_dna": {"platforms": platforms},
            "checkpoint": {"done": True},
        }

    async def retry_stage(self, project_id: str, stage: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project:
            return {"ok": False, "error": "project_not_found"}
        checkpoint = dict(project.get("stage_checkpoint") or {})
        checkpoint.pop(stage, None)
        # Clear later checkpoints too.
        try:
            stage_enum = ProjectStage(stage)
        except ValueError:
            return {"ok": False, "error": "invalid_stage"}
        idx = STAGE_INDEX.get(stage_enum, 0)
        for later in PIPELINE_STAGES[idx:]:
            checkpoint.pop(later.value, None)
        self.store.update_project(project_id, stage=stage, stage_checkpoint=checkpoint, error=None)
        return await self.advance_project(project_id)

    def cancel_project(self, project_id: str) -> dict[str, Any] | None:
        return self.store.update_project(project_id, cancel_requested=True)
