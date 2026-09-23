"""Immutable context snapshot hashes for run/eval reproducibility (U068)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .types import ContextPack


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ContextSnapshot:
    snapshot_hash: str
    created_at: str
    section_count: int
    token_estimate: int
    constraints_retained: bool
    manifest: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "snapshot_hash": self.snapshot_hash,
            "created_at": self.created_at,
            "section_count": self.section_count,
            "token_estimate": self.token_estimate,
            "constraints_retained": self.constraints_retained,
            "manifest": dict(self.manifest),
            "truth": {"snapshot_is_immutable_hash": True},
        }


def snapshot_context_pack(pack: ContextPack) -> ContextSnapshot:
    """Hash included section provenance + kinds (not full sensitive bodies by default)."""
    material = {
        "sections": [
            {
                "name": s.name,
                "kind": s.kind,
                "layer": s.layer,
                "tokens": s.token_estimate,
                "pinned": s.pinned,
                "included": s.included,
                "content_sha": hashlib.sha256(s.content.encode("utf-8")).hexdigest()[:16],
            }
            for s in pack.sections
            if s.included
        ],
        "dropped": list(pack.dropped),
        "token_estimate": pack.token_estimate,
        "token_budget": pack.token_budget,
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    manifest = {
        "kinds": sorted({s.kind for s in pack.sections if s.included}),
        "pinned": [s.name for s in pack.sections if s.pinned and s.included],
        "dropped_count": len(pack.dropped),
        "knowledge_count": pack.knowledge_count,
    }
    return ContextSnapshot(
        snapshot_hash=f"ctx:{digest[:24]}",
        created_at=_utc_now(),
        section_count=sum(1 for s in pack.sections if s.included),
        token_estimate=pack.token_estimate,
        constraints_retained=pack.constraints_retained,
        manifest=manifest,
    )
