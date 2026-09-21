"""T12 fixed agent quality task set — deterministic judges, live model when available.

The canonical corpus is ``evals.agent_tasks`` (20–50 holdout+dev tasks). This
module freezes the contract for release reporting: every run must emit tool
success ratio, task completion, model-call counts, tokens, and latency — with
null + reason when a live model is unavailable (never a fake pass).
"""

from __future__ import annotations

from typing import Any

from evals.agent_tasks import (
    AGENT_TASKS_DATASET_VERSION,
    combined_corpus_stats,
    list_agent_dev_tasks,
    list_agent_holdout_tasks,
)

FIXED_TASK_SET_VERSION = "fixed_task_set_v1"
FIXED_TASK_SET_MIN = 20
FIXED_TASK_SET_MAX = 50


def list_fixed_tasks(*, split: str = "holdout") -> list[dict[str, Any]]:
    """Return the fixed evaluation task list (holdout by default)."""
    if split == "development":
        return list(list_agent_dev_tasks())
    if split == "all":
        return list(list_agent_holdout_tasks()) + list(list_agent_dev_tasks())
    return list(list_agent_holdout_tasks())


def fixed_task_set_manifest() -> dict[str, Any]:
    """Metadata for the fixed set — size bounds are part of the T12 contract."""
    stats = combined_corpus_stats()
    holdout = list_fixed_tasks(split="holdout")
    return {
        "fixed_task_set_version": FIXED_TASK_SET_VERSION,
        "agent_tasks_version": AGENT_TASKS_DATASET_VERSION,
        "task_count": len(holdout),
        "task_ids": [t["id"] for t in holdout],
        "min_tasks": FIXED_TASK_SET_MIN,
        "max_tasks": FIXED_TASK_SET_MAX,
        "within_bounds": FIXED_TASK_SET_MIN <= len(holdout) <= FIXED_TASK_SET_MAX,
        "categories": stats.get("categories"),
        "fingerprint_sha256": stats.get("fingerprint_sha256"),
        "judge_policy": "deterministic_only",
        "llm_as_judge": False,
        "metrics": [
            "tool_success_ratio",
            "task_completion",
            "model_calls",
            "tokens",
            "latency_ms",
            "first_attempt_success",
            "false_success_rate",
        ],
    }


def assert_fixed_task_set_bounds(tasks: list[dict[str, Any]] | None = None) -> None:
    tasks = tasks if tasks is not None else list_fixed_tasks()
    n = len(tasks)
    if n < FIXED_TASK_SET_MIN or n > FIXED_TASK_SET_MAX:
        raise AssertionError(
            f"fixed task set size {n} outside [{FIXED_TASK_SET_MIN}, {FIXED_TASK_SET_MAX}]"
        )
