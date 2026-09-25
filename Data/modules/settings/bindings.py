"""Consumer binders for hot-applied settings."""

from __future__ import annotations

import os
from typing import Any

from Data.backend.config import Settings
from Data.modules.settings.service import SettingsControlPlane

# Settings keys → process env consumed by ``load_worker_settings``.
_WORKER_ENV_BY_KEY: dict[str, str] = {
    "workers.enabled": "LEVIATHAN_WORKERS_ENABLED",
    "workers.supervisor_enabled": "LEVIATHAN_WORKERS_SUPERVISOR_ENABLED",
    "workers.externalize_api_runners": "LEVIATHAN_WORKERS_EXTERNALIZE_API",
    "workers.heartbeat_seconds": "LEVIATHAN_WORKERS_HEARTBEAT_SECONDS",
    "workers.lease_ttl_seconds": "LEVIATHAN_WORKERS_LEASE_TTL_SECONDS",
    "workers.poll_seconds": "LEVIATHAN_WORKERS_POLL_SECONDS",
    "workers.shutdown_grace_seconds": "LEVIATHAN_WORKERS_SHUTDOWN_GRACE_SECONDS",
    "workers.restart.max_attempts": "LEVIATHAN_WORKERS_RESTART_MAX_ATTEMPTS",
    "workers.restart.window_seconds": "LEVIATHAN_WORKERS_RESTART_WINDOW_SECONDS",
    "workers.restart.base_backoff": "LEVIATHAN_WORKERS_RESTART_BASE_BACKOFF",
    "workers.restart.max_backoff": "LEVIATHAN_WORKERS_RESTART_MAX_BACKOFF",
    "workers.supervisor_lease_ttl_seconds": "LEVIATHAN_WORKERS_SUPERVISOR_LEASE_TTL_SECONDS",
    "resource.background.ram_headroom": "LEVIATHAN_RESOURCE_BACKGROUND_RAM_HEADROOM",
    "resource.background.vram_headroom": "LEVIATHAN_RESOURCE_BACKGROUND_VRAM_HEADROOM",
    "knowledge.commit.concurrency": "LEVIATHAN_WORKERS_POOL_KNOWLEDGE_COMMIT_COUNT",
    "workers.pools.db_commit.count": "LEVIATHAN_WORKERS_POOL_DB_COMMIT_COUNT",
    "dbCommit.enabled": "LEVIATHAN_DB_COMMIT_ENABLED",
    "dbCommit.maxPendingCount": "LEVIATHAN_DB_COMMIT_MAX_PENDING_COUNT",
    "dbCommit.maxPendingBytes": "LEVIATHAN_DB_COMMIT_MAX_PENDING_BYTES",
    "dbCommit.maxBatchRows": "LEVIATHAN_DB_COMMIT_MAX_BATCH_ROWS",
    "dbCommit.targetTransactionMs": "LEVIATHAN_DB_COMMIT_TARGET_TRANSACTION_MS",
    "dbCommit.retryLimit": "LEVIATHAN_DB_COMMIT_RETRY_LIMIT",
    "dbCommit.spoolRetentionHours": "LEVIATHAN_DB_COMMIT_SPOOL_RETENTION_HOURS",
    "dbCommit.appliedRetentionHours": "LEVIATHAN_DB_COMMIT_APPLIED_RETENTION_HOURS",
    "dbCommit.priorityAgingSeconds": "LEVIATHAN_DB_COMMIT_PRIORITY_AGING_SECONDS",
}

_WORKER_ATTR_BY_KEY: dict[str, str] = {
    "workers.enabled": "enabled",
    "workers.supervisor_enabled": "supervisor_enabled",
    "workers.externalize_api_runners": "externalize_api_runners",
    "workers.heartbeat_seconds": "heartbeat_seconds",
    "workers.lease_ttl_seconds": "lease_ttl_seconds",
    "workers.poll_seconds": "poll_seconds",
    "workers.shutdown_grace_seconds": "shutdown_grace_seconds",
    "workers.restart.max_attempts": "restart_max_attempts",
    "workers.restart.window_seconds": "restart_window_seconds",
    "workers.restart.base_backoff": "restart_base_backoff",
    "workers.restart.max_backoff": "restart_max_backoff",
    "workers.supervisor_lease_ttl_seconds": "supervisor_lease_ttl_seconds",
    "resource.background.ram_headroom": "ram_headroom_mb",
    "resource.background.vram_headroom": "vram_headroom_mb",
}


def _env_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def bind_default_consumers(
    plane: SettingsControlPlane,
    *,
    resource_manager: Any | None = None,
    function_runtime: Any | None = None,
    knowledge: Any | None = None,
    deep_recall: Any | None = None,
    staged_retriever: Any | None = None,
    why_library: Any | None = None,
    mcp_bridge: Any | None = None,
    cognition_runtime: Any | None = None,
    agent_runtime: Any | None = None,
    coding_service: Any | None = None,
    research_service: Any | None = None,
    dataset_service: Any | None = None,
    isolation_guard: Any | None = None,
    chaos: Any | None = None,
    model_plane: Any | None = None,
    llm: Any | None = None,
    neuro_advisor: Any | None = None,
    neuro_critic: Any | None = None,
    neuro_soak: Any | None = None,
    module_manager: Any | None = None,
    market_sim_service: Any | None = None,
    context_builder: Any | None = None,
    residual_orchestrator: Any | None = None,
    cortex_runtime: Any | None = None,
    residual_runtime: Any | None = None,
    reasoning_policy_holder: Any | None = None,
    worker_settings: Any | None = None,
    resource_admission: Any | None = None,
) -> None:
    """Register apply callbacks that push hot settings into live consumers."""

    def on_apply(key: str, value: Any, effective: Settings) -> None:
        if key == "resources.max_job_concurrency" and resource_manager is not None:
            if hasattr(resource_manager, "set_max_job_concurrency"):
                resource_manager.set_max_job_concurrency(int(value))
            else:
                resource_manager.max_job_concurrency = int(value)

        if key == "resources.max_function_concurrency" and function_runtime is not None:
            if hasattr(function_runtime, "max_concurrency"):
                function_runtime.max_concurrency = int(value)

        if key == "resources.max_model_concurrency" and model_plane is not None:
            mgr = getattr(model_plane, "resources", None) or getattr(model_plane, "resource_manager", None)
            if mgr is not None and hasattr(mgr, "max_concurrency"):
                mgr.max_concurrency = int(value)

        # Execution fabric: sync env so ``load_worker_settings`` / new workers see overrides.
        # Hot-apply poll + pool counts / headroom onto live holders when present.
        if key in _WORKER_ENV_BY_KEY:
            os.environ[_WORKER_ENV_BY_KEY[key]] = _env_str(value)

        if key.startswith("workers.pools.") and key.endswith(".count"):
            pool_id = key[len("workers.pools.") : -len(".count")]
            if pool_id:
                env_key = f"LEVIATHAN_WORKERS_POOL_{pool_id.upper()}_COUNT"
                os.environ[env_key] = str(int(value))
                if worker_settings is not None and hasattr(worker_settings, "pool_counts"):
                    worker_settings.pool_counts[pool_id] = int(value)

        if key == "knowledge.commit.concurrency":
            os.environ["LEVIATHAN_WORKERS_POOL_KNOWLEDGE_COMMIT_COUNT"] = str(int(value))
            if worker_settings is not None and hasattr(worker_settings, "pool_counts"):
                worker_settings.pool_counts["knowledge_commit"] = int(value)

        attr = _WORKER_ATTR_BY_KEY.get(key)
        if attr and worker_settings is not None and hasattr(worker_settings, attr):
            current = getattr(worker_settings, attr)
            if isinstance(current, bool):
                setattr(worker_settings, attr, bool(value))
            elif isinstance(current, int) and not isinstance(current, bool):
                setattr(worker_settings, attr, int(value))
            else:
                setattr(worker_settings, attr, float(value))

        if resource_admission is not None:
            if key == "resource.background.ram_headroom":
                resource_admission.ram_headroom_mb = float(value)
            elif key == "resource.background.vram_headroom":
                resource_admission.vram_headroom_mb = float(value)

        if key == "knowledge.top_k":
            pass  # request handlers read plane.effective

        if key in {"knowledge.chunk_max_chars", "knowledge.chunk_overlap"} and knowledge is not None:
            if key == "knowledge.chunk_max_chars":
                knowledge.chunk_max_chars = int(value)
            else:
                knowledge.chunk_overlap = int(value)

        if key == "knowledge.deep_recall_budget" and deep_recall is not None:
            if hasattr(deep_recall, "default_deep_recall_budget"):
                deep_recall.default_deep_recall_budget = int(value)
            elif hasattr(deep_recall, "budget"):
                deep_recall.budget = int(value)

        if key == "knowledge.rerank_policy":
            if staged_retriever is not None and hasattr(staged_retriever, "rerank_policy"):
                staged_retriever.rerank_policy = str(value)
            if cognition_runtime is not None:
                perception = getattr(cognition_runtime, "perception", None)
                if perception is not None and hasattr(perception, "rerank_policy"):
                    perception.rerank_policy = str(value)

        if key == "knowledge.query_expansion" and staged_retriever is not None:
            if hasattr(staged_retriever, "query_expansion"):
                staged_retriever.query_expansion = bool(value)

        if key == "knowledge.max_query_expansions" and staged_retriever is not None:
            if hasattr(staged_retriever, "max_query_expansions"):
                staged_retriever.max_query_expansions = max(0, int(value))

        if key == "knowledge.diversity_enabled" and knowledge is not None:
            # Prefer live HybridRetriever when passed as staged's authority.
            target = None
            if staged_retriever is not None and hasattr(staged_retriever, "retriever"):
                target = staged_retriever.retriever
            if target is not None and hasattr(target, "diversity_enabled"):
                target.diversity_enabled = bool(value)

        if key == "knowledge.diversity_strength":
            target = None
            if staged_retriever is not None and hasattr(staged_retriever, "retriever"):
                target = staged_retriever.retriever
            if target is not None and hasattr(target, "diversity_strength"):
                target.diversity_strength = float(value)

        if key == "features.deep_recall" and deep_recall is not None and hasattr(deep_recall, "enabled"):
            deep_recall.enabled = bool(value) and bool(effective.features.rag_v3)

        if key == "features.why_library" and why_library is not None and hasattr(why_library, "enabled"):
            why_library.enabled = bool(value) and bool(effective.features.rag_v3)

        if key == "features.rag_v3":
            if deep_recall is not None and hasattr(deep_recall, "enabled"):
                deep_recall.enabled = bool(effective.features.deep_recall) and bool(value)
            if why_library is not None and hasattr(why_library, "enabled"):
                why_library.enabled = bool(effective.features.why_library) and bool(value)

        if mcp_bridge is not None:
            if key == "features.mcp_enabled":
                mcp_bridge.enabled = bool(value)
            elif key == "features.mcp_stdio" and hasattr(mcp_bridge, "stdio_enabled"):
                mcp_bridge.stdio_enabled = bool(value)
            elif key == "features.mcp_http" and hasattr(mcp_bridge, "http_enabled"):
                mcp_bridge.http_enabled = bool(value)
            elif key == "features.mcp_auto_expand_modules" and hasattr(mcp_bridge, "auto_expand_modules"):
                mcp_bridge.auto_expand_modules = bool(value)
            elif key == "network.allow_outbound" and hasattr(mcp_bridge, "allow_outbound"):
                mcp_bridge.allow_outbound = bool(value)

        if cognition_runtime is not None:
            mapping = {
                "features.cognition_enabled": "enabled",
                # CognitiveRuntime stores the flag as shadow_default (not shadow).
                "features.cognition_shadow": "shadow_default",
                "features.cognition_iterative_loop": "iterative",
                "features.cognition_belief_state": "belief_enabled",
                "features.cognition_neuro": "neuro_enabled",
                "features.cognition_adaptive_depth": "adaptive_depth",
                "features.cognition_delegation": "delegation_enabled",
                "features.cognition_experience_learning": "experience_learning",
            }
            attr = mapping.get(key)
            if attr and hasattr(cognition_runtime, attr):
                setattr(cognition_runtime, attr, bool(value))

        if key == "features.reasoning_iterative_retrieval" and cognition_runtime is not None:
            if hasattr(cognition_runtime, "iterative_retrieval"):
                cognition_runtime.iterative_retrieval = bool(value)
            elif hasattr(cognition_runtime, "reasoning_iterative_retrieval"):
                cognition_runtime.reasoning_iterative_retrieval = bool(value)

        if key.startswith("reasoning.") and cognition_runtime is not None:
            try:
                from Data.modules.intelligence import ReasoningPolicy

                policy = ReasoningPolicy.from_settings(effective)
                meta = getattr(cognition_runtime, "meta", None)
                if meta is not None and hasattr(meta, "set_policy"):
                    meta.set_policy(policy)
                if reasoning_policy_holder is not None:
                    if isinstance(reasoning_policy_holder, dict):
                        reasoning_policy_holder["policy"] = policy
                    elif hasattr(reasoning_policy_holder, "reasoning_policy"):
                        reasoning_policy_holder.reasoning_policy = policy
                    elif hasattr(reasoning_policy_holder, "policy"):
                        reasoning_policy_holder.policy = policy
            except Exception:  # noqa: BLE001 — hot apply must not break settings plane
                pass

        if agent_runtime is not None:
            if key == "features.agents_enabled" and hasattr(agent_runtime, "agents_enabled"):
                agent_runtime.agents_enabled = bool(value)
            if key == "features.coding_enabled":
                agent_runtime.coding_enabled = bool(value)

        if coding_service is not None and hasattr(coding_service, "settings"):
            # CodingControlPlane holds a Settings reference; swap when possible.
            if key.startswith("coding.") or key == "features.coding_enabled":
                if hasattr(coding_service, "apply_settings"):
                    coding_service.apply_settings(effective)
                else:
                    coding_service.settings = effective

        if research_service is not None:
            if key == "network.allow_outbound":
                research_service.allow_outbound = bool(value)
            if key in {"web_search.endpoint", "web_search.api_key", "network.allow_outbound"}:
                if hasattr(research_service, "reconfigure_web"):
                    research_service.reconfigure_web(
                        allow_outbound=effective.network.allow_outbound,
                        search_endpoint=effective.research_integration.web_search_endpoint,
                        api_key=effective.research_integration.web_search_api_key,
                    )
            if key == "research.auto_promote_verified_knowledge" and hasattr(
                research_service, "auto_promote_verified_knowledge"
            ):
                research_service.auto_promote_verified_knowledge = bool(value)

        if dataset_service is not None:
            if key == "datasets.auto_index_ready_to_knowledge" and hasattr(
                dataset_service, "datasets_auto_index_ready_to_knowledge"
            ):
                dataset_service.datasets_auto_index_ready_to_knowledge = bool(value)

        if isolation_guard is not None and key == "network.allow_outbound":
            if hasattr(isolation_guard, "settings"):
                isolation_guard.settings = effective

        if chaos is not None and key.startswith("chaos."):
            from Data.modules.chaos.injector import ChaosPlan

            if hasattr(chaos, "configure"):
                chaos.configure(
                    ChaosPlan(
                        enabled=effective.chaos.enabled,
                        latency_ms=effective.chaos.latency_ms,
                        error_rate=effective.chaos.error_rate,
                    )
                )

        if llm is not None and key.startswith("model."):
            if hasattr(llm, "settings"):
                llm.settings = effective
            if key == "model.base_url" and hasattr(llm, "base_url"):
                llm.base_url = str(value).rstrip("/")
            if key == "model.api_key" and hasattr(llm, "api_key"):
                llm.api_key = str(value)
            if key == "model.timeout_seconds" and hasattr(llm, "timeout_seconds"):
                llm.timeout_seconds = float(value)
            if key == "model.model" and hasattr(llm, "model"):
                llm.model = value

        if neuro_advisor is not None and (
            key.startswith("features.neuro") or key in {"features.residual_production", "features.memory_semantic"}
        ):
            mapping = {
                "features.neuro_enabled": "enabled",
                "features.neuro_associative_memory": "associative_memory",
                "features.neuro_process_critic": "process_critic",
                "features.neuro_residual_injection": "residual_injection",
                "features.neuro_cortex": "cortex_enabled",
                "features.neuro_memory_tiers": "memory_tiers_enabled",
                "features.neuro_residual_orchestrator": "residual_orchestrator_enabled",
                "features.neuro_cortex_blocks": "cortex_blocks_enabled",
            }
            attr = mapping.get(key)
            if attr and hasattr(neuro_advisor, attr):
                setattr(neuro_advisor, attr, bool(value))

            if key == "features.neuro_cortex":
                planner = getattr(neuro_advisor, "cortex_planner", None)
                if planner is not None and hasattr(planner, "enabled"):
                    planner.enabled = bool(value)

            if key == "features.memory_semantic":
                facade = getattr(neuro_advisor, "memory_facade", None)
                if facade is not None and hasattr(facade, "use_embeddings"):
                    facade.use_embeddings = bool(value)

            if key == "features.neuro_memory_tiers":
                facade = getattr(neuro_advisor, "memory_facade", None)
                if facade is not None and hasattr(facade, "enabled"):
                    facade.enabled = bool(value) and bool(effective.features.neuro_enabled)

        if residual_orchestrator is not None and key in {
            "features.neuro_residual_orchestrator",
            "features.neuro_enabled",
        }:
            if hasattr(residual_orchestrator, "enabled"):
                residual_orchestrator.enabled = bool(
                    effective.features.neuro_enabled and effective.features.neuro_residual_orchestrator
                )

        if cortex_runtime is not None:
            if key == "features.neuro_cortex_blocks" and hasattr(cortex_runtime, "named_blocks_enabled"):
                cortex_runtime.named_blocks_enabled = bool(value)
            if key in {"neuro_runtime.cortex_max_k", "memory.tier0_max_slots"}:
                pass  # handled below for planner / capacity

        if key == "neuro_runtime.cortex_max_k":
            max_k = int(value)
            if cortex_runtime is not None and hasattr(cortex_runtime, "max_k"):
                cortex_runtime.max_k = max_k
            planner = getattr(neuro_advisor, "cortex_planner", None) if neuro_advisor is not None else None
            if planner is not None:
                if hasattr(planner, "max_k"):
                    planner.max_k = max_k
                if hasattr(planner, "max_depth"):
                    planner.max_depth = min(2, max(0, max_k))
                if hasattr(planner, "max_critic_rounds"):
                    planner.max_critic_rounds = max_k

        if key == "memory.tier0_max_slots":
            capacity = int(value)
            facade = getattr(neuro_advisor, "memory_facade", None) if neuro_advisor is not None else None
            working = getattr(facade, "working", None) if facade is not None else None
            if working is not None and hasattr(working, "capacity"):
                working.capacity = capacity

        if key == "features.residual_production" and residual_runtime is not None:
            if hasattr(residual_runtime, "enabled"):
                residual_runtime.enabled = bool(value) and bool(
                    effective.features.neuro_enabled and effective.features.neuro_residual_injection
                )
            elif hasattr(residual_runtime, "production_enabled"):
                residual_runtime.production_enabled = bool(value)

        if neuro_critic is not None and key == "features.neuro_process_critic":
            if hasattr(neuro_critic, "enabled"):
                neuro_critic.enabled = bool(value)

        if neuro_soak is not None and key == "features.neuro_soak_long":
            if hasattr(neuro_soak, "long_soak_enabled"):
                neuro_soak.long_soak_enabled = bool(value)

        if module_manager is not None:
            if key == "features.module_manager_enabled" and hasattr(module_manager, "enabled"):
                module_manager.enabled = bool(value)
            if key == "features.module_manager_subprocess" and hasattr(
                module_manager, "allow_subprocess_isolation"
            ):
                module_manager.allow_subprocess_isolation = bool(value)

        if market_sim_service is not None:
            if key == "features.market_sim_enabled" and hasattr(market_sim_service, "enabled"):
                market_sim_service.enabled = bool(value)
            if key == "market_sim.bars_per_slice" and hasattr(market_sim_service, "bars_per_slice"):
                market_sim_service.bars_per_slice = int(value)
            if key == "market_sim.default_initial_cash" and hasattr(
                market_sim_service, "default_initial_cash"
            ):
                market_sim_service.default_initial_cash = float(value)
            if hasattr(market_sim_service, "settings"):
                market_sim_service.settings = effective

        if context_builder is not None and key.startswith("context."):
            attr = key.split(".", 1)[1]
            if hasattr(context_builder, attr):
                current = getattr(context_builder, attr)
                if isinstance(current, bool) or attr == "auto_budget":
                    setattr(context_builder, attr, bool(value))
                elif isinstance(current, float) or "fraction" in attr:
                    setattr(context_builder, attr, float(value))
                else:
                    setattr(context_builder, attr, int(value) if isinstance(value, (int, float)) else value)
            if key == "resources.max_history_messages" and hasattr(
                context_builder, "max_history_messages"
            ):
                context_builder.max_history_messages = int(value)

        if key == "resources.max_history_messages" and context_builder is not None:
            if hasattr(context_builder, "max_history_messages"):
                context_builder.max_history_messages = int(value)

        if key == "hf_token":
            # Consumed via env-style lookup in huggingface helpers; set process env for workers.
            token = str(value or "").strip()
            if token:
                os.environ["LEVIATHAN_HF_TOKEN"] = token
                os.environ["HF_TOKEN"] = token
            else:
                os.environ.pop("LEVIATHAN_HF_TOKEN", None)

        if key == "training_fixture":
            os.environ["LEVIATHAN_TRAINING_FIXTURE"] = "1" if value else "0"

    plane.register_apply_callback(on_apply)
