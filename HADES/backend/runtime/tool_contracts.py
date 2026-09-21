"""Tool contract helpers — schema, read vs mutate, idempotency, reconciliation.

Installed ≠ ready. Healthcheck ≠ every action works.
"""

from __future__ import annotations

from typing import Any

READ_ACTIONS = frozenset({"read", "list", "get", "health", "status", "logs", "inspect", "search", "query"})
MUTATING_ACTIONS = frozenset(
    {
        "write",
        "create",
        "update",
        "delete",
        "start",
        "stop",
        "serve",
        "dev",
        "invoke",
        "execute",
        "send",
        "post",
        "patch",
        "put",
    }
)


def classify_tool_action(tool: dict[str, Any] | None) -> dict[str, Any]:
    tool = dict(tool or {})
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    action = str(meta.get("action") or meta.get("mode") or tool.get("action") or tool.get("name") or "").strip().lower()
    explicit = str(meta.get("effect") or meta.get("side_effect") or "").strip().lower()
    if explicit in {"read", "readonly", "read_only"}:
        mutating = False
    elif explicit in {"write", "mutate", "mutating", "side_effect"}:
        mutating = True
    else:
        mutating = any(token in action for token in MUTATING_ACTIONS) and not any(
            token == action for token in READ_ACTIONS
        )
        if action in READ_ACTIONS:
            mutating = False
        if action in MUTATING_ACTIONS:
            mutating = True
    idempotent = bool(meta.get("idempotent")) if "idempotent" in meta else (not mutating)
    return {
        "action": action or "unknown",
        "mutating": mutating,
        "read_only": not mutating,
        "idempotent": idempotent,
        "idempotency_limitations": list(meta.get("idempotency_limitations") or []),
        "capabilities": list(meta.get("capabilities") or tool.get("capabilities") or []),
        "timeout_seconds": meta.get("timeout_seconds") or tool.get("timeout"),
        "cancelable": bool(meta.get("cancelable", True)),
        "expected_artifacts": list(meta.get("expected_artifacts") or []),
        "error_categories": list(
            meta.get("error_categories")
            or ["validation", "timeout", "unavailable", "policy_blocked", "execution_failed", "unknown_outcome"]
        ),
        "reconciliation": meta.get("reconciliation") or ("none" if not mutating else "manual_or_ledger"),
        "compensation": meta.get("compensation"),
        "compensation_is_rollback": bool(meta.get("compensation_is_rollback", False)),
        "note": (
            "Do not call compensation a rollback unless external effects are demonstrably reversible."
            if mutating
            else "Read-only tool."
        ),
    }


def tool_contract_from_plugin_tool(tool: dict[str, Any]) -> dict[str, Any]:
    effect = classify_tool_action(tool)
    return {
        "contract_version": "tool_contract_v1",
        "name": tool.get("name"),
        "input_schema": tool.get("input_schema") or {},
        "output_schema": tool.get("output_schema") or meta_output(tool),
        **effect,
        "ready_requires": ["plugin_enabled", "plugin_status_ready", "contract_tests_optional"],
        "healthcheck_proves_all_actions": False,
        "installed_implies_ready": False,
    }


def meta_output(tool: dict[str, Any]) -> dict[str, Any]:
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    return dict(meta.get("output_schema") or tool.get("output_schema") or {})


def effect_class_for_tool(tool: dict[str, Any] | None) -> str:
    effect = classify_tool_action(tool)
    if not effect["mutating"]:
        return "read_only"
    action = effect["action"]
    if "delete" in action:
        return "fs_delete"
    if action in {"start", "stop", "serve", "dev"}:
        return "subprocess_mutating"
    return "plugin_side_effect"


def run_tool_contract_tests(tool: dict[str, Any], *, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Offline contract tests before treating a plugin tool as ready-for-action."""
    contract = tool_contract_from_plugin_tool(tool)
    results: list[dict[str, Any]] = []
    schema = contract.get("input_schema") or {}
    # Built-in: schema must be object-like when present.
    if schema and not isinstance(schema, dict):
        results.append({"id": "schema_type", "passed": False, "reason": "input_schema_not_object"})
    else:
        results.append({"id": "schema_type", "passed": True, "reason": "ok"})
    results.append(
        {
            "id": "effect_classified",
            "passed": contract.get("action") != "unknown" or bool(schema),
            "reason": contract.get("action"),
        }
    )
    for index, case in enumerate(cases or []):
        # Structural only — does not execute the plugin.
        required = list((schema.get("required") if isinstance(schema, dict) else None) or [])
        args = case.get("arguments") if isinstance(case, dict) else {}
        missing = [k for k in required if k not in (args or {})]
        expect_fail = bool(case.get("expect_validation_error")) if isinstance(case, dict) else False
        invalid = bool(missing)
        passed = invalid == expect_fail if expect_fail or required else True
        results.append(
            {
                "id": str((case or {}).get("id") or f"case_{index}"),
                "passed": passed,
                "missing": missing,
            }
        )
    passed = all(r.get("passed") for r in results)
    return {
        "passed": passed,
        "results": results,
        "contract": contract,
        "ready_for_use": passed,
        "note": "Contract tests are structural. They do not prove every action works on the host.",
    }
