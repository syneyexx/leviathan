"""Safe workflow variable / context resolution — no eval/exec."""

from __future__ import annotations

import re
from typing import Any

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def build_execution_context(
    *,
    inputs: dict[str, Any] | None = None,
    variables: dict[str, Any] | None = None,
    nodes: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "inputs": dict(inputs or {}),
        "variables": dict(variables or {}),
        "nodes": dict(nodes or {}),
        "trigger": dict(trigger or {}),
        "execution": dict(execution or {}),
    }


def _lookup_path(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
                continue
            # Allow nodes.<id>.output convenience
            return None
        return None
    return cur


def resolve_path(ctx: dict[str, Any], path: str) -> Any:
    return _lookup_path(ctx, path)


def resolve_value(value: Any, ctx: dict[str, Any]) -> Any:
    """Resolve ``{{path}}`` templates in strings; recurse into dict/list."""
    if isinstance(value, str):
        full = _VAR_PATTERN.fullmatch(value.strip())
        if full:
            return resolve_path(ctx, full.group(1))
        def repl(match: re.Match[str]) -> str:
            resolved = resolve_path(ctx, match.group(1))
            return "" if resolved is None else str(resolved)

        return _VAR_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: resolve_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, ctx) for v in value]
    return value


def eval_predicate(predicate: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Deterministic structured predicate — never eval()/exec()."""
    if not isinstance(predicate, dict):
        raise ValueError("CONDITION_INVALID: predicate must be an object")
    op = str(predicate.get("op") or predicate.get("operator") or "").lower()
    if op in {"and", "or"}:
        args = predicate.get("args") or predicate.get("predicates") or []
        if not isinstance(args, list) or not args:
            raise ValueError("CONDITION_INVALID: and/or require args")
        results = [eval_predicate(a, ctx) for a in args]
        return all(results) if op == "and" else any(results)
    if op == "not":
        inner = predicate.get("predicate") or predicate.get("arg")
        if not isinstance(inner, dict):
            raise ValueError("CONDITION_INVALID: not requires predicate")
        return not eval_predicate(inner, ctx)

    left = resolve_value(predicate.get("left"), ctx)
    right = resolve_value(predicate.get("right"), ctx)
    path = predicate.get("path")
    if path and "left" not in predicate:
        left = resolve_path(ctx, str(path))

    if op in {"eq", "equals", "=="}:
        return left == right
    if op in {"neq", "not_equals", "!="}:
        return left != right
    if op == "contains":
        if left is None:
            return False
        return right in left  # type: ignore[operator]
    if op == "exists":
        target = left if "left" in predicate or path else resolve_path(ctx, str(predicate.get("path") or ""))
        return target is not None
    if op in {"gt", ">"}:
        return left is not None and right is not None and left > right  # type: ignore[operator]
    if op in {"gte", ">="}:
        return left is not None and right is not None and left >= right  # type: ignore[operator]
    if op in {"lt", "<"}:
        return left is not None and right is not None and left < right  # type: ignore[operator]
    if op in {"lte", "<="}:
        return left is not None and right is not None and left <= right  # type: ignore[operator]
    raise ValueError(f"CONDITION_INVALID: unsupported op {op!r}")
