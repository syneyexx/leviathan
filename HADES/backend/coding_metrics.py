"""Operational coding-run timeline and metrics. No private chain-of-thought, no source dumps."""

from __future__ import annotations

import time
from typing import Any

EVENT_KINDS = (
    "task_created",
    "investigation_started",
    "finding_added",
    "plan_created",
    "context_selected",
    "model_called",
    "tool_called",
    "edit_proposed",
    "edit_applied",
    "verification_started",
    "verification_failed",
    "repair_started",
    "review_started",
    "approval_requested",
    "task_completed",
)


class CodingMetrics:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.events: list[dict[str, Any]] = []
        self.model_calls = 0
        self.tool_calls = 0
        self.files_inspected = 0
        self.files_changed = 0
        self.tests_executed = 0
        self.repair_attempts = 0
        self.repeat_patches_blocked = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cache_hit_rate = 0.0
        self.failure_categories: list[str] = []

    def emit(self, kind: str, **data: Any) -> None:
        if kind not in EVENT_KINDS:
            kind = "tool_called"
        safe = {k: v for k, v in data.items() if k not in {"content", "prompt", "source", "logs"}}
        self.events.append({"kind": kind, "ts": time.time(), "data": safe})
        if kind == "model_called":
            self.model_calls += 1
            self.tokens_in += int(data.get("tokens_in") or 0)
            self.tokens_out += int(data.get("tokens_out") or 0)
        elif kind == "tool_called":
            self.tool_calls += 1
        elif kind == "edit_applied":
            self.files_changed += int(data.get("count") or 1)
        elif kind == "verification_started":
            self.tests_executed += int(data.get("count") or 1)
        elif kind == "repair_started":
            self.repair_attempts += 1
        elif kind == "verification_failed":
            cat = str(data.get("failure_type") or "unknown")
            if cat not in self.failure_categories:
                self.failure_categories.append(cat)

    def snapshot(self) -> dict[str, Any]:
        return {
            "wall_time_s": round(time.perf_counter() - self.started, 3),
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "context_cache_hit_rate": self.cache_hit_rate,
            "files_inspected": self.files_inspected,
            "files_changed": self.files_changed,
            "tests_executed": self.tests_executed,
            "repair_attempts": self.repair_attempts,
            "repeated_patch_prevention": self.repeat_patches_blocked,
            "failure_categories": list(self.failure_categories),
            "events": self.events[-80:],
            "sensitive_contents_omitted": True,
        }
