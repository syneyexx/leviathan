"""Mission → initial public plan for coding sessions."""

from __future__ import annotations

from .types import Mission


def build_initial_plan(goal: str, mission: Mission) -> list[str]:
    """Return at most 3 public plan bullets (no hidden CoT)."""
    text = (goal or "").strip()
    preview = text[:100] + ("…" if len(text) > 100 else "")
    if mission == Mission.SCAFFOLD:
        return [
            f"Inspect workspace for scaffold target: {preview or 'new project'}",
            "Create only the files the goal requires (no drive-by extras)",
            "Summarize with observation_ids for every write",
        ]
    if mission == Mission.REVIEW:
        return [
            f"Locate and read the files under review: {preview or 'diff/review'}",
            "Report findings with file:line citations",
            "Propose patches only when explicitly asked",
        ]
    if mission == Mission.TEST:
        return [
            f"Read the code under test: {preview or 'tests'}",
            "Add or extend tests via file.write/file.patch",
            "Run coding.run_tests and cite the observation",
        ]
    if mission == Mission.FIX:
        return [
            f"Reproduce understanding by reading failing area: {preview or 'bug'}",
            "Apply a minimal file.patch",
            "Run coding.run_tests before claiming FIXED",
        ]
    return [
        f"Search and read relevant files for: {preview or 'goal'}",
        "Prefer file.patch over full-file writes",
        "Verify side effects via observations before DONE",
    ]


def mission_from_text(text: str | None) -> Mission:
    raw = (text or "").strip().upper()
    for item in Mission:
        if item.value == raw or item.name == raw:
            return item
    lowered = (text or "").strip().lower()
    if "scaffold" in lowered or "new project" in lowered:
        return Mission.SCAFFOLD
    if "review" in lowered or "diff" in lowered:
        return Mission.REVIEW
    if "test" in lowered:
        return Mission.TEST
    if "fix" in lowered or "bug" in lowered:
        return Mission.FIX
    return Mission.GENERIC
