"""User-controlled BehaviorProfile — SYSTEM_PROMPT / behavioral steering.

Separate from AuthorityProfile (technical capability scopes).
The SYSTEM_PROMPT is not a cryptographic authorization mechanism.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BehaviorProfile:
    """Versioned behavioral steering payload for the context compiler.

    Core remains behavior-policy neutral: no hardcoded moral/political/legal
    content rules belong here as source-enforced refusals.
    """

    id: str
    version: str
    system_prompt: str
    project_prompt_overlays: tuple[str, ...] = ()
    task_prompt_overlays: tuple[str, ...] = ()
    reasoning_mode_default: str = "standard"
    tool_use_style: str = "balanced"
    metadata: dict[str, Any] = field(default_factory=dict)
    hash: str | None = None

    def compute_hash(self) -> str:
        payload = {
            "id": self.id,
            "version": self.version,
            "system_prompt": self.system_prompt,
            "project_prompt_overlays": list(self.project_prompt_overlays),
            "task_prompt_overlays": list(self.task_prompt_overlays),
            "reasoning_mode_default": self.reasoning_mode_default,
            "tool_use_style": self.tool_use_style,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def with_hash(self) -> BehaviorProfile:
        return BehaviorProfile(
            id=self.id,
            version=self.version,
            system_prompt=self.system_prompt,
            project_prompt_overlays=self.project_prompt_overlays,
            task_prompt_overlays=self.task_prompt_overlays,
            reasoning_mode_default=self.reasoning_mode_default,
            tool_use_style=self.tool_use_style,
            metadata=dict(self.metadata),
            hash=self.compute_hash(),
        )

    def public_dict(self, *, include_prompt: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "version": self.version,
            "reasoning_mode_default": self.reasoning_mode_default,
            "tool_use_style": self.tool_use_style,
            "project_prompt_overlays_count": len(self.project_prompt_overlays),
            "task_prompt_overlays_count": len(self.task_prompt_overlays),
            "hash": self.hash or self.compute_hash(),
            "metadata": self.metadata,
            "truth": {
                "behavior_is_not_authority": True,
                "system_prompt_is_not_capability_grant": True,
            },
        }
        if include_prompt:
            data["system_prompt"] = self.system_prompt
            data["project_prompt_overlays"] = list(self.project_prompt_overlays)
            data["task_prompt_overlays"] = list(self.task_prompt_overlays)
        return data


DEFAULT_BEHAVIOR_PROFILE = BehaviorProfile(
    id="leviathan.default",
    version="1",
    system_prompt=(
        "You are LEVIATHAN, a local AI control-plane assistant. "
        "Be precise, truthful about uncertainty, and respect technical capability boundaries."
    ),
).with_hash()
