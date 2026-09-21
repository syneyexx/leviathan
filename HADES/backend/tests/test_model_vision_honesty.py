from __future__ import annotations

import unittest

from model_vision import (
    apply_vision_parts_to_messages,
    model_supports_vision,
)


class ModelVisionHonestyTests(unittest.TestCase):
    def test_text_only_without_vision_metadata(self) -> None:
        self.assertFalse(model_supports_vision({"id": "qwen", "type": "llm"}))
        self.assertFalse(model_supports_vision({"id": "qwen", "capabilities": {"vision": False}}))

    def test_vision_from_vlm_or_capabilities(self) -> None:
        self.assertTrue(model_supports_vision({"id": "llava", "type": "vlm"}))
        self.assertTrue(model_supports_vision({"id": "gemma", "capabilities": {"vision": True}}))

    def test_apply_vision_parts_to_latest_user_message(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "describe"},
        ]
        parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}}]
        out = apply_vision_parts_to_messages(messages, vision_parts=parts)
        content = out[-1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")


if __name__ == "__main__":
    unittest.main()
