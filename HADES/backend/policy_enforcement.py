"""Shared production-path policy enforcement (A09).

Wire G11 tool-arg boundary and G8 MCP allowlists into every real invoke path:
chat tool loop, manual plugin runs, workflows, and MCP-labelled tools.
Deterministic — never delegates permission decisions to the model.
"""

from __future__ import annotations

from typing import Any, Mapping


def enforce_tool_invocation_policies(
    *,
    tool_name: str,
    arguments: Any,
    settings: Mapping[str, Any] | None = None,
    source: str = "unknown",
    is_mcp_tool: bool | None = None,
) -> dict[str, Any]:
    """Return ``{allowed, reason, findings, args, defenses}``. Fail closed on injection."""
    from gen2.mcp_harden import tool_allowed_by_mcp_lists
    from gen2.tool_boundary import enforce_tool_args

    cfg = dict(settings or {})
    defenses: list[str] = []
    findings: list[dict[str, Any]] = []

    # G11 — tool argument boundary (all tools).
    boundary = enforce_tool_args(arguments, mode=str(cfg.get("tool_boundary_mode") or "reject"))
    defenses.append("g11_tool_boundary")
    if not boundary.get("allowed"):
        return {
            "allowed": False,
            "reason": f"g11_tool_boundary:{boundary.get('reason')}",
            "findings": list(boundary.get("findings") or []),
            "args": None,
            "defenses": defenses,
            "source": source,
            "tool_name": tool_name,
        }
    cleaned_args = boundary.get("args")
    if boundary.get("findings"):
        findings.extend(list(boundary.get("findings") or []))

    # G8 — MCP allow/deny when tool is MCP-scoped or MCP lists are configured.
    mcp_configured = any(
        cfg.get(key)
        for key in (
            "mcp_allowed_tools",
            "mcp_denied_tools",
            "allowed_tools",
            "denied_tools",
            "mcp.allowed_tools",
            "mcp.denied_tools",
            "mcp_enabled",
        )
    )
    treat_as_mcp = bool(is_mcp_tool) or bool(cfg.get("mcp_enforce_all_tools")) or (
        mcp_configured and str(tool_name).startswith("mcp.")
    )
    if treat_as_mcp or mcp_configured:
        # When deny/allow lists exist, apply to matching tool names (deny always wins).
        decision = tool_allowed_by_mcp_lists(tool_name, cfg)
        defenses.append("g8_mcp_allowlist")
        # Only hard-block when lists are non-empty or mcp explicitly disabled,
        # or tool is explicitly MCP-scoped.
        report = decision.get("report") or {}
        has_lists = bool(report.get("allowed_tools") or report.get("denied_tools"))
        if treat_as_mcp or has_lists or report.get("enabled") is False:
            if not decision.get("allowed"):
                return {
                    "allowed": False,
                    "reason": f"g8_mcp:{decision.get('reason')}",
                    "findings": [
                        {
                            "code": str(decision.get("reason") or "mcp_denied"),
                            "message": f"MCP policy blocked tool '{tool_name}'",
                        }
                    ],
                    "args": None,
                    "defenses": defenses,
                    "source": source,
                    "tool_name": tool_name,
                    "mcp": decision,
                }

    return {
        "allowed": True,
        "reason": "policies_pass",
        "findings": findings,
        "args": cleaned_args,
        "defenses": defenses,
        "source": source,
        "tool_name": tool_name,
    }


def stop_and_ask_response(
    *,
    route: Any,
    user_message: str = "",
) -> dict[str, Any]:
    """Build a persistent wait payload when route.stop_and_ask is set."""
    questions = list(getattr(route, "ask_questions", None) or [])
    if not questions:
        questions = list(getattr(route, "clarifying_questions", None) or [])
    if not questions:
        meta = getattr(route, "metadata", None) or {}
        if isinstance(meta, dict):
            questions = list(meta.get("clarifying_questions") or meta.get("questions") or [])
    if not questions:
        questions = [
            "Welke ontbrekende informatie of toestemming is nodig om veilig door te gaan?"
        ]
    return {
        "status": "awaiting_user_input",
        "stop_and_ask": True,
        "blocked_risky_actions": True,
        "questions": questions,
        "message": (
            "Ik stop hier en vraag om verduidelijking voordat er risicovolle acties starten.\n\n"
            + "\n".join(f"- {q}" for q in questions)
        ),
        "user_message_preview": (user_message or "")[:200],
        "reason": str(getattr(route, "rationale", None) or getattr(route, "reason", None) or "stop_and_ask"),
    }
