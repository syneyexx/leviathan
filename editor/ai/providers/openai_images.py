"""Optional OpenAI Images API-compatible provider.

Only enabled when LEVIATHAN_EDITOR_AI_IMAGE_ENDPOINT (or OPENAI_API_KEY + default)
is configured. Does not invent undocumented fields.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .base import Provider, ProviderCapability, ProviderMeta, ProviderRequest, ProviderResult

# Closest OpenAI Images size buckets
SIZE_BUCKETS = (
    (256, 256, "256x256"),
    (512, 512, "512x512"),
    (1024, 1024, "1024x1024"),
    (1024, 1792, "1024x1792"),
    (1792, 1024, "1792x1024"),
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def pick_size(width: int | None, height: int | None) -> tuple[str, int, int]:
    w = int(width or 1024)
    h = int(height or 1024)
    best = SIZE_BUCKETS[2]
    best_score = abs(best[0] - w) + abs(best[1] - h)
    for cand in SIZE_BUCKETS:
        score = abs(cand[0] - w) + abs(cand[1] - h)
        if score < best_score:
            best = cand
            best_score = score
    return best[2], best[0], best[1]


class OpenAIImagesProvider(Provider):
    id = "openai_images"
    label = "OpenAI Images"
    kind = "openai-images"
    is_mock = False

    def __init__(self) -> None:
        self.endpoint = _env("LEVIATHAN_EDITOR_AI_IMAGE_ENDPOINT")
        self.api_key = _env("LEVIATHAN_EDITOR_AI_IMAGE_API_KEY") or _env("OPENAI_API_KEY")
        self.model = _env("LEVIATHAN_EDITOR_AI_IMAGE_MODEL") or "dall-e-3"
        self.timeout = float(_env("LEVIATHAN_EDITOR_AI_TIMEOUT_SECONDS") or "90")

    def enabled(self) -> bool:
        if not self.endpoint or not self.api_key:
            return False
        try:
            parsed = urlparse(self.endpoint)
        except Exception:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower()
        if host in {"169.254.169.254", "metadata.google.internal"}:
            return False
        if parsed.scheme == "file":
            return False
        return True

    def meta(self) -> ProviderMeta:
        if not self.enabled():
            reason = "no-image-endpoint" if not self.endpoint else "no-image-api-key"
            return ProviderMeta(
                id=self.id,
                label=self.label,
                kind=self.kind,
                enabled=False,
                reason=reason,
                capabilities=[],
            )
        return ProviderMeta(
            id=self.id,
            label=self.label,
            kind=self.kind,
            enabled=True,
            models=[self.model],
            capabilities=[
                ProviderCapability(
                    id="image.generate",
                    inputs=["instruction", "dimensions"],
                    reference_images=False,
                    max_references=0,
                    dimensions={"buckets": [s[2] for s in SIZE_BUCKETS]},
                    aspect_ratios=["1:1", "9:16", "16:9"],
                    timeout_hint_ms=int(self.timeout * 1000),
                    notes="OpenAI Images generations endpoint; reference images not used by this adapter",
                ),
                ProviderCapability(
                    id="image.edit",
                    available=False,
                    notes="Image edit endpoint not wired in this adapter",
                ),
                ProviderCapability(
                    id="image.outpaint",
                    available=False,
                    notes="Outpaint not available via this adapter",
                ),
                ProviderCapability(
                    id="image.background.remove",
                    available=False,
                ),
                ProviderCapability(
                    id="image.variation",
                    available=False,
                    notes="Variations endpoint not wired; use generate_image with variants count where supported",
                ),
            ],
        )

    def supports(self, capability: str) -> bool:
        return self.enabled() and capability == "image.generate"

    def execute(self, request: ProviderRequest) -> ProviderResult:
        if not self.supports(request.capability):
            return ProviderResult(
                ok=False,
                kind="unsupported",
                error_code="unsupported_capability",
                error_message="OpenAI Images adapter only supports image.generate",
            )
        if request.cancel_event is not None and getattr(request.cancel_event, "is_set", lambda: False)():
            return ProviderResult(ok=False, kind="error", error_code="cancelled", error_message="Cancelled")

        size_label, gen_w, gen_h = pick_size(request.width, request.height)
        # Build prompt: separate user instruction from style facts
        style = (request.context or {}).get("style") or {}
        style_bits = []
        if style.get("styleSummary"):
            style_bits.append(str(style["styleSummary"])[:800])
        if style.get("palette"):
            style_bits.append("palette: " + ", ".join(str(p) for p in style["palette"][:8]))
        tokens = style.get("tokens") or {}
        if tokens:
            style_bits.append(
                "tokens: "
                + ", ".join(f"{k}={v}" for k, v in list(tokens.items())[:12])
            )
        visual = (request.context or {}).get("visualContext") or {}
        degraded = False
        degrade_reason = None
        if visual.get("pageSnapshot") or visual.get("selectionSnapshot"):
            # This adapter cannot send reference images to generations
            degraded = True
            degrade_reason = "provider_no_reference_images"

        prompt = (
            f"{request.instruction.strip()}\n\n"
            f"Composition constraints: target roughly {request.width or gen_w}x{request.height or gen_h}. "
            f"Use visual language hints only; do not reproduce the whole page.\n"
        )
        if style_bits:
            prompt += "Style facts (not content to copy): " + " | ".join(style_bits)

        n = 1  # dall-e-3 typically n=1
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt[:3900],
            "n": n,
            "size": size_label,
            "response_format": "b64_json",
        }
        raw_body = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = urllib.request.Request(self.endpoint, data=raw_body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=min(request.timeout_seconds, self.timeout)) as res:
                data = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 401:
                return ProviderResult(ok=False, kind="error", error_code="provider_auth", error_message="Image provider authentication failed")
            if err.code == 429:
                return ProviderResult(ok=False, kind="error", error_code="provider_rate_limit", error_message="Image provider rate limited")
            return ProviderResult(ok=False, kind="error", error_code="provider_failed", error_message=f"Image provider HTTP {err.code}")
        except TimeoutError:
            return ProviderResult(ok=False, kind="error", error_code="provider_timeout", error_message="Image provider timed out")
        except urllib.error.URLError:
            return ProviderResult(ok=False, kind="error", error_code="provider_unreachable", error_message="Image provider unreachable")
        except Exception as exc:
            return ProviderResult(ok=False, kind="error", error_code="provider_failed", error_message=str(exc)[:200])

        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            return ProviderResult(ok=False, kind="error", error_code="malformed_provider_result", error_message="No image data in provider response")

        variants = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json")
            if not isinstance(b64, str) or not b64:
                # Do not follow arbitrary remote URLs (SSRF). Require b64.
                return ProviderResult(
                    ok=False,
                    kind="error",
                    error_code="malformed_provider_result",
                    error_message="Provider returned URL without b64_json; refused to fetch remote URL",
                )
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return ProviderResult(ok=False, kind="error", error_code="malformed_provider_result", error_message="Invalid image base64")
            if not raw.startswith(b"\x89PNG") and not raw.startswith(b"\xff\xd8") and not (
                raw[0:4] == b"RIFF" and raw[8:12] == b"WEBP"
            ):
                return ProviderResult(ok=False, kind="error", error_code="invalid_image", error_message="Generated result failed magic-byte validation")
            mime = "image/png"
            if raw.startswith(b"\xff\xd8"):
                mime = "image/jpeg"
            elif raw[0:4] == b"RIFF":
                mime = "image/webp"
            variants.append(
                {
                    "id": f"oai-{i}-{request.request_id[:8]}",
                    "mime": mime,
                    "bytesBase64": base64.b64encode(raw).decode("ascii"),
                    "width": gen_w,
                    "height": gen_h,
                    "isMock": False,
                }
            )

        if not variants:
            return ProviderResult(ok=False, kind="error", error_code="malformed_provider_result", error_message="No valid variants")

        return ProviderResult(
            ok=True,
            kind="asset_preview" if len(variants) == 1 else "asset_variants",
            variants=variants,
            model=self.model,
            requested_size={"width": request.width or gen_w, "height": request.height or gen_h},
            generated_size={"width": gen_w, "height": gen_h},
            degraded_context=degraded,
            degrade_reason=degrade_reason,
            diagnostics={"sizeBucket": size_label, "referenceImagesUsed": False},
        )
