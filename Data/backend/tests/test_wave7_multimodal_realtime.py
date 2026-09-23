"""Wave 7 — Multimodal + realtime voice exit gates (U241–U260 foundations).

Exit gate: one project session combines text, images and audio, invokes normal
tools via ExecutionGateway, and keeps a single context/run history.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.context import (
    ContextBuilder,
    MultimodalPart,
    MultimodalSessionRegistry,
    new_sync_id,
)
from Data.modules.execution import (
    CapabilityProviderKind,
    CapabilityReceiptStore,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.media import MediaAction, MediaService
from Data.modules.models import VisionCapabilityProfile, attach_vision_profile
from Data.modules.models.contracts import CapabilityState, ModelCapabilities
from Data.modules.observations import ObservationStore
from Data.modules.reasoning import ReasoningEngine
from Data.modules.run import RunStore
from Data.modules.voice import RealtimeVoiceService, VoiceAction


class MultimodalSchemaTests(unittest.TestCase):
    def test_parts_share_sync_id_and_history_flattens(self) -> None:
        registry = MultimodalSessionRegistry()
        session = registry.create(conversation_id="c1", run_id="r1", project_id="p1")
        sync = new_sync_id()
        msg = session.append(
            "user",
            [
                MultimodalPart.text_part("describe this frame"),
                MultimodalPart.image_part(artifact_id="art_img", width=640, height=480),
                MultimodalPart.audio_part(artifact_id="art_aud", duration_ms=900, text="spoken cue"),
            ],
            sync_id=sync,
        )
        self.assertEqual(msg.sync_id, sync)
        self.assertTrue(all(p.sync_id == sync for p in msg.parts))
        history = session.history_for_context()
        self.assertEqual(len(history), 1)
        self.assertIn("describe this frame", history[0]["content"])
        self.assertEqual(len(history[0]["parts"]), 3)
        public = session.public_dict()
        self.assertTrue(public["truth"]["single_context_run_history"])


class VisionProfileTests(unittest.TestCase):
    def test_unmeasured_is_not_passed_and_fixture_merges(self) -> None:
        empty = VisionCapabilityProfile()
        self.assertEqual(empty.ocr, CapabilityState.UNMEASURED)
        self.assertTrue(empty.public_dict()["truth"]["unmeasured_is_not_passed"])
        measured = VisionCapabilityProfile.fixture_measured()
        caps = ModelCapabilities(chat=CapabilityState.SUPPORTED, vision=CapabilityState.UNKNOWN)
        payload = attach_vision_profile(caps, measured)
        self.assertEqual(payload["vision"], CapabilityState.SUPPORTED.value)
        self.assertEqual(payload["visionProfile"]["ocr"], CapabilityState.SUPPORTED.value)


class MediaFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.artifacts = ArtifactStore(root / "a.db", root / "artifacts")
        self.artifacts.initialize()
        self.media = MediaService(artifact_store=self.artifacts)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_image_generate_video_ingest_and_cross_modal(self) -> None:
        gen = self.media.execute(
            action=MediaAction.IMAGE_GENERATE,
            arguments={"prompt": "red cube on table", "sync_id": "sync_media"},
            run_id="run-media",
        )
        self.assertEqual(gen["status"], "COMPLETED")
        self.assertTrue(gen["artifact_id"])
        self.assertTrue(gen["truth"]["uses_shared_artifact_store"])

        video_path = Path(self.tmp.name) / "clip.mp4"
        video_path.write_bytes(b"fixture-video")
        ingest = self.media.execute(
            action=MediaAction.VIDEO_INGEST,
            arguments={"path": str(video_path), "duration_ms": 1500},
            run_id="run-media",
        )
        self.assertEqual(ingest["status"], "COMPLETED")
        self.assertGreaterEqual(len(ingest["frames"]), 1)
        self.assertGreaterEqual(len(ingest["shots"]), 1)
        self.assertTrue(ingest["truth"]["timestamp_citations_preserved"])

        hits = self.media.execute(
            action=MediaAction.CROSS_MODAL_SEARCH,
            arguments={"query": "cube table", "limit": 5},
        )
        self.assertEqual(hits["status"], "COMPLETED")
        self.assertGreaterEqual(hits["count"], 1)
        self.assertEqual(hits["hits"][0]["modality"], "image_region")


class VoiceBargeInTests(unittest.TestCase):
    def test_barge_in_cancels_tts(self) -> None:
        voice = RealtimeVoiceService()
        started = voice.execute(action=VoiceAction.START_SESSION, arguments={"run_id": "r-voice"})
        self.assertEqual(started["status"], "COMPLETED")
        session_id = started["session"]["session_id"]
        asr = voice.execute(
            action=VoiceAction.STREAM_ASR,
            arguments={"session_id": session_id, "text": "hello there operator"},
        )
        self.assertEqual(asr["status"], "COMPLETED")
        self.assertGreaterEqual(len(asr["partials"]), 2)

        # Start TTS then barge-in before a second synthesize
        voice.barge_in(session_id)
        cancelled = voice.execute(
            action=VoiceAction.STREAM_TTS,
            arguments={"session_id": session_id, "text": "this should cancel"},
        )
        self.assertEqual(cancelled["status"], "CANCELLED")
        session = voice.get_session(session_id)
        assert session is not None
        self.assertGreaterEqual(session.metrics.barge_ins, 1)
        self.assertTrue(session.public_dict()["truth"]["barge_in_propagates_to_asr_llm_tts"])


class Wave7ExitGateTests(unittest.TestCase):
    """One session: text+image+audio → tools → single ContextPack/run history."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "wave7.db"
        MigrationRunner(self.db).apply_all()
        self.runs = RunStore(self.db)
        self.runs.initialize()
        self.artifacts = ArtifactStore(self.db, self.root / "artifacts")
        self.artifacts.initialize()
        self.obs = ObservationStore(self.db)
        self.obs.initialize()
        self.receipts = CapabilityReceiptStore(self.db)
        self.receipts.initialize()
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.fn = FunctionRuntime(build_default_registry())
        self.catalog = build_default_catalog()
        self.media = MediaService(artifact_store=self.artifacts)
        self.voice = RealtimeVoiceService()
        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.fn,
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
            observation_store=self.obs,
            media_executor=self.media,
            voice_executor=self.voice,
            receipt_store=self.receipts,
        )
        self.sessions = MultimodalSessionRegistry()
        self.reasoner = ReasoningEngine()

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def _approve(self, capability_id: str, *, run_id: str) -> str:
        defn = self.catalog.require(capability_id)
        rec = self.approvals.request(
            capability_id=capability_id,
            side_effects=defn.side_effects,
            requested_by="wave7-test",
            run_id=run_id,
            reason="wave7 exit gate",
        )
        self.approvals.approve(rec.approval_id, decided_by="operator")
        return rec.approval_id

    def test_multimodal_session_tools_and_single_context(self) -> None:
        self.assertEqual(self.catalog.require("media.image_generate").provider_kind, CapabilityProviderKind.MEDIA)
        self.assertEqual(self.catalog.require("voice.barge_in").provider_kind, CapabilityProviderKind.VOICE)

        run = self.runs.create_run(user_request="wave7 multimodal exit gate")
        run_id = run.run_id
        session = self.sessions.create(conversation_id="conv-wave7", run_id=run_id, project_id="proj-wave7")

        # 1) Generate image via Gateway (shared Run + receipt)
        img_approval = self._approve("media.image_generate", run_id=run_id)
        img_result = self.gateway.execute(
            CapabilityRequest(
                capability_id="media.image_generate",
                arguments={"prompt": "blueprint of device", "sync_id": "sync_w7"},
                run_id=run_id,
                approval_id=img_approval,
                requested_by="wave7-media",
            )
        )
        self.assertEqual(img_result.status, CapabilityStatus.COMPLETED)
        artifact_id = (img_result.output or {}).get("artifact_id")
        self.assertTrue(artifact_id)

        # 2) Voice ASR on same run
        voice_approval = self._approve("voice.start_session", run_id=run_id)
        started = self.gateway.execute(
            CapabilityRequest(
                capability_id="voice.start_session",
                arguments={"conversation_id": "conv-wave7", "run_id": run_id, "sync_id": "sync_w7"},
                run_id=run_id,
                approval_id=voice_approval,
                requested_by="wave7-voice",
            )
        )
        self.assertEqual(started.status, CapabilityStatus.COMPLETED)
        voice_session_id = ((started.output or {}).get("session") or {}).get("session_id")
        self.assertTrue(voice_session_id)

        asr_approval = self._approve("voice.transcribe", run_id=run_id)
        asr = self.gateway.execute(
            CapabilityRequest(
                capability_id="voice.transcribe",
                arguments={
                    "session_id": voice_session_id,
                    "text": "please inspect the blueprint",
                },
                run_id=run_id,
                approval_id=asr_approval,
                requested_by="wave7-voice",
            )
        )
        self.assertEqual(asr.status, CapabilityStatus.COMPLETED)
        transcript = (asr.output or {}).get("transcript") or ""

        # 3) Fuse text + image + audio into one multimodal session
        session.append(
            "user",
            [
                MultimodalPart.text_part(transcript or "please inspect the blueprint"),
                MultimodalPart.image_part(artifact_id=str(artifact_id), width=640, height=480),
                MultimodalPart.audio_part(text=transcript, duration_ms=800),
            ],
            sync_id="sync_w7",
        )

        # 4) Normal tool (file.read) still via same Gateway / run
        note = self.root / "note.txt"
        note.write_text("device serial 42", encoding="utf-8")
        tool = self.gateway.execute(
            CapabilityRequest(
                capability_id="file.read",
                arguments={"path": str(note)},
                run_id=run_id,
                requested_by="wave7-tool",
            )
        )
        self.assertEqual(tool.status, CapabilityStatus.COMPLETED)

        # 5) Single ContextPack from fused history
        history = session.history_for_context()
        plan = self.reasoner.analyze(history[-1]["content"], has_knowledge=False)
        pack = ContextBuilder(token_budget=4000).build(history=history, knowledge=[], plan=plan)
        payload = pack.public_dict()
        self.assertGreaterEqual(len(history[0]["parts"]), 3)
        section_names = {s["name"] for s in payload["sections"]}
        self.assertTrue(any(name.startswith("history_") for name in section_names))
        self.assertIn("multimodal_fusion", section_names)

        receipts = self.receipts.list_for_run(run_id, limit=50)
        cap_ids = {r.capability_id for r in receipts}
        self.assertIn("media.image_generate", cap_ids)
        self.assertIn("voice.transcribe", cap_ids)
        self.assertIn("file.read", cap_ids)


if __name__ == "__main__":
    unittest.main()
