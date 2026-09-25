from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "Data"
BACKEND_ROOT = DATA_ROOT / "backend"
FRONTEND_ROOT = DATA_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_ROOT / "dist"

load_dotenv(PROJECT_ROOT / ".env")


class ConfigurationError(ValueError):
    """Raised when LEVIATHAN configuration is invalid."""


def _env_raw(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_raw(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"Invalid boolean for {name}: {raw!r}")


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = _env_raw(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ConfigurationError(f"Invalid integer for {name}: {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be <= {maximum}, got {value}")
    return value


def _parse_int_csv(raw: str) -> tuple[int, ...]:
    """Parse comma-separated integers; empty → (). Invalid tokens raise ConfigurationError."""
    text = (raw or "").strip()
    if not text:
        return ()
    values: list[int] = []
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.append(int(token))
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid integer in LEVIATHAN_NEURO_RESIDUAL_HOOK_LAYERS: {token!r}"
            ) from exc
    return tuple(values)


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = _env_raw(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise ConfigurationError(f"Invalid number for {name}: {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be <= {maximum}, got {value}")
    return value


def _resolve_path(raw: str, *, must_be_absolute_root: bool = False) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if must_be_absolute_root and not path.is_absolute():
        raise ConfigurationError(f"Path must resolve to an absolute location: {raw!r}")
    return path


def _resolve_data_root(raw: str) -> Path:
    """Resolve bulk-data root.

    Relative paths resolve under PROJECT_ROOT so installs remain relocatable.
    Absolute Windows drive-letter / UNC roots are preserved when operators set
    them explicitly (including on POSIX control-plane hosts).
    """
    text = raw.strip()
    if not text:
        raise ConfigurationError("LEVIATHAN_DATA_ROOT cannot be empty")
    # Drive-letter or UNC paths are treated as absolute operator roots.
    if len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in {"/", "\\"}:
        return Path(text)
    if text.startswith("\\\\") or text.startswith("//"):
        return Path(text)
    path = Path(text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _reasoning_budget_kwargs(prefix: str, defaults: dict[str, float | int]) -> dict[str, float | int]:
    """Load LEVIATHAN_REASONING_{PREFIX}_MAX_* budget fields from env."""
    env_prefix = f"LEVIATHAN_REASONING_{prefix.upper()}_"
    out: dict[str, float | int] = {}
    for field, default in defaults.items():
        env_name = env_prefix + field.upper()
        key = f"{prefix}_{field}"
        if isinstance(default, float):
            out[key] = _env_float(env_name, float(default), minimum=0.0)
        else:
            out[key] = _env_int(env_name, int(default), minimum=0)
    return out


_REASONING_BUDGET_DEFAULTS: dict[str, dict[str, float | int]] = {
    "fast": {
        "max_wall_time_seconds": 30.0,
        "max_model_calls": 1,
        "max_model_tokens": 2000,
        "max_retrieval_rounds": 1,
        "max_critic_passes": 0,
        "max_tool_calls": 0,
        "max_agent_delegations": 0,
        "max_iterations": 2,
        "max_context_tokens": 3000,
    },
    "standard": {
        "max_wall_time_seconds": 90.0,
        "max_model_calls": 3,
        "max_model_tokens": 6000,
        "max_retrieval_rounds": 2,
        "max_critic_passes": 1,
        "max_tool_calls": 4,
        "max_agent_delegations": 1,
        "max_iterations": 5,
        "max_context_tokens": 6000,
    },
    "deep": {
        "max_wall_time_seconds": 180.0,
        "max_model_calls": 6,
        "max_model_tokens": 12000,
        "max_retrieval_rounds": 3,
        "max_critic_passes": 2,
        "max_tool_calls": 8,
        "max_agent_delegations": 2,
        "max_iterations": 8,
        "max_context_tokens": 8000,
    },
    "maximum": {
        "max_wall_time_seconds": 300.0,
        "max_model_calls": 10,
        "max_model_tokens": 20000,
        "max_retrieval_rounds": 4,
        "max_critic_passes": 3,
        "max_tool_calls": 12,
        "max_agent_delegations": 3,
        "max_iterations": 12,
        "max_context_tokens": 12000,
    },
}


@dataclass(frozen=True)
class RuntimeSettings:
    host: str
    port: int
    loopback_only: bool


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model: str | None
    api_key: str
    timeout_seconds: float


@dataclass(frozen=True)
class ManagedServingSettings:
    """Managed local model worker / residency configuration."""

    enabled: bool = True
    allow_inproc_fixture: bool = False  # production must never default to echo/inproc success
    llama_cpp_executable: str | None = None
    vllm_executable: str | None = None
    bind_host: str = "127.0.0.1"
    port_start: int = 29100
    port_end: int = 29200
    worker_startup_timeout_seconds: float = 120.0
    worker_shutdown_timeout_seconds: float = 15.0
    default_residency_policy: str = "IDLE_UNLOAD"
    default_idle_unload_seconds: float = 300.0
    min_ram_reserve_bytes: int = 1_073_741_824
    min_vram_reserve_bytes: int = 536_870_912
    max_managed_resident_models: int = 4


@dataclass(frozen=True)
class KnowledgeSettings:
    top_k: int
    data_root: Path
    chunk_max_chars: int = 1200
    chunk_overlap: int = 120
    embedding_provider: str = "null"
    embedding_model: str | None = None
    embedding_hash_dimensions: int = 256
    reranker_model: str | None = None
    deep_recall_budget: int = 800
    rerank_policy: str = "auto"  # off | auto | always
    rerank_candidate_count: int = 20
    rerank_final_count: int = 5
    min_retrieval_score: float = 0.0
    min_confidence: float = 0.0
    query_expansion: bool = True
    max_query_expansions: int = 4
    max_retrieval_rounds: int = 3
    diversity_enabled: bool = True
    diversity_strength: float = 0.3
    lexical_enabled: bool = True
    dense_enabled: bool = True
    hybrid_enabled: bool = True
    rrf_k: int = 60
    contradiction_detection: bool = True
    retrieval_trace: bool = True
    atlas_retrieval: bool = True
    atlas_expansion_depth: int = 1
    auto_dedupe: bool = True
    integrity_checks: bool = True
    # Deprecated specialized knowledge.commit lane (max 1). Bulk writes owned by db_commit.
    commit_concurrency: int = 0


@dataclass(frozen=True)
class ReasoningSettings:
    enabled: bool
    default_mode: str = "adaptive"  # adaptive|fast|standard|deep|maximum
    allow_fast_path: bool = True
    minimum_evidence_coverage: float = 0.35
    uncertainty_deep_threshold: float = 0.75
    contradiction_replan_threshold: float = 0.3
    max_replans_global: int = 4
    max_retries_global: int = 3
    require_verification_for_high_risk: bool = True
    require_grounding_for_knowledge_tasks: bool = True
    # Budget profiles (flat fields for settings path mapping)
    fast_max_wall_time_seconds: float = 30.0
    fast_max_model_calls: int = 1
    fast_max_model_tokens: int = 2000
    fast_max_retrieval_rounds: int = 1
    fast_max_critic_passes: int = 0
    fast_max_tool_calls: int = 0
    fast_max_agent_delegations: int = 0
    fast_max_iterations: int = 2
    fast_max_context_tokens: int = 3000
    standard_max_wall_time_seconds: float = 90.0
    standard_max_model_calls: int = 3
    standard_max_model_tokens: int = 6000
    standard_max_retrieval_rounds: int = 2
    standard_max_critic_passes: int = 1
    standard_max_tool_calls: int = 4
    standard_max_agent_delegations: int = 1
    standard_max_iterations: int = 5
    standard_max_context_tokens: int = 6000
    deep_max_wall_time_seconds: float = 180.0
    deep_max_model_calls: int = 6
    deep_max_model_tokens: int = 12000
    deep_max_retrieval_rounds: int = 3
    deep_max_critic_passes: int = 2
    deep_max_tool_calls: int = 8
    deep_max_agent_delegations: int = 2
    deep_max_iterations: int = 8
    deep_max_context_tokens: int = 8000
    maximum_max_wall_time_seconds: float = 300.0
    maximum_max_model_calls: int = 10
    maximum_max_model_tokens: int = 20000
    maximum_max_retrieval_rounds: int = 4
    maximum_max_critic_passes: int = 3
    maximum_max_tool_calls: int = 12
    maximum_max_agent_delegations: int = 3
    maximum_max_iterations: int = 12
    maximum_max_context_tokens: int = 12000


@dataclass(frozen=True)
class VerificationSettings:
    """Verification / grounding toggles for high-risk and knowledge paths."""

    factual_grounding: bool = True
    contradiction_check: bool = True
    require_evidence: bool = True
    citation_required: bool = False
    unmeasured_blocks_completion: bool = True


@dataclass(frozen=True)
class FeatureFlags:
    """Experimental switches. Flags must never bypass security policy."""

    reasoning_iterative_retrieval: bool
    memory_semantic: bool
    neuro_enabled: bool
    neuro_associative_memory: bool
    neuro_process_critic: bool
    neuro_residual_injection: bool
    neuro_cortex: bool
    neuro_memory_tiers: bool
    neuro_residual_orchestrator: bool
    neuro_cortex_blocks: bool
    neuro_contrastive_training: bool
    neuro_soak_long: bool
    neuro_training_real_worker: bool
    module_manager_enabled: bool
    module_manager_subprocess: bool
    agents_enabled: bool
    coding_enabled: bool
    mcp_enabled: bool
    mcp_stdio: bool
    mcp_http: bool
    mcp_auto_expand_modules: bool
    market_sim_enabled: bool
    rag_v3: bool
    deep_recall: bool
    why_library: bool
    residual_production: bool
    chat_streaming: bool
    chat_sse: bool
    cognition_enabled: bool
    cognition_shadow: bool
    cognition_iterative_loop: bool
    cognition_belief_state: bool
    cognition_neuro: bool
    cognition_adaptive_depth: bool
    cognition_delegation: bool
    cognition_experience_learning: bool
    # Wave 0 — durable kernel / architecture guardrails (leases takeover, full envelope emission)
    durable_kernel: bool
    # Wave 2 — evaluation as release authority (persist reports, scorecards, promotion gates)
    eval_platform: bool
    # Wave 3 — managed local model serving + measured routing
    model_serving: bool
    # Wave 4 — context compiler / scoped memory / retrieval thresholds
    context_substrate: bool
    # Wave 5 — capability world interface (receipts, secrets broker, browser worker)
    capability_world: bool
    # Wave 6 — coding/research frontier (semantic map, claim graphs, reproducibility)
    coding_research_frontier: bool
    # Wave 7 — multimodal + realtime voice (media/voice fixture adapters)
    multimodal_realtime: bool
    # Wave 8 — industrial data + training factory (mixtures, integrity gate)
    data_training_factory: bool
    # Wave 9 — post-training improvement flywheel (prefs/DPO/promotion)
    posttraining_flywheel: bool


@dataclass(frozen=True)
class CodingSettings:
    """Coding Agent control-plane settings (workspace + loop bounds)."""

    workspace: Path
    max_rounds: int = 12
    max_file_bytes: int = 1_000_000
    command_allowlist: tuple[str, ...] = (
        "python",
        "python3",
        "pytest",
        "npm",
        "npx",
        "node",
        "git",
    )
    temperature: float = 0.1
    token_budget: int = 24_000
    reserve_response_tokens: int = 1024
    max_file_chars: int = 8000


@dataclass(frozen=True)
class MarketSimSettings:
    """Market simulation control-plane settings (data root + worker bounds)."""

    markets_root: Path
    bars_per_slice: int = 50
    default_initial_cash: float = 100_000.0


@dataclass(frozen=True)
class NeuroRuntimeSettings:
    residual_kind: str  # unsupported | deterministic | hf | vllm | llama_cpp | trt
    residual_model_id: str | None
    residual_device: str
    absorb_default_limit: int
    residual_load_weights: bool = False  # high-memory / dev-only HF weight load
    residual_hook_layers: tuple[int, ...] = ()
    cortex_max_k: int = 2
    memory_tier0_max_slots: int = 64
    residual_server_url: str | None = None


@dataclass(frozen=True)
class WorkersSettings:
    """Generic execution-fabric worker supervisor / pool knobs.

    Flat fields map 1:1 to settings catalog paths (depth-2 control plane).
    Env names match ``Data.modules.workers.settings.load_worker_settings``.
    """

    enabled: bool = True
    supervisor_enabled: bool = True
    externalize_api_runners: bool = True
    heartbeat_seconds: float = 5.0
    lease_ttl_seconds: float = 30.0
    poll_seconds: float = 0.5
    shutdown_grace_seconds: float = 30.0
    restart_max_attempts: int = 5
    restart_window_seconds: float = 120.0
    restart_base_backoff: float = 2.0
    restart_max_backoff: float = 60.0
    supervisor_lease_ttl_seconds: float = 20.0
    pool_db_commit_count: int = 1


@dataclass(frozen=True)
class DbCommitSettings:
    """DB Commit Coordinator — serialized COMMIT_WRITE fabric knobs."""

    enabled: bool = True
    max_pending_count: int = 2_000
    max_pending_bytes: int = 2_147_483_648
    max_batch_rows: int = 1_000
    target_transaction_ms: float = 250.0
    retry_limit: int = 8
    spool_retention_hours: float = 72.0
    applied_retention_hours: float = 24.0
    priority_aging_seconds: float = 120.0


@dataclass(frozen=True)
class ResourceLimits:
    max_model_concurrency: int
    max_function_concurrency: int
    max_job_concurrency: int
    max_history_messages: int
    background_ram_headroom: float = 512.0
    background_vram_headroom: float = 256.0


@dataclass(frozen=True)
class ContextSettings:
    token_budget: int
    reserve_response_tokens: int
    max_knowledge_chars: int
    auto_budget: bool = True
    max_context_fraction: float = 0.72
    reserve_response_fraction: float = 0.18
    minimum_response_tokens: int = 256
    retrieval_fraction: float = 0.35
    memory_fraction: float = 0.2
    history_fraction: float = 0.25


@dataclass(frozen=True)
class InferenceSettings:
    """Inference-efficiency plane knobs (Task C). Catalog paths: inference.*."""

    tokenizer_mode: str = "auto"
    context_safety_margin: float = 0.03
    caches_enabled: bool = True
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = 0.92
    exact_result_cache_enabled: bool = False
    token_cache_max_entries: int = 4096
    context_cache_max_entries: int = 256
    prefix_cache_mode: str = "auto"
    continuous_batching_mode: str = "auto"
    speculative_decoding_mode: str = "auto"
    observability_enabled: bool = True


@dataclass(frozen=True)
class NetworkSettings:
    allow_outbound: bool


@dataclass(frozen=True)
class ArtifactSettings:
    root: Path


@dataclass(frozen=True)
class BackupSettings:
    root: Path


@dataclass(frozen=True)
class ChaosSettings:
    enabled: bool
    latency_ms: int
    error_rate: float


@dataclass(frozen=True)
class ResearchIntegrationSettings:
    """External data/research integration knobs (secrets + endpoints)."""

    hf_token: str = ""
    web_search_endpoint: str | None = None
    web_search_api_key: str = ""
    training_fixture: bool = False
    corpus_root: str = ""
    auto_promote_verified_knowledge: bool = True
    datasets_auto_index_ready_to_knowledge: bool = True
    # Dataset learning / job runner: inprocess | external | none
    dataset_jobs_runner: str = "inprocess"
    dataset_index_batch_size: int = 50
    dataset_max_relations_per_doc: int = 24
    dataset_extract_relations: bool = True
    # Source ingestion worker: inprocess | external | none
    source_ingestion_runner: str = "inprocess"


@dataclass(frozen=True)
class Settings:
    """Canonical LEVIATHAN settings.

    Precedence (Settings Control Plane):
      hard safety invariants
        > persisted operator overrides (when allowed)
        > environment / .env defaults

    Bootstrap-critical values (especially database_path) remain environment-owned
    and are never sourced from the SQLite override store.

    Nested domains are the source of truth. Flat compatibility properties
    preserve existing callers until they migrate.
    """

    runtime: RuntimeSettings
    model: ModelSettings
    knowledge: KnowledgeSettings
    reasoning: ReasoningSettings
    verification: VerificationSettings
    features: FeatureFlags
    coding: CodingSettings
    market_sim: MarketSimSettings
    neuro_runtime: NeuroRuntimeSettings
    workers: WorkersSettings
    db_commit: DbCommitSettings
    resources: ResourceLimits
    context: ContextSettings
    inference: InferenceSettings
    network: NetworkSettings
    artifacts: ArtifactSettings
    backup: BackupSettings
    chaos: ChaosSettings
    research_integration: ResearchIntegrationSettings
    managed_serving: ManagedServingSettings
    database_path: Path

    # --- Compatibility accessors (Step 1 call sites) ---

    @property
    def llm_base_url(self) -> str:
        return self.model.base_url

    @property
    def llm_model(self) -> str | None:
        return self.model.model

    @property
    def llm_api_key(self) -> str:
        return self.model.api_key

    @property
    def llm_timeout_seconds(self) -> float:
        return self.model.timeout_seconds

    @property
    def knowledge_top_k(self) -> int:
        return self.knowledge.top_k

    @property
    def max_history_messages(self) -> int:
        return self.resources.max_history_messages

    @property
    def reasoning_enabled(self) -> bool:
        return self.reasoning.enabled

    def public_summary(self) -> dict:
        """Non-secret configuration snapshot for health/diagnostics."""
        return {
            "runtime": {
                "host": self.runtime.host,
                "port": self.runtime.port,
                "loopback_only": self.runtime.loopback_only,
            },
            "model": {
                "base_url": self.model.base_url,
                "model": self.model.model,
                "timeout_seconds": self.model.timeout_seconds,
            },
            "knowledge": {
                "top_k": self.knowledge.top_k,
                "data_root": str(self.knowledge.data_root),
                "chunk_max_chars": self.knowledge.chunk_max_chars,
                "chunk_overlap": self.knowledge.chunk_overlap,
                "embedding_provider": self.knowledge.embedding_provider,
                "embedding_model": self.knowledge.embedding_model,
                "reranker_model": self.knowledge.reranker_model,
                "deep_recall_budget": self.knowledge.deep_recall_budget,
                "rerank_policy": self.knowledge.rerank_policy,
                "rerank_candidate_count": self.knowledge.rerank_candidate_count,
                "rerank_final_count": self.knowledge.rerank_final_count,
                "min_retrieval_score": self.knowledge.min_retrieval_score,
                "min_confidence": self.knowledge.min_confidence,
                "query_expansion": self.knowledge.query_expansion,
                "max_query_expansions": self.knowledge.max_query_expansions,
                "max_retrieval_rounds": self.knowledge.max_retrieval_rounds,
                "diversity_enabled": self.knowledge.diversity_enabled,
                "diversity_strength": self.knowledge.diversity_strength,
                "lexical_enabled": self.knowledge.lexical_enabled,
                "dense_enabled": self.knowledge.dense_enabled,
                "hybrid_enabled": self.knowledge.hybrid_enabled,
                "rrf_k": self.knowledge.rrf_k,
                "contradiction_detection": self.knowledge.contradiction_detection,
                "retrieval_trace": self.knowledge.retrieval_trace,
                "atlas_retrieval": self.knowledge.atlas_retrieval,
                "atlas_expansion_depth": self.knowledge.atlas_expansion_depth,
                "auto_dedupe": self.knowledge.auto_dedupe,
                "integrity_checks": self.knowledge.integrity_checks,
            },
            "reasoning": {
                "enabled": self.reasoning.enabled,
                "default_mode": self.reasoning.default_mode,
                "allow_fast_path": self.reasoning.allow_fast_path,
                "minimum_evidence_coverage": self.reasoning.minimum_evidence_coverage,
                "uncertainty_deep_threshold": self.reasoning.uncertainty_deep_threshold,
                "contradiction_replan_threshold": self.reasoning.contradiction_replan_threshold,
                "max_replans_global": self.reasoning.max_replans_global,
                "max_retries_global": self.reasoning.max_retries_global,
                "require_verification_for_high_risk": self.reasoning.require_verification_for_high_risk,
                "require_grounding_for_knowledge_tasks": self.reasoning.require_grounding_for_knowledge_tasks,
                "fast_max_wall_time_seconds": self.reasoning.fast_max_wall_time_seconds,
                "fast_max_model_calls": self.reasoning.fast_max_model_calls,
                "fast_max_model_tokens": self.reasoning.fast_max_model_tokens,
                "fast_max_retrieval_rounds": self.reasoning.fast_max_retrieval_rounds,
                "fast_max_critic_passes": self.reasoning.fast_max_critic_passes,
                "fast_max_tool_calls": self.reasoning.fast_max_tool_calls,
                "fast_max_agent_delegations": self.reasoning.fast_max_agent_delegations,
                "fast_max_iterations": self.reasoning.fast_max_iterations,
                "fast_max_context_tokens": self.reasoning.fast_max_context_tokens,
                "standard_max_wall_time_seconds": self.reasoning.standard_max_wall_time_seconds,
                "standard_max_model_calls": self.reasoning.standard_max_model_calls,
                "standard_max_model_tokens": self.reasoning.standard_max_model_tokens,
                "standard_max_retrieval_rounds": self.reasoning.standard_max_retrieval_rounds,
                "standard_max_critic_passes": self.reasoning.standard_max_critic_passes,
                "standard_max_tool_calls": self.reasoning.standard_max_tool_calls,
                "standard_max_agent_delegations": self.reasoning.standard_max_agent_delegations,
                "standard_max_iterations": self.reasoning.standard_max_iterations,
                "standard_max_context_tokens": self.reasoning.standard_max_context_tokens,
                "deep_max_wall_time_seconds": self.reasoning.deep_max_wall_time_seconds,
                "deep_max_model_calls": self.reasoning.deep_max_model_calls,
                "deep_max_model_tokens": self.reasoning.deep_max_model_tokens,
                "deep_max_retrieval_rounds": self.reasoning.deep_max_retrieval_rounds,
                "deep_max_critic_passes": self.reasoning.deep_max_critic_passes,
                "deep_max_tool_calls": self.reasoning.deep_max_tool_calls,
                "deep_max_agent_delegations": self.reasoning.deep_max_agent_delegations,
                "deep_max_iterations": self.reasoning.deep_max_iterations,
                "deep_max_context_tokens": self.reasoning.deep_max_context_tokens,
                "maximum_max_wall_time_seconds": self.reasoning.maximum_max_wall_time_seconds,
                "maximum_max_model_calls": self.reasoning.maximum_max_model_calls,
                "maximum_max_model_tokens": self.reasoning.maximum_max_model_tokens,
                "maximum_max_retrieval_rounds": self.reasoning.maximum_max_retrieval_rounds,
                "maximum_max_critic_passes": self.reasoning.maximum_max_critic_passes,
                "maximum_max_tool_calls": self.reasoning.maximum_max_tool_calls,
                "maximum_max_agent_delegations": self.reasoning.maximum_max_agent_delegations,
                "maximum_max_iterations": self.reasoning.maximum_max_iterations,
                "maximum_max_context_tokens": self.reasoning.maximum_max_context_tokens,
            },
            "verification": {
                "factual_grounding": self.verification.factual_grounding,
                "contradiction_check": self.verification.contradiction_check,
                "require_evidence": self.verification.require_evidence,
                "citation_required": self.verification.citation_required,
                "unmeasured_blocks_completion": self.verification.unmeasured_blocks_completion,
            },
            "features": {
                "reasoning_iterative_retrieval": self.features.reasoning_iterative_retrieval,
                "memory_semantic": self.features.memory_semantic,
                "neuro_enabled": self.features.neuro_enabled,
                "neuro_associative_memory": self.features.neuro_associative_memory,
                "neuro_process_critic": self.features.neuro_process_critic,
                "neuro_residual_injection": self.features.neuro_residual_injection,
                "neuro_cortex": self.features.neuro_cortex,
                "neuro_memory_tiers": self.features.neuro_memory_tiers,
                "neuro_residual_orchestrator": self.features.neuro_residual_orchestrator,
                "neuro_cortex_blocks": self.features.neuro_cortex_blocks,
                "neuro_contrastive_training": self.features.neuro_contrastive_training,
                "neuro_soak_long": self.features.neuro_soak_long,
                "neuro_training_real_worker": self.features.neuro_training_real_worker,
                "module_manager_enabled": self.features.module_manager_enabled,
                "module_manager_subprocess": self.features.module_manager_subprocess,
                "agents_enabled": self.features.agents_enabled,
                "coding_enabled": self.features.coding_enabled,
                "mcp_enabled": self.features.mcp_enabled,
                "mcp_stdio": self.features.mcp_stdio,
                "mcp_http": self.features.mcp_http,
                "mcp_auto_expand_modules": self.features.mcp_auto_expand_modules,
                "market_sim_enabled": self.features.market_sim_enabled,
                "rag_v3": self.features.rag_v3,
                "deep_recall": self.features.deep_recall,
                "why_library": self.features.why_library,
                "residual_production": self.features.residual_production,
                "chat_streaming": self.features.chat_streaming,
                "chat_sse": self.features.chat_sse,
                "cognition_enabled": self.features.cognition_enabled,
                "cognition_shadow": self.features.cognition_shadow,
                "cognition_iterative_loop": self.features.cognition_iterative_loop,
                "cognition_belief_state": self.features.cognition_belief_state,
                "cognition_neuro": self.features.cognition_neuro,
                "cognition_adaptive_depth": self.features.cognition_adaptive_depth,
                "cognition_delegation": self.features.cognition_delegation,
                "cognition_experience_learning": self.features.cognition_experience_learning,
                "durable_kernel": self.features.durable_kernel,
                "eval_platform": self.features.eval_platform,
                "model_serving": self.features.model_serving,
                "context_substrate": self.features.context_substrate,
                "capability_world": self.features.capability_world,
                "coding_research_frontier": self.features.coding_research_frontier,
                "multimodal_realtime": self.features.multimodal_realtime,
                "data_training_factory": self.features.data_training_factory,
                "posttraining_flywheel": self.features.posttraining_flywheel,
            },
            "coding": {
                "enabled": self.features.coding_enabled,
                "max_rounds": self.coding.max_rounds,
                "max_file_bytes": self.coding.max_file_bytes,
                "temperature": self.coding.temperature,
                # Workspace path omitted from public summary (operator-local root).
                "workspace_configured": bool(str(self.coding.workspace).strip()),
            },
            "market_sim": {
                "enabled": self.features.market_sim_enabled,
                "markets_root_configured": bool(str(self.market_sim.markets_root).strip()),
                "bars_per_slice": self.market_sim.bars_per_slice,
                "default_initial_cash": self.market_sim.default_initial_cash,
            },
            "neuro_runtime": {
                "residual_kind": self.neuro_runtime.residual_kind,
                "residual_model_id": self.neuro_runtime.residual_model_id,
                "residual_device": self.neuro_runtime.residual_device,
                "absorb_default_limit": self.neuro_runtime.absorb_default_limit,
                "residual_load_weights": self.neuro_runtime.residual_load_weights,
                "residual_hook_layers": list(self.neuro_runtime.residual_hook_layers),
                "cortex_max_k": self.neuro_runtime.cortex_max_k,
                "memory_tier0_max_slots": self.neuro_runtime.memory_tier0_max_slots,
                "residual_server_url": self.neuro_runtime.residual_server_url,
            },
            "resources": {
                "max_model_concurrency": self.resources.max_model_concurrency,
                "max_function_concurrency": self.resources.max_function_concurrency,
                "max_job_concurrency": self.resources.max_job_concurrency,
                "max_history_messages": self.resources.max_history_messages,
            },
            "context": {
                "token_budget": self.context.token_budget,
                "reserve_response_tokens": self.context.reserve_response_tokens,
                "max_knowledge_chars": self.context.max_knowledge_chars,
                "auto_budget": self.context.auto_budget,
                "max_context_fraction": self.context.max_context_fraction,
                "reserve_response_fraction": self.context.reserve_response_fraction,
                "minimum_response_tokens": self.context.minimum_response_tokens,
                "retrieval_fraction": self.context.retrieval_fraction,
                "memory_fraction": self.context.memory_fraction,
                "history_fraction": self.context.history_fraction,
            },
            "network": {"allow_outbound": self.network.allow_outbound},
            "artifacts": {"root": str(self.artifacts.root)},
            "backup": {"root": str(self.backup.root)},
            "chaos": {
                "enabled": self.chaos.enabled,
                "latency_ms": self.chaos.latency_ms,
                "error_rate": self.chaos.error_rate,
            },
            "research_integration": {
                "hf_token_configured": bool(self.research_integration.hf_token.strip()),
                "web_search_endpoint": self.research_integration.web_search_endpoint,
                "web_search_key_configured": bool(
                    self.research_integration.web_search_api_key.strip()
                ),
                "training_fixture": self.research_integration.training_fixture,
                "corpus_root": self.research_integration.corpus_root or None,
                "auto_promote_verified_knowledge": (
                    self.research_integration.auto_promote_verified_knowledge
                ),
                "datasets_auto_index_ready_to_knowledge": (
                    self.research_integration.datasets_auto_index_ready_to_knowledge
                ),
                "dataset_jobs_runner": self.research_integration.dataset_jobs_runner,
                "dataset_index_batch_size": self.research_integration.dataset_index_batch_size,
                "dataset_extract_relations": self.research_integration.dataset_extract_relations,
                "source_ingestion_runner": self.research_integration.source_ingestion_runner,
            },
            "database_path": str(self.database_path),
        }

    @classmethod
    def from_env(cls) -> "Settings":
        host = (_env_raw("LEVIATHAN_HOST", "127.0.0.1") or "127.0.0.1").strip()
        port = _env_int("LEVIATHAN_PORT", 8765, minimum=1, maximum=65535)
        loopback_only = _env_bool("LEVIATHAN_LOOPBACK_ONLY", True)
        if loopback_only and host not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigurationError(
                "LEVIATHAN_LOOPBACK_ONLY=true requires LEVIATHAN_HOST to be a loopback address"
            )

        base_url = (_env_raw("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1") or "").strip().rstrip("/")
        if not base_url:
            raise ConfigurationError("LEVIATHAN_LLM_BASE_URL cannot be empty")
        if "://" not in base_url:
            raise ConfigurationError(f"LEVIATHAN_LLM_BASE_URL must include a scheme: {base_url!r}")

        model = (_env_raw("LEVIATHAN_LLM_MODEL", "") or "").strip() or None
        api_key = _env_raw("LEVIATHAN_LLM_API_KEY", "not-needed") or "not-needed"
        timeout = _env_float("LEVIATHAN_LLM_TIMEOUT_SECONDS", 90.0, minimum=1.0)

        db_raw = _env_raw("LEVIATHAN_DATABASE_PATH", "Data/backend/data/leviathan.db") or "Data/backend/data/leviathan.db"
        database_path = _resolve_path(db_raw)

        # Bulk corpora root. Configurable; default matches master program.
        data_root_raw = _env_raw("LEVIATHAN_DATA_ROOT", "ModelData") or "ModelData"
        data_root = _resolve_data_root(data_root_raw)

        knowledge_top_k = _env_int("LEVIATHAN_KNOWLEDGE_TOP_K", 5, minimum=1, maximum=100)
        chunk_max = _env_int("LEVIATHAN_KNOWLEDGE_CHUNK_MAX_CHARS", 1200, minimum=200, maximum=20_000)
        chunk_overlap = _env_int("LEVIATHAN_KNOWLEDGE_CHUNK_OVERLAP", 120, minimum=0, maximum=2000)
        if chunk_overlap >= chunk_max:
            raise ConfigurationError("LEVIATHAN_KNOWLEDGE_CHUNK_OVERLAP must be < CHUNK_MAX_CHARS")
        max_history = _env_int("LEVIATHAN_MAX_HISTORY_MESSAGES", 24, minimum=4, maximum=500)

        artifacts_raw = _env_raw("LEVIATHAN_ARTIFACTS_ROOT", "Data/backend/data/artifacts") or "Data/backend/data/artifacts"
        artifacts_root = _resolve_path(artifacts_raw)
        backup_raw = _env_raw("LEVIATHAN_BACKUP_ROOT", "Data/backend/data/backups") or "Data/backend/data/backups"
        backup_root = _resolve_path(backup_raw)
        chaos_enabled = _env_bool("LEVIATHAN_CHAOS_ENABLED", False)
        chaos_latency = _env_int("LEVIATHAN_CHAOS_LATENCY_MS", 0, minimum=0, maximum=60_000)
        chaos_error_rate = _env_float("LEVIATHAN_CHAOS_ERROR_RATE", 0.0, minimum=0.0)
        if chaos_error_rate > 1.0:
            raise ConfigurationError("LEVIATHAN_CHAOS_ERROR_RATE must be <= 1.0")

        coding_enabled = _env_bool("LEVIATHAN_FEATURE_CODING", False)
        mcp_enabled = _env_bool("LEVIATHAN_FEATURE_MCP", False)
        # Hierarchical children: default true only when parent is enabled; explicit
        # child=true with parent=false is rejected in validate().
        mcp_stdio = _env_bool("LEVIATHAN_FEATURE_MCP_STDIO", True) if mcp_enabled else False
        mcp_http = _env_bool("LEVIATHAN_FEATURE_MCP_HTTP", True) if mcp_enabled else False
        mcp_auto_expand = (
            _env_bool("LEVIATHAN_FEATURE_MCP_AUTO_EXPAND_MODULES", True) if mcp_enabled else False
        )
        # Default ON for local/dev so TradingCenter Market Sim opens usable.
        # Explicit LEVIATHAN_FEATURE_MARKET_SIM=false still disables.
        market_sim_enabled = _env_bool("LEVIATHAN_FEATURE_MARKET_SIM", True)
        rag_v3 = _env_bool("LEVIATHAN_FEATURE_RAG_V3", True)
        deep_recall = _env_bool("LEVIATHAN_FEATURE_DEEP_RECALL", True)
        why_library = _env_bool("LEVIATHAN_FEATURE_WHY_LIBRARY", True)
        residual_production = _env_bool("LEVIATHAN_FEATURE_RESIDUAL_PRODUCTION", True)
        chat_streaming = _env_bool("LEVIATHAN_FEATURE_CHAT_STREAMING", False)
        chat_sse = _env_bool("LEVIATHAN_FEATURE_CHAT_SSE", False)
        cognition_enabled = _env_bool("LEVIATHAN_FEATURE_COGNITION", True)
        # Children are read independently; hierarchy enforced in validate().
        cognition_shadow = _env_bool("LEVIATHAN_FEATURE_COGNITION_SHADOW", False)
        cognition_iterative = _env_bool("LEVIATHAN_FEATURE_COGNITION_ITERATIVE_LOOP", True)
        cognition_belief = _env_bool("LEVIATHAN_FEATURE_COGNITION_BELIEF_STATE", True)
        cognition_neuro = _env_bool("LEVIATHAN_FEATURE_COGNITION_NEURO", True)
        cognition_adaptive = _env_bool("LEVIATHAN_FEATURE_COGNITION_ADAPTIVE_DEPTH", True)
        cognition_delegation = _env_bool("LEVIATHAN_FEATURE_COGNITION_DELEGATION", True)
        cognition_experience = _env_bool("LEVIATHAN_FEATURE_COGNITION_EXPERIENCE_LEARNING", True)
        durable_kernel = _env_bool("LEVIATHAN_FEATURE_DURABLE_KERNEL", False)
        eval_platform = _env_bool("LEVIATHAN_FEATURE_EVAL_PLATFORM", True)
        model_serving = _env_bool("LEVIATHAN_FEATURE_MODEL_SERVING", True)
        context_substrate = _env_bool("LEVIATHAN_FEATURE_CONTEXT_SUBSTRATE", True)
        capability_world = _env_bool("LEVIATHAN_FEATURE_CAPABILITY_WORLD", True)
        coding_research_frontier = _env_bool("LEVIATHAN_FEATURE_CODING_RESEARCH", True)
        multimodal_realtime = _env_bool("LEVIATHAN_FEATURE_MULTIMODAL_REALTIME", True)
        data_training_factory = _env_bool("LEVIATHAN_FEATURE_DATA_TRAINING_FACTORY", True)
        posttraining_flywheel = _env_bool("LEVIATHAN_FEATURE_POSTTRAINING_FLYWHEEL", True)
        embedding_provider = (
            _env_raw("LEVIATHAN_EMBEDDING_PROVIDER", "auto" if rag_v3 else "null") or ("auto" if rag_v3 else "null")
        ).strip().lower()
        embedding_model = (_env_raw("LEVIATHAN_EMBEDDING_MODEL", "") or "").strip() or None
        reranker_model = (_env_raw("LEVIATHAN_RERANKER_MODEL", "") or "").strip() or None
        coding_workspace_raw = (
            _env_raw("LEVIATHAN_CODING_WORKSPACE", "codingworkspace")
            or "codingworkspace"
        )
        coding_workspace = _resolve_data_root(coding_workspace_raw)
        markets_root_raw = (
            _env_raw("LEVIATHAN_MARKETS_ROOT", "") or ""
        ).strip()
        if not markets_root_raw:
            markets_root_raw = str(data_root / "markets")
        markets_root = _resolve_data_root(markets_root_raw)
        allowlist_raw = (
            _env_raw(
                "LEVIATHAN_CODING_COMMAND_ALLOWLIST",
                "python,python3,pytest,npm,npx,node,git",
            )
            or "python,python3,pytest,npm,npx,node,git"
        )
        command_allowlist = tuple(
            part.strip() for part in allowlist_raw.split(",") if part.strip()
        )

        settings = cls(
            runtime=RuntimeSettings(host=host, port=port, loopback_only=loopback_only),
            model=ModelSettings(
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout_seconds=timeout,
            ),
            managed_serving=ManagedServingSettings(
                enabled=_env_bool("LEVIATHAN_MANAGED_MODEL_SERVING", True),
                allow_inproc_fixture=_env_bool("LEVIATHAN_ALLOW_INPROC_MODEL_FIXTURE", False),
                llama_cpp_executable=(
                    _env_raw("LEVIATHAN_LLAMA_CPP_EXECUTABLE", "") or ""
                ).strip()
                or None,
                vllm_executable=(
                    _env_raw("LEVIATHAN_VLLM_EXECUTABLE", "") or ""
                ).strip()
                or None,
                bind_host=(
                    _env_raw("LEVIATHAN_MANAGED_BIND_HOST", "127.0.0.1") or "127.0.0.1"
                ).strip(),
                port_start=_env_int("LEVIATHAN_MANAGED_PORT_START", 29100, minimum=1024, maximum=65000),
                port_end=_env_int("LEVIATHAN_MANAGED_PORT_END", 29200, minimum=1024, maximum=65535),
                worker_startup_timeout_seconds=_env_float(
                    "LEVIATHAN_MANAGED_WORKER_STARTUP_TIMEOUT_SECONDS", 120.0, minimum=5.0
                ),
                worker_shutdown_timeout_seconds=_env_float(
                    "LEVIATHAN_MANAGED_WORKER_SHUTDOWN_TIMEOUT_SECONDS", 15.0, minimum=1.0
                ),
                default_residency_policy=(
                    _env_raw("LEVIATHAN_DEFAULT_RESIDENCY_POLICY", "IDLE_UNLOAD") or "IDLE_UNLOAD"
                ).strip().upper(),
                default_idle_unload_seconds=_env_float(
                    "LEVIATHAN_DEFAULT_IDLE_UNLOAD_SECONDS", 300.0, minimum=0.0
                ),
                min_ram_reserve_bytes=_env_int(
                    "LEVIATHAN_MIN_RAM_RESERVE_BYTES",
                    1_073_741_824,
                    minimum=0,
                    maximum=64_000_000_000,
                ),
                min_vram_reserve_bytes=_env_int(
                    "LEVIATHAN_MIN_VRAM_RESERVE_BYTES",
                    536_870_912,
                    minimum=0,
                    maximum=64_000_000_000,
                ),
                max_managed_resident_models=_env_int(
                    "LEVIATHAN_MAX_MANAGED_RESIDENT_MODELS", 4, minimum=1, maximum=64
                ),
            ),
            knowledge=KnowledgeSettings(
                top_k=knowledge_top_k,
                data_root=data_root,
                chunk_max_chars=chunk_max,
                chunk_overlap=chunk_overlap,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                embedding_hash_dimensions=_env_int(
                    "LEVIATHAN_EMBEDDING_HASH_DIMENSIONS", 256, minimum=32, maximum=4096
                ),
                reranker_model=reranker_model,
                deep_recall_budget=_env_int(
                    "LEVIATHAN_DEEP_RECALL_BUDGET", 800, minimum=64, maximum=20_000
                ),
                rerank_policy=(
                    _env_raw("LEVIATHAN_RERANK_POLICY", "auto") or "auto"
                ).strip().lower(),
                rerank_candidate_count=_env_int(
                    "LEVIATHAN_RERANK_CANDIDATE_COUNT", 20, minimum=1, maximum=500
                ),
                rerank_final_count=_env_int(
                    "LEVIATHAN_RERANK_FINAL_COUNT", 5, minimum=1, maximum=100
                ),
                min_retrieval_score=_env_float(
                    "LEVIATHAN_KNOWLEDGE_MIN_RETRIEVAL_SCORE", 0.0, minimum=0.0, maximum=1.0
                ),
                min_confidence=_env_float(
                    "LEVIATHAN_KNOWLEDGE_MIN_CONFIDENCE", 0.0, minimum=0.0, maximum=1.0
                ),
                query_expansion=_env_bool("LEVIATHAN_KNOWLEDGE_QUERY_EXPANSION", True),
                max_query_expansions=_env_int(
                    "LEVIATHAN_KNOWLEDGE_MAX_QUERY_EXPANSIONS", 4, minimum=0, maximum=32
                ),
                max_retrieval_rounds=_env_int(
                    "LEVIATHAN_KNOWLEDGE_MAX_RETRIEVAL_ROUNDS", 3, minimum=1, maximum=16
                ),
                diversity_enabled=_env_bool("LEVIATHAN_KNOWLEDGE_DIVERSITY_ENABLED", True),
                diversity_strength=_env_float(
                    "LEVIATHAN_KNOWLEDGE_DIVERSITY_STRENGTH", 0.3, minimum=0.0, maximum=1.0
                ),
                lexical_enabled=_env_bool("LEVIATHAN_KNOWLEDGE_LEXICAL_ENABLED", True),
                dense_enabled=_env_bool("LEVIATHAN_KNOWLEDGE_DENSE_ENABLED", True),
                hybrid_enabled=_env_bool("LEVIATHAN_KNOWLEDGE_HYBRID_ENABLED", True),
                rrf_k=_env_int("LEVIATHAN_KNOWLEDGE_RRF_K", 60, minimum=1, maximum=10_000),
                contradiction_detection=_env_bool(
                    "LEVIATHAN_KNOWLEDGE_CONTRADICTION_DETECTION", True
                ),
                retrieval_trace=_env_bool("LEVIATHAN_KNOWLEDGE_RETRIEVAL_TRACE", True),
                atlas_retrieval=_env_bool("LEVIATHAN_KNOWLEDGE_ATLAS_RETRIEVAL", True),
                atlas_expansion_depth=_env_int(
                    "LEVIATHAN_KNOWLEDGE_ATLAS_EXPANSION_DEPTH", 1, minimum=0, maximum=8
                ),
                auto_dedupe=_env_bool("LEVIATHAN_KNOWLEDGE_AUTO_DEDUPE", True),
                integrity_checks=_env_bool("LEVIATHAN_KNOWLEDGE_INTEGRITY_CHECKS", True),
                commit_concurrency=_env_int(
                    "LEVIATHAN_WORKERS_POOL_KNOWLEDGE_COMMIT_COUNT", 0, minimum=0, maximum=1
                ),
            ),
            reasoning=ReasoningSettings(
                enabled=_env_bool("LEVIATHAN_REASONING_ENABLED", True),
                default_mode=(
                    _env_raw("LEVIATHAN_REASONING_DEFAULT_MODE", "adaptive") or "adaptive"
                ).strip().lower(),
                allow_fast_path=_env_bool("LEVIATHAN_REASONING_ALLOW_FAST_PATH", True),
                minimum_evidence_coverage=_env_float(
                    "LEVIATHAN_REASONING_MINIMUM_EVIDENCE_COVERAGE",
                    0.35,
                    minimum=0.0,
                    maximum=1.0,
                ),
                uncertainty_deep_threshold=_env_float(
                    "LEVIATHAN_REASONING_UNCERTAINTY_DEEP_THRESHOLD",
                    0.75,
                    minimum=0.0,
                    maximum=1.0,
                ),
                contradiction_replan_threshold=_env_float(
                    "LEVIATHAN_REASONING_CONTRADICTION_REPLAN_THRESHOLD",
                    0.3,
                    minimum=0.0,
                    maximum=1.0,
                ),
                max_replans_global=_env_int(
                    "LEVIATHAN_REASONING_MAX_REPLANS_GLOBAL", 4, minimum=0, maximum=64
                ),
                max_retries_global=_env_int(
                    "LEVIATHAN_REASONING_MAX_RETRIES_GLOBAL", 3, minimum=0, maximum=64
                ),
                require_verification_for_high_risk=_env_bool(
                    "LEVIATHAN_REASONING_REQUIRE_VERIFICATION_FOR_HIGH_RISK", True
                ),
                require_grounding_for_knowledge_tasks=_env_bool(
                    "LEVIATHAN_REASONING_REQUIRE_GROUNDING_FOR_KNOWLEDGE_TASKS", True
                ),
                **{  # type: ignore[arg-type]
                    k: v
                    for profile, defaults in _REASONING_BUDGET_DEFAULTS.items()
                    for k, v in _reasoning_budget_kwargs(profile, defaults).items()
                },
            ),
            verification=VerificationSettings(
                factual_grounding=_env_bool("LEVIATHAN_VERIFICATION_FACTUAL_GROUNDING", True),
                contradiction_check=_env_bool("LEVIATHAN_VERIFICATION_CONTRADICTION_CHECK", True),
                require_evidence=_env_bool("LEVIATHAN_VERIFICATION_REQUIRE_EVIDENCE", True),
                citation_required=_env_bool("LEVIATHAN_VERIFICATION_CITATION_REQUIRED", False),
                unmeasured_blocks_completion=_env_bool(
                    "LEVIATHAN_VERIFICATION_UNMEASURED_BLOCKS_COMPLETION", True
                ),
            ),
            features=FeatureFlags(
                reasoning_iterative_retrieval=_env_bool("LEVIATHAN_FEATURE_ITERATIVE_RETRIEVAL", True),
                memory_semantic=_env_bool("LEVIATHAN_FEATURE_MEMORY_SEMANTIC", True),
                neuro_enabled=_env_bool("LEVIATHAN_FEATURE_NEURO", True),
                neuro_associative_memory=_env_bool("LEVIATHAN_FEATURE_NEURO_ASSOCIATIVE_MEMORY", True),
                neuro_process_critic=_env_bool("LEVIATHAN_FEATURE_NEURO_PROCESS_CRITIC", True),
                neuro_residual_injection=_env_bool("LEVIATHAN_FEATURE_NEURO_RESIDUAL_INJECTION", True),
                neuro_cortex=_env_bool("LEVIATHAN_FEATURE_NEURO_CORTEX", True),
                neuro_memory_tiers=_env_bool("LEVIATHAN_FEATURE_NEURO_MEMORY_TIERS", True),
                neuro_residual_orchestrator=_env_bool(
                    "LEVIATHAN_FEATURE_NEURO_RESIDUAL_ORCHESTRATOR", True
                ),
                neuro_cortex_blocks=_env_bool("LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS", True),
                neuro_contrastive_training=_env_bool(
                    "LEVIATHAN_FEATURE_NEURO_CONTRASTIVE_TRAINING", True
                ),
                neuro_soak_long=_env_bool("LEVIATHAN_FEATURE_NEURO_SOAK_LONG", False),
                neuro_training_real_worker=_env_bool("LEVIATHAN_NEURO_TRAINING_REAL_WORKER", False),
                module_manager_enabled=_env_bool("LEVIATHAN_FEATURE_MODULE_MANAGER", False),
                module_manager_subprocess=_env_bool("LEVIATHAN_FEATURE_MODULE_MANAGER_SUBPROCESS", False),
                agents_enabled=_env_bool("LEVIATHAN_FEATURE_AGENTS", False),
                coding_enabled=coding_enabled,
                mcp_enabled=mcp_enabled,
                mcp_stdio=mcp_stdio,
                mcp_http=mcp_http,
                mcp_auto_expand_modules=mcp_auto_expand,
                market_sim_enabled=market_sim_enabled,
                rag_v3=rag_v3,
                deep_recall=deep_recall,
                why_library=why_library,
                residual_production=residual_production,
                chat_streaming=chat_streaming,
                chat_sse=chat_sse,
                cognition_enabled=cognition_enabled,
                cognition_shadow=cognition_shadow,
                cognition_iterative_loop=cognition_iterative,
                cognition_belief_state=cognition_belief,
                cognition_neuro=cognition_neuro,
                cognition_adaptive_depth=cognition_adaptive,
                cognition_delegation=cognition_delegation,
                cognition_experience_learning=cognition_experience,
                durable_kernel=durable_kernel,
                eval_platform=eval_platform,
                model_serving=model_serving,
                context_substrate=context_substrate,
                capability_world=capability_world,
                coding_research_frontier=coding_research_frontier,
                multimodal_realtime=multimodal_realtime,
                data_training_factory=data_training_factory,
                posttraining_flywheel=posttraining_flywheel,
            ),
            coding=CodingSettings(
                workspace=coding_workspace,
                max_rounds=_env_int("LEVIATHAN_CODING_MAX_ROUNDS", 12, minimum=1, maximum=64),
                max_file_bytes=_env_int(
                    "LEVIATHAN_CODING_MAX_FILE_BYTES", 1_000_000, minimum=1024, maximum=50_000_000
                ),
                command_allowlist=command_allowlist or ("python", "python3", "pytest"),
                temperature=_env_float("LEVIATHAN_CODING_TEMPERATURE", 0.1, minimum=0.0),
                token_budget=_env_int("LEVIATHAN_CODING_TOKEN_BUDGET", 24_000, minimum=512, maximum=200_000),
                reserve_response_tokens=_env_int(
                    "LEVIATHAN_CODING_RESERVE_RESPONSE_TOKENS", 1024, minimum=64, maximum=32_000
                ),
                max_file_chars=_env_int(
                    "LEVIATHAN_CODING_MAX_FILE_CHARS", 8000, minimum=200, maximum=200_000
                ),
            ),
            market_sim=MarketSimSettings(
                markets_root=markets_root,
                bars_per_slice=_env_int("LEVIATHAN_MARKET_SIM_BARS_PER_SLICE", 50, minimum=1, maximum=10_000),
                default_initial_cash=_env_float(
                    "LEVIATHAN_MARKET_SIM_INITIAL_CASH", 100_000.0, minimum=1.0
                ),
            ),
            neuro_runtime=NeuroRuntimeSettings(
                residual_kind=(
                    _env_raw("LEVIATHAN_NEURO_RESIDUAL_KIND", "unsupported") or "unsupported"
                ).strip().lower(),
                residual_model_id=(_env_raw("LEVIATHAN_NEURO_RESIDUAL_MODEL", "") or "").strip() or None,
                residual_device=(_env_raw("LEVIATHAN_NEURO_RESIDUAL_DEVICE", "cpu") or "cpu").strip(),
                absorb_default_limit=_env_int("LEVIATHAN_NEURO_ABSORB_LIMIT", 50, minimum=1, maximum=5000),
                residual_load_weights=_env_bool("LEVIATHAN_NEURO_RESIDUAL_LOAD_WEIGHTS", False),
                residual_hook_layers=_parse_int_csv(
                    _env_raw("LEVIATHAN_NEURO_RESIDUAL_HOOK_LAYERS", "") or ""
                ),
                cortex_max_k=_env_int("LEVIATHAN_NEURO_CORTEX_MAX_K", 2, minimum=0, maximum=16),
                memory_tier0_max_slots=_env_int(
                    "LEVIATHAN_NEURO_MEMORY_TIER0_MAX_SLOTS", 64, minimum=1, maximum=10_000
                ),
                residual_server_url=(
                    _env_raw("LEVIATHAN_NEURO_RESIDUAL_SERVER_URL", "") or ""
                ).strip()
                or None,
            ),
            resources=ResourceLimits(
                max_model_concurrency=_env_int("LEVIATHAN_MAX_MODEL_CONCURRENCY", 1, minimum=1, maximum=64),
                max_function_concurrency=_env_int("LEVIATHAN_MAX_FUNCTION_CONCURRENCY", 2, minimum=1, maximum=64),
                max_job_concurrency=_env_int("LEVIATHAN_MAX_JOB_CONCURRENCY", 1, minimum=1, maximum=64),
                max_history_messages=max_history,
                background_ram_headroom=_env_float(
                    "LEVIATHAN_RESOURCE_BACKGROUND_RAM_HEADROOM", 512.0, minimum=0.0
                ),
                background_vram_headroom=_env_float(
                    "LEVIATHAN_RESOURCE_BACKGROUND_VRAM_HEADROOM", 256.0, minimum=0.0
                ),
            ),
            workers=WorkersSettings(
                enabled=_env_bool("LEVIATHAN_WORKERS_ENABLED", True),
                supervisor_enabled=_env_bool("LEVIATHAN_WORKERS_SUPERVISOR_ENABLED", True),
                externalize_api_runners=_env_bool("LEVIATHAN_WORKERS_EXTERNALIZE_API", True),
                heartbeat_seconds=_env_float(
                    "LEVIATHAN_WORKERS_HEARTBEAT_SECONDS", 5.0, minimum=0.5
                ),
                lease_ttl_seconds=_env_float(
                    "LEVIATHAN_WORKERS_LEASE_TTL_SECONDS", 30.0, minimum=2.0
                ),
                poll_seconds=_env_float("LEVIATHAN_WORKERS_POLL_SECONDS", 0.5, minimum=0.05),
                shutdown_grace_seconds=_env_float(
                    "LEVIATHAN_WORKERS_SHUTDOWN_GRACE_SECONDS", 30.0, minimum=1.0
                ),
                restart_max_attempts=_env_int(
                    "LEVIATHAN_WORKERS_RESTART_MAX_ATTEMPTS", 5, minimum=1, maximum=100
                ),
                restart_window_seconds=_env_float(
                    "LEVIATHAN_WORKERS_RESTART_WINDOW_SECONDS", 120.0, minimum=1.0
                ),
                restart_base_backoff=_env_float(
                    "LEVIATHAN_WORKERS_RESTART_BASE_BACKOFF", 2.0, minimum=0.1
                ),
                restart_max_backoff=_env_float(
                    "LEVIATHAN_WORKERS_RESTART_MAX_BACKOFF", 60.0, minimum=1.0
                ),
                supervisor_lease_ttl_seconds=_env_float(
                    "LEVIATHAN_WORKERS_SUPERVISOR_LEASE_TTL_SECONDS", 20.0, minimum=2.0
                ),
                pool_db_commit_count=_env_int(
                    "LEVIATHAN_WORKERS_POOL_DB_COMMIT_COUNT", 1, minimum=0, maximum=1
                ),
            ),
            db_commit=DbCommitSettings(
                enabled=_env_bool("LEVIATHAN_DB_COMMIT_ENABLED", True),
                max_pending_count=_env_int(
                    "LEVIATHAN_DB_COMMIT_MAX_PENDING_COUNT", 2_000, minimum=10
                ),
                max_pending_bytes=_env_int(
                    "LEVIATHAN_DB_COMMIT_MAX_PENDING_BYTES",
                    2_147_483_648,
                    minimum=1_048_576,
                ),
                max_batch_rows=_env_int(
                    "LEVIATHAN_DB_COMMIT_MAX_BATCH_ROWS", 1_000, minimum=50, maximum=50_000
                ),
                target_transaction_ms=_env_float(
                    "LEVIATHAN_DB_COMMIT_TARGET_TRANSACTION_MS", 250.0, minimum=10.0
                ),
                retry_limit=_env_int(
                    "LEVIATHAN_DB_COMMIT_RETRY_LIMIT", 8, minimum=0, maximum=64
                ),
                spool_retention_hours=_env_float(
                    "LEVIATHAN_DB_COMMIT_SPOOL_RETENTION_HOURS", 72.0, minimum=1.0
                ),
                applied_retention_hours=_env_float(
                    "LEVIATHAN_DB_COMMIT_APPLIED_RETENTION_HOURS", 24.0, minimum=0.1
                ),
                priority_aging_seconds=_env_float(
                    "LEVIATHAN_DB_COMMIT_PRIORITY_AGING_SECONDS", 120.0, minimum=1.0
                ),
            ),
            context=ContextSettings(
                token_budget=_env_int("LEVIATHAN_CONTEXT_TOKEN_BUDGET", 6000, minimum=512, maximum=200_000),
                reserve_response_tokens=_env_int(
                    "LEVIATHAN_CONTEXT_RESERVE_RESPONSE_TOKENS", 512, minimum=64, maximum=32_000
                ),
                max_knowledge_chars=_env_int(
                    "LEVIATHAN_CONTEXT_MAX_KNOWLEDGE_CHARS", 1800, minimum=200, maximum=50_000
                ),
                auto_budget=_env_bool("LEVIATHAN_CONTEXT_AUTO_BUDGET", True),
                max_context_fraction=_env_float(
                    "LEVIATHAN_CONTEXT_MAX_CONTEXT_FRACTION", 0.72, minimum=0.05, maximum=1.0
                ),
                reserve_response_fraction=_env_float(
                    "LEVIATHAN_CONTEXT_RESERVE_RESPONSE_FRACTION", 0.18, minimum=0.0, maximum=1.0
                ),
                minimum_response_tokens=_env_int(
                    "LEVIATHAN_CONTEXT_MINIMUM_RESPONSE_TOKENS", 256, minimum=32, maximum=32_000
                ),
                retrieval_fraction=_env_float(
                    "LEVIATHAN_CONTEXT_RETRIEVAL_FRACTION", 0.35, minimum=0.0, maximum=1.0
                ),
                memory_fraction=_env_float(
                    "LEVIATHAN_CONTEXT_MEMORY_FRACTION", 0.2, minimum=0.0, maximum=1.0
                ),
                history_fraction=_env_float(
                    "LEVIATHAN_CONTEXT_HISTORY_FRACTION", 0.25, minimum=0.0, maximum=1.0
                ),
            ),
            inference=InferenceSettings(
                tokenizer_mode=(
                    _env_raw("LEVIATHAN_TOKENIZER_MODE", "auto") or "auto"
                ).strip().lower(),
                context_safety_margin=_env_float(
                    "LEVIATHAN_CONTEXT_SAFETY_MARGIN", 0.03, minimum=0.0, maximum=0.25
                ),
                caches_enabled=_env_bool("LEVIATHAN_INFERENCE_CACHES_ENABLED", True),
                semantic_cache_enabled=_env_bool("LEVIATHAN_SEMANTIC_CACHE_ENABLED", False),
                semantic_cache_threshold=_env_float(
                    "LEVIATHAN_SEMANTIC_CACHE_THRESHOLD", 0.92, minimum=0.5, maximum=0.999
                ),
                exact_result_cache_enabled=_env_bool(
                    "LEVIATHAN_EXACT_RESULT_CACHE_ENABLED", False
                ),
                token_cache_max_entries=_env_int(
                    "LEVIATHAN_TOKEN_CACHE_MAX_ENTRIES", 4096, minimum=64, maximum=100_000
                ),
                context_cache_max_entries=_env_int(
                    "LEVIATHAN_CONTEXT_CACHE_MAX_ENTRIES", 256, minimum=16, maximum=10_000
                ),
                prefix_cache_mode=(
                    _env_raw("LEVIATHAN_PREFIX_CACHE_MODE", "auto") or "auto"
                ).strip().lower(),
                continuous_batching_mode=(
                    _env_raw("LEVIATHAN_CONTINUOUS_BATCHING_MODE", "auto") or "auto"
                ).strip().lower(),
                speculative_decoding_mode=(
                    _env_raw("LEVIATHAN_SPECULATIVE_DECODING_MODE", "auto") or "auto"
                ).strip().lower(),
                observability_enabled=_env_bool("LEVIATHAN_INFERENCE_OBSERVABILITY", True),
            ),
            network=NetworkSettings(allow_outbound=_env_bool("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", False)),
            artifacts=ArtifactSettings(root=artifacts_root),
            backup=BackupSettings(root=backup_root),
            chaos=ChaosSettings(
                enabled=chaos_enabled,
                latency_ms=chaos_latency,
                error_rate=chaos_error_rate,
            ),
            research_integration=ResearchIntegrationSettings(
                hf_token=(_env_raw("LEVIATHAN_HF_TOKEN", "") or "").strip(),
                web_search_endpoint=(
                    (_env_raw("LEVIATHAN_WEB_SEARCH_ENDPOINT", "") or "").strip() or None
                ),
                web_search_api_key=(_env_raw("LEVIATHAN_WEB_SEARCH_API_KEY", "") or "").strip(),
                training_fixture=_env_bool("LEVIATHAN_TRAINING_FIXTURE", False),
                corpus_root=(_env_raw("LEVIATHAN_CORPUS_ROOT", "") or "").strip(),
                auto_promote_verified_knowledge=_env_bool(
                    "LEVIATHAN_RESEARCH_AUTO_PROMOTE_VERIFIED_KNOWLEDGE", True
                ),
                datasets_auto_index_ready_to_knowledge=_env_bool(
                    "LEVIATHAN_DATASETS_AUTO_INDEX_READY_TO_KNOWLEDGE", True
                ),
                dataset_jobs_runner=(
                    (_env_raw("LEVIATHAN_DATASET_JOBS_RUNNER", "inprocess") or "inprocess")
                    .strip()
                    .lower()
                ),
                dataset_index_batch_size=_env_int(
                    "LEVIATHAN_DATASET_INDEX_BATCH_SIZE", 50, minimum=1, maximum=5000
                ),
                dataset_max_relations_per_doc=_env_int(
                    "LEVIATHAN_DATASET_MAX_RELATIONS_PER_DOC", 24, minimum=1, maximum=200
                ),
                dataset_extract_relations=_env_bool(
                    "LEVIATHAN_DATASET_EXTRACT_RELATIONS", True
                ),
                source_ingestion_runner=(
                    (_env_raw("LEVIATHAN_SOURCE_INGESTION_RUNNER", "inprocess") or "inprocess")
                    .strip()
                    .lower()
                ),
            ),
            database_path=database_path,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.chaos.enabled and self.runtime.loopback_only is False:
            raise ConfigurationError(
                "LEVIATHAN_CHAOS_ENABLED=true is refused when loopback_only is false"
            )
        if self.features.neuro_residual_injection and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_RESIDUAL_INJECTION requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_associative_memory and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_ASSOCIATIVE_MEMORY requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_process_critic and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_PROCESS_CRITIC requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_cortex and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_CORTEX requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_memory_tiers and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_MEMORY_TIERS requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_residual_orchestrator and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_RESIDUAL_ORCHESTRATOR requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_cortex_blocks and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_cortex_blocks and not self.features.neuro_cortex:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS requires LEVIATHAN_FEATURE_NEURO_CORTEX=true"
            )
        if self.features.neuro_contrastive_training and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_CONTRASTIVE_TRAINING requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_soak_long and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_NEURO_SOAK_LONG requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.neuro_training_real_worker and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_NEURO_TRAINING_REAL_WORKER requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.chat_sse and not self.features.chat_streaming:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_CHAT_SSE requires LEVIATHAN_FEATURE_CHAT_STREAMING=true"
            )
        if self.features.module_manager_subprocess and not self.features.module_manager_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_MODULE_MANAGER_SUBPROCESS requires LEVIATHAN_FEATURE_MODULE_MANAGER=true"
            )
        if self.features.coding_enabled and not self.features.agents_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_CODING requires LEVIATHAN_FEATURE_AGENTS=true"
            )
        if self.features.mcp_stdio and not self.features.mcp_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_MCP_STDIO requires LEVIATHAN_FEATURE_MCP=true"
            )
        if self.features.mcp_http and not self.features.mcp_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_MCP_HTTP requires LEVIATHAN_FEATURE_MCP=true"
            )
        if self.features.mcp_auto_expand_modules and not self.features.mcp_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_MCP_AUTO_EXPAND_MODULES requires LEVIATHAN_FEATURE_MCP=true"
            )
        if self.features.mcp_enabled and not self.features.mcp_stdio and not self.features.mcp_http:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_MCP=true requires MCP_STDIO and/or MCP_HTTP"
            )
        if self.features.deep_recall and not self.features.rag_v3:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_DEEP_RECALL requires LEVIATHAN_FEATURE_RAG_V3=true"
            )
        if self.features.why_library and not self.features.rag_v3:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_WHY_LIBRARY requires LEVIATHAN_FEATURE_RAG_V3=true"
            )
        if self.features.residual_production and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_RESIDUAL_PRODUCTION requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.residual_production and not self.features.neuro_residual_injection:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_RESIDUAL_PRODUCTION requires LEVIATHAN_FEATURE_NEURO_RESIDUAL_INJECTION=true"
            )
        if self.features.cognition_shadow and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_SHADOW requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        if self.features.cognition_iterative_loop and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_ITERATIVE_LOOP requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        if self.features.cognition_belief_state and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_BELIEF_STATE requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        if self.features.cognition_neuro and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_NEURO requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        if self.features.cognition_neuro and not self.features.neuro_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_NEURO requires LEVIATHAN_FEATURE_NEURO=true"
            )
        if self.features.cognition_adaptive_depth and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_ADAPTIVE_DEPTH requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        if self.features.cognition_delegation and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_DELEGATION requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        if self.features.cognition_experience_learning and not self.features.cognition_enabled:
            raise ConfigurationError(
                "LEVIATHAN_FEATURE_COGNITION_EXPERIENCE_LEARNING requires LEVIATHAN_FEATURE_COGNITION=true"
            )
        emb = self.knowledge.embedding_provider
        if emb not in {
            "null",
            "none",
            "off",
            "auto",
            "hash",
            "local_hash",
            "local",
            "sentence_transformers",
            "st",
            "sbert",
            "huggingface",
            "hf",
        }:
            raise ConfigurationError(f"LEVIATHAN_EMBEDDING_PROVIDER invalid: {emb!r}")
        if self.knowledge.rerank_policy not in {"off", "auto", "always"}:
            raise ConfigurationError(
                f"LEVIATHAN_RERANK_POLICY invalid: {self.knowledge.rerank_policy!r}"
            )
        if self.knowledge.rerank_final_count > self.knowledge.rerank_candidate_count:
            raise ConfigurationError(
                "LEVIATHAN_RERANK_FINAL_COUNT must be <= LEVIATHAN_RERANK_CANDIDATE_COUNT"
            )
        if self.reasoning.default_mode not in {
            "adaptive",
            "fast",
            "standard",
            "deep",
            "maximum",
        }:
            raise ConfigurationError(
                f"LEVIATHAN_REASONING_DEFAULT_MODE invalid: {self.reasoning.default_mode!r}"
            )
        kind = self.neuro_runtime.residual_kind
        if kind not in {
            "unsupported",
            "deterministic",
            "toy",
            "deterministic_toy",
            "hf",
            "transformers",
            "huggingface",
            "vllm",
            "llama_cpp",
            "llamacpp",
            "llama.cpp",
            "trt",
            "tensorrt",
            "tensorrt_llm",
            "trt_llm",
        }:
            raise ConfigurationError(
                f"LEVIATHAN_NEURO_RESIDUAL_KIND invalid: {kind!r}"
            )
        if self.features.neuro_enabled and self.features.agents_enabled:
            # Allowed combination — neuro remains advisory; agents still need gateway later.
            pass


def load_settings() -> Settings:
    """Load env defaults, then merge SQLite operator overrides when available.

    ``database_path`` itself is never taken from the override store (bootstrap-only).
    """
    base = Settings.from_env()
    try:
        from Data.modules.settings.service import merge_db_overrides_if_available

        return merge_db_overrides_if_available(base)
    except Exception:
        # Settings module / DB unavailable during early import or tests — env only.
        return base


settings = load_settings()
