"""Immutable mixture manifests for governed training data (U269)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MixtureComponent:
    """One weighted source version inside a frozen mixture."""

    version_id: str
    content_hash: str
    weight: float
    domain: str = "general"
    quality: float = 1.0
    split: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "content_hash": self.content_hash,
            "weight": self.weight,
            "domain": self.domain,
            "quality": self.quality,
            "split": self.split,
        }


@dataclass
class MixtureManifest:
    """Trainable immutable mixture — not a mutable folder (U269)."""

    mixture_id: str
    name: str
    components: list[MixtureComponent]
    content_hash: str
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    sealed: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "mixture_id": self.mixture_id,
            "name": self.name,
            "components": [c.public_dict() for c in self.components],
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "sealed": self.sealed,
            "truth": {
                "mixture_is_immutable_once_sealed": True,
                "trainable_manifest_not_mutable_folder": True,
            },
        }


def build_mixture_manifest(
    *,
    name: str,
    components: list[MixtureComponent],
    metadata: dict[str, Any] | None = None,
    mixture_id: str | None = None,
) -> MixtureManifest:
    if not components:
        raise ValueError("mixture requires at least one component")
    total = sum(c.weight for c in components)
    if total <= 0:
        raise ValueError("mixture weights must sum to > 0")
    # Normalize weights for hashing stability.
    normalized = [
        MixtureComponent(
            version_id=c.version_id,
            content_hash=c.content_hash,
            weight=round(c.weight / total, 8),
            domain=c.domain,
            quality=c.quality,
            split=c.split,
        )
        for c in components
    ]
    body = {
        "name": name,
        "components": [c.public_dict() for c in normalized],
        "metadata": dict(metadata or {}),
    }
    content_hash = _stable_hash(body)
    return MixtureManifest(
        mixture_id=mixture_id or f"mix_{uuid.uuid4().hex[:12]}",
        name=name,
        components=normalized,
        content_hash=content_hash,
        metadata=dict(metadata or {}),
        sealed=True,
    )
