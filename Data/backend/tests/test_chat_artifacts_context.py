"""Tests for Chat attachment → multimodal context resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore
from Data.modules.chat.artifacts_context import (
    attach_parts_to_history,
    resolve_artifact_parts,
)
from Data.modules.context.multimodal import MultimodalSessionRegistry


class ChatArtifactsContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ArtifactStore(root / "a.db", root / "artifacts")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_text_attachment_inlined_into_history(self) -> None:
        rec = self.store.create_from_bytes(
            data=b"hello from attachment file",
            artifact_type="text",
            producer="test",
            filename="notes.txt",
            metadata={"filename": "notes.txt", "declared_mime_type": "text/plain"},
        )
        resolved = resolve_artifact_parts(
            artifact_store=self.store,
            artifact_ids=[rec.artifact_id, "missing-id"],
        )
        self.assertEqual(resolved["safe_ids"], [rec.artifact_id])
        self.assertEqual(len(resolved["unavailable"]), 1)
        self.assertTrue(resolved["text_excerpts"])
        history = [
            {"role": "user", "content": "Summarize the file"},
            {"role": "assistant", "content": "ok"},
        ]
        # Attach to a new user turn at the end
        history.append({"role": "user", "content": "Please read this"})
        merged = attach_parts_to_history(
            history,
            parts=resolved["parts"],
            text_excerpts=resolved["text_excerpts"],
        )
        self.assertIn("hello from attachment file", merged[-1]["content"])
        self.assertTrue(merged[-1].get("parts"))

    def test_image_attachment_creates_vision_part(self) -> None:
        rec = self.store.create_from_bytes(
            data=b"\x89PNG\r\n\x1a\nfake",
            artifact_type="image",
            producer="test",
            filename="shot.png",
            metadata={"filename": "shot.png", "declared_mime_type": "image/png"},
        )
        resolved = resolve_artifact_parts(
            artifact_store=self.store,
            artifact_ids=[rec.artifact_id],
        )
        self.assertEqual(resolved["vision_parts"], 1)
        kinds = {p.get("kind") for p in resolved["parts"]}
        self.assertIn("image", kinds)
        registry = MultimodalSessionRegistry()
        from Data.modules.chat.artifacts_context import register_turn_multimodal_session

        sid = register_turn_multimodal_session(
            registry,
            conversation_id="c1",
            run_id="r1",
            user_text="describe",
            parts=resolved["parts"],
        )
        self.assertTrue(sid)
        session = registry.require(sid)
        self.assertGreaterEqual(len(session.messages), 1)


if __name__ == "__main__":
    unittest.main()
