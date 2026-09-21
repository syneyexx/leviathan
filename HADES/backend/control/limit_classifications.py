"""Classification registry for behavioral hardcodes discovered by the limit detector.

Every finding must resolve to one of:
  configurable | provider_capability | security_invariant | protocol_constraint
  | display_only | test_only | false_positive

``configurable`` is NEVER implied. It requires an explicit entry with Control Plane
binding metadata that CI verifies against the registry and enforcement location.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

LimitClass = Literal[
    "configurable",
    "provider_capability",
    "security_invariant",
    "protocol_constraint",
    "display_only",
    "test_only",
    "false_positive",
]


@dataclass(frozen=True, slots=True)
class LimitClassification:
    classification: LimitClass
    reason: str
    control_key: str | None = None
    definition_location: str | None = None
    enforcement_location: str | None = None
    unlimited_supported: bool | None = None

    def to_public(self) -> dict[str, Any]:
        return asdict(self)


def _cfg(
    control_key: str,
    *,
    reason: str,
    definition_location: str,
    enforcement_location: str,
    unlimited_supported: bool,
) -> LimitClassification:
    return LimitClassification(
        classification="configurable",
        reason=reason,
        control_key=control_key,
        definition_location=definition_location,
        enforcement_location=enforcement_location,
        unlimited_supported=unlimited_supported,
    )


def _proto(reason: str) -> LimitClassification:
    return LimitClassification(classification="protocol_constraint", reason=reason)


def _sec(reason: str, *, enforcement_location: str) -> LimitClassification:
    return LimitClassification(
        classification="security_invariant",
        reason=reason,
        enforcement_location=enforcement_location,
    )


def _disp(reason: str) -> LimitClassification:
    return LimitClassification(classification="display_only", reason=reason)


def _fp(reason: str) -> LimitClassification:
    return LimitClassification(classification="false_positive", reason=reason)


def _test(reason: str) -> LimitClassification:
    return LimitClassification(classification="test_only", reason=reason)


def _prov(reason: str) -> LimitClassification:
    return LimitClassification(classification="provider_capability", reason=reason)


# Fingerprint format: "{kind}|{name}|{relpath}|{symbol}" (line-independent).
# Configurable entries MUST use _cfg(...) with a real control_key.
LIMIT_ENTRIES: dict[str, LimitClassification] = {
    # --- Control Plane-bound filesystem ceilings (module defaults; runtime resolves) ---
    "named_constant|MAX_TEXT_BYTES|backend/platform_services_core.py|module": _cfg(
        "filesystem.max_text_bytes",
        reason="Default fallback only; runtime uses max_text_bytes() → resolve_setting.",
        definition_location="backend/control/definitions.py:filesystem.max_text_bytes",
        enforcement_location="backend/platform_services_core.py:max_text_bytes",
        unlimited_supported=True,
    ),
    "named_constant|MAX_ARCHIVE_FILES|backend/platform_services_core.py|module": _cfg(
        "filesystem.max_archive_files",
        reason="Default fallback only; runtime uses max_archive_files().",
        definition_location="backend/control/definitions.py:filesystem.max_archive_files",
        enforcement_location="backend/platform_services_core.py:max_archive_files",
        unlimited_supported=True,
    ),
    "named_constant|MAX_ARCHIVE_BYTES|backend/platform_services_core.py|module": _cfg(
        "filesystem.max_archive_bytes",
        reason="Default fallback only; runtime uses max_archive_bytes().",
        definition_location="backend/control/definitions.py:filesystem.max_archive_bytes",
        enforcement_location="backend/platform_services_core.py:max_archive_bytes",
        unlimited_supported=True,
    ),
    "named_constant|MAX_PLUGIN_UPLOAD_BYTES|backend/platform_services_core.py|module": _cfg(
        "filesystem.max_plugin_upload_bytes",
        reason="Default fallback only; runtime uses max_plugin_upload_bytes().",
        definition_location="backend/control/definitions.py:filesystem.max_plugin_upload_bytes",
        enforcement_location="backend/platform_services_core.py:max_plugin_upload_bytes",
        unlimited_supported=True,
    ),
    "named_constant|MAX_FILE_BYTES|backend/repo_intelligence.py|module": _cfg(
        "codeindex.max_file_bytes",
        reason="Default fallback only; runtime uses max_file_bytes() → resolve_setting.",
        definition_location="backend/control/definitions.py:codeindex.max_file_bytes",
        enforcement_location="backend/repo_intelligence.py:max_file_bytes",
        unlimited_supported=True,
    ),
    "named_constant|MAX_FILES|backend/repo_intelligence.py|module": _proto(
        "Repo-intelligence indexer soft file ceiling (800); distinct from symbol-scan codeindex.max_files (400)."
    ),
    "named_constant|MAX_CACHE_BYTES|backend/repo_intelligence.py|module": _proto(
        "In-process index cache blob ceiling protecting memory; not a Control Plane product knob."
    ),
    "named_constant|MAX_CACHE_ENTRIES|backend/coding_context.py|module": _proto(
        "In-process coding context hash-cache entry bound; operational protocol, not Control Plane."
    ),
    "named_constant|MAX_BLOB_CHARS|backend/coding_context.py|module": _proto(
        "Per-blob truncation for coding context summaries; protocol bound, not Control Plane."
    ),
    "named_constant|max_model_calls|backend/main.py|run_model_with_optional_tool": _cfg(
        "max_model_calls_per_task",
        reason="Fallback when no ExecutionBudget/profile; live path prefers budget/profile then settings.",
        definition_location="backend/control/definitions.py",
        enforcement_location="backend/main.py:run_model_with_optional_tool",
        unlimited_supported=True,
    ),
    "named_constant|max_tool_rounds|backend/reasoning/understanding.py|build_route_decision": _cfg(
        "max_tool_rounds",
        reason="Understanding path zeros tool rounds for classify-only; settings govern tool loops elsewhere.",
        definition_location="backend/control/definitions.py",
        enforcement_location="backend/reasoning/understanding.py:build_route_decision",
        unlimited_supported=True,
    ),
    "assign_pattern|bars|backend/trading_service.py|_knowledge_payload_verified": _cfg(
        "trading.default_bars",
        reason="Paper trading seed/default window; Control Plane trading.default_bars owns policy.",
        definition_location="backend/control/definitions.py:trading.default_bars",
        enforcement_location="backend/trading_service.py",
        unlimited_supported=False,
    ),
    "assign_pattern|bars|backend/trading_service.py|_std": _cfg(
        "trading.default_bars",
        reason="Paper trading seed/default window; Control Plane trading.default_bars owns policy.",
        definition_location="backend/control/definitions.py:trading.default_bars",
        enforcement_location="backend/trading_service.py",
        unlimited_supported=False,
    ),
    # --- Immutable / security ---
    "named_constant|MAX_CATCHUP|backend/schedules.py|module": _sec(
        "Prevents schedule stampede after downtime; user configurability would enable DoS.",
        enforcement_location="backend/schedules.py:MAX_CATCHUP",
    ),
    # --- Explicit residuals: NOT configurable until bound ---
    "named_constant|max_bytes|backend/capability_routes.py|upload_chat_attachment": _proto(
        "Chat attachment upload ceiling; API protocol bound, not a user Control Plane knob."
    ),
    "named_constant|max_steps_resolved|backend/coding_agent.py|CodingAgentService.run_from_goal": _proto(
        "Local resolution of investigate step budget from settings overlay; literal is fallback only when profile absent."
    ),
    "assign_pattern|max_retries|backend/main.py|sync_model_gateway_from_settings": _proto(
        "Bounded gateway retry default (1) for transport-class failures; not a product concurrency ceiling."
    ),
    "named_constant|max_attempts|backend/reasoning/model_gateway.py|ModelGateway.chat": _proto(
        "Derived as 1+max_retries for a single invoke loop; protocol bound of the shared gateway, not a Control Plane knob."
    ),
    "named_constant|MAX_CAPTURE_CHARS|backend/plugin_dependency_runtime.py|module": _proto(
        "Dependency installer log capture ceiling to protect memory; not a product policy knob."
    ),
    "named_constant|MAX_LOG_BYTES|backend/plugin_dependency_runtime.py|module": _proto(
        "Dependency installer on-disk log ceiling; operational protocol bound."
    ),
    "named_constant|MAX_MESSAGE_BYTES|backend/native_runtime.py|module": _proto(
        "Native JSON-RPC stdin/stdout maximum message size; companion protocol safety bound, not a Control Plane knob."
    ),
    "named_constant|MAX_MESSAGE_BYTES|backend/infrastructure/native/transport.py|module": _proto(
        "Native JSON-RPC stdin/stdout maximum message size; companion protocol safety bound, not a Control Plane knob."
    ),
    "named_constant|MAX_JSONL_ROW_CHARS|backend/dataset_brain_worker.py|module": _proto(
        "Dataset Brain JSONL/CSV row ceiling protecting memory during offline materialization; not a Control Plane knob."
    ),
    "named_constant|MAX_TOOL_LIST_PAGES|backend/mcp_host/protocol.py|module": _proto(
        "MCP tools/list pagination safety bound; protocol transport limit, not a product policy knob."
    ),
    "named_constant|MAX_PAYLOAD_BYTES|backend/mcp_host/protocol.py|module": _proto(
        "MCP JSON-RPC payload size ceiling; protocol safety bound."
    ),
    "named_constant|MAX_SSE_BYTES|backend/mcp_host/protocol.py|module": _proto(
        "MCP SSE event body ceiling; protocol safety bound."
    ),
    "named_constant|MAX_STDERR_TAIL_BYTES|backend/mcp_host/protocol.py|module": _proto(
        "MCP stderr capture tail bound for diagnostics; operational protocol limit."
    ),
    "named_constant|MAX_SCHEMA_DEPTH|backend/mcp_host/validation.py|module": _proto(
        "MCP JSON Schema walk depth guard against hostile recursion; protocol validation bound."
    ),
    "named_constant|MAX_REF_EXPANSIONS|backend/mcp_host/validation.py|module": _proto(
        "MCP $ref expansion ceiling against cyclic schemas; protocol validation bound."
    ),
    "named_constant|MAX_SYSTEM_PROMPT_CHARS|backend/models_routes.py|module": _proto(
        "Pydantic request ceiling for model profile system prompts; API validation bound, not a runtime Control Plane knob."
    ),
    "named_constant|max_drawdown|backend/trading_service.py|TradingBotService.backtest": _fp(
        "Running metric accumulator initialized at 0.0, not a behavioral limit constant."
    ),
    "named_constant|DEFAULT_MAX_FILE_BYTES|plugins/deep-web-downloader/deep_utils.py|module": _proto(
        "Plugin-local download safety default; plugin manifests may expose typed settings later."
    ),
    # Timeouts that are operational / provider — not Control Plane knobs
    "assign_pattern|timeout|backend/folder_picker.py|_pick_windows_powershell": _proto(
        "Native folder dialog wait ceiling; OS UI protocol, not agent policy."
    ),
    "assign_pattern|timeout|backend/host_verify_sim.py|run_host_verify_simulation": _test(
        "Host verification simulator harness timeout."
    ),
    "assign_pattern|timeout|backend/language_servers.py|read_diagnostics": _proto(
        "LSP diagnostics request timeout; language-server protocol operational bound."
    ),
    "assign_pattern|timeout|backend/platform_services_core.py|extract_document": _proto(
        "Document extraction subprocess timeout; operational bound."
    ),
    "assign_pattern|timeout|backend/plugin_dependency_runtime.py|read_dependency_snapshot": _proto(
        "Dependency probe short timeout; installer operational bound."
    ),
    "assign_pattern|timeout|backend/release_confidence.py|run_focused_unittest": _proto(
        "Release confidence stage wall-clock; CI harness bound, not user agent policy."
    ),
    "assign_pattern|timeout|backend/speech/memory_gate.py|probe_host_memory": _proto(
        "VoiceStudio memory probe timeout; provider health check."
    ),
    "assign_pattern|timeout_seconds|backend/speech/runtime.py|get_speech_runtime": _prov(
        "VoiceStudio TTS/STT request timeout tied to local provider capability."
    ),
    "assign_pattern|timeout|backend/voice/providers/piper_tts.py|module": _prov(
        "Piper TTS subprocess timeout; local binary provider bound."
    ),
    "assign_pattern|timeout|plugins/_shared/pack_lib.py|clone_upstream": _proto(
        "Plugin pack/clone network timeout; packaging tooling, not agent policy."
    ),
    "assign_pattern|timeout|plugins/gods-eye-view/pack_hadesplugin.py|clone_upstream": _proto(
        "Plugin pack/clone network timeout; packaging tooling, not agent policy."
    ),
    "timeout_literal|timeout|backend/main.py|TaskRunner.shutdown": _proto(
        "Graceful worker drain during app shutdown; lifecycle protocol, not agent budget."
    ),
    "timeout_literal|timeout|backend/main.py|event_generator": _proto(
        "SSE long-poll wait; transport protocol bound."
    ),
    "named_constant|max_replans|backend/gen2/eval_lab.py|_planning_quality_case": _test(
        "Offline planning_quality_v1 fixture constant; not a runtime agent budget."
    ),
    "named_constant|THRESHOLD_VERSION|backend/evals/release_thresholds.py|module": _proto(
        "Pinned release-gate threshold schema version; fixed for measurement honesty, not an agent budget."
    ),
}

# Legacy alias used by older tests/docs — maps fingerprint → class label only.
LIMIT_CLASSIFICATIONS: dict[str, LimitClass] = {
    key: entry.classification for key, entry in LIMIT_ENTRIES.items()
}

LIMIT_CLASSIFICATION_NOTES: dict[str, str] = {
    key: entry.reason for key, entry in LIMIT_ENTRIES.items()
}


def _normalize_path(path: str) -> str:
    path = str(path or "").replace("\\", "/")
    for marker in (
        "/backend/",
        "/components/",
        "/lib/",
        "/hooks/",
        "/app/",
        "/scripts/",
        "/plugins/",
        "/tests/",
    ):
        if marker in f"/{path}":
            idx = path.find(marker.lstrip("/"))
            if idx >= 0:
                return path[idx:]
    return path


def fingerprint(finding: dict) -> str:
    kind = str(finding.get("kind") or "")
    name = str(finding.get("name") or "")
    path = _normalize_path(str(finding.get("file") or ""))
    symbol = str(finding.get("symbol") or "module").strip() or "module"
    return f"{kind}|{name}|{path}|{symbol}"


def fingerprint_candidates(finding: dict) -> list[str]:
    """Primary fingerprint plus legacy `{kind}|{name}|{path}` for migration."""
    primary = fingerprint(finding)
    kind = str(finding.get("kind") or "")
    name = str(finding.get("name") or "")
    path = _normalize_path(str(finding.get("file") or ""))
    legacy = f"{kind}|{name}|{path}"
    out = [primary]
    if legacy != primary:
        out.append(legacy)
    return out


def _heuristic_non_configurable(finding: dict) -> LimitClassification | None:
    """Narrow heuristics that MUST NOT assign ``configurable``."""
    kind = str(finding.get("kind") or "")
    path = _normalize_path(str(finding.get("file") or ""))
    name = str(finding.get("name") or "")
    snippet = str(finding.get("snippet") or "")

    if kind == "test_only" or "/tests/" in f"/{path}" or path.startswith("tests/"):
        return _test("Test harness / fixture path.")
    if "backend/control/" in path:
        return _fp("Control Plane source defines defaults/registry.")

    # Pydantic Field bounds are request/protocol envelopes. Configurability of the
    # underlying setting is proven separately via storage_key + runtime resolve —
    # not by the presence of Field(le=...).
    if kind == "pydantic_bound":
        if name in {"max_length", "min_length"}:
            return _proto("Pydantic string length envelope on API model.")
        if name in {"le", "ge", "lt", "gt", "multiple_of"}:
            return _proto(
                "Pydantic numeric request validation envelope; not proof of Control Plane binding."
            )

    # UI truncation / presentation clamps — only when clearly display-side.
    if kind in {"ts_slice", "ts_clamp"} and (
        path.startswith("components/") or path.startswith("hooks/") or path.startswith("app/")
    ):
        return _disp("Frontend presentation truncation/clamp; does not change backend agent budgets.")

    if kind == "ts_literal" and path.startswith("lib/"):
        lowered = name.lower()
        if lowered in {"limit", "pagesize", "page_size", "maxfiles", "max_files"}:
            return _disp("Frontend API client default pagination/cap; server enforces real policy.")
        if lowered in {"timeout", "retrycount", "pollinterval", "max_tokens", "maxtokens", "batchsize", "concurrency"}:
            return _proto("Frontend client transport/default literal; server/Control Plane owns policy.")

    if kind == "ts_literal" and (
        path.startswith("components/") or path.startswith("hooks/") or path.startswith("app/")
    ):
        return _disp("UI-side literal; display or form default only.")

    # Plugin packaging / bridge presentation slices (skill previews, log lines).
    if kind == "py_slice" and path.startswith("plugins/"):
        if any(token in snippet.lower() for token in ("first[", "line[", "name", "filename", "title", "preview", "summary")):
            return _disp("Plugin bridge/packaging presentation slice.")
        return _proto("Plugin-local truncation; not a core Control Plane setting.")

    if kind == "assign_pattern" and path.startswith("plugins/") and name in {"timeout", "timeout_seconds"}:
        return _proto("Plugin packaging/runtime operational timeout.")

    if kind == "named_constant" and path.startswith("plugins/"):
        return _proto("Plugin-local named ceiling; core Control Plane does not own plugin-private defaults.")

    # Python numeric slices used for ID/title formatting.
    snippet_l = snippet.lower()
    if kind == "py_slice" and any(
        token in snippet_l for token in (".hex", "uuid", "title", "label", "hash", "content_hash", "[:8]", "[:12]", "[:16]")
    ):
        return _disp("Identifier/title formatting slice.")

    if kind == "py_slice" and (path.startswith("backend/") or path.startswith("scripts/")):
        return _proto("In-process truncation; classify as configurable only with explicit binding.")

    if kind in {"min_clamp", "max_clamp", "range_cap"}:
        return _proto("Local numeric clamp/range; requires explicit binding to be configurable.")

    if kind in {"thread_pool", "process_pool", "queue_size", "sleep_literal", "poll_literal"}:
        return _proto("Operational concurrency/timing literal; not auto-configurable.")

    if kind == "semaphore_literal":
        return _proto("Semaphore size literal; shared budget settings cover intentional pools.")

    if kind == "timeout_literal":
        return _proto("Timeout literal; requires explicit binding to be configurable.")

    if kind == "assign_pattern" and name in {"timeout", "timeout_seconds", "poll_interval", "concurrency", "batch_size"}:
        return _proto("Assign-pattern operational literal; requires explicit binding to be configurable.")

    return None


def classification_entry(finding: dict) -> LimitClassification | None:
    for fp in fingerprint_candidates(finding):
        if fp in LIMIT_ENTRIES:
            return LIMIT_ENTRIES[fp]
    return _heuristic_non_configurable(finding)


def classify(finding: dict) -> LimitClass | None:
    entry = classification_entry(finding)
    return entry.classification if entry else None


def configurable_entries() -> dict[str, LimitClassification]:
    return {k: v for k, v in LIMIT_ENTRIES.items() if v.classification == "configurable"}


def unbound_configurable_entries(registry: Any | None = None) -> list[dict[str, Any]]:
    """Return configurable LIMIT_ENTRIES that lack a valid Control Plane definition."""
    if registry is None:
        from .definitions import create_default_registry

        registry = create_default_registry()
    ids = {d.id for d in registry.all()}
    storage = set(registry.storage_keys())
    bad: list[dict[str, Any]] = []
    for fp, entry in configurable_entries().items():
        key = entry.control_key or ""
        ok = bool(key) and (key in ids or key in storage)
        if not ok or not entry.enforcement_location or not entry.definition_location or not entry.reason:
            bad.append(
                {
                    "fingerprint": fp,
                    "control_key": entry.control_key,
                    "definition_location": entry.definition_location,
                    "enforcement_location": entry.enforcement_location,
                    "reason": entry.reason,
                    "registry_hit": ok,
                }
            )
    return bad


def validate_configurable_finding(finding: dict, registry: Any | None = None) -> list[str]:
    """Return human-readable problems if a finding claims configurable without binding."""
    entry = classification_entry(finding)
    problems: list[str] = []
    if entry is None:
        return ["unclassified"]
    if entry.classification != "configurable":
        return []
    if registry is None:
        from .definitions import create_default_registry

        registry = create_default_registry()
    ids = {d.id for d in registry.all()}
    storage = set(registry.storage_keys())
    key = entry.control_key or ""
    if not key:
        problems.append("missing control_key")
    elif key not in ids and key not in storage:
        problems.append(f"control_key not in registry: {key}")
    if not entry.definition_location:
        problems.append("missing definition_location")
    if not entry.enforcement_location:
        problems.append("missing enforcement_location")
    if not entry.reason:
        problems.append("missing reason")
    if entry.unlimited_supported is None:
        problems.append("missing unlimited_supported")
    # Enforcement path should point at a real repo file when local path-like.
    enf = entry.enforcement_location.replace("\\", "/")
    file_part = enf.split(":")[0]
    if file_part.startswith(("backend/", "components/", "lib/", "hooks/", "app/", "scripts/", "plugins/")):
        root = Path(__file__).resolve().parents[2]
        if not (root / file_part).exists():
            problems.append(f"enforcement_location file missing: {file_part}")
    return problems
