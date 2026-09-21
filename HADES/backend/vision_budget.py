"""Vision attachment resource bounds (HADES-10 Phase 6).

Bounds are enforced before base64 construction so huge payloads never leave the host.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

# Reasonable defaults for local VLM turns — configurable via kwargs in callers.
DEFAULT_MAX_IMAGES = 4
DEFAULT_MAX_RAW_BYTES = 12 * 1024 * 1024  # combined raw bytes before encode
DEFAULT_MAX_PIXELS = 8_000_000  # combined decoded pixels
DEFAULT_MAX_DIMENSION = 4096
DEFAULT_MAX_SINGLE_BYTES = 6 * 1024 * 1024


@dataclass(frozen=True)
class VisionBudget:
    max_images: int = DEFAULT_MAX_IMAGES
    max_raw_bytes: int = DEFAULT_MAX_RAW_BYTES
    max_pixels: int = DEFAULT_MAX_PIXELS
    max_dimension: int = DEFAULT_MAX_DIMENSION
    max_single_bytes: int = DEFAULT_MAX_SINGLE_BYTES


@dataclass
class VisionAccept:
    ok: bool
    reason: str = ""
    width: int | None = None
    height: int | None = None
    pixels: int | None = None
    raw_bytes: int = 0


def _probe_image(payload: bytes) -> tuple[int | None, int | None]:
    """Return (width, height) when decodable; never trust upload size alone."""
    if not payload:
        return None, None
    # Decompression-bomb protection: refuse absurd compressed sizes early.
    if len(payload) > 40 * 1024 * 1024:
        return None, None
    try:
        from PIL import Image  # type: ignore

        Image.MAX_IMAGE_PIXELS = DEFAULT_MAX_PIXELS
        with Image.open(io.BytesIO(payload)) as img:
            img.verify()
        with Image.open(io.BytesIO(payload)) as img:
            width, height = img.size
            return int(width), int(height)
    except Exception:
        # Without Pillow, fall back to header sniff for JPEG/PNG dimensions when cheap.
        try:
            if payload[:8] == b"\x89PNG\r\n\x1a\n" and len(payload) >= 24:
                width = int.from_bytes(payload[16:20], "big")
                height = int.from_bytes(payload[20:24], "big")
                return width, height
            if payload[:2] == b"\xff\xd8":
                # Minimal SOF scan
                i = 2
                while i + 9 < len(payload):
                    if payload[i] != 0xFF:
                        break
                    marker = payload[i + 1]
                    if marker in {0xC0, 0xC1, 0xC2}:
                        height = int.from_bytes(payload[i + 5 : i + 7], "big")
                        width = int.from_bytes(payload[i + 7 : i + 9], "big")
                        return width, height
                    length = int.from_bytes(payload[i + 2 : i + 4], "big")
                    i += 2 + length
        except Exception:
            return None, None
        return None, None


def evaluate_vision_attachment(
    payload: bytes,
    *,
    budget: VisionBudget | None = None,
    already_count: int = 0,
    already_bytes: int = 0,
    already_pixels: int = 0,
) -> VisionAccept:
    """Decide whether one image may enter the model request."""
    limits = budget or VisionBudget()
    size = len(payload or b"")
    if already_count >= limits.max_images:
        return VisionAccept(False, "max_image_count", raw_bytes=size)
    if size <= 0:
        return VisionAccept(False, "empty_image", raw_bytes=0)
    if size > limits.max_single_bytes:
        return VisionAccept(False, "single_image_too_large", raw_bytes=size)
    if already_bytes + size > limits.max_raw_bytes:
        return VisionAccept(False, "combined_raw_bytes", raw_bytes=size)
    width, height = _probe_image(payload)
    if width is None or height is None:
        return VisionAccept(False, "undecodable_or_bomb", raw_bytes=size)
    if width > limits.max_dimension or height > limits.max_dimension:
        return VisionAccept(False, "dimension_limit", width=width, height=height, raw_bytes=size)
    pixels = int(width) * int(height)
    if pixels <= 0:
        return VisionAccept(False, "invalid_pixels", width=width, height=height, raw_bytes=size)
    if already_pixels + pixels > limits.max_pixels:
        return VisionAccept(
            False,
            "combined_pixel_budget",
            width=width,
            height=height,
            pixels=pixels,
            raw_bytes=size,
        )
    return VisionAccept(True, "", width=width, height=height, pixels=pixels, raw_bytes=size)


def vision_budget_report(accepted: list[VisionAccept], rejected: list[VisionAccept]) -> dict[str, Any]:
    return {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "raw_bytes": sum(item.raw_bytes for item in accepted),
        "pixels": sum(int(item.pixels or 0) for item in accepted),
        "reject_reasons": [item.reason for item in rejected if item.reason],
    }
