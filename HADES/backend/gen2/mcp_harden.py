"""MCP tool allowlists + hardened schema validation (G8).

Validates settings/config shapes offline. Does not contact MCP servers.
"""

from __future__ import annotations

from typing import Any


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def validate_mcp_allowlist_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate MCP allow/deny lists and basic schema discipline.

    Empty allowlist means "all registered" (documented) — not an error.
    Deny always wins over allow when both list a tool.
    """
    cfg = dict(config or {})
    findings: list[dict[str, Any]] = []
    allowed = _as_str_list(cfg.get("mcp_allowed_tools") or cfg.get("allowed_tools") or cfg.get("mcp.allowed_tools"))
    denied = _as_str_list(cfg.get("mcp_denied_tools") or cfg.get("denied_tools") or cfg.get("mcp.denied_tools"))
    enabled = cfg.get("mcp_enabled")
    if enabled is None:
        enabled = cfg.get("mcp.enabled", True)

    overlap = sorted(set(allowed) & set(denied))
    if overlap:
        findings.append(
            {
                "code": "allow_deny_overlap",
                "severity": "warning",
                "message": f"Tools in both allow and deny lists (deny wins): {overlap}",
                "tools": overlap,
            }
        )

    for name in allowed + denied:
        if any(ch in name for ch in ("*", "?", "[", "]")) and name not in {"*"}:
            findings.append(
                {
                    "code": "glob_in_allowlist",
                    "severity": "error",
                    "message": f"Globs are not supported in MCP allow/deny lists: {name}",
                    "tool": name,
                }
            )
        if "\n" in name or "\r" in name:
            findings.append(
                {
                    "code": "newline_in_tool_name",
                    "severity": "error",
                    "message": "Tool names must not contain newlines",
                    "tool": name,
                }
            )

    schemas = cfg.get("tool_schemas") or cfg.get("mcp_tool_schemas") or {}
    if schemas is not None and not isinstance(schemas, dict):
        findings.append(
            {
                "code": "invalid_tool_schemas_type",
                "severity": "error",
                "message": "tool_schemas must be an object keyed by tool name",
            }
        )
        schemas = {}

    schema_reports: list[dict[str, Any]] = []
    for tool_name, schema in (schemas or {}).items():
        schema_reports.append(validate_mcp_tool_schema(tool_name, schema))

    hard_errors = [f for f in findings if f.get("severity") == "error"]
    hard_errors.extend([r for r in schema_reports if not r.get("ok")])

    return {
        "ok": len(hard_errors) == 0,
        "enabled": bool(enabled),
        "allowed_tools": allowed,
        "denied_tools": denied,
        "allowlist_mode": "explicit" if allowed else "all_registered",
        "deny_wins": True,
        "findings": findings,
        "schema_reports": schema_reports,
        "scope": "gen2_mcp_harden_v1",
        "network_required": False,
        "note": (
            "Offline allowlist/schema validation only. Empty allowlist = all registered MCP tools; "
            "runtime still requires Permission Engine + Ready status."
        ),
    }


def validate_mcp_tool_schema(tool_name: str, schema: Any) -> dict[str, Any]:
    """Hardened JSON-schema-ish checks for one MCP tool input schema."""
    issues: list[str] = []
    name = str(tool_name or "").strip() or "unknown"
    if not isinstance(schema, dict):
        return {
            "ok": False,
            "tool": name,
            "issues": ["schema_must_be_object"],
        }
    if schema.get("type") not in (None, "object"):
        issues.append("root_type_should_be_object")
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        issues.append("properties_must_be_object")
    if schema.get("additionalProperties") is not False:
        issues.append("prefer_additionalProperties_false")
    # Injection-prone freeform keys in schema descriptions
    blob = str(schema)
    for marker in ("ignore previous", "grant_admin", "system:"):
        if marker in blob.lower():
            issues.append(f"suspicious_schema_text:{marker}")
    # Soft preference only for additionalProperties — do not fail solely on that.
    hard = [i for i in issues if not i.startswith("prefer_")]
    return {
        "ok": len(hard) == 0,
        "tool": name,
        "issues": issues,
        "hardened": schema.get("additionalProperties") is False,
    }


def tool_allowed_by_mcp_lists(tool_name: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """Pure allow/deny decision for a tool name against validated lists."""
    report = validate_mcp_allowlist_config(config)
    name = str(tool_name or "").strip()
    if not name:
        return {"allowed": False, "reason": "empty_tool_name", "report": report}
    denied = set(report["denied_tools"])
    allowed = set(report["allowed_tools"])
    if name in denied:
        return {"allowed": False, "reason": "denied_list", "report": report}
    if allowed and name not in allowed:
        return {"allowed": False, "reason": "not_in_allowlist", "report": report}
    if not report.get("enabled", True):
        return {"allowed": False, "reason": "mcp_disabled", "report": report}
    return {
        "allowed": True,
        "reason": "allowlist_pass" if allowed else "all_registered_mode",
        "report": report,
    }
