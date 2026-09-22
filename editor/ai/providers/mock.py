"""Deterministic development/mock AI provider.

Visibly labeled as mock/dev. Never presented as a real AI generation success
in provider metadata.
"""

from __future__ import annotations

import hashlib
import struct
import time
import zlib
from typing import Any

from .base import Provider, ProviderCapability, ProviderMeta, ProviderRequest, ProviderResult


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_placeholder_png(width: int, height: int, seed: str) -> bytes:
    """Create a deterministic PNG gradient branded as MOCK."""
    width = max(16, min(int(width or 512), 1280))
    height = max(16, min(int(height or 288), 1280))
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    r0, g0, b0 = digest[0], digest[1], digest[2]
    r1, g1, b1 = digest[3], digest[4], digest[5]

    rows = []
    for y in range(height):
        row = bytearray()
        row.append(0)  # filter none
        ty = y / max(1, height - 1)
        for x in range(width):
            tx = x / max(1, width - 1)
            # Diagonal brand band
            band = abs(tx - ty) < 0.04
            if band:
                row.extend((255, 200, 80))
            else:
                row.append(int(r0 * (1 - tx) + r1 * tx))
                row.append(int(g0 * (1 - ty) + g1 * ty))
                row.append(int(b0 * (1 - (tx + ty) / 2) + b1 * ((tx + ty) / 2)))
        rows.append(bytes(row))

    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


class MockProvider(Provider):
    id = "mock"
    label = "Studio Dev Mock"
    kind = "mock"
    is_mock = True

    def __init__(self, *, latency_ms: int = 50, fail_mode: str | None = None) -> None:
        self.latency_ms = max(0, int(latency_ms))
        self.fail_mode = fail_mode  # None | error | timeout | unsupported

    def meta(self) -> ProviderMeta:
        caps = [
            ProviderCapability(
                id="image.generate",
                inputs=["instruction", "dimensions", "style"],
                reference_images=True,
                max_references=2,
                dimensions={"min": 16, "max": 1280, "step": 1},
                aspect_ratios=["any"],
                timeout_hint_ms=5_000,
                notes="Deterministic placeholder PNG — not a real generator",
            ),
            ProviderCapability(
                id="image.variation",
                inputs=["instruction", "asset"],
                reference_images=True,
                max_references=1,
                notes="Mock variants from seed",
            ),
            ProviderCapability(
                id="image.edit",
                available=False,
                notes="Mock does not simulate true image editing",
            ),
            ProviderCapability(
                id="image.outpaint",
                available=False,
                notes="No outpaint simulation (would be dishonest stretch)",
            ),
            ProviderCapability(
                id="image.background.remove",
                available=False,
                notes="No background removal in mock",
            ),
            ProviderCapability(
                id="text.generate",
                inputs=["instruction"],
                notes="Deterministic mock copy",
            ),
            ProviderCapability(
                id="text.rewrite",
                inputs=["instruction", "currentText"],
                notes="Deterministic mock rewrite",
            ),
            ProviderCapability(
                id="vision.analyze",
                inputs=["style", "visualContext"],
                notes="Deterministic style summary from structured context",
            ),
            ProviderCapability(
                id="layout.reason",
                available=False,
                notes="Structured layout actions require a real reasoning provider",
            ),
        ]
        return ProviderMeta(
            id=self.id,
            label=self.label,
            kind=self.kind,
            enabled=True,
            is_mock=True,
            models=["mock-v1"],
            capabilities=caps,
            reason=None,
        )

    def supports(self, capability: str) -> bool:
        meta = self.meta()
        for cap in meta.capabilities:
            if cap.id == capability and cap.available:
                return True
        return False

    def execute(self, request: ProviderRequest) -> ProviderResult:
        if self.latency_ms:
            # Honour cancel between sleeps in small chunks
            remaining = self.latency_ms / 1000.0
            step = 0.02
            while remaining > 0:
                if request.cancel_event is not None and getattr(request.cancel_event, "is_set", lambda: False)():
                    return ProviderResult(
                        ok=False,
                        kind="error",
                        error_code="cancelled",
                        error_message="Request cancelled",
                    )
                time.sleep(min(step, remaining))
                remaining -= step

        if self.fail_mode == "timeout":
            return ProviderResult(
                ok=False,
                kind="error",
                error_code="provider_timeout",
                error_message="Mock simulated timeout",
            )
        if self.fail_mode == "error":
            return ProviderResult(
                ok=False,
                kind="error",
                error_code="provider_failed",
                error_message="Mock simulated provider failure",
            )
        if self.fail_mode == "unsupported" or not self.supports(request.capability):
            return ProviderResult(
                ok=False,
                kind="unsupported",
                error_code="unsupported_capability",
                error_message=f"Mock does not support {request.capability}",
            )

        if request.capability.startswith("image."):
            return self._image(request)
        if request.capability.startswith("text."):
            return self._text(request)
        if request.capability == "vision.analyze":
            return self._analyze(request)
        return ProviderResult(
            ok=False,
            kind="unsupported",
            error_code="unsupported_capability",
            error_message=f"Unsupported: {request.capability}",
        )

    def _image(self, request: ProviderRequest) -> ProviderResult:
        width = request.width or 512
        height = request.height or 288
        # Snap to even dims for clean PNG
        width = max(16, min(int(width), 1280))
        height = max(16, min(int(height), 1280))
        variants: list[dict[str, Any]] = []
        for i in range(max(1, request.variants)):
            seed = f"{request.request_id}:{request.instruction}:{i}"
            raw = make_placeholder_png(width, height, seed)
            variants.append(
                {
                    "id": f"mock-{hashlib.sha1(seed.encode()).hexdigest()[:12]}",
                    "mime": "image/png",
                    "bytesBase64": __import__("base64").b64encode(raw).decode("ascii"),
                    "width": width,
                    "height": height,
                    "label": f"Mock variant {i + 1}",
                    "isMock": True,
                }
            )
        kind = "asset_variants" if len(variants) > 1 else "asset_preview"
        return ProviderResult(
            ok=True,
            kind=kind,
            variants=variants,
            model="mock-v1",
            requested_size={"width": request.width or width, "height": request.height or height},
            generated_size={"width": width, "height": height},
            diagnostics={"mock": True, "seeded": True},
            degraded_context=False,
        )

    def _text(self, request: ProviderRequest) -> ProviderResult:
        ctx = request.context or {}
        selection = ctx.get("selection") or {}
        current = ""
        asset = ctx.get("asset") or {}
        if isinstance(selection.get("computedSummary"), dict):
            current = str(selection["computedSummary"].get("text") or "")
        instruction = request.instruction
        if request.task == "shorten_text" and current:
            text = current[: max(12, len(current) // 2)]
        elif request.task == "expand_text" and current:
            text = f"{current} — {instruction}"
        elif current and request.capability == "text.rewrite":
            text = f"[MOCK REWRITE] {instruction}: {current}"
        else:
            text = f"[MOCK] {instruction}"
        return ProviderResult(
            ok=True,
            kind="text_preview",
            text=text[:8000],
            model="mock-v1",
            diagnostics={"mock": True},
        )

    def _analyze(self, request: ProviderRequest) -> ProviderResult:
        style = (request.context or {}).get("style") or {}
        analysis = {
            "source": "mock-deterministic",
            "isMock": True,
            "theme": style.get("theme"),
            "palette": style.get("palette") or [],
            "tokensUsed": list((style.get("tokens") or {}).keys())[:12],
            "styleSummary": style.get("styleSummary")
            or "Mock analysis from structured tokens only (no vision model).",
            "tags": style.get("tags") or [],
        }
        return ProviderResult(
            ok=True,
            kind="analysis",
            analysis=analysis,
            model="mock-v1",
            diagnostics={"mock": True},
        )
