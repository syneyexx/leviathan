"""Core HADES setting definitions. Defaults preserve pre-migration behavior."""

from __future__ import annotations

from typing import Any

from .registry import SettingRegistry
from .types import SettingDefinition, SettingScope, SettingType


def _ni(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: Any,
    *,
    allow_unlimited: bool = False,
    min_v: float | int | None = None,
    max_v: float | int | None = None,
    risk: str = "low",
    apply: str = "immediate",
    scopes: list[SettingScope] | None = None,
    unit: str = "",
    tags: list[str] | None = None,
    legacy: list[str] | None = None,
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    stype = SettingType.NULLABLE_INTEGER if allow_unlimited else SettingType.INTEGER
    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=stype,
        default_value=default,
        allow_unlimited=allow_unlimited,
        min=min_v,
        max=max_v,
        scopes=scopes or [SettingScope.GLOBAL, SettingScope.PROJECT, SettingScope.AGENT_TYPE, SettingScope.AGENT, SettingScope.TASK],
        apply_mode=ApplyMode(apply),
        risk_level=RiskLevel(risk),
        unit=unit,
        tags=tags or [],
        legacy_keys=legacy or [],
        implemented=implemented,
    )


def _fl(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: float,
    *,
    min_v: float | None = None,
    max_v: float | None = None,
    risk: str = "low",
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=SettingType.FLOAT,
        default_value=default,
        min=min_v,
        max=max_v,
        scopes=[SettingScope.GLOBAL, SettingScope.PROJECT, SettingScope.AGENT],
        apply_mode=ApplyMode.IMMEDIATE,
        risk_level=RiskLevel(risk),
        implemented=implemented,
    )


def _bool(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: bool,
    *,
    risk: str = "low",
    apply: str = "immediate",
    legacy: list[str] | None = None,
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=SettingType.BOOLEAN,
        default_value=default,
        scopes=[SettingScope.GLOBAL, SettingScope.PROJECT, SettingScope.AGENT_TYPE, SettingScope.AGENT, SettingScope.TASK],
        apply_mode=ApplyMode(apply),
        risk_level=RiskLevel(risk),
        legacy_keys=legacy or [],
        implemented=implemented,
    )


def _enum(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: str,
    values: list[str],
    *,
    risk: str = "medium",
    apply: str = "next_task",
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=SettingType.ENUM,
        default_value=default,
        enum_values=values,
        scopes=[SettingScope.GLOBAL, SettingScope.PROJECT, SettingScope.AGENT],
        apply_mode=ApplyMode(apply),
        risk_level=RiskLevel(risk),
        implemented=implemented,
    )


def _str(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: str,
    *,
    risk: str = "low",
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=SettingType.STRING,
        default_value=default,
        scopes=[SettingScope.GLOBAL],
        apply_mode=ApplyMode.IMMEDIATE,
        risk_level=RiskLevel(risk),
        implemented=implemented,
    )


def _list(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: list[Any] | None = None,
    *,
    risk: str = "medium",
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=SettingType.STRING_LIST,
        default_value=list(default or []),
        scopes=[SettingScope.GLOBAL, SettingScope.PROJECT, SettingScope.AGENT],
        apply_mode=ApplyMode.IMMEDIATE,
        risk_level=RiskLevel(risk),
        implemented=implemented,
    )


def _obj(
    setting_id: str,
    storage_key: str,
    category: str,
    label: str,
    description: str,
    default: dict[str, Any] | None = None,
    *,
    risk: str = "medium",
    implemented: bool | None = None,
) -> SettingDefinition:
    from .types import ApplyMode, RiskLevel

    return SettingDefinition(
        id=setting_id,
        storage_key=storage_key,
        category=category,
        label=label,
        description=description,
        type=SettingType.OBJECT,
        default_value=dict(default or {}),
        scopes=[SettingScope.GLOBAL, SettingScope.PROJECT, SettingScope.AGENT],
        apply_mode=ApplyMode.NEXT_TASK,
        risk_level=RiskLevel(risk),
        implemented=implemented,
    )


def build_core_definitions() -> list[SettingDefinition]:
    """All HADES-owned setting definitions. Defaults preserve pre-migration behavior."""
    d: list[SettingDefinition] = []

    # ── Legacy / general (existing DEFAULT_SETTINGS) ─────────────────────────
    d += [
        _str("models.lm_studio_base_url", "lm_studio_base_url", "model", "LM Studio base URL", "OpenAI-compatible base URL for local inference.", "http://127.0.0.1:1234/v1"),
        _str("models.lm_studio_api_key", "lm_studio_api_key", "model", "LM Studio API key", "API key sent to LM Studio (local).", "lm-studio", risk="critical"),
        _ni("models.request_timeout_seconds", "request_timeout_seconds", "model", "Request timeout", "HTTP timeout for model requests.", 120, min_v=1, unit="s", risk="medium"),
        _ni("models.model_refresh_seconds", "model_refresh_seconds", "model", "Model list refresh", "How often to refresh the model catalogue.", 60, min_v=5, unit="s"),
        _bool("models.streaming", "streaming", "model", "Streaming", "Enable token streaming when supported.", True),
        _bool("models.auto_connect", "auto_connect", "model", "Auto-connect", "Connect to LM Studio on startup.", True),
        _enum("ui.language", "language", "logging", "Language", "UI language.", "nl", ["nl", "en"], risk="low", apply="immediate"),
        _enum("ui.theme", "theme", "logging", "Theme", "UI theme.", "light", ["light", "dark", "system"], risk="low", apply="immediate"),
        _enum("ui.style", "ui_style", "logging", "UI style", "HADES Lux Atelier is the default product shell. FINALBETA is an optional Phase 1 visual variant. Legacy values are accepted and coerced to lux in the UI provider.", "lux", ["lux", "finalbeta", "classic", "obsidian", "beta", "beta2"], risk="low", apply="immediate"),
        _enum("ui.motion_level", "motion_level", "logging", "Motion level", "UI motion intensity; system reduced-motion still wins.", "standard", ["reduced", "standard", "cinematic"], risk="low", apply="immediate"),
        _enum("runtime.native_mode", "native_runtime_mode", "resources", "Native runtime mode", "Requested native companion mode.", "auto", ["auto", "enabled", "disabled"], risk="low", apply="immediate"),
        _str("agents.system_prompt", "system_prompt", "reasoning", "System prompt", "Global system prompt injected into chats.", "Je bent HADES, een scherpe lokale AI-assistent. Antwoord standaard in het Nederlands, wees feitelijk, gebruik beschikbare HADES-tools wanneer ze de taak aantoonbaar verbeteren en benoem onzekerheid duidelijk.", risk="medium"),
        _enum("agents.reasoning_profile", "reasoning_profile", "reasoning", "Reasoning mode", "Product reasoning mode (Normal/Medium/High/Adaptive). Legacy fast/standard map to product ids; maximum stays stored until the user picks a product mode.", "adaptive", ["normal", "medium", "high", "adaptive", "maximum"]),
        _bool("agents.conversation_learning", "conversation_learning", "memory", "Conversation learning", "Learn durable facts from conversations.", True),
        _enum("memory.auto_memory_mode", "auto_memory_mode", "memory", "Auto memory mode", "When to auto-write memories.", "project", ["off", "project", "all"]),
        _bool("memory.auto_promote", "memory_auto_promote", "memory", "Auto-promote memories", "Promote session memories to project/global.", False),
        _enum("memory.default_scope", "memory_default_scope", "memory", "Default memory scope", "Default scope for new memories.", "project", ["session", "project", "global"]),
        _bool("progress.events_enabled", "progress_events_enabled", "logging", "Progress events", "Emit live progress/SSE events.", True),
        _bool("progress.stream_provisional_text", "stream_provisional_text", "logging", "Provisional text streaming", "Stream provisional assistant text.", True),
        _str("ui.onboarding_completed_at", "onboarding_completed_at", "logging", "Onboarding completed at", "Timestamp when onboarding finished.", ""),
    ]

    # ── Agent execution ─────────────────────────────────────────────────────
    d += [
        _ni("agents.execution.max_concurrent_tasks", "max_concurrent_tasks", "agent_execution", "Max concurrent tasks", "TaskRunner worker concurrency.", 2, allow_unlimited=True, min_v=1, risk="high", unit="tasks", legacy=["max_concurrent_tasks"]),
        _ni("agents.execution.max_model_calls_per_task", "max_model_calls_per_task", "agent_execution", "Max model calls per task", "Ceiling on model invocations within one task.", 24, allow_unlimited=True, min_v=1, risk="high", unit="calls"),
        _ni("agents.execution.max_specialist_steps", "max_specialist_steps", "agent_execution", "Max specialist steps", "Ceiling on specialist agent steps.", 32, allow_unlimited=True, min_v=1, risk="high"),
        _ni("agents.execution.max_subtasks", "max_subtasks", "agent_execution", "Max subtasks", "Maximum planned subtasks / work steps.", 8, allow_unlimited=True, min_v=1, risk="high"),
        _ni("agents.execution.max_dependency_depth", "max_dependency_depth", "agent_execution", "Max dependency depth", "Maximum plan dependency graph depth.", 6, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("agents.execution.max_parallel_steps", "max_parallel_steps", "agent_execution", "Max parallel steps", "Parallel work-step wave size.", 2, allow_unlimited=True, min_v=1, risk="high"),
        _ni("agents.execution.max_model_concurrency", "max_model_concurrency", "agent_execution", "Max model concurrency", "Parallel in-flight model calls.", 1, allow_unlimited=True, min_v=1, risk="high"),
        _ni("agents.execution.max_repair_attempts", "max_repair_attempts", "agent_execution", "Max repair attempts", "Verification/repair loop attempts.", 2, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("agents.execution.work_plan_max_steps", "work_plan_max_steps", "agent_execution", "Work plan max steps", "Hard ceiling used by the work planner when generating steps.", 8, allow_unlimited=True, min_v=1, risk="high"),
        _ni("agents.execution.max_consecutive_failures", "max_consecutive_failures", "agent_execution", "Max consecutive failures", "Stop after this many consecutive failures.", 5, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("agents.execution.task_timeout_seconds", "task_timeout_seconds", "agent_execution", "Task timeout", "Maximum wall-clock runtime for a task.", None, allow_unlimited=True, min_v=1, risk="high", unit="s"),
        _ni("agents.execution.idle_timeout_seconds", "idle_timeout_seconds", "agent_execution", "Idle timeout", "Cancel if no progress for this long.", None, allow_unlimited=True, min_v=1, risk="medium", unit="s"),
        _ni("agents.execution.graceful_shutdown_timeout_seconds", "graceful_shutdown_timeout_seconds", "agent_execution", "Graceful shutdown timeout", "Wait for workers on shutdown.", 2, min_v=1, unit="s"),
        _ni("agents.execution.checkpoint_interval_seconds", "checkpoint_interval_seconds", "agent_execution", "Checkpoint interval", "How often to persist checkpoints during long work.", 30, min_v=1, unit="s"),
        _ni("agents.execution.progress_queue_timeout_seconds", "progress_queue_timeout_seconds", "agent_execution", "Progress queue timeout", "SSE/progress queue idle wait.", 25, min_v=1, unit="s"),
        _bool("agents.execution.loop_detection", "loop_detection_enabled", "agent_execution", "Loop detection", "Detect stagnating/repeating agent loops.", True, risk="medium"),
        _ni("agents.execution.loop_threshold", "loop_detection_threshold", "agent_execution", "Loop detection threshold", "Identical-state repeats before stop.", 3, allow_unlimited=True, min_v=1, risk="medium"),
        _bool("agents.execution.automatic_recovery", "automatic_recovery", "agent_execution", "Automatic recovery", "Attempt recovery after recoverable failures.", True, risk="medium"),
        _ni("agents.execution.retry_count", "execution_retry_count", "agent_execution", "Execution retry count", "Retries for failed steps.", 2, allow_unlimited=True, min_v=0, risk="medium"),
        _fl("agents.execution.retry_backoff_seconds", "execution_retry_backoff_seconds", "agent_execution", "Retry backoff", "Base backoff between retries.", 1.0, min_v=0.0),
        _enum("agents.execution.retry_strategy", "execution_retry_strategy", "agent_execution", "Retry strategy", "Backoff strategy.", "exponential", ["fixed", "exponential", "linear"]),
        _bool("agents.execution.retry_jitter", "execution_retry_jitter", "agent_execution", "Retry jitter", "Add jitter to retry backoff.", True),
    ]

    # ── Agent autonomy ──────────────────────────────────────────────────────
    d += [
        _enum("agents.autonomy.level", "autonomy_level", "agent_autonomy", "Autonomy level", "Preset autonomy profile (resolves to underlying settings).", "balanced", ["restricted", "balanced", "autonomous", "maximum", "custom"]),
        _enum("agents.autonomy.confirmation_policy", "confirmation_policy", "agent_autonomy", "Confirmation policy", "When to require user confirmation.", "destructive_only", ["always", "destructive_only", "never"], risk="high"),
        _bool("agents.autonomy.automatic_planning", "automatic_planning", "agent_autonomy", "Automatic planning", "Create plans without confirmation.", True),
        _bool("agents.autonomy.automatic_execution", "automatic_execution", "agent_autonomy", "Automatic execution", "Execute plans without confirmation.", False, risk="high"),
        _bool("agents.autonomy.automatic_retries", "automatic_retries", "agent_autonomy", "Automatic retries", "Retry failed steps automatically.", True),
        _bool("agents.autonomy.automatic_delegation", "automatic_delegation", "agent_autonomy", "Automatic delegation", "Allow spawning sub-agents without confirmation.", False, risk="high"),
        _bool("agents.autonomy.automatic_tool_invocation", "plugin_autonomous_tools", "agent_autonomy", "Automatic tool invocation", "Allow autonomous plugin/tool calls.", True, risk="high", legacy=["plugin_autonomous_tools"]),
        _enum("agents.autonomy.destructive_actions_policy", "destructive_actions_policy", "agent_autonomy", "Destructive actions policy", "Policy for destructive filesystem/network actions.", "ask", ["allow", "ask", "block"], risk="critical", implemented=False),
        _enum("agents.autonomy.external_side_effect_policy", "external_side_effect_policy", "agent_autonomy", "External side-effect policy", "Policy for actions that affect the outside world.", "ask", ["allow", "ask", "block"], risk="critical", implemented=False),
    ]

    # Policies (existing)
    d += [
        _enum("filesystem.read_policy", "file_read_policy", "filesystem", "File read policy", "Permission for reading files.", "allow", ["allow", "ask", "block"], risk="high"),
        _enum("filesystem.write_policy", "file_write_policy", "filesystem", "File write policy", "Permission for writing files.", "ask", ["allow", "ask", "block"], risk="critical"),
        _enum("network.policy", "network_policy", "network", "Network policy", "Outbound network permission.", "block", ["allow", "ask", "block"], risk="critical"),
        _enum("terminal.subprocess_policy", "subprocess_policy", "terminal", "Subprocess policy", "Permission for spawning subprocesses.", "allow", ["allow", "ask", "block"], risk="critical"),
    ]

    # ── Delegation ──────────────────────────────────────────────────────────
    d += [
        _bool("agents.delegation.enabled", "subagents_enabled", "agent_delegation", "Enable sub-agents", "Allow delegation to sub-agents.", True, risk="high"),
        _ni("agents.delegation.max_subagents", "max_subagents", "agent_delegation", "Max sub-agents", "Maximum sub-agents per parent.", 4, allow_unlimited=True, min_v=0, risk="high"),
        _ni("agents.delegation.max_active_subagents", "max_active_subagents", "agent_delegation", "Max active sub-agents", "Concurrent sub-agent ceiling.", 2, allow_unlimited=True, min_v=0, risk="high"),
        _ni("agents.delegation.max_depth", "max_delegation_depth", "agent_delegation", "Max delegation depth", "Recursive delegation depth.", 3, allow_unlimited=True, min_v=0, risk="high"),
        _bool("agents.delegation.recursive", "recursive_delegation", "agent_delegation", "Recursive delegation", "Allow children to delegate further.", False, risk="high"),
        _ni("agents.delegation.timeout_seconds", "delegation_timeout_seconds", "agent_delegation", "Delegation timeout", "Timeout for a delegated child.", None, allow_unlimited=True, min_v=1, unit="s", risk="medium", implemented=False),
        _ni("agents.delegation.child_budget_model_calls", "child_agent_budget_model_calls", "agent_delegation", "Child model-call budget", "Model-call budget inherited by children.", 12, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("agents.delegation.child_context_chars", "child_agent_context_chars", "agent_delegation", "Child context size", "Context char budget for child agents.", 40_000, allow_unlimited=True, min_v=1000, risk="medium"),
    ]

    # ── Tool use ────────────────────────────────────────────────────────────
    d += [
        _ni("tools.max_rounds", "max_tool_rounds", "tool_use", "Max tool rounds", "Maximum tool-calling rounds per chat/work turn.", 3, allow_unlimited=True, min_v=0, risk="high", legacy=["max_tool_rounds"]),
        _ni("tools.max_calls", "max_tool_calls", "tool_use", "Max tool calls", "Absolute tool invocation ceiling (shared pool).", 200, allow_unlimited=True, min_v=0, risk="high"),
        _ni("tools.max_calls_per_iteration", "max_tool_calls_per_iteration", "tool_use", "Max tool calls per iteration", "Parallel/serial tools allowed in one model turn.", 8, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("tools.max_parallel", "max_parallel_tool_calls", "tool_use", "Max parallel tool calls", "Concurrent tool executions.", 4, allow_unlimited=True, min_v=1, risk="high"),
        _ni("tools.timeout_seconds", "tool_timeout_seconds", "tool_use", "Tool timeout", "Default timeout for a single tool call.", 120, allow_unlimited=True, min_v=1, unit="s", risk="medium", implemented=False),
        _ni("tools.retries", "tool_retries", "tool_use", "Tool retries", "Retries for transient tool failures.", 1, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("tools.result_max_chars", "tool_result_max_chars", "tool_use", "Tool result max chars", "Truncate tool stdout/stderr fed back to the model.", 30_000, allow_unlimited=True, min_v=500, risk="medium", unit="chars"),
        _ni("tools.shortlist_limit", "plugin_shortlist_limit", "tool_use", "First-party tool kernel size", "Max first-party HADES tools offered to the model (plugins/MCP are broker capabilities, not permanent schemas). Hard-capped at 12 in code.", 12, allow_unlimited=True, min_v=1, risk="low"),
        _ni("tools.shortlist_default_limit", "plugin_shortlist_default_limit", "tool_use", "Capability search page", "Default hades.capabilities.search page size.", 5, allow_unlimited=True, min_v=1),
        _ni("tools.discover_page_limit", "plugin_discover_page_limit", "tool_use", "Discover tools page limit", "Built-in discover_tools page size.", 8, allow_unlimited=True, min_v=1),
        _ni("tools.discover_schema_max", "plugin_discover_schema_max", "tool_use", "Discover schema max", "Max tool schemas returned by discovery.", 20, allow_unlimited=True, min_v=1),
        _bool("tools.identical_call_loop_protection", "identical_tool_call_loop_protection", "tool_use", "Identical call loop protection", "Block repeated identical tool calls.", True, risk="medium"),
        _ni("tools.identical_call_threshold", "identical_tool_call_threshold", "tool_use", "Identical call threshold", "Repeats before loop protection trips.", 3, allow_unlimited=True, min_v=1),
        _list("tools.allowed", "allowed_tools", "tool_use", "Allowed tools", "Allowlist of tool names (empty = all eligible).", [], risk="high"),
        _list("tools.denied", "denied_tools", "tool_use", "Denied tools", "Denylist of tool names.", [], risk="high"),
    ]

    # ── Reasoning / profiles ────────────────────────────────────────────────
    d += [
        _ni("reasoning.profiles.fast.retrieval_limit", "profile_fast_retrieval_limit", "reasoning", "Fast: retrieval limit", "Retrieval hits for fast profile.", 4, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.fast.max_tool_rounds", "profile_fast_max_tool_rounds", "reasoning", "Fast: max tool rounds", "Tool rounds for fast profile.", 1, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.fast.max_replans", "profile_fast_max_replans", "reasoning", "Fast: max replans", "Replans for fast profile.", 0, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.fast.max_model_calls", "profile_fast_max_model_calls", "reasoning", "Fast: max model calls", "Model calls for fast profile.", 2, allow_unlimited=True, min_v=1),
        _ni("reasoning.profiles.fast.context_chars", "profile_fast_context_chars", "reasoning", "Fast: context chars", "Context budget for fast profile.", 24_000, allow_unlimited=True, min_v=1000),
        _ni("reasoning.profiles.fast.min_max_tokens", "profile_fast_min_max_tokens", "reasoning", "Fast: min max_tokens", "Minimum max_tokens for fast profile.", 1024, min_v=64, unit="tokens"),
        _bool("reasoning.profiles.fast.verify", "profile_fast_verify", "reasoning", "Fast: verify", "Require verification for fast profile.", False),
        _bool("reasoning.profiles.fast.require_plan", "profile_fast_require_plan", "reasoning", "Fast: require plan", "Require planning for fast profile.", False),
        _bool("reasoning.profiles.fast.allow_specialists", "profile_fast_allow_specialists", "reasoning", "Fast: allow specialists", "Allow specialists for fast profile.", False),
        _ni("reasoning.profiles.standard.retrieval_limit", "profile_standard_retrieval_limit", "reasoning", "Standard: retrieval limit", "Retrieval hits for standard profile.", 8, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.standard.max_tool_rounds", "profile_standard_max_tool_rounds", "reasoning", "Standard: max tool rounds", "Tool rounds for standard profile.", 3, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.standard.max_replans", "profile_standard_max_replans", "reasoning", "Standard: max replans", "Replans for standard profile.", 1, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.standard.max_model_calls", "profile_standard_max_model_calls", "reasoning", "Standard: max model calls", "Model calls for standard profile.", 6, allow_unlimited=True, min_v=1),
        _ni("reasoning.profiles.standard.context_chars", "profile_standard_context_chars", "reasoning", "Standard: context chars", "Context budget for standard profile.", 55_000, allow_unlimited=True, min_v=1000),
        _ni("reasoning.profiles.standard.min_max_tokens", "profile_standard_min_max_tokens", "reasoning", "Standard: min max_tokens", "Minimum max_tokens for standard profile.", 2048, min_v=64, unit="tokens"),
        _bool("reasoning.profiles.standard.verify", "profile_standard_verify", "reasoning", "Standard: verify", "Require verification for standard profile.", False),
        _bool("reasoning.profiles.standard.require_plan", "profile_standard_require_plan", "reasoning", "Standard: require plan", "Require planning for standard profile.", False),
        _bool("reasoning.profiles.standard.allow_specialists", "profile_standard_allow_specialists", "reasoning", "Standard: allow specialists", "Allow specialists for standard profile.", False),
        _ni("reasoning.profiles.high.retrieval_limit", "profile_high_retrieval_limit", "reasoning", "High: retrieval limit", "Retrieval hits for high profile.", 12, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.high.max_tool_rounds", "profile_high_max_tool_rounds", "reasoning", "High: max tool rounds", "Tool rounds for high profile.", 5, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.high.max_replans", "profile_high_max_replans", "reasoning", "High: max replans", "Replans for high profile.", 2, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.high.max_model_calls", "profile_high_max_model_calls", "reasoning", "High: max model calls", "Model calls for high profile.", 12, allow_unlimited=True, min_v=1),
        _ni("reasoning.profiles.high.context_chars", "profile_high_context_chars", "reasoning", "High: context chars", "Context budget for high profile.", 80_000, allow_unlimited=True, min_v=1000),
        _ni("reasoning.profiles.high.min_max_tokens", "profile_high_min_max_tokens", "reasoning", "High: min max_tokens", "Minimum max_tokens for high profile.", 4096, min_v=64, unit="tokens"),
        _bool("reasoning.profiles.high.verify", "profile_high_verify", "reasoning", "High: verify", "Require verification for high profile.", True),
        _bool("reasoning.profiles.high.require_plan", "profile_high_require_plan", "reasoning", "High: require plan", "Require planning for high profile.", True),
        _bool("reasoning.profiles.high.allow_specialists", "profile_high_allow_specialists", "reasoning", "High: allow specialists", "Allow specialists for high profile.", True),
        _ni("reasoning.profiles.maximum.retrieval_limit", "profile_maximum_retrieval_limit", "reasoning", "Maximum: retrieval limit", "Retrieval hits for maximum profile.", 16, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.maximum.max_tool_rounds", "profile_maximum_max_tool_rounds", "reasoning", "Maximum: max tool rounds", "Tool rounds for maximum profile.", 8, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.maximum.max_replans", "profile_maximum_max_replans", "reasoning", "Maximum: max replans", "Replans for maximum profile.", 3, allow_unlimited=True, min_v=0),
        _ni("reasoning.profiles.maximum.max_model_calls", "profile_maximum_max_model_calls", "reasoning", "Maximum: max model calls", "Model calls for maximum profile.", 20, allow_unlimited=True, min_v=1),
        _ni("reasoning.profiles.maximum.context_chars", "profile_maximum_context_chars", "reasoning", "Maximum: context chars", "Context budget for maximum profile.", 110_000, allow_unlimited=True, min_v=1000),
        _ni("reasoning.profiles.maximum.min_max_tokens", "profile_maximum_min_max_tokens", "reasoning", "Maximum: min max_tokens", "Minimum max_tokens for maximum profile.", 6144, min_v=64, unit="tokens"),
        _bool("reasoning.profiles.maximum.verify", "profile_maximum_verify", "reasoning", "Maximum: verify", "Require verification for maximum profile.", True),
        _bool("reasoning.profiles.maximum.require_plan", "profile_maximum_require_plan", "reasoning", "Maximum: require plan", "Require planning for maximum profile.", True),
        _bool("reasoning.profiles.maximum.allow_specialists", "profile_maximum_allow_specialists", "reasoning", "Maximum: allow specialists", "Allow specialists for maximum profile.", True),
        _ni("reasoning.default_context_chars", "default_context_chars", "reasoning", "Default context chars", "Fallback context budget when profile missing.", 55_000, allow_unlimited=True, min_v=1000),
        _ni("reasoning.verification_passes", "verification_passes", "reasoning", "Verification passes", "Independent verification passes.", 1, allow_unlimited=True, min_v=0, implemented=False),
        _ni("reasoning.critic_passes", "critic_passes", "reasoning", "Critic passes", "Critic/review passes.", 1, allow_unlimited=True, min_v=0, implemented=False),
        _ni("reasoning.solution_candidates", "solution_candidates", "reasoning", "Solution candidates", "Number of solution candidates to consider.", 1, allow_unlimited=True, min_v=1),
        _fl("reasoning.confidence_threshold", "confidence_threshold", "reasoning", "Confidence threshold", "Minimum confidence before accepting an answer.", 0.55, min_v=0.0, max_v=1.0),
        _bool("reasoning.evidence_requirement", "evidence_requirement", "reasoning", "Evidence requirement", "Require evidence refs for factual claims when available.", False),
        _bool("reasoning.contradiction_checking", "contradiction_checking", "reasoning", "Contradiction checking", "Check retrieved sources for contradictions.", True),
    ]

    # ── Model routing ───────────────────────────────────────────────────────
    d += [
        _ni("models.unavailable_after_errors", "model_unavailable_after_errors", "model", "Unavailable after errors", "Circuit-breaker: mark model unavailable after N errors.", 3, allow_unlimited=True, min_v=1, risk="medium"),
        _bool("models.allow_cloud_fallback", "allow_cloud_model_fallback", "model", "Allow cloud model fallback", "Permit cloud fallback when configured.", False, risk="critical"),
        _list("models.fallback_order", "model_fallback_order", "model", "Model fallback order", "Ordered fallback model IDs.", []),
        _obj("models.role_overrides", "role_model_overrides", "model", "Role model overrides", "Map of role → model_id overrides.", {}),
    ]

    # ── Context management ──────────────────────────────────────────────────
    d += [
        _ni("context.max_retrieval_items", "max_retrieval_items", "context", "Max retrieval items", "Maximum packed retrieval hits.", 8, allow_unlimited=True, min_v=1, legacy=["max_retrieval_items"]),
        _ni("context.max_retrieval_chars", "max_retrieval_chars", "context", "Max retrieval chars", "Total retrieval character budget.", 6000, allow_unlimited=True, min_v=100, unit="chars"),
        _ni("context.max_retrieval_chars_per_hit", "max_retrieval_chars_per_hit", "context", "Max chars per retrieval hit", "Per-hit character budget.", 1200, allow_unlimited=True, min_v=50, unit="chars"),
        _ni("context.reserve_output_tokens", "context_reserve_output_tokens", "context", "Reserve output tokens", "Tokens reserved for the model response.", 1024, min_v=64, unit="tokens"),
        _ni("context.reserve_protocol_tokens", "context_reserve_protocol_tokens", "context", "Reserve protocol tokens", "Tokens reserved for protocol overhead.", 512, min_v=0, unit="tokens"),
        _ni("context.usable_floor_chars", "context_usable_floor_chars", "context", "Usable floor chars", "Minimum usable context before emergency trim.", 1000, min_v=100, unit="chars"),
        _ni("context.emergency_system_clip_chars", "context_emergency_system_clip_chars", "context", "Emergency system clip", "Clip system prompt during emergency trim.", 800, min_v=100, unit="chars"),
        _ni("context.emergency_history_body_chars", "context_emergency_history_body_chars", "context", "Emergency history body clip", "Clip history bodies during emergency trim.", 360, min_v=50, unit="chars"),
        _ni("context.work_context_max_chars", "work_context_max_chars", "context", "Work context max chars", "Context clip for work planner prompts.", 30_000, allow_unlimited=True, min_v=1000, unit="chars"),
        _ni("context.work_step_context_max_chars", "work_step_context_max_chars", "context", "Work step context max chars", "Context clip for work step prompts.", 35_000, allow_unlimited=True, min_v=1000, unit="chars"),
        _ni("context.prior_step_count", "prior_step_context_count", "context", "Prior step context count", "How many prior step outputs to include.", 4, allow_unlimited=True, min_v=0),
        _ni("context.prior_step_chars", "prior_step_context_chars", "context", "Prior step context chars", "Chars per prior step output.", 12_000, allow_unlimited=True, min_v=500, unit="chars"),
        _ni("context.attachment_preview_chars", "attachment_preview_chars", "context", "Attachment preview chars", "Chars of attachment text injected into chat.", 8_000, allow_unlimited=True, min_v=100, unit="chars"),
        _ni("context.max_attachments", "max_attachments", "context", "Max attachments", "Attachments per chat message.", 10, allow_unlimited=True, min_v=0),
        _ni("context.indexed_files_limit", "retrieval_indexed_files_limit", "context", "Indexed files retrieval limit", "Workspace file hits in retrieval.", 80, allow_unlimited=True, min_v=1),
        _bool("context.preserve_system_instructions", "context_preserve_system", "context", "Preserve system instructions", "Never drop system instructions during compaction.", True),
        _bool("context.preserve_recent_messages", "context_preserve_recent", "context", "Preserve recent messages", "Prefer dropping older history first.", True),
        _enum("context.truncation_strategy", "context_truncation_strategy", "context", "Truncation strategy", "How to drop context under pressure.", "oldest_first", ["oldest_first", "relevance_first", "middle_out"]),
        _fl("retrieval.lexical_weight", "retrieval_lexical_weight", "context", "Lexical weight", "Hybrid retrieval lexical weight.", 0.55, min_v=0.0, max_v=1.0),
        _fl("retrieval.semantic_weight", "retrieval_semantic_weight", "context", "Semantic weight", "Hybrid retrieval semantic weight.", 0.45, min_v=0.0, max_v=1.0),
        _bool("retrieval.multilingual_expand", "retrieval_multilingual_expand", "context", "Multilingual query expand", "Opt-in NL↔EN lexical query expansion for retrieval (default off).", False),
        _bool("retrieval.semantic_enabled", "enable_semantic_retrieval", "context", "Semantic retrieval", "Enable embedding-based retrieval when available.", False),
        _str("retrieval.embedding_model_id", "embedding_model_id", "context", "Embedding model", "Model ID used for embeddings.", ""),
        _bool("retrieval.context_compiler_chat", "enable_context_compiler_chat", "context", "Context Compiler in chat", "Compile retrieved context via Context Compiler on the chat path (new installs default on; explicit false is preserved).", True),
        _fl("retrieval.embedding_timeout_seconds", "embedding_timeout_seconds", "context", "Embedding timeout", "HTTP timeout for local embedding calls.", 30.0, min_v=1.0),
        _ni("retrieval.embedding_batch_size", "embedding_batch_size", "context", "Embedding batch size", "Max texts per local embeddings request.", 16, min_v=1),
        _ni("retrieval.diversity_window", "retrieval_diversity_window", "context", "Diversity window", "Diversity window for retrieval packing.", 3, allow_unlimited=True, min_v=1),
        _ni("retrieval.length_penalty_chars", "retrieval_length_penalty_chars", "context", "Length penalty chars", "Soft length penalty threshold during rerank.", 900, min_v=100, unit="chars"),
    ]

    # ── Memory ──────────────────────────────────────────────────────────────
    d += [
        _bool("memory.enabled", "memory_enabled", "memory", "Memory enabled", "Master switch for memory read/write.", True),
        _bool("memory.read_enabled", "memory_read_enabled", "memory", "Memory read enabled", "Allow retrieving memories into context.", True, implemented=False),
        _bool("memory.write_enabled", "memory_write_enabled", "memory", "Memory write enabled", "Allow writing new memories.", True),
        _ni("memory.max_retrieved", "memory_max_retrieved", "memory", "Max memories retrieved", "Maximum memories injected per turn.", 8, allow_unlimited=True, min_v=0),
        _fl("memory.similarity_threshold", "memory_similarity_threshold", "memory", "Similarity threshold", "Minimum similarity for memory hits.", 0.35, min_v=0.0, max_v=1.0),
        _ni("memory.working_state_item_limit", "memory_working_state_item_limit", "memory", "Working-state item limit", "Artifacts/constraints retained in working state.", 12, allow_unlimited=True, min_v=1),
        _ni("memory.injection_budget_chars", "memory_injection_budget_chars", "memory", "Memory injection budget", "Character budget for memory injection.", 4000, allow_unlimited=True, min_v=100, unit="chars"),
        _bool("memory.deduplication", "memory_deduplication", "memory", "Memory deduplication", "Deduplicate near-identical memories.", True),
    ]

    # ── Mentions ────────────────────────────────────────────────────────────
    d += [
        _ni("chat.mentions_memory_limit", "mentions_memory_limit", "context", "Mention memory limit", "@-mention memory results.", 40, allow_unlimited=True, min_v=1),
        _ni("chat.mentions_symbols_limit", "mentions_symbols_limit", "context", "Mention symbols limit", "@-mention symbol results.", 20, allow_unlimited=True, min_v=1),
        _ni("chat.mentions_workspaces_limit", "mentions_workspaces_limit", "context", "Mention workspaces limit", "@-mention workspace results.", 2, allow_unlimited=True, min_v=1),
        _ni("chat.mentions_projects_limit", "mentions_projects_limit", "context", "Mention projects limit", "@-mention project results.", 4, allow_unlimited=True, min_v=1),
        _ni("chat.mentions_tasks_limit", "mentions_tasks_limit", "context", "Mention tasks limit", "@-mention task results.", 40, allow_unlimited=True, min_v=1),
    ]

    # ── Search / research ───────────────────────────────────────────────────
    d += [
        _enum("research.default_depth", "research_default_depth", "search", "Default research depth", "Default depth for new research projects.", "deep", ["quick", "standard", "deep", "expert"]),
        _ni("research.max_questions", "research_max_questions", "search", "Max research questions", "Generated research questions ceiling.", 8, allow_unlimited=True, min_v=1),
        _bool("research.prefer_local", "research_prefer_local", "search", "Prefer local sources", "Prefer local knowledge before web.", True, implemented=False),
        _bool("research.auto_web", "auto_web_research", "search", "Auto web research", "Automatically refresh web evidence when allowed.", True, risk="high"),
        _ni("research.expert_mastery_target", "expert_mastery_target", "search", "Expert mastery target", "Mastery % target for expert research.", 90, min_v=1, max_v=100),
        _ni("research.expert_max_cycles", "expert_max_cycles", "search", "Expert max cycles", "Default research round budget for expert depth (overridable per project).", 6, allow_unlimited=True, min_v=1, risk="high"),
        _ni("research.expert_sources_per_cycle", "expert_sources_per_cycle", "search", "Expert sources per cycle", "Source scaling factor for expert mode.", 30, allow_unlimited=True, min_v=1),
        _ni("research.auto_web_discover", "auto_web_discover_count", "search", "Auto-web discover count", "DuckDuckGo results for auto web refresh.", 4, allow_unlimited=True, min_v=1),
        _ni("research.auto_web_ingest", "auto_web_ingest_count", "search", "Auto-web ingest count", "URLs ingested during auto web refresh.", 3, allow_unlimited=True, min_v=1),
        _ni("research.search_max_results", "research_search_max_results", "search", "Search max results", "Default DuckDuckGo result count.", 8, allow_unlimited=True, min_v=1),
        _ni("research.llm_max_tokens", "research_llm_max_tokens", "search", "Research LLM max tokens", "Token cap for research synthesis calls.", 2500, min_v=256, unit="tokens"),
        _ni("research.http_timeout_seconds", "research_http_timeout_seconds", "search", "Research HTTP timeout", "General web research HTTP timeout.", 30, min_v=1, unit="s"),
        _ni("research.robots_timeout_seconds", "research_robots_timeout_seconds", "search", "Robots.txt timeout", "Timeout for robots.txt fetch.", 10, min_v=1, unit="s"),
        _ni("research.ddg_timeout_seconds", "research_ddg_timeout_seconds", "search", "DuckDuckGo timeout", "Timeout for DDG discover.", 20, min_v=1, unit="s"),
        _ni("research.harvest_max_documents", "research_harvest_max_documents", "search", "Harvest max documents", "Default harvest document ceiling.", 40, allow_unlimited=True, min_v=1),
        _ni("research.harvest_max_pages", "research_harvest_max_pages", "search", "Harvest max pages", "Default harvest page ceiling.", 25, allow_unlimited=True, min_v=1),
        _ni("research.harvest_max_depth", "research_harvest_max_depth", "search", "Harvest max depth", "Default harvest crawl depth.", 2, allow_unlimited=True, min_v=0),
        _ni("research.harvest_clamp_documents", "research_harvest_clamp_documents", "search", "Harvest documents hard clamp", "Maximum allowed harvest documents from commands.", 100, allow_unlimited=True, min_v=1, risk="high"),
        _ni("research.harvest_clamp_pages", "research_harvest_clamp_pages", "search", "Harvest pages hard clamp", "Maximum allowed harvest pages from commands.", 80, allow_unlimited=True, min_v=1, risk="high"),
        _ni("research.harvest_clamp_depth", "research_harvest_clamp_depth", "search", "Harvest depth hard clamp", "Maximum allowed harvest depth from commands.", 4, allow_unlimited=True, min_v=0, risk="high"),
        _ni("research.crawl_max_pages", "research_crawl_max_pages", "search", "Crawl max pages", "Default site crawl page limit.", 10, allow_unlimited=True, min_v=1),
        _ni("research.crawl_max_depth", "research_crawl_max_depth", "search", "Crawl max depth", "Default site crawl depth.", 1, allow_unlimited=True, min_v=0),
        _ni("research.evidence_interim_limit", "research_evidence_interim_limit", "search", "Evidence interim limit", "Interim evidence packing limit.", 16, allow_unlimited=True, min_v=1),
        _ni("research.evidence_final_limit", "research_evidence_final_limit", "search", "Evidence final limit", "Final evidence packing limit.", 24, allow_unlimited=True, min_v=1),
        _ni("research.evidence_content_chars", "research_evidence_content_chars", "search", "Evidence content chars", "Chars per evidence snippet.", 4500, allow_unlimited=True, min_v=200, unit="chars"),
        _ni("research.evidence_source_limit", "research_evidence_source_limit", "search", "Evidence source limit", "Sources packed into synthesis.", 18, allow_unlimited=True, min_v=1),
        _obj("research.depth.quick", "research_depth_quick", "search", "Depth config: quick", "Research depth matrix for quick.", {"search_queries": 1, "urls_per_query": 3, "max_sources": 5, "rounds": 1, "crawl_pages": 2, "crawl_depth": 0}),
        _obj("research.depth.standard", "research_depth_standard", "search", "Depth config: standard", "Research depth matrix for standard.", {"search_queries": 2, "urls_per_query": 4, "max_sources": 10, "rounds": 1, "crawl_pages": 5, "crawl_depth": 1}),
        _obj("research.depth.deep", "research_depth_deep", "search", "Depth config: deep", "Research depth matrix for deep.", {"search_queries": 3, "urls_per_query": 5, "max_sources": 22, "rounds": 2, "crawl_pages": 10, "crawl_depth": 1}),
        _obj("research.depth.expert", "research_depth_expert", "search", "Depth config: expert", "Research depth matrix for expert.", {"search_queries": 8, "urls_per_query": 10, "max_sources": 180, "rounds": 18, "crawl_pages": 80, "crawl_depth": 3}),
        _ni("search.global_limit_per_type", "global_search_limit_per_type", "search", "Global search per-type limit", "Results per type in global search.", 8, allow_unlimited=True, min_v=1),
    ]

    # ── Filesystem ──────────────────────────────────────────────────────────
    d += [
        _ni("filesystem.max_text_bytes", "max_text_bytes", "filesystem", "Max text bytes", "Maximum text payload for knowledge ingest.", 40 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes", risk="high"),
        _ni("filesystem.max_archive_files", "max_archive_files", "filesystem", "Max archive files", "Maximum files extracted from an archive.", 20_000, allow_unlimited=True, min_v=1, risk="high"),
        _ni("filesystem.max_archive_bytes", "max_archive_bytes", "filesystem", "Max archive bytes", "Maximum extracted archive bytes.", 2 * 1024 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes", risk="high"),
        _ni("filesystem.max_plugin_upload_bytes", "max_plugin_upload_bytes", "filesystem", "Max plugin upload bytes", "Maximum plugin package upload size.", 256 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes", risk="high"),
        _ni("filesystem.max_download_bytes", "max_download_bytes", "filesystem", "Max download bytes", "Maximum fetched/uploaded document size.", 250 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes", risk="high"),
        _ni("filesystem.workspace_max_files", "workspace_max_files", "filesystem", "Workspace max files", "Maximum files scanned in a workspace ingest.", 5000, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("filesystem.detail_chunk_limit", "file_detail_chunk_limit", "filesystem", "File detail chunk limit", "Chunks returned in file detail view.", 40, allow_unlimited=True, min_v=1),
        _ni("filesystem.chat_max_upload_bytes", "chat_max_upload_bytes", "filesystem", "Chat upload max bytes", "Maximum chat attachment upload size.", 20 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes", risk="medium"),
        _ni("filesystem.artifacts_preview_chars", "artifacts_preview_max_chars", "filesystem", "Artifact preview chars", "Preview size for artifacts.", 20_000, allow_unlimited=True, min_v=100, unit="chars"),
        _ni("knowledge.chunk_target_chars", "knowledge_chunk_target_chars", "filesystem", "Knowledge chunk size", "Target characters per knowledge chunk.", 5000, min_v=200, unit="chars"),
        _ni("knowledge.chunk_overlap_chars", "knowledge_chunk_overlap_chars", "filesystem", "Knowledge chunk overlap", "Overlap between knowledge chunks.", 500, min_v=0, unit="chars"),
    ]

    # ── Code index ──────────────────────────────────────────────────────────
    d += [
        _ni("codeindex.max_files", "codeindex_max_files", "filesystem", "Code index max files", "Maximum files scanned for symbols.", 400, allow_unlimited=True, min_v=1),
        _ni("codeindex.max_file_bytes", "codeindex_max_file_bytes", "filesystem", "Code index max file bytes", "Skip files larger than this.", 400_000, allow_unlimited=True, min_v=1024, unit="bytes"),
        _ni("codeindex.symbols_per_file", "codeindex_symbols_per_file", "filesystem", "Symbols per file", "Max symbols extracted per file.", 80, allow_unlimited=True, min_v=1),
        _ni("codeindex.reference_max_files", "codeindex_reference_max_files", "filesystem", "Reference search max files", "Stop reference search after N files.", 400, allow_unlimited=True, min_v=1),
    ]

    # ── Terminal ────────────────────────────────────────────────────────────
    d += [
        _ni("terminal.timeout_seconds", "terminal_timeout_seconds", "terminal", "Terminal timeout", "Default command timeout.", 30, allow_unlimited=True, min_v=1, unit="s", risk="medium"),
        _ni("terminal.max_timeout_seconds", "terminal_max_timeout_seconds", "terminal", "Terminal max timeout", "Hard ceiling for terminal timeouts (None = no HADES ceiling).", 120, allow_unlimited=True, min_v=1, unit="s", risk="high"),
        _ni("terminal.output_max_chars", "terminal_output_max_chars", "terminal", "Terminal output max chars", "Stdout/stderr returned to caller.", 20_000, allow_unlimited=True, min_v=100, unit="chars"),
        _list("terminal.allowlist", "terminal_allowlist", "terminal", "Terminal allowlist", "Allowed binaries (empty = built-in default allowlist).", [], risk="critical"),
        _ni("terminal.max_commands", "terminal_max_commands", "terminal", "Max terminal commands", "Maximum terminal commands per task.", None, allow_unlimited=True, min_v=1, risk="high"),
        _ni("terminal.max_parallel", "terminal_max_parallel", "terminal", "Max parallel commands", "Concurrent terminal processes.", 1, allow_unlimited=True, min_v=1, risk="high"),
    ]

    # ── Network ─────────────────────────────────────────────────────────────
    d += [
        _ni("network.request_timeout_seconds", "network_request_timeout_seconds", "network", "Request timeout", "Default outbound HTTP timeout.", 30, min_v=1, unit="s"),
        _ni("network.connection_timeout_seconds", "network_connection_timeout_seconds", "network", "Connection timeout", "TCP connect timeout.", 10, min_v=1, unit="s"),
        _ni("network.max_requests", "network_max_requests", "network", "Max requests", "Maximum outbound requests per task.", None, allow_unlimited=True, min_v=1, risk="high"),
        _ni("network.concurrent_requests", "network_concurrent_requests", "network", "Concurrent requests", "Parallel outbound HTTP requests.", 4, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("network.retry_count", "network_retry_count", "network", "Network retries", "Retries for transient HTTP failures.", 2, allow_unlimited=True, min_v=0),
        _ni("network.redirect_limit", "network_redirect_limit", "network", "Redirect limit", "Maximum HTTP redirects.", 10, allow_unlimited=True, min_v=0, implemented=True),
        _list("network.allowed_protocols", "network_allowed_protocols", "network", "Allowed protocols", "Protocols permitted for outbound requests.", ["http", "https"], risk="high"),
        _list("network.domain_allowlist", "network_domain_allowlist", "network", "Domain allowlist", "If non-empty, only these domains are allowed.", [], risk="critical", implemented=True),
        _list("network.domain_denylist", "network_domain_denylist", "network", "Domain denylist", "Domains that are always blocked.", [], risk="critical", implemented=True),
    ]

    # ── Plugins ─────────────────────────────────────────────────────────────
    d += [
        _bool("plugins.auto_install_dependencies", "plugin_auto_install_dependencies", "plugins", "Auto-install dependencies", "Install plugin dependencies automatically when permitted.", True, risk="high"),
        _ni("plugins.install_git_clone_timeout_seconds", "plugin_git_clone_timeout_seconds", "plugins", "Git clone timeout", "Timeout for plugin git clone.", 180, min_v=1, unit="s"),
        _ni("plugins.install_git_fetch_timeout_seconds", "plugin_git_fetch_timeout_seconds", "plugins", "Git fetch timeout", "Timeout for plugin git fetch.", 120, min_v=1, unit="s"),
        _ni("plugins.install_pip_timeout_seconds", "plugin_pip_timeout_seconds", "plugins", "Pip install timeout", "Timeout for pip dependency installs.", 120, min_v=1, unit="s"),
        _ni("plugins.install_npm_timeout_seconds", "plugin_npm_timeout_seconds", "plugins", "Npm install timeout", "Timeout for npm dependency installs.", 600, min_v=1, unit="s"),
        _ni("plugins.invoke_timeout_seconds", "plugin_invoke_timeout_seconds", "plugins", "Plugin invoke timeout", "Default plugin tool invoke timeout.", 120, allow_unlimited=True, min_v=1, unit="s"),
        _ni("plugins.service_stop_timeout_seconds", "plugin_service_stop_timeout_seconds", "plugins", "Service stop timeout", "Wait for plugin service stop.", 8, min_v=1, unit="s"),
        _ni("plugins.healthcheck_timeout_seconds", "plugin_healthcheck_timeout_seconds", "plugins", "Healthcheck timeout", "Plugin healthcheck timeout.", 3, min_v=1, unit="s"),
        _ni("plugins.max_restarts", "plugin_max_restarts", "plugins", "Max plugin restarts", "Restart attempts for crashed plugin services.", 3, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("plugins.max_plugin_processes", "max_plugin_processes", "plugins", "Max plugin processes", "Shared pool ceiling for plugin processes.", 8, allow_unlimited=True, min_v=0, risk="high"),
        _ni("plugins.dependency_max_capture_chars", "plugin_dependency_max_capture_chars", "plugins", "Dependency capture chars", "Stdout/stderr capture for dependency installs.", 1_000_000, allow_unlimited=True, min_v=1000, unit="chars"),
        _ni("plugins.dependency_max_log_bytes", "plugin_dependency_max_log_bytes", "plugins", "Dependency log bytes", "On-disk dependency log size.", 2 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes"),
    ]

    # ── MCP ─────────────────────────────────────────────────────────────────
    d += [
        _bool("mcp.enabled", "mcp_enabled", "mcp", "MCP enabled", "Master switch for MCP integrations.", True, risk="high"),
        _ni("mcp.timeout_seconds", "mcp_timeout_seconds", "mcp", "MCP timeout", "Default MCP bridge/call timeout.", 90, allow_unlimited=True, min_v=1, unit="s"),
        _ni("mcp.max_tool_calls", "mcp_max_tool_calls", "mcp", "MCP max tool calls", "Ceiling on MCP tool calls per task.", None, allow_unlimited=True, min_v=0, risk="high"),
        _ni("mcp.max_connections", "mcp_max_connections", "mcp", "MCP max connections", "Maximum concurrent MCP server connections.", 8, allow_unlimited=True, min_v=1, risk="medium"),
        _ni("mcp.reconnect_attempts", "mcp_reconnect_attempts", "mcp", "MCP reconnect attempts", "Reconnect attempts for MCP servers.", 3, allow_unlimited=True, min_v=0),
        _list("mcp.allowed_tools", "mcp_allowed_tools", "mcp", "Allowed MCP tools", "Allowlist (empty = all registered).", [], risk="high"),
        _list("mcp.denied_tools", "mcp_denied_tools", "mcp", "Denied MCP tools", "Denylist of MCP tools.", [], risk="high"),
    ]

    # ── Concurrency / shared budget ─────────────────────────────────────────
    d += [
        _ni("runtime.shared_budget.max_active_tasks", "shared_budget_max_active_tasks", "concurrency", "Shared: max active tasks", "Process-wide active task ceiling.", 4, allow_unlimited=True, min_v=0, risk="high"),
        _ni("runtime.shared_budget.max_model_calls", "shared_budget_max_model_calls", "concurrency", "Shared: max model calls", "Process-wide model-call ceiling (None = derive from per-task).", None, allow_unlimited=True, min_v=0, risk="high"),
        _ni("runtime.shared_budget.model_calls_multiplier", "shared_budget_model_calls_multiplier", "concurrency", "Shared: model-calls multiplier", "When shared max is unset: per-task max × this multiplier.", 20, min_v=1, risk="medium"),
        _ni("runtime.shared_budget.max_tool_calls", "shared_budget_max_tool_calls", "concurrency", "Shared: max tool calls", "Process-wide tool-call ceiling.", 200, allow_unlimited=True, min_v=0, risk="high"),
        _ni("runtime.shared_budget.max_specialist_steps", "shared_budget_max_specialist_steps", "concurrency", "Shared: max specialist steps", "Process-wide specialist step ceiling.", 100, allow_unlimited=True, min_v=0, risk="high"),
        _ni("runtime.shared_budget.max_subtasks", "shared_budget_max_subtasks", "concurrency", "Shared: max subtasks", "Process-wide subtask ceiling.", 64, allow_unlimited=True, min_v=0, risk="high"),
        _ni("runtime.shared_budget.max_runtime_seconds", "shared_budget_max_runtime_seconds", "concurrency", "Shared: max runtime", "Process-wide runtime budget.", 3600, allow_unlimited=True, min_v=1, unit="s", risk="high"),
        _ni("runtime.event_buffer_maxlen", "event_buffer_maxlen", "concurrency", "Event buffer maxlen", "In-memory run-event buffer size.", 2000, allow_unlimited=True, min_v=10),
        _ni("runtime.event_subscriber_queue_size", "event_subscriber_queue_size", "concurrency", "Event subscriber queue", "Per-subscriber event queue size.", 256, allow_unlimited=True, min_v=8),
        _ni("runtime.scheduler_interval_seconds", "scheduler_interval_seconds", "concurrency", "Scheduler interval", "Background schedule poll interval.", 15, min_v=1, unit="s"),
    ]

    # ── Resources ───────────────────────────────────────────────────────────
    d += [
        _enum("resources.cpu_mode", "resource_cpu_mode", "resources", "CPU mode", "CPU budget mode.", "automatic", ["automatic", "unlimited", "custom"]),
        _enum("resources.ram_mode", "resource_ram_mode", "resources", "RAM mode", "RAM budget mode.", "automatic", ["automatic", "unlimited", "custom"]),
        _enum("resources.vram_mode", "resource_vram_mode", "resources", "VRAM mode", "VRAM budget mode.", "automatic", ["automatic", "unlimited", "custom"]),
        _ni("resources.custom_ram_mb", "resource_custom_ram_mb", "resources", "Custom RAM MB", "Custom RAM budget when mode=custom.", None, allow_unlimited=True, min_v=128, unit="MB"),
        _ni("resources.custom_vram_mb", "resource_custom_vram_mb", "resources", "Custom VRAM MB", "Custom VRAM budget when mode=custom.", None, allow_unlimited=True, min_v=128, unit="MB"),
        _ni("resources.max_concurrent_inference", "max_concurrent_inference", "resources", "Max concurrent inference", "Concurrent local inference jobs.", 1, allow_unlimited=True, min_v=1, risk="high"),
    ]

    # ── API / rate limits ───────────────────────────────────────────────────
    d += [
        _ni("api.requests_per_second", "api_requests_per_second", "api_rate", "Requests per second", "HADES-owned API rate limit (None = unlimited).", None, allow_unlimited=True, min_v=1),
        _ni("api.requests_per_minute", "api_requests_per_minute", "api_rate", "Requests per minute", "HADES-owned API rate limit (None = unlimited).", None, allow_unlimited=True, min_v=1),
        _ni("api.burst_size", "api_burst_size", "api_rate", "Burst size", "Token-bucket burst size.", None, allow_unlimited=True, min_v=1),
        _ni("api.concurrent_requests", "api_concurrent_requests", "api_rate", "Concurrent API requests", "Max in-flight API requests.", None, allow_unlimited=True, min_v=1),
    ]

    # ── Logging ─────────────────────────────────────────────────────────────
    d += [
        _enum("logging.level", "log_level", "logging", "Log level", "Application log level.", "info", ["debug", "info", "warning", "error"], risk="low"),
        _ni("logging.retention_days", "log_retention_days", "logging", "Log retention days", "Days to retain logs.", 30, allow_unlimited=True, min_v=1, implemented=True),
        _ni("logging.max_log_size_bytes", "max_log_size_bytes", "logging", "Max log size", "Maximum log file size before rotation.", 50 * 1024 * 1024, allow_unlimited=True, min_v=1024, unit="bytes"),
        _ni("logging.max_event_history", "max_event_history", "logging", "Max event history", "Persisted event history size.", 10_000, allow_unlimited=True, min_v=100),
        _ni("logging.agent_trace_depth", "agent_trace_depth", "logging", "Agent trace depth", "Depth of agent trace retention.", 50, allow_unlimited=True, min_v=1),
        _ni("logging.tool_trace_depth", "tool_trace_depth", "logging", "Tool trace depth", "Depth of tool trace retention.", 100, allow_unlimited=True, min_v=1),
        _bool("logging.model_request_logging", "model_request_logging", "logging", "Model request logging", "Log model request metadata (never secrets).", False, risk="medium"),
        _bool("logging.tool_io_logging", "tool_io_logging", "logging", "Tool I/O logging", "Log tool inputs/outputs (redacted).", False, risk="high"),
    ]

    # ── Approvals / build ───────────────────────────────────────────────────
    d += [
        _ni("approvals.default_ttl_seconds", "approvals_default_ttl_seconds", "agent_autonomy", "Approval TTL", "Default approval request lifetime.", 3600, min_v=60, unit="s"),
        _ni("approvals.extended_ttl_seconds", "approvals_extended_ttl_seconds", "agent_autonomy", "Extended approval TTL", "Extended approval lifetime.", 7200, min_v=60, unit="s"),
        _ni("build.max_repair_attempts", "build_max_repair_attempts", "agent_execution", "Build max repair attempts", "Coding/build agent repair waves.", 2, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("build.test_timeout_seconds", "build_test_timeout_seconds", "agent_execution", "Build test timeout", "Timeout for build-agent tests.", 180, min_v=1, unit="s"),
        # Coding investigate budgets (Control Plane; missing → investigator defaults)
        _ni("coding.investigate.max_actions", "coding_investigate_max_actions", "agent_execution", "Investigate max actions", "Ceiling on investigate actions per run.", 16, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("coding.investigate.max_reads", "coding_investigate_max_reads", "agent_execution", "Investigate max reads", "Ceiling on investigate file reads.", 10, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("coding.investigate.max_searches", "coding_investigate_max_searches", "agent_execution", "Investigate max searches", "Ceiling on investigate code searches.", 6, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("coding.investigate.max_tests", "coding_investigate_max_tests", "agent_execution", "Investigate max tests", "Ceiling on investigate test runs.", 3, allow_unlimited=True, min_v=0, risk="medium"),
        _ni("coding.investigate.max_steps", "coding_investigate_max_steps", "agent_execution", "Investigate max steps", "Ceiling on investigate loop steps.", 14, allow_unlimited=True, min_v=0, risk="medium"),
        _enum(
            "coding.autonomy.profile",
            "coding_autonomy_profile",
            "agent_execution",
            "Coding autonomy profile",
            "Analyze-only, managed worktree edits, or reviewable result. Does not grant publish/push/merge.",
            "reviewable_result",
            ["analyze_only", "managed_workspace_modify", "reviewable_result"],
            risk="high",
        ),
        _bool(
            "coding.omniroute.enabled_by_default",
            "coding_omniroute_enabled_by_default",
            "agent_execution",
            "Coding OmniRoute default",
            "Default the Coding OmniRoute toggle ON for new runs. The plugin must still be installed, enabled and Ready.",
            False,
            risk="medium",
        ),
        _bool(
            "coding.omniroute.allow_fallback",
            "coding_omniroute_allow_fallback",
            "agent_execution",
            "Coding OmniRoute fallback",
            "When OmniRoute is requested but cannot complete, fall back to the normal coding model.",
            True,
            risk="medium",
        ),
        _ni(
            "coding.omniroute.inventory_cache_ttl_seconds",
            "coding_omniroute_inventory_cache_ttl_seconds",
            "agent_execution",
            "OmniRoute inventory cache TTL",
            "Seconds to reuse OmniRoute list_routes discovery while healthy.",
            30,
            min_v=5,
            max_v=300,
            unit="s",
            risk="low",
        ),
        _ni(
            "coding.lm_timeout_seconds",
            "coding_lm_timeout_seconds",
            "agent_execution",
            "Coding LM timeout",
            "Bounded timeout for Coding model invocations (edit/repair/report).",
            180,
            min_v=30,
            max_v=900,
            unit="s",
            risk="medium",
        ),
        _ni(
            "coding.lm_max_tokens",
            "coding_lm_max_tokens",
            "agent_execution",
            "Coding LM max tokens",
            "Output token budget for Coding structured edit generation.",
            8192,
            min_v=1024,
            max_v=32768,
            risk="medium",
        ),
    ]

    # ── Trading (HADES-controlled windows) ──────────────────────────────────
    d += [
        _ni("trading.default_bars", "trading_default_bars", "resources", "Trading default bars", "Default OHLCV window.", 500, allow_unlimited=True, min_v=10),
        _ni("trading.discover_bars", "trading_discover_bars", "resources", "Trading discover bars", "Bars used during strategy discovery.", 5000, allow_unlimited=True, min_v=50),
        _ni("trading.dashboard_bars", "trading_dashboard_bars", "resources", "Trading dashboard bars", "Bars shown on dashboard.", 180, allow_unlimited=True, min_v=10),
        _ni("trading.min_bars", "trading_min_bars", "resources", "Trading min bars", "Reject strategies with fewer bars.", 50, min_v=10),
        _ni("trading.discover_top_n", "trading_discover_top_n", "resources", "Trading discover top-N", "Top strategies retained from discovery.", 5, allow_unlimited=True, min_v=1),
        _ni("trading.seed_bars", "trading_seed_bars", "resources", "Trading seed bars", "Synthetic seed bar count.", 720, allow_unlimited=True, min_v=50),
    ]

    # ── Storage ─────────────────────────────────────────────────────────────
    d += [
        _ni("storage.sqlite_timeout_seconds", "sqlite_timeout_seconds", "resources", "SQLite timeout", "sqlite3.connect timeout.", 10, min_v=1, unit="s", apply="hades_restart"),
        _ni("storage.sqlite_busy_timeout_ms", "sqlite_busy_timeout_ms", "resources", "SQLite busy timeout", "PRAGMA busy_timeout.", 5000, min_v=100, unit="ms", apply="hades_restart"),
    ]

    # ── Voice (local ASR/TTS) ───────────────────────────────────────────────
    d += [
        _bool("voice.enabled", "voice_enabled", "logging", "Voice enabled", "Enable local voice features in the UI.", True),
        _enum("voice.asr_provider", "voice_asr_provider", "logging", "ASR provider", "Local speech recognition provider.", "faster_whisper", ["faster_whisper"]),
        _enum("voice.asr_model", "voice_asr_model", "logging", "ASR model", "faster-whisper model size.", "base", ["tiny", "base", "small", "medium", "large-v3"]),
        _enum("voice.asr_device", "voice_asr_device", "logging", "ASR device", "CPU or CUDA (auto detects).", "auto", ["auto", "cpu", "cuda"]),
        _enum("voice.asr_compute_type", "voice_asr_compute_type", "logging", "ASR compute type", "CTranslate2 compute type.", "auto", ["auto", "int8", "float16", "float32"]),
        _enum("voice.tts_provider", "voice_tts_provider", "logging", "TTS provider", "Local speech synthesis provider.", "piper", ["piper", "browser"]),
        _str("voice.tts_voice", "voice_tts_voice", "logging", "TTS voice", "Piper voice id (e.g. nl_NL-pim-medium).", "nl_NL-pim-medium"),
        _fl("voice.tts_speed", "voice_tts_speed", "logging", "TTS speed", "Speech rate multiplier.", 1.0, min_v=0.5, max_v=2.0),
        _fl("voice.tts_volume", "voice_tts_volume", "logging", "TTS volume", "Client playback volume.", 1.0, min_v=0.0, max_v=1.0),
        _enum("voice.language", "voice_language", "logging", "Voice language", "ASR/TTS language.", "nl", ["nl", "en", "auto"]),
        _bool("voice.spoken_answers_default", "voice_spoken_answers_default", "logging", "Spoken answers default", "Speak assistant replies by default.", False),
        _enum("voice.speak_style", "voice_speak_style", "logging", "Speak style", "Compact or full reading style.", "compact", ["compact", "full"]),
        _enum("voice.turn_mode", "voice_turn_mode", "logging", "Turn mode", "Manual push-to-talk or automatic VAD turns.", "manual", ["manual", "auto"]),
        _fl("voice.vad_sensitivity", "voice_vad_sensitivity", "logging", "VAD sensitivity", "Higher = more sensitive.", 0.55, min_v=0.0, max_v=1.0),
        _ni("voice.vad_end_silence_ms", "voice_vad_end_silence_ms", "logging", "VAD end silence", "Silence before ending a turn.", 900, min_v=300, max_v=5000, unit="ms"),
        _bool("voice.barge_in", "voice_barge_in", "logging", "Barge-in", "Allow interrupting spoken replies by talking.", True),
        _bool("voice.wake_word_enabled", "voice_wake_word_enabled", "logging", "Wake word", "Optional local 'Hades' wake word (default off).", False, risk="medium"),
        _ni("voice.session_idle_seconds", "voice_session_idle_seconds", "logging", "Session idle timeout", "Pause session after inactivity.", 120, min_v=30, unit="s"),
        _bool("voice.keep_recordings", "voice_keep_recordings", "logging", "Keep recordings", "Persist new mic recordings (default temporary only).", False, risk="medium"),
        _str("voice.input_device_id", "voice_input_device_id", "logging", "Input device id", "Browser microphone deviceId when supported.", ""),
        _str("voice.output_device_id", "voice_output_device_id", "logging", "Output device id", "Browser audio output deviceId when supported.", ""),
        _str("voice.setup_completed_at", "voice_setup_completed_at", "logging", "Voice setup completed at", "Timestamp when voice setup wizard finished.", ""),
    ]

    # ── Speech (TTS/STT) — independent of LM Studio model selection ─────────
    d += [
        _bool("speech.spoken_answers_enabled", "spoken_answers_enabled", "logging", "Gesproken antwoorden", "Lees definitieve assistentantwoorden automatisch voor via de TTS-provider.", False, risk="low"),
        _enum("speech.tts_provider", "tts_provider", "resources", "TTS-provider", "Lokale TTS-provider. Geen stille cloud-fallback.", "none", ["none", "voicestudio"], risk="medium"),
        _str("speech.tts_base_url", "tts_base_url", "resources", "TTS base URL", "VoiceStudio OpenAI-compatible base URL (…/v1).", "http://127.0.0.1:3900/v1"),
        _str("speech.tts_api_key", "tts_api_key", "resources", "TTS API key", "Optioneel; alleen nodig als VoiceStudio OMNIVOICE_API_KEY vereist.", "", risk="critical"),
        _str("speech.tts_voice_id", "tts_voice_id", "resources", "TTS stemprofiel", "VoiceStudio voice profile id, default, of OpenAI-alias.", "default"),
        _str("speech.tts_model", "tts_model", "resources", "TTS-model/engine", "tts-1/tts-1-hd (actieve engine) of een VoiceStudio-engine-id.", "tts-1"),
        _fl("speech.tts_speed", "tts_speed", "resources", "TTS snelheid", "Spraaksnelheid 0.25–4.0.", 1.0, min_v=0.25, max_v=4.0),
        _str("speech.tts_language", "tts_language", "resources", "TTS taal", "ISO 639-1 taalhint voor VoiceStudio.", "nl"),
        _enum("speech.tts_response_format", "tts_response_format", "resources", "TTS audioformaat", "VoiceStudio response_format.", "wav", ["mp3", "opus", "aac", "flac", "wav", "pcm"]),
        _bool("speech.tts_sentence_chunking", "tts_sentence_chunking", "resources", "Zinsgewijze TTS", "HADES splitst tekst in zinnen voor snellere eerste audio; VoiceStudio streamt geen PCM.", True),
        _ni("speech.tts_min_free_ram_mb", "tts_min_free_ram_mb", "resources", "Min. vrij RAM voor TTS", "Weiger TTS als minder RAM vrij is; forceert geen LM Studio-ontlading.", 1500, min_v=0, unit="MB"),
        _ni("speech.tts_min_free_vram_mb", "tts_min_free_vram_mb", "resources", "Min. vrije VRAM voor TTS", "Optionele VRAM-drempel; 0 = niet afdwingen wanneer onbekend.", 0, min_v=0, unit="MB"),
        _str("speech.tts_instruct", "tts_instruct", "resources", "TTS instruct", "Style instruction wanneer de gekozen engine dat ondersteunt.", ""),
        _str("speech.tts_description", "tts_description", "resources", "TTS description", "Voice-design description (o.a. VoxCPM2) wanneer ondersteund.", ""),
        _enum("speech.stt_provider", "stt_provider", "resources", "STT-provider", "Spraakherkenning apart van TTS: paste, VoiceStudio of uit.", "paste", ["none", "voicestudio", "paste"], risk="medium"),
        _str("speech.stt_base_url", "stt_base_url", "resources", "STT base URL", "VoiceStudio /v1 voor transcriptie.", "http://127.0.0.1:3900/v1"),
        _str("speech.stt_api_key", "stt_api_key", "resources", "STT API key", "Optionele VoiceStudio API-key voor STT.", "", risk="critical"),
        _str("speech.stt_model", "stt_model", "resources", "STT-model", "whisper-1 of VoiceStudio ASR-engine-id.", "whisper-1"),
        _str("speech.stt_language", "stt_language", "resources", "STT taal", "ISO 639-1 taalhint voor transcriptie.", "nl"),
        _ni("speech.stt_echo_guard_ms", "stt_echo_guard_ms", "resources", "STT echo-guard", "Blokkeer microfoon/STT tijdens/na TTS-afspelen.", 750, min_v=0, unit="ms"),
    ]

    return d


def create_default_registry() -> SettingRegistry:
    registry = SettingRegistry()
    registry.register_many(build_core_definitions())
    return registry

