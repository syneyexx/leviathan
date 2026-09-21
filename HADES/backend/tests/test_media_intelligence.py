"""Media Intelligence domain regressions — lifecycle, trends, publish, security, learning."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from media.creative.pipeline import CreativePipeline, originality_similarity
from media.learning.engine import LearningEngine, confidence_for_sample
from media.models import ChannelCreate, CapabilityTruth
from media.paths import MediaPaths, validate_media_id
from media.platforms.tiktok import TikTokAdapter
from media.platforms.youtube import YouTubeAdapter
from media.platforms.instagram import InstagramAdapter
from media.platforms.facebook import FacebookAdapter
from media.platforms.meta_auth import MetaAuthState
from media.publishing.service import PublishingService
from media.rendering.ffmpeg_renderer import FFmpegRenderer, probe_media, which_ffmpeg
from media.service import MediaService
from media.store import MediaStore
from media.transcription.engine import TranscriptionEngine
from media.trends.engine import TrendEngine, score_opportunity
from media.trends.providers import StaticSeedTrendProvider


class MediaLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = MediaService(database_path=self.tmp / "media.db", data_root=self.tmp)

    def test_channel_multi_platform_and_project_resume(self) -> None:
        channel = self.svc.create_channel(
            ChannelCreate(
                name="History EN",
                platforms=["tiktok", "youtube", "instagram", "facebook"],
                niche="Strange historical facts",
                autonomy_level="PRODUCE",
            )
        )
        self.assertEqual(len(channel["platforms"]), 4)
        project = self.svc.create_project({"channel_id": channel["id"], "topic": "Roman concrete"})
        first = asyncio.run(self.svc.run_project(project["id"], max_stages=5))
        mid_stage = (first.get("project") or {})["stage"]
        self.assertNotEqual(mid_stage, "CREATED")
        second = asyncio.run(self.svc.run_project(project["id"], max_stages=40))
        final = second.get("project") or {}
        self.assertEqual(final["stage"], "WAITING_FOR_APPROVAL")
        self.assertTrue((final.get("artifacts") or {}).get("render_path"))
        # Resume/cancel
        cancelled = self.svc.orchestrator.cancel_project(project["id"])
        self.assertTrue(cancelled["cancel_requested"])
        again = asyncio.run(self.svc.run_project(project["id"], max_stages=3))
        self.assertEqual((again.get("project") or {})["stage"], "CANCELLED")

    def test_lease_ownership_blocks_second_owner(self) -> None:
        channel = self.svc.create_channel(ChannelCreate(name="C", platforms=["youtube"]))
        project = self.svc.create_project({"channel_id": channel["id"], "topic": "x"})
        ok = self.svc.store.claim_project_lease(project["id"], "owner-a", ttl_seconds=60)
        self.assertTrue(ok)
        blocked = self.svc.store.claim_project_lease(project["id"], "owner-b", ttl_seconds=60)
        self.assertFalse(blocked)
        self.svc.store.release_project_lease(project["id"], "owner-a")
        ok2 = self.svc.store.claim_project_lease(project["id"], "owner-b", ttl_seconds=60)
        self.assertTrue(ok2)

    def test_publish_idempotency(self) -> None:
        channel = self.svc.create_channel(ChannelCreate(name="C", platforms=["youtube"]))
        project = self.svc.create_project({"channel_id": channel["id"], "topic": "x"})
        job1 = self.svc.store.create_publish_job(
            {"project_id": project["id"], "platform": "youtube", "idempotency_key": "same-key"}
        )
        job2 = self.svc.store.create_publish_job(
            {"project_id": project["id"], "platform": "youtube", "idempotency_key": "same-key"}
        )
        self.assertEqual(job1["id"], job2["id"])


class MediaTranscriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.store = MediaStore(self.tmp / "t.db")
        self.engine = TranscriptionEngine(self.store)

    def test_transcript_cache_by_hash(self) -> None:
        source = self.store.create_source(
            {"source_kind": "transcript", "content_hash": "abc", "text_excerpt": "hello world"}
        )
        first = self.engine.transcribe_source(
            source_id=source["id"], official_transcript="hello world", language="en"
        )
        second = self.engine.transcribe_source(
            source_id=source["id"], official_transcript="hello world", language="en"
        )
        self.assertTrue(first["ok"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["transcript"]["id"], second["transcript"]["id"])


class MediaTrendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.store = MediaStore(self.tmp / "t.db")
        self.engine = TrendEngine(
            self.store,
            providers=[
                StaticSeedTrendProvider(
                    [
                        {"topic": "Roman concrete", "platform": "web", "velocity": 80, "freshness": 90, "competition": 40},
                        {"topic": "Roman concrete", "platform": "youtube", "velocity": 70, "freshness": 85, "competition": 50},
                    ]
                )
            ],
        )

    def test_merge_and_opportunity_score(self) -> None:
        result = asyncio.run(self.engine.discover(query="roman", limit=10))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["trends"]), 1)
        trend = result["trends"][0]
        self.assertGreaterEqual(len(trend["evidence"]), 2)
        scored = score_opportunity(trend=trend, channel={"niche": "history", "preferred_topics": ["roman"]})
        self.assertIn("score", scored)
        self.assertLessEqual(scored["score"], 100)
        self.assertNotIn("guaranteed viral", scored["explanation"].lower())
        self.assertIn("not a virality guarantee", scored["explanation"].lower())
        # Unsupported fields remain absent in raw scores when never provided.
        empty = score_opportunity(trend={"display_topic": "x", "evidence": [], "scores": {}})
        self.assertIsInstance(empty["components"]["trend_velocity"], float)

    def test_provider_unavailable_is_honest(self) -> None:
        class Broken(StaticSeedTrendProvider):
            id = "broken"

            async def health(self):
                return {"ok": False, "status": "UNAVAILABLE"}

        engine = TrendEngine(self.store, providers=[Broken()])
        result = asyncio.run(engine.discover())
        self.assertEqual(result["providers"][0]["status"], "UNAVAILABLE")


class MediaCreativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.store = MediaStore(self.tmp / "t.db")
        self.creative = CreativePipeline(self.store, max_repair_rounds=2)

    def test_bounded_critics_and_storyboard(self) -> None:
        channel = self.store.create_channel({"name": "Hist", "platforms": ["youtube"], "niche": "history"})
        opp = self.store.create_opportunity({"channel_id": channel["id"], "score": 80, "explanation": "Opportunity 80/100"})
        ideas = self.creative.generate_ideas(channel=channel, opportunity=opp)
        self.assertTrue(ideas)
        project = self.store.create_project({"channel_id": channel["id"], "topic": "x", "platforms": ["youtube"]})
        claims = [
            self.store.save_research_claim(
                {
                    "project_id": project["id"],
                    "claim": "Roman concrete includes reactive lime.",
                    "evidence": "internal note",
                    "source_ref": "local://note",
                    "confidence": 0.7,
                }
            )
        ]
        script = self.creative.write_script(
            project_id=project["id"],
            channel=channel,
            idea=ideas[0],
            research_claims=claims,
            prior_scripts=["completely different prior"],
            source_transcripts=["source about unrelated topic"],
        )
        self.assertTrue(script["body"])
        self.assertLessEqual(len(script["critiques"]), 2)
        board = self.creative.storyboard_from_script(project_id=project["id"], script=script["body"], target_duration=30)
        self.assertGreaterEqual(len(board["scenes"]), 1)
        self.assertAlmostEqual(board["scenes"][-1]["end"], 30, delta=2.5)
        self.assertGreaterEqual(originality_similarity("hello world", "hello there world"), 0.4)


class MediaRenderTests(unittest.TestCase):
    def test_ffmpeg_render_or_honest_missing(self) -> None:
        renderer = FFmpegRenderer()
        if not which_ffmpeg():
            health = renderer.health()
            self.assertEqual(health["status"], "SETUP_REQUIRED")
            self.skipTest("FFmpeg missing — recorded as SETUP_REQUIRED")
        tmp = Path(tempfile.mkdtemp())
        plan = renderer.build_edit_plan(
            scenes=[{"start": 0, "end": 1.5, "narration": "Test", "caption_text": "Test"}]
        )
        out = tmp / "tiny.mp4"
        result = renderer.render(plan, out, work_dir=tmp / "w")
        self.assertTrue(result["ok"], result)
        probe = probe_media(out)
        self.assertTrue(probe["ok"])
        self.assertTrue(probe["has_video"])
        self.assertTrue(probe["has_audio"])
        self.assertEqual(probe["width"], 1080)
        self.assertEqual(probe["height"], 1920)
        self.assertGreater(probe["duration"], 1.0)


class MediaPublishAdapterTests(unittest.TestCase):
    def test_tiktok_requires_consent_and_privacy_option(self) -> None:
        adapter = TikTokAdapter(access_token="tok", client_audited=False)
        status = adapter.auth_status()
        self.assertEqual(status["status"], CapabilityTruth.PRIVATE_ONLY.value)
        job = {"id": "j1", "platform": "tiktok"}
        variant = {"metadata": {"title": "x", "render_path": "/missing.mp4"}}
        no_consent = adapter.publish(job, variant, consent=None)
        self.assertEqual(no_consent["status"], "WAITING_PLATFORM_CONSENT")
        bad_privacy = adapter.publish(
            job,
            variant,
            consent={
                "creator_confirmed": True,
                "privacy_level": "MUTUAL_FOLLOW_FRIENDS",
                "creator_info": {"privacy_level_options": ["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS"]},
            },
        )
        self.assertEqual(bad_privacy["status"], CapabilityTruth.PRIVATE_ONLY.value)

    def test_youtube_auth_missing(self) -> None:
        adapter = YouTubeAdapter(access_token=None)
        result = adapter.publish({"id": "j"}, {"metadata": {}}, consent=None)
        self.assertEqual(result["status"], CapabilityTruth.AUTH_REQUIRED.value)

    def test_instagram_and_facebook_auth_truth(self) -> None:
        ig = InstagramAdapter(auth=MetaAuthState())
        self.assertEqual(ig.auth_status()["status"], CapabilityTruth.AUTH_REQUIRED.value)
        fb = FacebookAdapter(auth=MetaAuthState())
        self.assertEqual(fb.auth_status()["status"], CapabilityTruth.AUTH_REQUIRED.value)
        fb2 = FacebookAdapter(
            auth=MetaAuthState(
                secrets={"meta_app_id": "1", "meta_app_secret": "2", "facebook_page_access_token": "t"},
                config={},
            )
        )
        self.assertEqual(fb2.auth_status()["status"], CapabilityTruth.PAGE_REQUIRED.value)

    def test_publish_service_idempotent_after_mark(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = MediaStore(tmp / "t.db")
        channel = store.create_channel({"name": "c", "platforms": ["youtube"]})
        project = store.create_project({"channel_id": channel["id"], "topic": "t", "platforms": ["youtube"]})
        variant = store.upsert_variant(
            {"project_id": project["id"], "platform": "youtube", "format_key": "YOUTUBE_SHORT", "metadata": {"title": "t"}}
        )
        job = store.create_publish_job(
            {"project_id": project["id"], "variant_id": variant["id"], "platform": "youtube", "status": "PUBLISHED", "approval_state": "approved"}
        )
        store.update_publish_job(job["id"], external_post_id="vid123", status="PUBLISHED")
        from media.platforms.registry import build_adapter_registry

        pub = PublishingService(store, build_adapter_registry())
        result = pub.publish_job(job["id"])
        self.assertTrue(result.get("idempotent"))


class MediaSecurityTests(unittest.TestCase):
    def test_path_traversal_rejected(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        paths = MediaPaths(tmp)
        with self.assertRaises(ValueError):
            validate_media_id("../etc/passwd")
        with self.assertRaises(ValueError):
            paths.project_dir("..")
        with self.assertRaises(ValueError):
            paths.cache_path("ok", "../escape")

    def test_tiktok_redacts_bearer(self) -> None:
        from media.platforms.tiktok import _redact

        text = _redact({"Authorization": "Bearer super-secret-token-value"})
        self.assertIn("[REDACTED]", str(text))
        self.assertNotIn("super-secret-token-value", str(text))


class MediaAnalyticsLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.store = MediaStore(self.tmp / "t.db")

    def test_snapshots_and_unsupported_not_zero(self) -> None:
        from media.analytics.engine import AnalyticsEngine

        engine = AnalyticsEngine(self.store)
        snap = engine.record_snapshot(
            platform="tiktok",
            external_post_id="p1",
            metrics=None,
            unsupported=True,
            hours_since_publish=1,
        )
        self.assertTrue((snap.get("metrics") or {}).get("_unsupported"))
        hist = engine.history(platform="tiktok", external_post_id="p1")
        self.assertEqual(len(hist), 1)
        self.assertIsNone(engine.value_at_or_after(hist, 1, "views"))

    def test_learning_confidence_bounds(self) -> None:
        self.assertEqual(confidence_for_sample(3), "low")
        self.assertEqual(confidence_for_sample(15), "moderate")
        engine = LearningEngine(self.store)
        rows = [{"hook_type": "contradiction", "metric_value": 40, "platform": "youtube"} for _ in range(3)]
        rows += [{"hook_type": "question", "metric_value": 30, "platform": "youtube"} for _ in range(3)]
        finding = engine.analyze_hook_performance(channel_id=None, rows=rows, platform="youtube", min_samples=10)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["confidence"], "low")


class MediaAdversarialTests(unittest.TestCase):
    def test_crash_after_upload_before_db_save_reconcile(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = MediaStore(tmp / "t.db")
        channel = store.create_channel({"name": "c", "platforms": ["youtube"]})
        project = store.create_project({"channel_id": channel["id"], "topic": "t", "platforms": ["youtube"]})
        variant = store.upsert_variant(
            {"project_id": project["id"], "platform": "youtube", "format_key": "YOUTUBE_SHORT", "metadata": {"title": "t"}}
        )
        job = store.create_publish_job(
            {
                "project_id": project["id"],
                "variant_id": variant["id"],
                "platform": "youtube",
                "status": "PROCESSING",
                "approval_state": "approved",
            }
        )
        store.update_publish_job(job["id"], external_upload_id="upl1", status="PROCESSING")

        class FakeYT(YouTubeAdapter):
            def publish_status(self, external_upload_id: str):
                return {"ok": True, "status": "PUBLISHED", "external_post_id": "vid999"}

        from media.platforms.base import AdapterRegistry

        reg = AdapterRegistry()
        reg.register(FakeYT(access_token="t"))
        pub = PublishingService(store, reg)
        result = pub.reconcile_job(job["id"])
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(store.get_publish_job(job["id"])["external_post_id"], "vid999")

    def test_duplicate_scheduler_claim(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = MediaStore(tmp / "t.db")
        self.assertTrue(store.claim_scheduler_lease("media_main", "a", ttl_seconds=30))
        self.assertFalse(store.claim_scheduler_lease("media_main", "b", ttl_seconds=30))


if __name__ == "__main__":
    unittest.main()
