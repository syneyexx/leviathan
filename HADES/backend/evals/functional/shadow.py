"""Shadow-mode decision recorder for high-risk behavioral changes.

Records legacy vs candidate decisions without changing user-visible behavior.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SHADOW_VERSION = "functional_shadow_v1"


@dataclass
class ShadowDecision:
    area: str
    task_id: str
    legacy: dict[str, Any]
    candidate: dict[str, Any]
    difference: str
    eventual_outcome: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowRecorder:
    """In-memory (+ optional JSONL) shadow log. Never mutates production routing."""

    def __init__(self, *, enabled: bool = True, path: str | Path | None = None) -> None:
        self.enabled = enabled
        self.path = Path(path) if path else None
        self.rows: list[ShadowDecision] = []

    def record(
        self,
        *,
        area: str,
        task_id: str,
        legacy: dict[str, Any],
        candidate: dict[str, Any],
        difference: str | None = None,
        eventual_outcome: str | None = None,
    ) -> ShadowDecision | None:
        if not self.enabled:
            return None
        if difference is None:
            difference = "same" if legacy == candidate else "differs"
        row = ShadowDecision(
            area=area,
            task_id=task_id,
            legacy=legacy,
            candidate=candidate,
            difference=difference,
            eventual_outcome=eventual_outcome,
        )
        self.rows.append(row)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"version": SHADOW_VERSION, **row.to_dict()}, default=str) + "\n")
        return row

    def summary(self) -> dict[str, Any]:
        differs = sum(1 for r in self.rows if r.difference != "same")
        return {
            "version": SHADOW_VERSION,
            "sample_size": len(self.rows),
            "differences": differs,
            "areas": sorted({r.area for r in self.rows}),
        }


# Process-local default (opt-in via enabled flag / env in callers).
default_shadow = ShadowRecorder(enabled=False)
