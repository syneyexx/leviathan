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


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
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

    Windows-style roots such as ``D:/ModelData`` are preserved even when the
    control plane runs on POSIX, so configuration remains portable with the
    master-program default without rewriting the operator path under the repo.
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


@dataclass(frozen=True)
class ReasoningSettings:
    enabled: bool


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
class ResourceLimits:
    max_model_concurrency: int
    max_function_concurrency: int
    max_job_concurrency: int
    max_history_messages: int


@dataclass(frozen=True)
class ContextSettings:
    token_budget: int
    reserve_response_tokens: int
    max_knowledge_chars: int


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
class Settings:
    """Canonical LEVIATHAN settings.

    Precedence today:
      hard safety defaults → environment variables (.env loaded)

    Nested domains are the source of truth. Flat compatibility properties
    preserve existing callers until they migrate.
    """

    runtime: RuntimeSettings
    model: ModelSettings
    knowledge: KnowledgeSettings
    reasoning: ReasoningSettings
    features: FeatureFlags
    coding: CodingSettings
    market_sim: MarketSimSettings
    neuro_runtime: NeuroRuntimeSettings
    resources: ResourceLimits
    context: ContextSettings
    network: NetworkSettings
    artifacts: ArtifactSettings
    backup: BackupSettings
    chaos: ChaosSettings
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
            },
            "reasoning": {"enabled": self.reasoning.enabled},
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
            },
            "network": {"allow_outbound": self.network.allow_outbound},
            "artifacts": {"root": str(self.artifacts.root)},
            "backup": {"root": str(self.backup.root)},
            "chaos": {
                "enabled": self.chaos.enabled,
                "latency_ms": self.chaos.latency_ms,
                "error_rate": self.chaos.error_rate,
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
        data_root_raw = _env_raw("LEVIATHAN_DATA_ROOT", "D:/ModelData") or "D:/ModelData"
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
        market_sim_enabled = _env_bool("LEVIATHAN_FEATURE_MARKET_SIM", False)
        rag_v3 = _env_bool("LEVIATHAN_FEATURE_RAG_V3", False)
        deep_recall = _env_bool("LEVIATHAN_FEATURE_DEEP_RECALL", False)
        why_library = _env_bool("LEVIATHAN_FEATURE_WHY_LIBRARY", False)
        residual_production = _env_bool("LEVIATHAN_FEATURE_RESIDUAL_PRODUCTION", False)
        embedding_provider = (
            _env_raw("LEVIATHAN_EMBEDDING_PROVIDER", "hash" if rag_v3 else "null") or ("hash" if rag_v3 else "null")
        ).strip().lower()
        embedding_model = (_env_raw("LEVIATHAN_EMBEDDING_MODEL", "") or "").strip() or None
        reranker_model = (_env_raw("LEVIATHAN_RERANKER_MODEL", "") or "").strip() or None
        coding_workspace_raw = (
            _env_raw("LEVIATHAN_CODING_WORKSPACE", "D:/leviathan/codingworkspace")
            or "D:/leviathan/codingworkspace"
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
            ),
            reasoning=ReasoningSettings(enabled=_env_bool("LEVIATHAN_REASONING_ENABLED", True)),
            features=FeatureFlags(
                reasoning_iterative_retrieval=_env_bool("LEVIATHAN_FEATURE_ITERATIVE_RETRIEVAL", False),
                memory_semantic=_env_bool("LEVIATHAN_FEATURE_MEMORY_SEMANTIC", False),
                neuro_enabled=_env_bool("LEVIATHAN_FEATURE_NEURO", False),
                neuro_associative_memory=_env_bool("LEVIATHAN_FEATURE_NEURO_ASSOCIATIVE_MEMORY", False),
                neuro_process_critic=_env_bool("LEVIATHAN_FEATURE_NEURO_PROCESS_CRITIC", False),
                neuro_residual_injection=_env_bool("LEVIATHAN_FEATURE_NEURO_RESIDUAL_INJECTION", False),
                neuro_cortex=_env_bool("LEVIATHAN_FEATURE_NEURO_CORTEX", False),
                neuro_memory_tiers=_env_bool("LEVIATHAN_FEATURE_NEURO_MEMORY_TIERS", False),
                neuro_residual_orchestrator=_env_bool(
                    "LEVIATHAN_FEATURE_NEURO_RESIDUAL_ORCHESTRATOR", False
                ),
                neuro_cortex_blocks=_env_bool("LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS", False),
                neuro_contrastive_training=_env_bool(
                    "LEVIATHAN_FEATURE_NEURO_CONTRASTIVE_TRAINING", False
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
            ),
            context=ContextSettings(
                token_budget=_env_int("LEVIATHAN_CONTEXT_TOKEN_BUDGET", 6000, minimum=512, maximum=200_000),
                reserve_response_tokens=_env_int(
                    "LEVIATHAN_CONTEXT_RESERVE_RESPONSE_TOKENS", 512, minimum=64, maximum=32_000
                ),
                max_knowledge_chars=_env_int(
                    "LEVIATHAN_CONTEXT_MAX_KNOWLEDGE_CHARS", 1800, minimum=200, maximum=50_000
                ),
            ),
            network=NetworkSettings(allow_outbound=_env_bool("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", False)),
            artifacts=ArtifactSettings(root=artifacts_root),
            backup=BackupSettings(root=backup_root),
            chaos=ChaosSettings(
                enabled=chaos_enabled,
                latency_ms=chaos_latency,
                error_rate=chaos_error_rate,
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
        emb = self.knowledge.embedding_provider
        if emb not in {
            "null",
            "none",
            "off",
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
    return Settings.from_env()


settings = load_settings()
