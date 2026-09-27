"""Shared types for the generic external capability fabric."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class AdapterType(str, Enum):
    MCP = "MCP"
    CLI = "CLI"
    PROCESS_SERVICE = "PROCESS_SERVICE"
    HTTP_OPENAPI = "HTTP_OPENAPI"
    SKILL_PACK = "SKILL_PACK"
    CATALOG_SOURCE = "CATALOG_SOURCE"
    SCRIPT_PACKAGE = "SCRIPT_PACKAGE"
    COMPOSITE = "COMPOSITE"


class InstallStrategy(str, Enum):
    NONE = "NONE"
    GIT_CHECKOUT = "GIT_CHECKOUT"
    PYTHON_VENV = "PYTHON_VENV"
    PIP_PACKAGE = "PIP_PACKAGE"
    NODE_NPM = "NODE_NPM"
    NODE_PNPM = "NODE_PNPM"
    NODE_SCRIPT = "NODE_SCRIPT"
    BINARY = "BINARY"


class RuntimeMode(str, Enum):
    EPHEMERAL = "EPHEMERAL"
    RESIDENT = "RESIDENT"
    LAZY = "LAZY"
    NONE = "NONE"


class ResultFormat(str, Enum):
    JSON = "JSON"
    JSONL = "JSONL"
    TEXT = "TEXT"
    FILES = "FILES"
    MIXED = "MIXED"


class AssimilationMode(str, Enum):
    NONE = "NONE"
    EVIDENCE = "EVIDENCE"
    KNOWLEDGE_CANDIDATE = "KNOWLEDGE_CANDIDATE"
    AUTO_KNOWLEDGE = "AUTO_KNOWLEDGE"


class ExternalRuntimeState(str, Enum):
    """Semantic runtime states for external adapters (not forced on every kind)."""

    DISCOVERED = "DISCOVERED"
    INSTALLED = "INSTALLED"
    LOADED = "LOADED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    BUSY = "BUSY"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    NOT_INSTALLED = "NOT_INSTALLED"


class ExternalFailureCode(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    START_FAILED = "START_FAILED"
    HEALTH_FAILED = "HEALTH_FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    EXIT_NONZERO = "EXIT_NONZERO"
    INVALID_RESULT = "INVALID_RESULT"
    REMOTE_ERROR = "REMOTE_ERROR"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    CANCEL_UNSUPPORTED = "CANCEL_UNSUPPORTED"
    INSTALL_FAILED = "INSTALL_FAILED"
    UPDATE_BLOCKED_ACTIVE = "UPDATE_BLOCKED_ACTIVE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    PORT_IN_USE = "PORT_IN_USE"


@dataclass(frozen=True)
class InstallSpec:
    strategies: tuple[InstallStrategy, ...] = (InstallStrategy.NONE,)
    python_packages: tuple[str, ...] = ()
    npm_packages: tuple[str, ...] = ()
    requirements_file: str | None = None
    package_json: str | None = None
    post_install: tuple[tuple[str, ...], ...] = ()
    dependencies: tuple[str, ...] = ()  # binary deps checked, not auto-installed

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategies": [s.value for s in self.strategies],
            "python_packages": list(self.python_packages),
            "npm_packages": list(self.npm_packages),
            "requirements_file": self.requirements_file,
            "package_json": self.package_json,
            "post_install": [list(cmd) for cmd in self.post_install],
            "dependencies": list(self.dependencies),
        }


@dataclass(frozen=True)
class RuntimeSpec:
    mode: RuntimeMode = RuntimeMode.EPHEMERAL
    command: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    env_secret_refs: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    startup_timeout_seconds: float = 60.0
    idle_timeout_seconds: float | None = None
    ready_probe: dict[str, Any] | None = None
    health_probe: dict[str, Any] | None = None
    stop_signal: str = "SIGTERM"
    stdin_format: str | None = None  # json|text|None
    base_url: str | None = None
    operations: tuple[dict[str, Any], ...] = ()
    mcp_server_id: str | None = None
    eager_start: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "command": list(self.command),
            "cwd": self.cwd,
            "env": dict(self.env),
            "env_secret_refs": dict(self.env_secret_refs),
            "timeout_seconds": self.timeout_seconds,
            "startup_timeout_seconds": self.startup_timeout_seconds,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "ready_probe": self.ready_probe,
            "health_probe": self.health_probe,
            "stop_signal": self.stop_signal,
            "stdin_format": self.stdin_format,
            "base_url": self.base_url,
            "operations": list(self.operations),
            "mcp_server_id": self.mcp_server_id,
            "eager_start": self.eager_start,
        }


@dataclass(frozen=True)
class ResultSpec:
    format: ResultFormat = ResultFormat.MIXED
    artifact_globs: tuple[str, ...] = ()
    summary_path: str | None = None
    sources_path: str | None = None
    parse_stdout_json: bool = True
    treat_nonzero_as_failure: bool = True
    max_inline_bytes: int = 64_000

    def public_dict(self) -> dict[str, Any]:
        return {
            "format": self.format.value,
            "artifact_globs": list(self.artifact_globs),
            "summary_path": self.summary_path,
            "sources_path": self.sources_path,
            "parse_stdout_json": self.parse_stdout_json,
            "treat_nonzero_as_failure": self.treat_nonzero_as_failure,
            "max_inline_bytes": self.max_inline_bytes,
        }


@dataclass(frozen=True)
class SourceSpec:
    source_type: str = "git"  # git|path|pip|npm|none
    source: str = ""
    ref: str | None = None
    path: str | None = None  # local path override / relative

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source": self.source,
            "ref": self.ref,
            "path": self.path,
        }


@dataclass(frozen=True)
class ExternalConfig:
    adapter: AdapterType
    source: SourceSpec = field(default_factory=SourceSpec)
    install: InstallSpec = field(default_factory=InstallSpec)
    runtime: RuntimeSpec = field(default_factory=RuntimeSpec)
    result: ResultSpec = field(default_factory=ResultSpec)
    assimilation_mode: AssimilationMode = AssimilationMode.NONE
    children: tuple[AdapterType, ...] = ()  # COMPOSITE child adapters
    skill_roots: tuple[str, ...] = ()
    catalog_globs: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    domain: str | None = None
    resource_class: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter.value,
            "source": self.source.public_dict(),
            "install": self.install.public_dict(),
            "runtime": self.runtime.public_dict(),
            "result": self.result.public_dict(),
            "assimilation_mode": self.assimilation_mode.value,
            "children": [c.value for c in self.children],
            "skill_roots": list(self.skill_roots),
            "catalog_globs": list(self.catalog_globs),
            "tags": list(self.tags),
            "domain": self.domain,
            "resource_class": self.resource_class,
            "metadata": dict(self.metadata),
        }


def _parse_strategies(raw: Any) -> tuple[InstallStrategy, ...]:
    if raw is None:
        return (InstallStrategy.NONE,)
    if isinstance(raw, str):
        # Accept both "python_venv" and "PYTHON_VENV" and strategy objects.
        key = raw.strip().upper().replace("-", "_")
        aliases = {
            "PYTHON_VENV": InstallStrategy.PYTHON_VENV,
            "GIT": InstallStrategy.GIT_CHECKOUT,
            "GIT_CHECKOUT": InstallStrategy.GIT_CHECKOUT,
            "PIP": InstallStrategy.PIP_PACKAGE,
            "PIP_PACKAGE": InstallStrategy.PIP_PACKAGE,
            "NPM": InstallStrategy.NODE_NPM,
            "NODE_NPM": InstallStrategy.NODE_NPM,
            "PNPM": InstallStrategy.NODE_PNPM,
            "NODE_PNPM": InstallStrategy.NODE_PNPM,
            "NODE_SCRIPT": InstallStrategy.NODE_SCRIPT,
            "BINARY": InstallStrategy.BINARY,
            "NONE": InstallStrategy.NONE,
        }
        return (aliases.get(key, InstallStrategy.NONE),)
    if isinstance(raw, dict):
        strategy = raw.get("strategy") or raw.get("strategies")
        return _parse_strategies(strategy)
    if isinstance(raw, (list, tuple)):
        out: list[InstallStrategy] = []
        for item in raw:
            out.extend(_parse_strategies(item))
        return tuple(out) or (InstallStrategy.NONE,)
    return (InstallStrategy.NONE,)


def parse_external_config(data: Mapping[str, Any] | None) -> ExternalConfig | None:
    if not data or not isinstance(data, Mapping):
        return None
    adapter_raw = str(data.get("adapter") or "").strip().upper()
    if not adapter_raw:
        return None
    try:
        adapter = AdapterType(adapter_raw)
    except ValueError as exc:
        raise ValueError(f"Unknown external adapter: {adapter_raw}") from exc

    source_raw = data.get("source")
    if isinstance(source_raw, str):
        source = SourceSpec(
            source_type=str(data.get("source_type") or "git"),
            source=source_raw,
            ref=(str(data["ref"]) if data.get("ref") else None),
            path=(str(data["path"]) if data.get("path") else None),
        )
    elif isinstance(source_raw, Mapping):
        source = SourceSpec(
            source_type=str(source_raw.get("source_type") or data.get("source_type") or "git"),
            source=str(source_raw.get("source") or source_raw.get("url") or ""),
            ref=(str(source_raw["ref"]) if source_raw.get("ref") else (str(data["ref"]) if data.get("ref") else None)),
            path=(str(source_raw["path"]) if source_raw.get("path") else None),
        )
    else:
        source = SourceSpec(
            source_type=str(data.get("source_type") or "none"),
            source=str(data.get("source") or ""),
            ref=(str(data["ref"]) if data.get("ref") else None),
            path=(str(data["path"]) if data.get("path") else None),
        )

    install_raw = data.get("install") or {}
    if not isinstance(install_raw, Mapping):
        install_raw = {"strategy": install_raw}
    strategies = _parse_strategies(install_raw.get("strategy") or install_raw.get("strategies") or data.get("install_strategy"))
    # Auto-include GIT_CHECKOUT when source is git and not already present.
    if source.source_type == "git" and source.source and InstallStrategy.GIT_CHECKOUT not in strategies:
        if strategies == (InstallStrategy.NONE,):
            strategies = (InstallStrategy.GIT_CHECKOUT,)
        else:
            strategies = (InstallStrategy.GIT_CHECKOUT, *strategies)

    post_install: list[tuple[str, ...]] = []
    for cmd in install_raw.get("post_install") or ():
        if isinstance(cmd, (list, tuple)) and cmd:
            post_install.append(tuple(str(x) for x in cmd))

    install = InstallSpec(
        strategies=strategies,
        python_packages=tuple(str(x) for x in (install_raw.get("python_packages") or ())),
        npm_packages=tuple(str(x) for x in (install_raw.get("npm_packages") or ())),
        requirements_file=(str(install_raw["requirements_file"]) if install_raw.get("requirements_file") else None),
        package_json=(str(install_raw["package_json"]) if install_raw.get("package_json") else None),
        post_install=tuple(post_install),
        dependencies=tuple(str(x) for x in (install_raw.get("dependencies") or ())),
    )

    runtime_raw = data.get("runtime") or {}
    if not isinstance(runtime_raw, Mapping):
        runtime_raw = {}
    mode_raw = str(runtime_raw.get("mode") or "EPHEMERAL").upper()
    try:
        mode = RuntimeMode(mode_raw)
    except ValueError:
        mode = RuntimeMode.EPHEMERAL
    command_raw = runtime_raw.get("command") or ()
    command = tuple(str(x) for x in command_raw) if isinstance(command_raw, (list, tuple)) else ()
    ops_raw = runtime_raw.get("operations") or data.get("operations") or ()
    operations = tuple(dict(op) for op in ops_raw if isinstance(op, Mapping))

    runtime = RuntimeSpec(
        mode=mode,
        command=command,
        cwd=(str(runtime_raw["cwd"]) if runtime_raw.get("cwd") else None),
        env={str(k): str(v) for k, v in dict(runtime_raw.get("env") or {}).items()},
        env_secret_refs={str(k): str(v) for k, v in dict(runtime_raw.get("env_secret_refs") or {}).items()},
        timeout_seconds=float(runtime_raw.get("timeout_seconds") or 120.0),
        startup_timeout_seconds=float(runtime_raw.get("startup_timeout_seconds") or 60.0),
        idle_timeout_seconds=(
            float(runtime_raw["idle_timeout_seconds"])
            if runtime_raw.get("idle_timeout_seconds") is not None
            else None
        ),
        ready_probe=dict(runtime_raw["ready_probe"]) if isinstance(runtime_raw.get("ready_probe"), Mapping) else None,
        health_probe=dict(runtime_raw["health_probe"]) if isinstance(runtime_raw.get("health_probe"), Mapping) else None,
        stop_signal=str(runtime_raw.get("stop_signal") or "SIGTERM"),
        stdin_format=(str(runtime_raw["stdin_format"]) if runtime_raw.get("stdin_format") else None),
        base_url=(str(runtime_raw["base_url"]) if runtime_raw.get("base_url") else (str(data["base_url"]) if data.get("base_url") else None)),
        operations=operations,
        mcp_server_id=(str(runtime_raw["mcp_server_id"]) if runtime_raw.get("mcp_server_id") else (str(data["mcp_server_id"]) if data.get("mcp_server_id") else None)),
        eager_start=bool(runtime_raw.get("eager_start", False)),
    )

    result_raw = data.get("result") or {}
    if not isinstance(result_raw, Mapping):
        result_raw = {}
    fmt_raw = str(result_raw.get("format") or "MIXED").upper()
    try:
        fmt = ResultFormat(fmt_raw)
    except ValueError:
        fmt = ResultFormat.MIXED
    result = ResultSpec(
        format=fmt,
        artifact_globs=tuple(str(x) for x in (result_raw.get("artifact_globs") or ())),
        summary_path=(str(result_raw["summary_path"]) if result_raw.get("summary_path") else None),
        sources_path=(str(result_raw["sources_path"]) if result_raw.get("sources_path") else None),
        parse_stdout_json=bool(result_raw.get("parse_stdout_json", True)),
        treat_nonzero_as_failure=bool(result_raw.get("treat_nonzero_as_failure", True)),
        max_inline_bytes=int(result_raw.get("max_inline_bytes") or 64_000),
    )

    assim_raw = str(data.get("assimilation_mode") or AssimilationMode.NONE.value).upper()
    try:
        assimilation = AssimilationMode(assim_raw)
    except ValueError:
        assimilation = AssimilationMode.NONE

    children_raw = data.get("children") or ()
    children: list[AdapterType] = []
    for item in children_raw:
        try:
            children.append(AdapterType(str(item).upper()))
        except ValueError:
            continue

    return ExternalConfig(
        adapter=adapter,
        source=source,
        install=install,
        runtime=runtime,
        result=result,
        assimilation_mode=assimilation,
        children=tuple(children),
        skill_roots=tuple(str(x) for x in (data.get("skill_roots") or ())),
        catalog_globs=tuple(str(x) for x in (data.get("catalog_globs") or ("**/SKILL.md",))),
        tags=tuple(str(x) for x in (data.get("tags") or ())),
        domain=(str(data["domain"]) if data.get("domain") else None),
        resource_class=(str(data["resource_class"]) if data.get("resource_class") else None),
        metadata=dict(data.get("metadata") or {}),
    )


def normalize_capability_parts(
    *,
    summary: str | None = None,
    structured_data: Any = None,
    sources: Sequence[Mapping[str, Any]] | None = None,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
    files: Sequence[Mapping[str, Any]] | None = None,
    tables: Sequence[Mapping[str, Any]] | None = None,
    images: Sequence[Mapping[str, Any]] | None = None,
    progress: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
    module_status: Mapping[str, Any] | None = None,
    raw_text: str | None = None,
    stdout_artifact: str | None = None,
    stderr_artifact: str | None = None,
    raw_result_artifact: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded CapabilityResult.output bag with typed optional parts."""
    parts: list[dict[str, Any]] = []
    if summary:
        parts.append({"kind": "TEXT", "text": summary})
    if structured_data is not None:
        parts.append({"kind": "STRUCTURED", "data": structured_data})
    if sources:
        parts.append({"kind": "SOURCE", "sources": list(sources), "count": len(sources)})
    if artifacts:
        parts.append({"kind": "ARTIFACT", "artifacts": list(artifacts), "count": len(artifacts)})
    if files:
        parts.append({"kind": "FILE", "files": list(files), "count": len(files)})
    if tables:
        parts.append({"kind": "TABLE", "tables": list(tables), "count": len(tables)})
    if images:
        parts.append({"kind": "IMAGE", "images": list(images), "count": len(images)})
    if progress:
        parts.append({"kind": "PROGRESS", **dict(progress)})
    if error:
        parts.append({"kind": "ERROR", **dict(error)})
    if module_status:
        parts.append({"kind": "MODULE_STATUS", **dict(module_status)})
    if raw_text is not None:
        # Bound inline text — large bodies must be artifacts.
        max_inline = 8_000
        text = raw_text if len(raw_text) <= max_inline else raw_text[:max_inline] + "\n…[truncated]"
        parts.append({"kind": "TEXT", "text": text, "truncated": len(raw_text) > max_inline})

    # Prefer ArtifactStore ids/refs; fall back to declared file paths so Chat/SSE
    # can emit artifact.created for CLI artifact_globs before store registration.
    artifact_ref_list: list[str] = []
    for a in list(artifacts or []) + list(files or []):
        if not isinstance(a, Mapping):
            continue
        ref = a.get("artifact_id") or a.get("ref") or a.get("path") or a.get("name")
        if ref is None:
            continue
        sref = str(ref)
        if sref and sref not in artifact_ref_list:
            artifact_ref_list.append(sref)

    output: dict[str, Any] = {
        "summary": summary,
        "parts": parts,
        "artifact_refs": artifact_ref_list,
        "source_refs": [s.get("url") or s.get("id") for s in (sources or []) if isinstance(s, Mapping)],
        "stdout_artifact": stdout_artifact,
        "stderr_artifact": stderr_artifact,
        "raw_result_artifact": raw_result_artifact,
        "metadata": dict(metadata or {}),
        "truth": {
            "tool_success_is_not_factual_truth": True,
            "large_payloads_must_be_artifacts": True,
        },
    }
    if structured_data is not None and isinstance(structured_data, dict):
        output["structured_data"] = structured_data
    return output
