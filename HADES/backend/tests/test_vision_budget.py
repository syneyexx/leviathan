"""Tests for vision attachment resource bounds."""

from __future__ import annotations

import struct
import unittest
import zlib

from vision_budget import VisionBudget, evaluate_vision_attachment


def _png(width: int, height: int) -> bytes:
    """Minimal valid PNG with given dimensions (1-bit grayscale)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    # One filter byte + one gray byte per row.
    raw = b"".join(b"\x00" + (b"\x00" * width) for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class VisionBudgetTests(unittest.TestCase):
    def test_accepts_small_png(self) -> None:
        payload = _png(32, 24)
        result = evaluate_vision_attachment(payload)
        self.assertTrue(result.ok)
        self.assertEqual(result.width, 32)
        self.assertEqual(result.height, 24)

    def test_rejects_over_count(self) -> None:
        payload = _png(16, 16)
        result = evaluate_vision_attachment(payload, already_count=4, budget=VisionBudget(max_images=4))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "max_image_count")

    def test_rejects_combined_bytes(self) -> None:
        payload = _png(64, 64)
        result = evaluate_vision_attachment(
            payload,
            already_bytes=10,
            budget=VisionBudget(max_raw_bytes=len(payload) + 5, max_single_bytes=10_000_000),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "combined_raw_bytes")

    def test_rejects_dimension(self) -> None:
        payload = _png(500, 20)
        result = evaluate_vision_attachment(payload, budget=VisionBudget(max_dimension=256))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "dimension_limit")


if __name__ == "__main__":
    unittest.main()
