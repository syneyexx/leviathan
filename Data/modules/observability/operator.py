"""Controlled operator command registry for Console (no shell)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class OperatorCommandResult:
    ok: bool
    command: str
    output: Any
    error: str | None = None
    events_emitted: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "output": self.output,
            "error": self.error,
            "events_emitted": self.events_emitted,
        }


class OperatorCommandError(ValueError):
    pass


class OperatorCommandRegistry:
    """Map console text commands to real backend callables.

    Security invariants:
    - No shell interpolation / eval / subprocess from raw text
    - Grammar is explicit argv tokens via shlex (POSIX-like quoting only)
    - Unknown commands fail closed
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[list[str]], dict[str, Any]]] = {}
        self._help: dict[str, str] = {}

    def register(
        self,
        name: str,
        handler: Callable[[list[str]], dict[str, Any]],
        *,
        help_text: str,
    ) -> None:
        key = name.strip().lower()
        if not key or " " in key:
            raise ValueError("command name must be a single token")
        self._handlers[key] = handler
        self._help[key] = help_text

    def list_commands(self) -> list[dict[str, str]]:
        return [{"name": k, "help": self._help[k]} for k in sorted(self._handlers)]

    def execute(self, line: str) -> OperatorCommandResult:
        text = (line or "").strip()
        if not text:
            return OperatorCommandResult(ok=False, command="", output=None, error="empty_command")
        try:
            argv = shlex.split(text, posix=True)
        except ValueError as exc:
            return OperatorCommandResult(
                ok=False, command=text, output=None, error=f"parse_error: {exc}"
            )
        if not argv:
            return OperatorCommandResult(ok=False, command=text, output=None, error="empty_command")

        # Reject shell metacharacters that survived tokenization oddly
        for token in argv:
            if any(ch in token for ch in ("`", "$(", "${", ";", "|", "&", ">", "<", "\n")):
                return OperatorCommandResult(
                    ok=False,
                    command=text,
                    output=None,
                    error="shell_metacharacters_rejected",
                )

        name = argv[0].lower()
        if name in {"help", "?"}:
            return OperatorCommandResult(
                ok=True,
                command=text,
                output={"commands": self.list_commands()},
            )
        handler = self._handlers.get(name)
        if handler is None:
            return OperatorCommandResult(
                ok=False,
                command=text,
                output=None,
                error=f"unknown_command: {name}",
            )
        try:
            output = handler(argv[1:])
            return OperatorCommandResult(ok=True, command=text, output=output)
        except OperatorCommandError as exc:
            return OperatorCommandResult(ok=False, command=text, output=None, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return OperatorCommandResult(
                ok=False,
                command=text,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
            )


def build_default_operator_registry(*, deps: dict[str, Any]) -> OperatorCommandRegistry:
    """Wire real Leviathan services into operator commands.

    ``deps`` may include: observability, module_manager, mcp_bridge, workflow_store,
    workflow_runtime, job_runtime, job_store, capability_catalog, research_service,
    dataset_service, metrics, system_telemetry_sampler, health_fn
    """
    registry = OperatorCommandRegistry()
    obs = deps.get("observability")
    modules = deps.get("module_manager")
    mcp = deps.get("mcp_bridge")
    workflows = deps.get("workflow_store")
    workflow_runtime = deps.get("workflow_runtime")
    jobs = deps.get("job_store")
    job_runtime = deps.get("job_runtime")
    capabilities = deps.get("capability_catalog")
    research = deps.get("research_service")
    datasets = deps.get("dataset_service")
    metrics = deps.get("metrics")
    sampler = deps.get("system_telemetry_sampler")
    health_fn = deps.get("health_fn")

    def _require(args: list[str], n: int, usage: str) -> None:
        if len(args) < n:
            raise OperatorCommandError(f"usage: {usage}")

    def cmd_health(_args: list[str]) -> dict[str, Any]:
        if callable(health_fn):
            return {"health": health_fn()}
        return {"health": "ok", "note": "no_health_fn"}

    def cmd_status(_args: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if obs is not None:
            out["observability"] = obs.snapshot()
        if metrics is not None:
            out["metrics"] = metrics.snapshot().public_dict()
        if sampler is not None:
            out["system"] = sampler.latest_public()
        return out

    def cmd_events(args: list[str]) -> dict[str, Any]:
        if obs is None:
            raise OperatorCommandError("observability_unavailable")
        limit = 50
        if args:
            try:
                limit = max(1, min(500, int(args[0])))
            except ValueError as exc:
                raise OperatorCommandError("usage: events [limit]") from exc
        events = [e.public_dict() if hasattr(e, "public_dict") else e for e in obs.recent(limit=limit)]
        return {"events": events, "count": len(events)}

    def cmd_modules(args: list[str]) -> dict[str, Any]:
        if modules is None:
            raise OperatorCommandError("module_manager_unavailable")
        if not args or args[0] == "list":
            return modules.public_snapshot()
        action = args[0]
        if action == "discover":
            manifests = modules.discover()
            return {"discovered": [m.public_dict() if hasattr(m, "public_dict") else m for m in manifests]}
        if action in {"start", "stop", "restart", "load", "initialize", "shutdown", "reload"}:
            _require(args, 2, f"modules {action} <id>")
            module_id = args[1]
            from Data.modules.module_manager import ModuleContext

            ctx = ModuleContext()
            if action in {"start", "initialize"}:
                result = modules.initialize(module_id, ctx)
            elif action == "load":
                result = modules.load(module_id)
            elif action in {"stop", "shutdown"}:
                result = modules.shutdown(module_id)
            elif action == "reload":
                result = modules.reload(module_id, ctx)
            elif action == "restart":
                try:
                    modules.shutdown(module_id)
                except Exception:
                    pass
                result = modules.initialize(module_id, ctx)
            else:
                raise OperatorCommandError(f"unsupported_action: {action}")
            return {"result": result.public_dict() if hasattr(result, "public_dict") else result}
        raise OperatorCommandError("usage: modules list|discover|start|stop|restart <id>")

    def cmd_mcp(args: list[str]) -> dict[str, Any]:
        if mcp is None:
            raise OperatorCommandError("mcp_unavailable")
        if not args or args[0] == "list":
            servers = mcp.list_servers() if hasattr(mcp, "list_servers") else []
            return {
                "servers": [s.public_dict() if hasattr(s, "public_dict") else s for s in servers]
            }
        action = args[0]
        _require(args, 2, f"mcp {action} <id>")
        server_id = args[1]
        mapping = {
            "connect": "connect",
            "disconnect": "disconnect",
            "refresh": "refresh_tools",
            "enable": "enable",
            "disable": "disable",
        }
        method_name = mapping.get(action)
        if method_name is None:
            raise OperatorCommandError("usage: mcp list|connect|disconnect|refresh <id>")
        method = getattr(mcp, method_name, None)
        if method is None:
            raise OperatorCommandError(f"unsupported_action: {action}")
        result = method(server_id)
        return {"result": result.public_dict() if hasattr(result, "public_dict") else result}

    def cmd_tools(args: list[str]) -> dict[str, Any]:
        if capabilities is None:
            raise OperatorCommandError("capability_catalog_unavailable")
        limit = 100
        q = None
        if args:
            q = args[0]
        items = capabilities.list() if not q else capabilities.search(q, limit=limit)
        return {
            "tools": [i.public_dict() if hasattr(i, "public_dict") else i for i in items[:limit]]
        }

    def cmd_capabilities(args: list[str]) -> dict[str, Any]:
        return cmd_tools(args)

    def cmd_workflows(args: list[str]) -> dict[str, Any]:
        if workflows is None:
            raise OperatorCommandError("workflow_store_unavailable")
        if not args or args[0] == "list":
            items = workflows.list(limit=50) if hasattr(workflows, "list") else []
            return {
                "workflows": [w.public_dict() if hasattr(w, "public_dict") else w for w in items]
            }
        action = args[0]
        _require(args, 2, f"workflows {action} <id>")
        wf_id = args[1]
        if action == "run":
            if workflow_runtime is None:
                raise OperatorCommandError("workflow_runtime_unavailable")
            result = workflow_runtime.run(wf_id)
            return {"workflow": result.public_dict() if hasattr(result, "public_dict") else result}
        if action == "cancel":
            if workflow_runtime is None and not hasattr(workflows, "cancel"):
                raise OperatorCommandError("workflow_cancel_unavailable")
            target = workflow_runtime or workflows
            result = target.cancel(wf_id)
            return {"workflow": result.public_dict() if hasattr(result, "public_dict") else result}
        raise OperatorCommandError("usage: workflows list|run|cancel <id>")

    def cmd_jobs(args: list[str]) -> dict[str, Any]:
        source = job_runtime or jobs
        if source is None:
            raise OperatorCommandError("job_store_unavailable")
        if not args or args[0] == "list":
            items = source.list(limit=50) if hasattr(source, "list") else []
            return {"jobs": [j.public_dict() if hasattr(j, "public_dict") else j for j in items]}
        if args[0] == "cancel":
            _require(args, 2, "jobs cancel <id>")
            if job_runtime is None:
                raise OperatorCommandError("job_runtime_unavailable")
            result = job_runtime.cancel(args[1])
            return {"job": result.public_dict() if hasattr(result, "public_dict") else result}
        raise OperatorCommandError("usage: jobs list|cancel <id>")

    def cmd_workers(args: list[str]) -> dict[str, Any]:
        """List worker pools / instances from the durable registry (not model serving)."""
        from Data.modules.workers.pools import POOL_CATALOG
        from Data.modules.workers.registry import WorkerRegistry
        from Data.modules.workers.settings import load_worker_settings

        db_path = deps.get("database_path")
        if db_path is None and jobs is not None:
            db_path = getattr(jobs, "db_path", None) or getattr(jobs, "path", None)
        if db_path is None:
            raise OperatorCommandError("worker_registry_unavailable")
        registry_store = WorkerRegistry(db_path)
        registry_store.initialize()
        wsettings = load_worker_settings()
        pool_filter = args[0] if args and args[0] not in {"list", "pools"} else (
            args[1] if len(args) > 1 and args[0] == "list" else None
        )
        if args and args[0] == "pools":
            pools = []
            for pid, defn in POOL_CATALOG.items():
                regs = registry_store.list(pool_id=pid)
                pools.append(
                    {
                        **defn.public_dict(),
                        "desired": wsettings.desired_count(pid),
                        "instances": len(regs),
                        "ready": sum(1 for r in regs if r.state.value == "READY"),
                        "busy": sum(1 for r in regs if r.state.value == "BUSY"),
                    }
                )
            return {
                "pools": pools,
                "truth": {"model_serving_not_listed_here": True},
            }
        workers = registry_store.list(pool_id=pool_filter)
        return {
            "workers": [w.public_dict() for w in workers],
            "settings": wsettings.public_dict(),
            "truth": {
                "stale_row_is_not_live_worker": True,
                "model_serving_not_listed_here": True,
            },
        }

    def cmd_research(args: list[str]) -> dict[str, Any]:
        if research is None:
            raise OperatorCommandError("research_unavailable")
        if not args or args[0] == "list":
            items = research.list_projects(limit=50) if hasattr(research, "list_projects") else []
            return {
                "projects": [p.public_dict() if hasattr(p, "public_dict") else p for p in items]
            }
        raise OperatorCommandError("usage: research list")

    def cmd_datasets(args: list[str]) -> dict[str, Any]:
        if datasets is None:
            raise OperatorCommandError("datasets_unavailable")
        if not args or args[0] in {"list", "jobs"}:
            if args and args[0] == "jobs":
                store = getattr(datasets, "store", None)
                if store is not None and hasattr(store, "list_jobs"):
                    items = store.list_jobs(limit=50)
                elif hasattr(datasets, "list_jobs"):
                    items = datasets.list_jobs(limit=50)
                else:
                    items = []
                return {"jobs": [j.public_dict() if hasattr(j, "public_dict") else j for j in items]}
            items = datasets.list_datasets(limit=50) if hasattr(datasets, "list_datasets") else []
            return {
                "datasets": [d.public_dict() if hasattr(d, "public_dict") else d for d in items]
            }
        raise OperatorCommandError("usage: datasets list|jobs")

    def cmd_telemetry(_args: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if sampler is not None:
            out["system"] = sampler.latest_public()
        if metrics is not None:
            out["metrics"] = metrics.snapshot().public_dict()
        if obs is not None:
            out["observability"] = obs.snapshot()
        return out

    registry.register("health", cmd_health, help_text="Show backend health snapshot")
    registry.register("status", cmd_status, help_text="Show observability/metrics/system status")
    registry.register("events", cmd_events, help_text="events [limit] — recent events")
    registry.register("modules", cmd_modules, help_text="modules list|discover|start|stop|restart <id>")
    registry.register("mcp", cmd_mcp, help_text="mcp list|connect|disconnect|refresh <id>")
    registry.register("tools", cmd_tools, help_text="tools [query] — list capabilities")
    registry.register("capabilities", cmd_capabilities, help_text="capabilities [query]")
    registry.register("workflows", cmd_workflows, help_text="workflows list|run|cancel <id>")
    registry.register("jobs", cmd_jobs, help_text="jobs list|cancel <id>")
    registry.register(
        "workers",
        cmd_workers,
        help_text="workers [list [pool]|pools] — generic worker registry (not model serving)",
    )
    registry.register("research", cmd_research, help_text="research list")
    registry.register("datasets", cmd_datasets, help_text="datasets list|jobs")
    registry.register("telemetry", cmd_telemetry, help_text="telemetry snapshot")
    return registry
