/**
 * Bounded UI poll intervals. Prefer events as invalidation; these are fallbacks.
 * Keep Chat-path polling coarse so it does not compete with an active run.
 */
export const PLUGIN_DEPENDENCY_POLL_MS = 2500;
export const RESEARCH_ACTIVE_POLL_MS = 4000;
export const TASKS_ACTIVE_POLL_MS = 4000;
export const CHAT_USAGE_POLL_ACTIVE_MS = 2000;
export const CHAT_USAGE_POLL_IDLE_MS = 12000;
export const CHAT_APPROVALS_POLL_MS = 8000;
export const CHAT_RUN_EVENT_POLL_FALLBACK_MS = 800;
export const CODING_JOB_POLL_MS = 2000;
