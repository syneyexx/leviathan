"""Resource-aware local intelligence helpers (WP8).

Reuses ModelRouter capacity lanes and usage telemetry — does not invent a
second scheduler. Never assumes two heavy loaded models as a default.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_SIMPLE_PATTERNS = (
    r"^\s*(hi|hello|hey|hallo|goedemorgen|goedemiddag)\b",
    r"^\s*what('?s| is) your name\b",
    r"^\s*wie ben je\b",
    r"^\s*\d[\d\s\+\-\*/\(\)\.]+\d\s*$",
    r"^\s*(thanks|thank you|bedankt|dank je)\b",
)


def classify_task_complexity(prompt: str, *, has_tools: bool = False, has_files: bool = False) -> dict[str, Any]:
    """Cheap heuristic: simple questions skip planner/critic/committee.

    Length is a hint, not a verdict that the question is intellectually hard.
    """
    text = (prompt or "").strip()
    lower = text.lower()
    if not text:
        return {"complexity": "empty", "use_committee": False, "use_planner": False, "use_critic": False}
    try:
        from reasoning.understanding import build_request_spec, extract_task_features

        spec = build_request_spec(text)
        features = extract_task_features(spec)
        if features.direct_answer or spec.kind in {"chat", "question"} and not features.tools_required:
            return {
                "complexity": "simple",
                "use_committee": False,
                "use_planner": False,
                "use_critic": False,
                "reason": "direct_answer",
            }
        if features.tools_required or features.has_step_dependencies or spec.kind in {"code", "debug", "planning", "multi_step"}:
            return {
                "complexity": "complex",
                "use_committee": False,
                "use_planner": bool(features.has_step_dependencies or spec.needs_plan),
                "use_critic": bool(spec.needs_tools or spec.kind in {"code", "multi_step", "planning"}),
                "reason": "structured_execution",
            }
        if spec.kind in {"analysis", "research"}:
            return {
                "complexity": "standard",
                "use_committee": False,
                "use_planner": bool(features.has_step_dependencies),
                "use_critic": False,
                "reason": "structured_analysis",
            }
    except Exception:
        pass
    if has_tools or has_files:
        return {
            "complexity": "complex",
            "use_committee": False,
            "use_planner": True,
            "use_critic": True,
            "reason": "tools_or_files",
        }
    if any(re.search(pat, lower) for pat in _SIMPLE_PATTERNS):
        return {
            "complexity": "simple",
            "use_committee": False,
            "use_planner": False,
            "use_critic": False,
            "reason": "simple_pattern",
        }
    if "?" in text and not has_tools:
        return {
            "complexity": "simple",
            "use_committee": False,
            "use_planner": False,
            "use_critic": False,
            "reason": "question",
        }
    return {
        "complexity": "standard",
        "use_committee": False,
        "use_planner": False,
        "use_critic": False,
        "reason": "default_standard",
    }


def cache_key(
    *,
    namespace: str,
    input_version: str,
    source_version: str = "",
    model_id: str = "",
    config_version: str = "",
    policy_version: str = "",
    capability_status: str = "",
) -> str:
    """Versioned cache key — permissions/uncertain mutating outcomes must not be cached as success."""
    material = {
        "namespace": namespace,
        "input_version": input_version,
        "source_version": source_version,
        "model_id": model_id,
        "config_version": config_version,
        "policy_version": policy_version,
        "capability_status": capability_status,
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class VersionedCache:
    """Small in-process cache with explicit invalidation. Not a permission store."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry.get("uncertain") or entry.get("mutating"):
            # Never reuse uncertain mutating outcomes as success.
            return None
        return entry.get("value")

    def set(
        self,
        key: str,
        value: Any,
        *,
        uncertain: bool = False,
        mutating: bool = False,
        permission_bound: bool = False,
    ) -> None:
        if permission_bound:
            # Permissions are not cached as indefinitely valid.
            return
        if uncertain and mutating:
            return
        self._store[key] = {
            "value": value,
            "uncertain": bool(uncertain),
            "mutating": bool(mutating),
        }

    def invalidate(self, *, prefix: str | None = None, key: str | None = None) -> int:
        if key:
            return 1 if self._store.pop(key, None) is not None else 0
        if prefix:
            victims = [k for k in self._store if k.startswith(prefix)]
            for k in victims:
                self._store.pop(k, None)
            return len(victims)
        count = len(self._store)
        self._store.clear()
        return count


def backpressure_decision(
    *,
    active_inference: int,
    max_concurrent_inference: int,
    queue_depth: int = 0,
    memory_pressure: str | None = None,
) -> dict[str, Any]:
    """Predictable degrade/stop when resources are missing — no dual-GPU assumption."""
    max_c = max(1, int(max_concurrent_inference or 1))
    active = max(0, int(active_inference or 0))
    if memory_pressure in {"critical", "oom_risk"}:
        return {"action": "stop", "reason": "memory_pressure", "retry_after_ms": None}
    if active >= max_c:
        return {
            "action": "wait",
            "reason": "inference_capacity",
            "retry_after_ms": 250,
            "active": active,
            "max": max_c,
        }
    if queue_depth > max_c * 4:
        return {
            "action": "degrade",
            "reason": "queue_backpressure",
            "skip_committee": True,
            "skip_planner": True,
            "retry_after_ms": 100,
        }
    return {"action": "proceed", "reason": "capacity_available"}
