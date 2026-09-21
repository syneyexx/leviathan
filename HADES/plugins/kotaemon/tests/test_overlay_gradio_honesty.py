#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class KotaemonOverlayHonestyTests(unittest.TestCase):
    def test_overlay_requires_gradio_like_root(self) -> None:
        root = Path(__file__).resolve().parents[1]
        overlay = (root / "overlay" / "hades_bridge.py").read_text(encoding="utf-8")
        self.assertIn("gradio", overlay)
        self.assertIn("gradio_not_importable", overlay)


if __name__ == "__main__":
    unittest.main()
