"""Configuration presets — pure collections of normal settings (no hidden behavior)."""

from __future__ import annotations

from typing import Any


PRESETS: dict[str, dict[str, Any]] = {
    "safe": {
        "label": "Safe",
        "description": "Conservative ceilings, confirmations on, network blocked.",
        "values": {
            "autonomy_level": "restricted",
            "confirmation_policy": "always",
            "automatic_execution": False,
            "automatic_delegation": False,
            "plugin_autonomous_tools": False,
            "auto_web_research": False,
            "network_policy": "block",
            "file_write_policy": "ask",
            "max_tool_rounds": 3,
            "max_model_calls_per_task": 12,
            "max_subtasks": 4,
            "max_delegation_depth": 1,
            "max_subagents": 1,
            "task_timeout_seconds": 1800,
            "loop_detection_enabled": True,
        },
    },
    "balanced": {
        "label": "Balanced",
        "description": "Normal HADES defaults with outbound network available; explicit block remains available.",
        "values": {
            "autonomy_level": "balanced",
            "confirmation_policy": "destructive_only",
            "automatic_execution": False,
            "automatic_delegation": False,
            "plugin_autonomous_tools": True,
            "auto_web_research": True,
            "network_policy": "allow",
            "file_write_policy": "ask",
            "max_tool_rounds": 3,
            "max_model_calls_per_task": 24,
            "max_subtasks": 8,
            "max_delegation_depth": 3,
            "max_subagents": 4,
            "task_timeout_seconds": None,
            "loop_detection_enabled": True,
        },
    },
    "power_user": {
        "label": "Power User",
        "description": "Higher ceilings while keeping confirmations for destructive actions.",
        "values": {
            "autonomy_level": "autonomous",
            "confirmation_policy": "destructive_only",
            "automatic_execution": True,
            "automatic_delegation": True,
            "plugin_autonomous_tools": True,
            "auto_web_research": True,
            "network_policy": "allow",
            "max_tool_rounds": 12,
            "max_model_calls_per_task": 64,
            "max_subtasks": 24,
            "max_parallel_steps": 4,
            "max_delegation_depth": 6,
            "max_subagents": 8,
            "task_timeout_seconds": None,
            "shared_budget_max_tool_calls": 500,
            "loop_detection_enabled": True,
        },
    },
    "maximum_autonomy": {
        "label": "Maximum Autonomy",
        "description": "Removes HADES-owned artificial limits where technically meaningful. Does not override provider limits or security invariants.",
        "values": {
            "autonomy_level": "maximum",
            "confirmation_policy": "destructive_only",
            "automatic_planning": True,
            "automatic_execution": True,
            "automatic_retries": True,
            "automatic_delegation": True,
            "plugin_autonomous_tools": True,
            "auto_web_research": True,
            "network_policy": "allow",
            "subagents_enabled": True,
            "recursive_delegation": True,
            "max_tool_rounds": None,
            "max_tool_calls": None,
            "max_model_calls_per_task": None,
            "max_specialist_steps": None,
            "max_subtasks": None,
            "max_dependency_depth": None,
            "work_plan_max_steps": None,
            "max_parallel_steps": None,
            "max_model_concurrency": None,
            "max_subagents": None,
            "max_active_subagents": None,
            "max_delegation_depth": None,
            "task_timeout_seconds": None,
            "idle_timeout_seconds": None,
            "execution_retry_count": None,
            "tool_retries": None,
            "shared_budget_max_model_calls": None,
            "shared_budget_max_tool_calls": None,
            "shared_budget_max_specialist_steps": None,
            "shared_budget_max_subtasks": None,
            "shared_budget_max_runtime_seconds": None,
            "max_plugin_processes": None,
            "terminal_timeout_seconds": None,
            "terminal_max_timeout_seconds": None,
            "research_harvest_max_documents": None,
            "research_harvest_max_pages": None,
            "loop_detection_enabled": True,
            "identical_tool_call_loop_protection": True,
        },
        "warnings": [
            "Unlimited iterations/tool calls can produce infinite loops and resource exhaustion.",
            "Provider/model context windows and OS limits still apply and will be shown as effective caps.",
            "Security invariants (terminal jail, shell=False, network block semantics) remain immutable.",
        ],
    },
    "custom": {
        "label": "Custom",
        "description": "No preset values — every underlying setting is exposed for manual control.",
        "values": {},
    },
}


def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": value["label"],
            "description": value["description"],
            "values": dict(value.get("values") or {}),
            "warnings": list(value.get("warnings") or []),
        }
        for key, value in PRESETS.items()
    ]


def preset_values(preset_id: str) -> dict[str, Any]:
    preset = PRESETS.get(preset_id)
    if not preset:
        raise KeyError(f"unknown preset: {preset_id}")
    return dict(preset.get("values") or {})
