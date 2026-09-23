"""Explicit AI task types and capability requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    id: str
    capability: str
    output_kind: str  # asset | text | analysis | actions
    preview_mandatory: bool = True
    require_accept: bool = True
    selection_kinds: tuple[str, ...] = ("any",)
    required_inputs: tuple[str, ...] = ("instruction",)
    optional_inputs: tuple[str, ...] = ()
    description: str = ""


TASKS: dict[str, TaskSpec] = {
    # IMAGE
    "generate_image": TaskSpec(
        id="generate_image",
        capability="image.generate",
        output_kind="asset",
        selection_kinds=("visual", "container", "image", "any"),
        optional_inputs=("dimensions", "style", "visualContext"),
        description="Generate a new image for the selected region",
    ),
    "replace_image": TaskSpec(
        id="replace_image",
        capability="image.generate",
        output_kind="asset",
        selection_kinds=("image",),
        optional_inputs=("asset", "visualContext"),
        description="Generate a replacement for the selected image",
    ),
    "restyle_image": TaskSpec(
        id="restyle_image",
        capability="image.edit",
        output_kind="asset",
        selection_kinds=("image",),
        optional_inputs=("asset", "visualContext"),
        description="Restyle existing image (requires image.edit provider)",
    ),
    "image_variants": TaskSpec(
        id="image_variants",
        capability="image.variation",
        output_kind="asset",
        selection_kinds=("image", "visual"),
        optional_inputs=("asset", "variants"),
        description="Generate variants of an image",
    ),
    "expand_image": TaskSpec(
        id="expand_image",
        capability="image.outpaint",
        output_kind="asset",
        selection_kinds=("image",),
        description="Outpaint / expand image bounds",
    ),
    "remove_background": TaskSpec(
        id="remove_background",
        capability="image.background.remove",
        output_kind="asset",
        selection_kinds=("image",),
        description="Remove image background",
    ),
    "generate_icon": TaskSpec(
        id="generate_icon",
        capability="image.generate",
        output_kind="asset",
        selection_kinds=("visual", "container", "any"),
        description="Generate a small icon/emblem",
    ),
    "generate_texture": TaskSpec(
        id="generate_texture",
        capability="image.generate",
        output_kind="asset",
        selection_kinds=("visual", "container", "any"),
        description="Generate a texture or pattern",
    ),
    # TEXT
    "rewrite_text": TaskSpec(
        id="rewrite_text",
        capability="text.rewrite",
        output_kind="text",
        selection_kinds=("text",),
        optional_inputs=("currentText",),
        description="Rewrite selected text",
    ),
    "generate_text": TaskSpec(
        id="generate_text",
        capability="text.generate",
        output_kind="text",
        selection_kinds=("text", "any"),
        description="Generate text content",
    ),
    "shorten_text": TaskSpec(
        id="shorten_text",
        capability="text.rewrite",
        output_kind="text",
        selection_kinds=("text",),
        description="Shorten selected text",
    ),
    "expand_text": TaskSpec(
        id="expand_text",
        capability="text.rewrite",
        output_kind="text",
        selection_kinds=("text",),
        description="Expand selected text",
    ),
    # DESIGN / VISION
    "analyze_style": TaskSpec(
        id="analyze_style",
        capability="vision.analyze",
        output_kind="analysis",
        preview_mandatory=False,
        require_accept=False,
        selection_kinds=("any",),
        description="Analyze visual style of selection/page",
    ),
    "suggest_design_change": TaskSpec(
        id="suggest_design_change",
        capability="layout.reason",
        output_kind="actions",
        selection_kinds=("any",),
        description="Propose structured design actions",
    ),
    "improve_responsiveness": TaskSpec(
        id="improve_responsiveness",
        capability="layout.reason",
        output_kind="actions",
        selection_kinds=("any",),
        description="Propose responsive layout improvements",
    ),
    "create_component": TaskSpec(
        id="create_component",
        capability="layout.reason",
        output_kind="actions",
        selection_kinds=("any",),
        description="Propose a new component structure",
    ),
    "create_section": TaskSpec(
        id="create_section",
        capability="layout.reason",
        output_kind="actions",
        selection_kinds=("any",),
        description="Propose a new section structure",
    ),
}


def get_task(task_id: str) -> TaskSpec | None:
    return TASKS.get(str(task_id or "").strip())


def list_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "capability": t.capability,
            "outputKind": t.output_kind,
            "previewMandatory": t.preview_mandatory,
            "requireAccept": t.require_accept,
            "selectionKinds": list(t.selection_kinds),
            "description": t.description,
        }
        for t in TASKS.values()
    ]


# Alias map for UI convenience
TASK_ALIASES = {
    "generate": "generate_image",
    "image": "generate_image",
    "replace": "replace_image",
    "restyle": "restyle_image",
    "variants": "image_variants",
    "rewrite": "rewrite_text",
    "text": "generate_text",
    "analyze": "analyze_style",
}


def resolve_task_id(raw: str) -> str | None:
    key = str(raw or "").strip()
    if key in TASKS:
        return key
    return TASK_ALIASES.get(key)
