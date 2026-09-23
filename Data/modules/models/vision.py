"""Measured vision-language capability profile for Model Control Plane (U242)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from Data.modules.models.contracts import CapabilityState, ModelCapabilities


class VisionTask(str, Enum):
    OCR = "ocr"
    CHARTS = "charts"
    SCREENSHOTS = "screenshots"
    DOCUMENTS = "documents"
    VISUAL_QA = "visual_qa"


@dataclass(frozen=True)
class VisionCapabilityProfile:
    """Measured VLM sub-capabilities — UNMEASURED ≠ PASS."""

    ocr: CapabilityState = CapabilityState.UNMEASURED
    charts: CapabilityState = CapabilityState.UNMEASURED
    screenshots: CapabilityState = CapabilityState.UNMEASURED
    documents: CapabilityState = CapabilityState.UNMEASURED
    visual_qa: CapabilityState = CapabilityState.UNMEASURED
    general_vision: CapabilityState = CapabilityState.UNMEASURED

    def public_dict(self) -> dict[str, Any]:
        return {
            "ocr": self.ocr.value,
            "charts": self.charts.value,
            "screenshots": self.screenshots.value,
            "documents": self.documents.value,
            "visual_qa": self.visual_qa.value,
            "general_vision": self.general_vision.value,
            "truth": {
                "unmeasured_is_not_passed": True,
                "registered_via_model_control_plane": True,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "VisionCapabilityProfile":
        raw = dict(data or {})

        def read(key: str) -> CapabilityState:
            try:
                return CapabilityState(str(raw.get(key) or "unmeasured").lower())
            except ValueError:
                return CapabilityState.UNMEASURED

        return cls(
            ocr=read("ocr"),
            charts=read("charts"),
            screenshots=read("screenshots"),
            documents=read("documents"),
            visual_qa=read("visual_qa"),
            general_vision=read("general_vision"),
        )

    @classmethod
    def fixture_measured(cls) -> "VisionCapabilityProfile":
        """CI/fixture profile — explicit MEASURED/SUPPORTED for local tests."""
        return cls(
            ocr=CapabilityState.SUPPORTED,
            charts=CapabilityState.SUPPORTED,
            screenshots=CapabilityState.SUPPORTED,
            documents=CapabilityState.SUPPORTED,
            visual_qa=CapabilityState.SUPPORTED,
            general_vision=CapabilityState.SUPPORTED,
        )


def attach_vision_profile(
    capabilities: ModelCapabilities,
    vision: VisionCapabilityProfile,
) -> dict[str, Any]:
    """Merge vision profile into a public capabilities payload without a second registry."""
    payload = capabilities.public_dict()
    payload["visionProfile"] = vision.public_dict()
    if vision.general_vision == CapabilityState.SUPPORTED:
        payload["vision"] = CapabilityState.SUPPORTED.value
    return payload
