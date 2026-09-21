"""Append-only training event log (JSONL) — transport aid, DB remains source of truth."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.secrets import redact_secrets


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TrainingEventLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        ensure_dir(self.path.parent)

    def emit(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "type": event_type,
            "at": utc_now(),
            **payload,
        }
        line = redact_secrets(json.dumps(event, default=str))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return event

    def read(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-max(1, limit) :]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
