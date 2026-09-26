"""SystemInspectService — honest self-inspection from injectable real providers.

GI2: never invent model-generated values (no fake "brain percentage").
Missing measurements → UNMEASURED / null with an honest reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

UNMEASURED = "UNMEASURED"

ProviderFn = Callable[[], Any]


def _safe_call(provider: ProviderFn | None, *, reason: str) -> tuple[Any, str | None]:
    if provider is None:
        return None, reason
    try:
        return provider(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{reason}: {type(exc).__name__}: {exc}"


def _field(value: Any, *, measured: bool, reason: str | None = None) -> dict[str, Any]:
    """Wrap a value with measurement honesty metadata."""
    out: dict[str, Any] = {
        "value": value if measured else None,
        "status": "MEASURED" if measured and value is not UNMEASURED else UNMEASURED,
    }
    if not measured or value is UNMEASURED:
        out["value"] = None if value is UNMEASURED else value
        out["status"] = UNMEASURED
        if reason:
            out["reason"] = reason
    elif reason:
        out["reason"] = reason
    return out


def _measured(value: Any) -> dict[str, Any]:
    return _field(value, measured=value is not None and value is not UNMEASURED)


def _unmeasured(reason: str) -> dict[str, Any]:
    return _field(None, measured=False, reason=reason)


@dataclass
class SystemInspectService:
    """Aggregate REAL process state from injectable providers.

    Each provider is optional. Absence never fabricates a number — it yields
    UNMEASURED with a reason. Consumers (chat / cognition) must not invent
    "brain percentage"; expose only named measurable metrics (hits, util, …).
    """

    application_version_provider: ProviderFn | None = None
    application_commit_provider: ProviderFn | None = None
    active_model_provider: ProviderFn | None = None
    model_role_backend_provider: ProviderFn | None = None
    context_window_provider: ProviderFn | None = None
    cognition_runtime_provider: ProviderFn | None = None
    behavior_profile_provider: ProviderFn | None = None
    brain_status_provider: ProviderFn | None = None
    knowledge_count_provider: ProviderFn | None = None
    memory_count_provider: ProviderFn | None = None
    evidence_count_provider: ProviderFn | None = None
    verification_outcome_provider: ProviderFn | None = None
    agent_fleet_provider: ProviderFn | None = None
    worker_pools_provider: ProviderFn | None = None
    jobs_provider: ProviderFn | None = None
    tool_calls_provider: ProviderFn | None = None
    web_usage_provider: ProviderFn | None = None
    context_budget_provider: ProviderFn | None = None
    telemetry_provider: ProviderFn | None = None
    turn_context_provider: ProviderFn | None = None
    extra_providers: dict[str, ProviderFn] = field(default_factory=dict)

    def inspect(self, scope: str | None = None) -> dict[str, Any]:
        """Return a public_dict inspection snapshot.

        ``scope`` may be ``None``/``"all"`` or a comma-separated subset of
        section names: application, model, cognition, behavior, brain,
        knowledge, memory, evidence, verification, fleet, workers, jobs,
        tools, web, context, telemetry, turn.
        """
        wanted = self._parse_scope(scope)
        sections: dict[str, Any] = {}
        if "application" in wanted:
            sections["application"] = self._section_application()
        if "model" in wanted:
            sections["model"] = self._section_model()
        if "cognition" in wanted:
            sections["cognition"] = self._section_cognition()
        if "behavior" in wanted:
            sections["behavior"] = self._section_behavior()
        if "brain" in wanted:
            sections["brain"] = self._section_brain()
        if "knowledge" in wanted:
            sections["knowledge"] = self._section_knowledge()
        if "memory" in wanted:
            sections["memory"] = self._section_memory()
        if "evidence" in wanted:
            sections["evidence"] = self._section_evidence()
        if "verification" in wanted:
            sections["verification"] = self._section_verification()
        if "fleet" in wanted:
            sections["fleet"] = self._section_fleet()
        if "workers" in wanted:
            sections["workers"] = self._section_workers()
        if "jobs" in wanted:
            sections["jobs"] = self._section_jobs()
        if "tools" in wanted:
            sections["tools"] = self._section_tools()
        if "web" in wanted:
            sections["web"] = self._section_web()
        if "context" in wanted:
            sections["context"] = self._section_context()
        if "telemetry" in wanted:
            sections["telemetry"] = self._section_telemetry()
        if "turn" in wanted:
            sections["turn"] = self._section_turn()

        for name, provider in self.extra_providers.items():
            if name in wanted or "all" in wanted:
                value, err = _safe_call(provider, reason=f"{name}_provider_failed")
                sections[name] = (
                    _measured(value) if err is None else _unmeasured(err or "unknown")
                )

        return {
            "scope": sorted(wanted) if "all" not in (scope or "all").lower() else "all",
            "sections": sections,
            "truth": {
                "no_model_generated_values": True,
                "missing_is_unmeasured": True,
                "never_invents_brain_percentage": True,
                "brain_percentage_is_not_a_metric": True,
                "named_metrics_only": True,
            },
        }

    def public_dict(self, scope: str | None = None) -> dict[str, Any]:
        return self.inspect(scope=scope)

    # --- sections ---------------------------------------------------------

    def _section_application(self) -> dict[str, Any]:
        version, v_err = _safe_call(
            self.application_version_provider, reason="application_version_unavailable"
        )
        commit, c_err = _safe_call(
            self.application_commit_provider, reason="application_commit_unavailable"
        )
        return {
            "version": _measured(version) if v_err is None else _unmeasured(v_err),
            "commit": _measured(commit) if c_err is None else _unmeasured(c_err),
        }

    def _section_model(self) -> dict[str, Any]:
        active, a_err = _safe_call(
            self.active_model_provider, reason="active_model_unavailable"
        )
        role_backend, r_err = _safe_call(
            self.model_role_backend_provider, reason="model_role_backend_unavailable"
        )
        window, w_err = _safe_call(
            self.context_window_provider, reason="context_window_unavailable"
        )
        role = None
        backend = None
        if isinstance(role_backend, Mapping):
            role = role_backend.get("role") or role_backend.get("model_role")
            backend = (
                role_backend.get("backend")
                or role_backend.get("backend_kind")
                or role_backend.get("provider")
            )
        elif isinstance(role_backend, (list, tuple)) and len(role_backend) >= 2:
            role, backend = role_backend[0], role_backend[1]
        return {
            "active_model": _measured(active) if a_err is None else _unmeasured(a_err),
            "model_role": _measured(role) if r_err is None else _unmeasured(r_err),
            "model_backend": _measured(backend) if r_err is None else _unmeasured(r_err),
            "context_window": _measured(window) if w_err is None else _unmeasured(w_err),
        }

    def _section_cognition(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.cognition_runtime_provider, reason="cognition_runtime_unavailable"
        )
        if err is not None:
            return {"summary": _unmeasured(err)}
        if hasattr(value, "health") and callable(value.health):
            try:
                summary = value.health()
            except Exception as exc:  # noqa: BLE001
                return {"summary": _unmeasured(f"cognition_health_failed: {exc}")}
        elif isinstance(value, Mapping):
            summary = dict(value)
        else:
            summary = value
        return {"summary": _measured(summary)}

    def _section_behavior(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.behavior_profile_provider, reason="behavior_profile_unavailable"
        )
        if err is not None:
            return {
                "hash": _unmeasured(err),
                "version": _unmeasured(err),
            }
        profile = value
        if hasattr(profile, "get_effective") and callable(profile.get_effective):
            try:
                profile = profile.get_effective()
            except Exception as exc:  # noqa: BLE001
                return {
                    "hash": _unmeasured(f"behavior_get_effective_failed: {exc}"),
                    "version": _unmeasured(f"behavior_get_effective_failed: {exc}"),
                }
        if isinstance(profile, Mapping):
            return {
                "hash": _measured(profile.get("hash")),
                "version": _measured(profile.get("version")),
                "id": _measured(profile.get("id")),
            }
        return {
            "hash": _measured(getattr(profile, "hash", None)),
            "version": _measured(getattr(profile, "version", None)),
            "id": _measured(getattr(profile, "id", None)),
        }

    def _section_brain(self) -> dict[str, Any]:
        """Brain status — never invent a percentage. Expose measurable hits only."""
        value, err = _safe_call(
            self.brain_status_provider, reason="brain_status_unavailable"
        )
        if err is not None:
            return {
                "status": _unmeasured(err),
                "hits": _unmeasured(err),
                "brain_percentage": {
                    "value": None,
                    "status": UNMEASURED,
                    "reason": "brain_percentage_is_not_a_supported_metric",
                },
                "capability_self_knowledge_truth": {
                    "never_invents_brain_percentage": True,
                    "same_model_critique_is_not_independent_verification": True,
                },
            }
        status = value
        hits = None
        if isinstance(value, Mapping):
            status = value.get("status") or value.get("state")
            hits = value.get("hits") or value.get("hit_count")
            # Strip any invented percentage if a provider wrongly supplies one.
            if "brain_percentage" in value or "brain_pct" in value or "percent" in value:
                # Do not forward invented percentages.
                pass
        return {
            "status": _measured(status),
            "hits": _measured(hits) if hits is not None else _unmeasured(
                "brain_hits_not_provided"
            ),
            "brain_percentage": {
                "value": None,
                "status": UNMEASURED,
                "reason": "brain_percentage_is_not_a_supported_metric",
            },
        }

    def _section_knowledge(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.knowledge_count_provider, reason="knowledge_count_unavailable"
        )
        if err is not None:
            return {"count": _unmeasured(err), "turn_hits": _unmeasured(err)}
        if isinstance(value, Mapping):
            return {
                "count": _measured(value.get("count")),
                "turn_hits": _measured(value.get("turn_hits")),
            }
        return {"count": _measured(value), "turn_hits": _unmeasured("turn_hits_not_provided")}

    def _section_memory(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.memory_count_provider, reason="memory_count_unavailable"
        )
        if err is not None:
            return {"count": _unmeasured(err), "turn_hits": _unmeasured(err)}
        if isinstance(value, Mapping):
            return {
                "count": _measured(value.get("count")),
                "turn_hits": _measured(value.get("turn_hits")),
            }
        return {"count": _measured(value), "turn_hits": _unmeasured("turn_hits_not_provided")}

    def _section_evidence(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.evidence_count_provider, reason="evidence_count_unavailable"
        )
        if err is not None:
            return {"count": _unmeasured(err), "turn_hits": _unmeasured(err)}
        if isinstance(value, Mapping):
            return {
                "count": _measured(value.get("count")),
                "turn_hits": _measured(value.get("turn_hits")),
            }
        return {"count": _measured(value), "turn_hits": _unmeasured("turn_hits_not_provided")}

    def _section_verification(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.verification_outcome_provider, reason="verification_outcome_unavailable"
        )
        if err is not None:
            return {"outcome": _unmeasured(err)}
        return {"outcome": _measured(value)}

    def _section_fleet(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.agent_fleet_provider, reason="agent_fleet_unavailable"
        )
        if err is not None:
            return {
                "active_agents": _unmeasured(err),
                "active_missions": _unmeasured(err),
            }
        if isinstance(value, Mapping):
            return {
                "active_agents": _measured(value.get("active_agents")),
                "active_missions": _measured(value.get("active_missions")),
                "agents": _measured(value.get("agents")),
                "missions": _measured(value.get("missions")),
            }
        return {"snapshot": _measured(value)}

    def _section_workers(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.worker_pools_provider, reason="worker_pools_unavailable"
        )
        if err is not None:
            return {"pools": _unmeasured(err)}
        return {"pools": _measured(value)}

    def _section_jobs(self) -> dict[str, Any]:
        value, err = _safe_call(self.jobs_provider, reason="jobs_unavailable")
        if err is not None:
            return {"summary": _unmeasured(err)}
        return {"summary": _measured(value)}

    def _section_tools(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.tool_calls_provider, reason="tool_calls_unavailable"
        )
        if err is not None:
            return {"summary": _unmeasured(err)}
        return {"summary": _measured(value)}

    def _section_web(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.web_usage_provider, reason="web_usage_unavailable"
        )
        if err is not None:
            return {"usage": _unmeasured(err)}
        return {"usage": _measured(value)}

    def _section_context(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.context_budget_provider, reason="context_budget_unavailable"
        )
        if err is not None:
            return {
                "budget_tokens": _unmeasured(err),
                "used_tokens": _unmeasured(err),
                "context_utilization": _unmeasured(err),
            }
        if isinstance(value, Mapping):
            budget = value.get("budget_tokens") or value.get("budget")
            used = value.get("used_tokens") or value.get("used")
            util = value.get("context_utilization") or value.get("utilization")
            # Compute util only from measured budget/used — never invent.
            if util is None and budget is not None and used is not None:
                try:
                    b = float(budget)
                    u = float(used)
                    util = (u / b) if b > 0 else None
                except (TypeError, ValueError):
                    util = None
            return {
                "budget_tokens": _measured(budget),
                "used_tokens": _measured(used),
                "context_utilization": (
                    _measured(util)
                    if util is not None
                    else _unmeasured("context_utilization_not_computable")
                ),
            }
        return {"snapshot": _measured(value)}

    def _section_telemetry(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.telemetry_provider, reason="telemetry_unavailable"
        )
        if err is not None:
            return {
                "cpu": _unmeasured(err),
                "ram": _unmeasured(err),
                "gpu": _unmeasured(err),
            }
        if not isinstance(value, Mapping):
            return {"snapshot": _measured(value)}
        dash = value.get("dashboard") if isinstance(value.get("dashboard"), Mapping) else {}
        cpu = value.get("cpu") if isinstance(value.get("cpu"), Mapping) else {}
        mem = value.get("memory") if isinstance(value.get("memory"), Mapping) else {}
        gpu = value.get("gpu") if isinstance(value.get("gpu"), Mapping) else {}
        cpu_pct = dash.get("cpuPct") if dash else cpu.get("utilizationPct")
        ram_pct = dash.get("ramPct") if dash else mem.get("utilizationPct")
        gpu_pct = dash.get("gpuPct") if dash else None
        # Honest: null gauges stay null (unavailableIsNotZero).
        return {
            "cpu": (
                _measured(cpu_pct)
                if cpu_pct is not None
                else _unmeasured("cpu_not_measured")
            ),
            "ram": (
                _measured(ram_pct)
                if ram_pct is not None
                else _unmeasured("ram_not_measured")
            ),
            "gpu": (
                _measured(gpu_pct)
                if gpu_pct is not None
                else _unmeasured("gpu_not_measured")
            ),
            "raw": _measured(
                {
                    "cpu": cpu or None,
                    "memory": mem or None,
                    "gpu": gpu or None,
                    "notes": list(value.get("notes") or []),
                }
            ),
        }

    def _section_turn(self) -> dict[str, Any]:
        value, err = _safe_call(
            self.turn_context_provider, reason="turn_context_unavailable"
        )
        if err is not None:
            return {"counts": _unmeasured(err)}
        return {"counts": _measured(value)}

    @staticmethod
    def _parse_scope(scope: str | None) -> set[str]:
        if scope is None or str(scope).strip() == "" or str(scope).strip().lower() == "all":
            return {
                "application",
                "model",
                "cognition",
                "behavior",
                "brain",
                "knowledge",
                "memory",
                "evidence",
                "verification",
                "fleet",
                "workers",
                "jobs",
                "tools",
                "web",
                "context",
                "telemetry",
                "turn",
            }
        parts = {p.strip().lower() for p in str(scope).split(",") if p.strip()}
        return parts or {"application"}


# Process-bound service for FUNCTION provider dispatch (set from main.py).
_BOUND: SystemInspectService | None = None


def bind_system_inspect_service(service: SystemInspectService | None) -> None:
    global _BOUND
    _BOUND = service


def get_system_inspect_service() -> SystemInspectService:
    global _BOUND
    if _BOUND is None:
        # Honest empty service — all sections UNMEASURED until main wires deps.
        _BOUND = SystemInspectService()
    return _BOUND
