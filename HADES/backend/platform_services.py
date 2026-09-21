from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import urllib.parse
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from platform_services_core import *  # noqa: F401,F403
from platform_services_core import (
    PluginManager as _CorePluginManager,
    ResearchRunner as _CoreResearchRunner,
    WebResearchService as _CoreWebResearchService,
    _UNSET,
)
from plugin_dependency_runtime import DependencyCommandRunner, read_dependency_snapshot, write_dependency_status


# The public API payloads predate this per-project policy. Keep the compatibility
# marker inside the existing source_inputs field so older clients/backends remain
# compatible while a project can still persist its explicit opt-out across reruns.
RESEARCH_ROBOTS_OFF_SOURCE = "hades-internal://research-policy/respect-robots-txt=off"
RESEARCH_ROBOTS_OFF_FRAGMENT = "hades-respect-robots-txt=off"
_RESEARCH_ROBOTS_POLICY: ContextVar[bool | None] = ContextVar("hades_research_robots_policy", default=None)


class _ResearchPolicyDatabaseView:
    """Hide internal policy markers from the core research runner."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)

    def get_research_project(self, project_id: str) -> dict[str, Any] | None:
        project = self._db.get_research_project(project_id)
        if not project:
            return project
        source_inputs = [str(item) for item in project.get("source_inputs") or []]
        respect_robots = RESEARCH_ROBOTS_OFF_SOURCE not in source_inputs
        return {
            **project,
            "source_inputs": [item for item in source_inputs if item != RESEARCH_ROBOTS_OFF_SOURCE],
            "respect_robots_txt": respect_robots,
        }


class WebResearchService(_CoreWebResearchService):
    """Core web research with an explicit, task-local robots.txt policy.

    Turning robots.txt off changes only that check. The core ``_get`` path still
    performs public-URL/redirect validation and therefore keeps SSRF protections.
    """

    @staticmethod
    def _harvest_policy(seed_url: str) -> tuple[str, bool | None]:
        parsed = urllib.parse.urlparse(seed_url)
        if not parsed.fragment:
            return seed_url, None
        parts = parsed.fragment.split("&")
        if RESEARCH_ROBOTS_OFF_FRAGMENT not in parts:
            return seed_url, None
        clean_fragment = "&".join(part for part in parts if part != RESEARCH_ROBOTS_OFF_FRAGMENT)
        clean_url = urllib.parse.urlunparse(parsed._replace(fragment=clean_fragment))
        return clean_url, False

    async def _get(self, url: str, *, respect_robots: bool = True):
        active_policy = _RESEARCH_ROBOTS_POLICY.get()
        effective_policy = respect_robots if active_policy is None else bool(active_policy)
        return await super()._get(url, respect_robots=effective_policy)

    async def harvest_site_documents(
        self,
        seed_url: str,
        *,
        max_pages: Any = _UNSET,
        max_depth: Any = _UNSET,
        max_documents: Any = _UNSET,
        authorized_downloads: bool = False,
        include_html_pages: bool = True,
    ) -> dict[str, Any]:
        clean_url, explicit_policy = self._harvest_policy(seed_url)
        active_policy = _RESEARCH_ROBOTS_POLICY.get()
        effective_policy = (
            explicit_policy
            if explicit_policy is not None
            else (bool(active_policy) if active_policy is not None else True)
        )
        token = _RESEARCH_ROBOTS_POLICY.set(effective_policy)
        try:
            result = await super().harvest_site_documents(
                clean_url,
                max_pages=max_pages,
                max_depth=max_depth,
                max_documents=max_documents,
                authorized_downloads=authorized_downloads,
                include_html_pages=include_html_pages,
            )
        finally:
            _RESEARCH_ROBOTS_POLICY.reset(token)
        result["respect_robots_txt"] = effective_policy
        return result


class ResearchRunner(_CoreResearchRunner):
    """Research runner that restores the persisted robots policy for every rerun."""

    def __init__(self, db: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(_ResearchPolicyDatabaseView(db), *args, **kwargs)

    async def _run(self, project_id: str) -> None:
        project = self.db.get_research_project(project_id)
        respect_robots = True if not project else bool(project.get("respect_robots_txt", True))
        token = _RESEARCH_ROBOTS_POLICY.set(respect_robots)
        try:
            await super()._run(project_id)
        finally:
            _RESEARCH_ROBOTS_POLICY.reset(token)


class PluginManager(_CorePluginManager):
    """HADES plugin manager with observable and bounded dependency preparation.

    The core plugin contract remains in ``platform_services_core``. Dependency
    installation is isolated here so long-running package managers can report
    live progress without turning Settings into an installer-control surface.
    Plugins may override the conservative runtime defaults through an optional
    ``manifest.dependency_install`` object.
    """

    _DEPENDENCY_TIMEOUT_DEFAULTS = {
        "python": 1200,
        "node": 1800,
        "rust": 1800,
        "go": 1200,
        "java": 1800,
        "dotnet": 1200,
    }
    _DEPENDENCY_STALL_DEFAULTS = {
        "python": 600,
        "node": 600,
        "rust": 900,
        "go": 600,
        "java": 900,
        "dotnet": 600,
    }

    def _dependency_paths(self, plugin_id: str) -> tuple[Path, Path]:
        runtime_dir = self.runtimes / plugin_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir / "dependencies.log", runtime_dir / "dependencies.status.json"

    def _dependency_limits(self, plugin_id: str, runtime: str) -> tuple[int, int]:
        default_timeout = self._DEPENDENCY_TIMEOUT_DEFAULTS.get(runtime, 1200)
        default_stall = self._DEPENDENCY_STALL_DEFAULTS.get(runtime, 600)
        plugin = self.db.get_plugin(plugin_id) or {}
        manifest = plugin.get("manifest", {}) if isinstance(plugin.get("manifest"), dict) else {}
        raw = manifest.get("dependency_install", {}) if isinstance(manifest, dict) else {}
        config = raw if isinstance(raw, dict) else {}
        try:
            timeout = int(config.get("timeout_seconds", default_timeout))
        except (TypeError, ValueError):
            timeout = default_timeout
        try:
            stall = int(config.get("stall_timeout_seconds", default_stall))
        except (TypeError, ValueError):
            stall = default_stall
        timeout = max(60, min(timeout, 7200))
        stall = 0 if stall <= 0 else max(60, min(stall, timeout, 3600))
        return timeout, stall

    def _dependency_output_callback(self, plugin_id: str) -> Callable[[str, str], None]:
        """Emit a redacted, rate-limited live trace through the existing plugin event stream."""
        lock = threading.Lock()
        last_emit = 0.0
        pending: list[str] = []

        def emit(label: str, text: str) -> None:
            nonlocal last_emit
            if label == "hades":
                return
            now = time.monotonic()
            with lock:
                pending.append(f"[{label}] {text}".strip())
                if now - last_emit < 0.75:
                    return
                message = " | ".join(pending)[-1200:]
                pending.clear()
                last_emit = now
            self.db.add_plugin_event(plugin_id, "info", f"Dependency output: {message}")

        return emit

    def dependency_status(self, plugin_id: str, tail_bytes: int = 100_000) -> dict[str, Any]:
        if not self.db.get_plugin(plugin_id):
            raise KeyError(plugin_id)
        log_path, status_path = self._dependency_paths(plugin_id)
        snapshot = read_dependency_snapshot(log_path, status_path, tail_bytes=tail_bytes)
        return {
            "plugin_id": plugin_id,
            "call": self.db.latest_dependency_call(plugin_id),
            **snapshot,
        }

    def _install_dependencies(self, root: Path, runtime: str, plugin_id: str) -> dict[str, Any]:
        plan = self._dependency_plan(root, runtime)
        timeout_seconds, stall_timeout_seconds = self._dependency_limits(plugin_id, runtime)
        call_id = self.db.create_tool_call(
            plugin_id,
            "__dependencies__",
            {"runtime": runtime, "commands": plan["commands"]},
            invocation_type="install",
            approved_by_user=True,
            metadata={
                "kind": "dependency_install",
                "timeout_seconds": timeout_seconds,
                "stall_timeout_seconds": stall_timeout_seconds,
            },
        )
        started = time.perf_counter()
        log_path, status_path = self._dependency_paths(plugin_id)
        log_path.write_text("", encoding="utf-8")
        write_dependency_status(
            status_path,
            {
                "phase": "preparing",
                "runtime": runtime,
                "command_index": 0,
                "total_commands": len(plan["commands"]),
                "command": [],
                "pid": None,
                "started_at": None,
                "elapsed_seconds": 0,
                "silence_seconds": 0,
                "timeout_seconds": timeout_seconds,
                "stall_timeout_seconds": stall_timeout_seconds,
                "last_output_at": None,
                "reason": "",
            },
        )
        self.db.add_plugin_event(
            plugin_id,
            "info",
            f"Dependency-preparatie gestart voor {runtime}: timeout {timeout_seconds}s, stall-detectie {stall_timeout_seconds or 'uit'}s.",
        )

        if plan["system_missing"]:
            error = "Ontbrekende systeemruntime: " + ", ".join(plan["system_missing"])
            write_dependency_status(
                status_path,
                {
                    "phase": "failed",
                    "runtime": runtime,
                    "command_index": 0,
                    "total_commands": len(plan["commands"]),
                    "command": [],
                    "pid": None,
                    "started_at": None,
                    "elapsed_seconds": 0,
                    "silence_seconds": 0,
                    "timeout_seconds": timeout_seconds,
                    "stall_timeout_seconds": stall_timeout_seconds,
                    "last_output_at": None,
                    "reason": error,
                },
            )
            self.db.finish_tool_call(
                call_id,
                "failed",
                error=error,
                stderr=error,
                duration_ms=round((time.perf_counter() - started) * 1000),
                metadata={"kind": "dependency_install", "system_missing": plan["system_missing"]},
            )
            return {**plan, "installed": False, "error": error, "call_id": call_id}

        env = os.environ.copy()
        if runtime == "node":
            # npm can otherwise stay nearly silent for long stretches, which makes
            # a legitimate install indistinguishable from a hang in the UI.
            env.setdefault("NPM_CONFIG_LOGLEVEL", "info")
            env.setdefault("NPM_CONFIG_PROGRESS", "false")
        runtime_dir = self.runtimes / plugin_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        python_bin = sys.executable
        logs: list[dict[str, Any]] = []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        current_command: list[str] = []
        live_output = self._dependency_output_callback(plugin_id)
        try:
            if runtime == "python":
                venv = runtime_dir / "venv"
                python_candidate = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                if not python_candidate.exists():
                    self.db.add_plugin_event(plugin_id, "info", "Plugin-lokale Python virtual environment wordt aangemaakt.")
                    venv_runner = DependencyCommandRunner(
                        log_path=log_path,
                        status_path=status_path,
                        runtime=runtime,
                        command_index=0,
                        total_commands=len(plan["commands"]),
                        timeout_seconds=min(300, timeout_seconds),
                        stall_timeout_seconds=0,
                        phase="creating_venv",
                        on_output=live_output,
                    )
                    venv_result = venv_runner.run(
                        [sys.executable, "-m", "venv", str(venv)],
                        cwd=root,
                        env=env,
                    )
                    stdout_parts.append(venv_result["stdout"])
                    stderr_parts.append(venv_result["stderr"])
                    logs.append(venv_result)
                    if venv_result["error"]:
                        raise RuntimeError(venv_result["error"])
                python_bin = str(python_candidate)

            for index, raw in enumerate(plan["commands"], start=1):
                command = [python_bin if part == "{python}" else part for part in raw]
                if command and command[0] == "npm":
                    command[0] = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
                current_command = command
                self.db.add_plugin_event(
                    plugin_id,
                    "info",
                    f"Dependency-commando {index}/{len(plan['commands'])} gestart: {' '.join(command)}",
                )
                runner = DependencyCommandRunner(
                    log_path=log_path,
                    status_path=status_path,
                    runtime=runtime,
                    command_index=index,
                    total_commands=len(plan["commands"]),
                    timeout_seconds=timeout_seconds,
                    stall_timeout_seconds=stall_timeout_seconds,
                    on_output=live_output,
                )
                result = runner.run(command, cwd=root, env=env)
                stdout_parts.append(result["stdout"])
                stderr_parts.append(result["stderr"])
                logs.append(result)
                if result["error"]:
                    raise RuntimeError(result["error"])
                self.db.add_plugin_event(
                    plugin_id,
                    "success",
                    f"Dependency-commando {index}/{len(plan['commands'])} voltooid in {result['duration_ms']} ms.",
                )
        except Exception as exc:
            error = str(exc)
            duration = round((time.perf_counter() - started) * 1000)
            last = logs[-1] if logs else {}
            write_dependency_status(
                status_path,
                {
                    "phase": "failed",
                    "runtime": runtime,
                    "command_index": len(logs),
                    "total_commands": len(plan["commands"]),
                    "command": current_command,
                    "pid": None,
                    "started_at": None,
                    "elapsed_seconds": round(duration / 1000, 1),
                    "silence_seconds": 0,
                    "timeout_seconds": timeout_seconds,
                    "stall_timeout_seconds": stall_timeout_seconds,
                    "last_output_at": None,
                    "reason": error,
                },
            )
            output = "\n".join(part for part in [*stdout_parts, *stderr_parts] if part).strip()[-100_000:]
            self.db.finish_tool_call(
                call_id,
                "failed",
                output=output,
                stdout="\n".join(stdout_parts),
                stderr="\n".join([*stderr_parts, error]),
                error=error,
                exit_code=last.get("exit_code"),
                duration_ms=duration,
                metadata={
                    "kind": "dependency_install",
                    "commands": len(plan["commands"]),
                    "timeout_seconds": timeout_seconds,
                    "stall_timeout_seconds": stall_timeout_seconds,
                    "timed_out": bool(last.get("timed_out")),
                    "stalled": bool(last.get("stalled")),
                    "last_command": current_command,
                },
            )
            self.db.add_plugin_event(plugin_id, "error", f"Dependency-preparatie mislukt: {error}")
            return {
                **plan,
                "installed": False,
                "error": error,
                "logs": logs,
                "python": python_bin,
                "call_id": call_id,
                "timeout_seconds": timeout_seconds,
                "stall_timeout_seconds": stall_timeout_seconds,
            }

        duration = round((time.perf_counter() - started) * 1000)
        output = "\n".join(part for part in [*stdout_parts, *stderr_parts] if part).strip()[-100_000:]
        write_dependency_status(
            status_path,
            {
                "phase": "completed",
                "runtime": runtime,
                "command_index": len(plan["commands"]),
                "total_commands": len(plan["commands"]),
                "command": current_command,
                "pid": None,
                "started_at": None,
                "elapsed_seconds": round(duration / 1000, 1),
                "silence_seconds": 0,
                "timeout_seconds": timeout_seconds,
                "stall_timeout_seconds": stall_timeout_seconds,
                "last_output_at": None,
                "reason": "",
            },
        )
        self.db.finish_tool_call(
            call_id,
            "completed",
            output=output,
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            exit_code=0,
            duration_ms=duration,
            metadata={
                "kind": "dependency_install",
                "commands": len(plan["commands"]),
                "timeout_seconds": timeout_seconds,
                "stall_timeout_seconds": stall_timeout_seconds,
            },
        )
        self.db.add_plugin_event(plugin_id, "success", f"Dependency-preparatie voltooid in {duration} ms.")
        return {
            **plan,
            "installed": True,
            "logs": logs,
            "python": python_bin,
            "call_id": call_id,
            "timeout_seconds": timeout_seconds,
            "stall_timeout_seconds": stall_timeout_seconds,
        }