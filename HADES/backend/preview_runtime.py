"""Local preview / browser capability adapters (Phase J).

Does not auto-install a second browser stack. Reuses PATH browsers / existing plugins when present.
BrowserAdapter binds PluginManager for open/fill/click/screenshot — never claims success when the
plugin is missing or not Ready. Preview start ≠ healthy until an explicit healthcheck passes.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


class PreviewManager:
    """Plan/start/stop local preview processes bound to a coding run."""

    def __init__(self) -> None:
        self._procs: dict[str, dict[str, Any]] = {}

    def plan_preview(self, project_root: Path, *, kind: str = "auto") -> dict[str, Any]:
        root = Path(project_root).expanduser().resolve()
        has_pkg = (root / "package.json").is_file()
        has_index = (root / "index.html").is_file()
        command: list[str] | None = None
        if kind in {"auto", "vite", "npm"} and has_pkg and shutil.which("npm"):
            command = ["npm", "run", "dev", "--", "--host", "127.0.0.1"]
            kind = "npm_dev"
        elif kind in {"auto", "static_check"}:
            kind = "static_check"
            command = None
        return {
            "supported": True,
            "kind": kind,
            "command": command,
            "cwd": str(root),
            "started": False,
            "healthy": False,
            "healthcheck": "http://127.0.0.1:5173/" if kind == "npm_dev" else None,
            "has_index_html": has_index,
            "note": "Preview is planned only until start_preview is called; started≠healthy until healthcheck passes.",
        }

    def start_preview(self, run_id: str, project_root: Path, *, kind: str = "auto") -> dict[str, Any]:
        plan = self.plan_preview(project_root, kind=kind)
        if not plan.get("command"):
            return {**plan, "started": False, "healthy": False, "reason": "no_dev_command", "run_id": run_id}
        # Do not start long-lived servers in unit tests / agents unless explicitly requested.
        # Operators can enable via HADES_PREVIEW_START=1.
        import os

        if os.environ.get("HADES_PREVIEW_START") != "1":
            return {
                **plan,
                "started": False,
                "healthy": False,
                "reason": "start_disabled_set_HADES_PREVIEW_START=1",
                "run_id": run_id,
            }
        proc = subprocess.Popen(  # noqa: S603
            plan["command"],
            cwd=plan["cwd"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._procs[run_id] = {"proc": proc, "plan": plan, "started_at": time.time()}
        # Process spawn is not health proof — probe explicitly.
        health = self.check_health(run_id)
        return {
            **plan,
            "started": True,
            "healthy": bool(health.get("healthy")),
            "pid": proc.pid,
            "run_id": run_id,
            "health": health,
            "note": "Process started; healthy only after healthcheck passes (started≠healthy).",
        }

    def check_health(self, run_id: str, *, timeout: float = 1.5) -> dict[str, Any]:
        """Return healthy only when process still runs AND healthcheck URL responds (when configured)."""
        item = self._procs.get(run_id)
        if not item:
            return {"run_id": run_id, "running": False, "healthy": False, "reason": "not_running"}
        proc = item["proc"]
        code = proc.poll()
        if code is not None:
            return {
                "run_id": run_id,
                "running": False,
                "healthy": False,
                "exit_code": code,
                "reason": f"exited:{code}",
            }
        plan = item.get("plan") or {}
        url = plan.get("healthcheck")
        if not url:
            # No healthcheck configured: running process is still not claimed healthy.
            return {
                "run_id": run_id,
                "running": True,
                "healthy": False,
                "reason": "no_healthcheck_configured_started_not_healthy",
                "pid": proc.pid,
            }
        try:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local preview probe
                ok = 200 <= int(getattr(resp, "status", 200) or 200) < 500
            return {
                "run_id": run_id,
                "running": True,
                "healthy": bool(ok),
                "healthcheck": url,
                "reason": None if ok else "healthcheck_non_success",
                "pid": proc.pid,
            }
        except Exception as exc:
            return {
                "run_id": run_id,
                "running": True,
                "healthy": False,
                "healthcheck": url,
                "reason": f"healthcheck_failed:{exc}",
                "pid": proc.pid,
            }

    def stop_preview(self, run_id: str) -> dict[str, Any]:
        item = self._procs.pop(run_id, None)
        if not item:
            return {"ok": True, "status": "not_running", "run_id": run_id}
        proc = item["proc"]
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        return {"ok": True, "status": "stopped", "run_id": run_id}

    def status(self, run_id: str) -> dict[str, Any]:
        item = self._procs.get(run_id)
        if not item:
            return {"run_id": run_id, "running": False, "healthy": False, "status": "not_running"}
        proc = item["proc"]
        code = proc.poll()
        running = code is None
        health = self.check_health(run_id) if running else {"healthy": False, "reason": f"exited:{code}"}
        return {
            "run_id": run_id,
            "running": running,
            "healthy": bool(health.get("healthy")),
            "status": "running" if running else f"exited:{code}",
            "pid": proc.pid,
            "plan": item.get("plan"),
            "health": health,
        }


_PREVIEW_MANAGER = PreviewManager()


def get_preview_manager() -> PreviewManager:
    return _PREVIEW_MANAGER


class BrowserAdapter:
    """Capability declaration + PluginManager-backed browser actions when Ready."""

    DOM_TOOLS = ("fill", "click", "submit")
    OPEN_TOOLS = ("fetch", "open_page", "open")
    SCREENSHOT_TOOLS = ("screenshot",)

    def __init__(self, plugin_manager: Any | None = None) -> None:
        self.plugin_manager = plugin_manager

    def set_plugin_manager(self, plugin_manager: Any | None) -> None:
        self.plugin_manager = plugin_manager

    def capabilities(self) -> dict[str, Any]:
        available = self._plugin_availability()
        ready = bool(available.get("available"))
        tools = {str(t).lower() for t in (available.get("tools") or [])}
        can_open = ready and bool(tools & {t.lower() for t in self.OPEN_TOOLS})
        can_shot = ready and bool(tools & {t.lower() for t in self.SCREENSHOT_TOOLS})
        can_fill = ready and "fill" in tools
        can_click = ready and ("click" in tools or "submit" in tools)
        can_console = ready and ("console" in tools or "console_errors" in tools)
        return {
            # Capability *intent* vs *executable now* — only claim tools present on the Ready plugin.
            "open_page": can_open,
            "screenshot": can_shot,
            "fill": can_fill,
            "click": can_click,
            "console_errors": can_console,
            "simple_flows": can_open and can_shot,
            "dom_a11y": False,
            "vision_model_required_for_image_judge": True,
            "plugin_available": ready,
            "plugin_status": available,
            "executable_now": ready,
            "note": (
                "A text-only model cannot judge screenshots as if it saw them. "
                "Use a vision-capable available model or rely on measurable browser signals. "
                "open/fill/click/screenshot require a Ready puppeteer plugin via PluginManager; "
                "otherwise actions fail honestly (never claimed success)."
            ),
            "reuse": ["plugins/puppeteer", "plugins/scrapling", "plugins/chrome-devtools-mcp"],
        }

    def _plugin_availability(self) -> dict[str, Any]:
        pm = self.plugin_manager
        if pm is None:
            return {"available": False, "reason": "plugin_manager_not_bound"}
        try:
            plugin = None
            if hasattr(pm, "db") and hasattr(pm.db, "get_plugin"):
                plugin = pm.db.get_plugin("puppeteer")
            if not plugin:
                return {"available": False, "reason": "puppeteer_plugin_not_installed"}
            ready = bool(plugin.get("enabled")) and str(plugin.get("status")) == "ready"
            tools: list[str] = []
            if hasattr(pm.db, "plugin_tools"):
                try:
                    tools = [str(t.get("name") or "") for t in (pm.db.plugin_tools("puppeteer") or []) if t.get("enabled")]
                except Exception:
                    tools = []
            return {
                "available": ready,
                "plugin_id": "puppeteer",
                "status": plugin.get("status"),
                "enabled": plugin.get("enabled"),
                "failure_state": plugin.get("failure_state"),
                "tools": tools,
                "tools_known": True,
                "reason": None if ready else "plugin_not_ready",
            }
        except Exception as exc:
            return {"available": False, "reason": f"plugin_probe_error:{exc}"}

    def _invoke(self, tool_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Route every browser action through PluginManager policy."""
        avail = self._plugin_availability()
        if not avail.get("available"):
            return {
                "ok": False,
                "status": "unavailable",
                "reason": avail.get("reason") or "browser_plugin_unavailable",
                "plugin": avail,
                "policy": "plugin_manager_gate",
            }
        pm = self.plugin_manager
        if pm is None or not hasattr(pm, "invoke"):
            return {
                "ok": False,
                "status": "unavailable",
                "reason": "plugin_manager_not_bound",
                "plugin": avail,
                "policy": "plugin_manager_gate",
            }
        # Prefer declared tool names; map aliases to manifest tools.
        candidates = [tool_name]
        if tool_name in {"open", "open_page"}:
            candidates = ["fetch", "open_page", "open"]
        known = set(avail.get("tools") or [])
        chosen = next((c for c in candidates if not known or c in known), candidates[0])
        if known and chosen not in known:
            # Tool not in Ready plugin manifest — fail via policy, optionally record rejection.
            error = f"tool_not_in_plugin_manifest:{tool_name}"
            if hasattr(pm, "record_rejected_call"):
                try:
                    pm.record_rejected_call(
                        "puppeteer",
                        tool_name,
                        input_data,
                        invocation_type="manual",
                        approved_by_user=True,
                        status="rejected",
                        error=error,
                    )
                except Exception:
                    pass
            return {
                "ok": False,
                "status": "unavailable",
                "reason": error,
                "plugin": avail,
                "tool": tool_name,
                "policy": "plugin_manager_manifest",
            }
        try:
            result = pm.invoke(
                "puppeteer",
                chosen,
                input_data,
                invocation_type="manual",
                approved_by_user=True,
            )
            # PluginManager may return blocked/failed records without raising.
            status = str((result or {}).get("status") or "executed")
            if status in {"failed", "blocked", "rejected", "error"}:
                return {
                    "ok": False,
                    "status": status,
                    "reason": (result or {}).get("error") or status,
                    "result": result,
                    "plugin": "puppeteer",
                    "tool": chosen,
                    "policy": "plugin_manager_invoke",
                }
            return {
                "ok": True,
                "status": "executed",
                "result": result,
                "plugin": "puppeteer",
                "tool": chosen,
                "policy": "plugin_manager_invoke",
            }
        except KeyError as exc:
            error = f"tool_not_found:{exc}"
            if hasattr(pm, "record_rejected_call"):
                try:
                    pm.record_rejected_call(
                        "puppeteer",
                        tool_name,
                        input_data,
                        invocation_type="manual",
                        approved_by_user=True,
                        status="rejected",
                        error=error,
                    )
                except Exception:
                    pass
            return {
                "ok": False,
                "status": "unavailable",
                "reason": error,
                "plugin": "puppeteer",
                "tool": tool_name,
                "policy": "plugin_manager_invoke",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "unavailable",
                "reason": str(exc),
                "plugin": "puppeteer",
                "tool": tool_name,
                "policy": "plugin_manager_invoke",
            }

    def open_page(self, url: str) -> dict[str, Any]:
        invoked = self._invoke("fetch", {"url": url})
        if invoked.get("ok"):
            return {
                "ok": True,
                "status": "opened",
                "url": url,
                "execution": invoked,
                "capabilities": self.capabilities(),
            }
        reason = invoked.get("reason") or "operator_or_plugin_required"
        status = "unavailable" if invoked.get("status") in {"unavailable", "rejected", "blocked", "failed"} else "not_started"
        return {
            "ok": False,
            "status": status,
            "url": url,
            "reason": reason,
            "execution": invoked,
            "capabilities": self.capabilities(),
        }

    def fill(self, selector: str, value: str, *, url: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"selector": selector, "value": value}
        if url:
            payload["url"] = url
        invoked = self._invoke("fill", payload)
        if invoked.get("ok"):
            return {"ok": True, "status": "filled", "selector": selector, "execution": invoked}
        return {
            "ok": False,
            "status": "unavailable" if invoked.get("status") in {"unavailable", "rejected", "blocked", "failed"} else "failed",
            "selector": selector,
            "reason": invoked.get("reason") or "fill_requires_ready_puppeteer_plugin",
            "execution": invoked,
            "capabilities": self.capabilities(),
        }

    def click(self, selector: str, *, url: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"selector": selector}
        if url:
            payload["url"] = url
        invoked = self._invoke("click", payload)
        if invoked.get("ok"):
            return {"ok": True, "status": "clicked", "selector": selector, "execution": invoked}
        return {
            "ok": False,
            "status": "unavailable" if invoked.get("status") in {"unavailable", "rejected", "blocked", "failed"} else "failed",
            "selector": selector,
            "reason": invoked.get("reason") or "click_requires_ready_puppeteer_plugin",
            "execution": invoked,
            "capabilities": self.capabilities(),
        }

    def screenshot(self, url: str, *, out_path: str | None = None) -> dict[str, Any]:
        output = out_path or str(Path("data") / "browser_artifacts" / f"shot_{uuid.uuid4().hex[:10]}.png")
        try:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        invoked = self._invoke("screenshot", {"url": url, "output": output})
        if invoked.get("ok"):
            exists = Path(output).is_file()
            return {
                "ok": exists,
                "status": "captured" if exists else "executed_missing_file",
                "url": url,
                "out_path": output,
                "artifact": {"path": output, "exists": exists, "captured_at": time.time()},
                "execution": invoked,
                "capabilities": self.capabilities(),
                # File must exist — do not claim live host PASS from invoke alone.
                "live_host_pass": False,
                "note": "Mock/unit success is not a live host screenshot PASS.",
            }
        return {
            "ok": False,
            "status": "unavailable" if invoked.get("status") in {"unavailable", "rejected", "blocked", "failed"} else "not_started",
            "url": url,
            "out_path": output,
            "reason": invoked.get("reason") or "use_puppeteer_or_scrapling_plugin",
            "execution": invoked,
            "capabilities": self.capabilities(),
            "live_host_pass": False,
        }

    def run_user_flow(
        self,
        *,
        url: str,
        steps: list[dict[str, Any]],
        out_dir: str | None = None,
        change_hash: str | None = None,
        run_id: str | None = None,
        work_root: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Controlled user flow bound to a change version (fill/click/navigate/assert/console)."""
        avail = self._plugin_availability()
        artifact_dir = Path(out_dir or (Path("data") / "browser_artifacts" / (run_id or uuid.uuid4().hex[:10])))
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        evidence = {
            "run_id": run_id,
            "work_root": work_root,
            "change_hash": change_hash,
            "config": config or {},
            "artifacts": [],
            "stale_if_change_hash_differs": True,
        }
        if not avail.get("available"):
            return {
                "ok": False,
                "status": "unavailable",
                "reason": avail.get("reason"),
                "url": url,
                "steps": steps,
                "evidence": evidence,
                "live_host_pass": False,
            }
        results: list[dict[str, Any]] = []
        console_errors: list[str] = []
        open_res = self.open_page(url)
        results.append({"step": {"action": "open_page", "url": url}, "result": open_res})
        shot = self.screenshot(url, out_path=str(artifact_dir / "flow_start.png"))
        results.append({"step": {"action": "screenshot", "url": url}, "result": shot})
        if shot.get("artifact"):
            evidence["artifacts"].append(shot["artifact"])
        for index, step in enumerate(steps):
            action = str(step.get("action") or "").lower()
            if action in {"navigate", "open"}:
                res = self.open_page(str(step.get("url") or url))
                results.append({"step": step, "result": res})
            elif action == "screenshot":
                path = str(artifact_dir / f"flow_{index}.png")
                res = self.screenshot(str(step.get("url") or url), out_path=path)
                results.append({"step": step, "result": res})
                if res.get("artifact"):
                    evidence["artifacts"].append(res["artifact"])
            elif action == "assert_visible":
                # Do not greenwash visibility via screenshot success — no selector assert tool yet.
                results.append(
                    {
                        "step": step,
                        "result": {
                            "ok": False,
                            "status": "unsupported",
                            "reason": "assert_visible_requires_selector_tool",
                            "selector": step.get("selector"),
                        },
                    }
                )
            elif action in {"fill", "type"}:
                res = self.fill(str(step.get("selector") or ""), str(step.get("value") or ""), url=url)
                results.append({"step": step, "result": res})
            elif action in {"click", "submit"}:
                if action == "submit" and step.get("selector"):
                    res = self.click(str(step.get("selector")), url=url)
                elif action == "click":
                    res = self.click(str(step.get("selector") or ""), url=url)
                else:
                    res = self._invoke("submit", {"selector": step.get("selector"), "url": url})
                    if not res.get("ok"):
                        res = {
                            "ok": False,
                            "status": "unavailable",
                            "reason": res.get("reason") or "submit_requires_ready_puppeteer_tool",
                            "execution": res,
                        }
                results.append({"step": step, "result": res})
            elif action in {"console", "console_errors"}:
                results.append(
                    {
                        "step": step,
                        "result": {
                            "ok": False,
                            "status": "unavailable",
                            "reason": "console_capture_tool_not_available",
                            "errors": console_errors,
                        },
                    }
                )
            else:
                results.append({"step": step, "result": {"ok": False, "status": "unknown_action"}})
        # Require open + every actionable step to succeed. A lone screenshot/open
        # must not greenwash failed fill/click/submit/assert steps.
        # All explicit flow steps are actionable — including console/assert once requested.
        actionable = list(results)
        failed_steps = [row for row in actionable if not (row.get("result") or {}).get("ok")]
        all_ok = bool(open_res.get("ok")) and not failed_steps
        return {
            "ok": all_ok,
            "status": "executed" if all_ok else "failed",
            "url": url,
            "steps_executed": results,
            "failed_steps": len(failed_steps),
            "console_errors": console_errors,
            "evidence": evidence,
            "live_host_pass": False,
            "note": "Evidence is bound to change_hash; mark stale when code changes after verification. Not a live host PASS.",
        }
