"""Development-time hardcoded limit detector for regression checks.

Scans Python and TypeScript/TSX for behavioral constraints across runtime
source trees. Findings must be classified via ``limit_classifications``;
unclassified findings and unbound ``configurable`` labels fail CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .limit_classifications import (
    classify,
    classification_entry,
    fingerprint,
    unbound_configurable_entries,
    validate_configurable_finding,
)


SUSPICIOUS_NAME_RE = re.compile(
    r"^(MAX_|DEFAULT_MAX_|LIMIT_|TIMEOUT_|RETRY_|CAP_|THRESHOLD_|max_|min_).+"
)
SUSPICIOUS_ASSIGN_RE = re.compile(
    r"^(?!\s*#)\s*(max_iterations|max_retries|max_tools|max_depth|batch_size|timeout_seconds|timeout|top_n|window|bars|page_size|poll_interval|concurrency)\s*=\s*-?\d+",
    re.M,
)

PYDANTIC_BOUND_KEYS = {"le", "ge", "lt", "gt", "max_length", "min_length", "multiple_of"}

TS_CAP_RE = re.compile(
    r"\b(maxFiles|max_files|maxTokens|max_tokens|timeout|retryCount|pollInterval|pageSize|page_size|limit|concurrency|batchSize)\s*[:=]\s*(\d+)",
    re.I,
)
TS_MATH_CLAMP_RE = re.compile(r"Math\.(min|max)\s*\(\s*[^,]+,\s*(\d+)")
TS_SLICE_RE = re.compile(r"\.(?:slice|splice)\s*\(\s*0\s*,\s*(\d+)\s*\)")

SKIP_PARTS = {
    "node_modules",
    ".git",
    "dist",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    "build",
    ".next",
    "coverage",
}

# Detector source itself + classification registry are allowed to mention limits.
SKIP_FILES = {
    "backend/control/detect.py",
    "backend/control/limit_classifications.py",
    "backend/control/definitions.py",
    "backend/control/immutable.py",
}

SCAN_ROOTS = (
    "backend",
    "components",
    "lib",
    "hooks",
    "app",
    "scripts",
    "plugins",
)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _should_skip(path: Path, root: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_PARTS:
        return True
    rel = _rel(path, root)
    if rel in SKIP_FILES:
        return True
    if path.suffix not in {".py", ".ts", ".tsx"}:
        return True
    return False


def _parents_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    cur: ast.AST | None = node
    class_name = ""
    func_name = ""
    while cur is not None:
        if isinstance(cur, ast.ClassDef) and not class_name:
            class_name = cur.name
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)) and not func_name:
            func_name = cur.name
        cur = parents.get(cur)
    if class_name and func_name:
        return f"{class_name}.{func_name}"
    if class_name:
        return class_name
    if func_name:
        return func_name
    return "module"


def _const_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return int(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        if isinstance(node.operand.value, (int, float)):
            return -int(node.operand.value)
    return None


def scan_python_file(path: Path, *, root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return findings
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return findings

    rel = _rel(path, root)
    parents = _parents_map(tree)

    def add(
        node: ast.AST,
        *,
        kind: str,
        name: str,
        snippet: str,
        value: Any = None,
    ) -> None:
        row: dict[str, Any] = {
            "file": rel,
            "line": getattr(node, "lineno", 0) or 0,
            "kind": kind,
            "name": name,
            "symbol": _enclosing_symbol(node, parents),
            "snippet": (snippet or name)[:200],
        }
        if value is not None:
            row["value"] = value
        findings.append(row)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and SUSPICIOUS_NAME_RE.match(target.id):
                    if isinstance(node.value, (ast.Constant, ast.UnaryOp, ast.BinOp)):
                        add(
                            node,
                            kind="named_constant",
                            name=target.id,
                            snippet=ast.get_source_segment(source, node) or target.id,
                        )

        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr

            if name in {"Semaphore", "BoundedSemaphore"} and node.args:
                val = _const_int(node.args[0])
                if val is not None:
                    add(
                        node,
                        kind="semaphore_literal",
                        name=name,
                        snippet=ast.get_source_segment(source, node) or name,
                        value=val,
                    )

            if name in {"ThreadPoolExecutor", "ProcessPoolExecutor"}:
                for kw in node.keywords:
                    if kw.arg == "max_workers":
                        val = _const_int(kw.value)
                        if val is not None:
                            add(
                                node,
                                kind="thread_pool" if name == "ThreadPoolExecutor" else "process_pool",
                                name="max_workers",
                                snippet=ast.get_source_segment(source, node) or name,
                                value=val,
                            )

            if name in {"Queue", "LifoQueue", "PriorityQueue", "SimpleQueue"}:
                for kw in node.keywords:
                    if kw.arg == "maxsize":
                        val = _const_int(kw.value)
                        if val is not None:
                            add(
                                node,
                                kind="queue_size",
                                name="maxsize",
                                snippet=ast.get_source_segment(source, node) or name,
                                value=val,
                            )
                if node.args:
                    val = _const_int(node.args[0])
                    if val is not None and val > 0:
                        add(
                            node,
                            kind="queue_size",
                            name="maxsize",
                            snippet=ast.get_source_segment(source, node) or name,
                            value=val,
                        )

            if name == "Field":
                for kw in node.keywords:
                    if kw.arg in PYDANTIC_BOUND_KEYS and isinstance(kw.value, ast.Constant):
                        add(
                            node,
                            kind="pydantic_bound",
                            name=str(kw.arg),
                            snippet=ast.get_source_segment(source, node) or str(kw.arg),
                            value=kw.value.value,
                        )

            if name in {"wait_for", "sleep"} or name.endswith("timeout"):
                for kw in node.keywords:
                    if kw.arg in {"timeout", "timeout_seconds"} and isinstance(kw.value, ast.Constant):
                        add(
                            node,
                            kind="timeout_literal",
                            name=kw.arg,
                            snippet=ast.get_source_segment(source, node) or str(kw.arg),
                            value=kw.value.value,
                        )
                if name == "sleep" and node.args:
                    val = _const_int(node.args[0])
                    if val is not None:
                        add(
                            node,
                            kind="sleep_literal",
                            name="sleep",
                            snippet=ast.get_source_segment(source, node) or "sleep",
                            value=val,
                        )

            if name in {"min", "max"} and len(node.args) >= 2:
                for arg in node.args:
                    val = _const_int(arg)
                    if val is not None and abs(val) >= 1:
                        add(
                            node,
                            kind="min_clamp" if name == "min" else "max_clamp",
                            name=name,
                            snippet=ast.get_source_segment(source, node) or name,
                            value=val,
                        )
                        break

            if name == "range" and node.args:
                # range(N) or range(a, b) — treat large/caps as range_cap
                last = node.args[-1]
                val = _const_int(last)
                if val is not None and val >= 8:
                    add(
                        node,
                        kind="range_cap",
                        name="range",
                        snippet=ast.get_source_segment(source, node) or "range",
                        value=val,
                    )

        # Numeric slices [:N] / [0:N]
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            upper = node.slice.upper
            val = _const_int(upper) if upper is not None else None
            if val is not None and val >= 1:
                add(
                    node,
                    kind="py_slice",
                    name=f"[:{val}]",
                    snippet=ast.get_source_segment(source, node) or f"[:{val}]",
                    value=val,
                )

    for match in SUSPICIOUS_ASSIGN_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        # Approximate symbol: nearest prior def line (best-effort textual).
        prior = source[: match.start()].rsplit("\ndef ", 1)
        symbol = "module"
        if len(prior) == 2:
            symbol = prior[1].split("(", 1)[0].split("\n", 1)[0].strip() or "module"
        prior_async = source[: match.start()].rsplit("\nasync def ", 1)
        if len(prior_async) == 2:
            cand = prior_async[1].split("(", 1)[0].split("\n", 1)[0].strip()
            if cand and source[: match.start()].rfind(f"async def {cand}") > source[: match.start()].rfind(
                f"def {symbol}"
            ):
                symbol = cand
        findings.append(
            {
                "file": rel,
                "line": line,
                "kind": "assign_pattern",
                "name": match.group(1),
                "symbol": symbol,
                "snippet": match.group(0)[:200],
            }
        )
    return _dedupe(findings)


def scan_typescript_file(path: Path, *, root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return findings
    rel = _rel(path, root)
    is_test = "/tests/" in f"/{rel}" or rel.startswith("tests/")

    def symbol_at(index: int) -> str:
        window = source[max(0, index - 400) : index]
        for pattern in (
            r"function\s+([A-Za-z0-9_]+)\s*\(",
            r"(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(",
            r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)",
        ):
            matches = list(re.finditer(pattern, window))
            if matches:
                return matches[-1].group(1)
        return "module"

    for match in TS_CAP_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "file": rel,
                "line": line,
                "kind": "test_only" if is_test else "ts_literal",
                "name": match.group(1),
                "symbol": symbol_at(match.start()),
                "snippet": match.group(0)[:200],
                "value": int(match.group(2)),
            }
        )
    for match in TS_MATH_CLAMP_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "file": rel,
                "line": line,
                "kind": "ts_clamp",
                "name": f"Math.{match.group(1)}",
                "symbol": symbol_at(match.start()),
                "snippet": match.group(0)[:200],
                "value": int(match.group(2)),
            }
        )
    for match in TS_SLICE_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "file": rel,
                "line": line,
                "kind": "ts_slice",
                "name": f"slice(0,{match.group(1)})",
                "symbol": symbol_at(match.start()),
                "snippet": match.group(0)[:200],
                "value": int(match.group(1)),
            }
        )
    return _dedupe(findings)


def _dedupe(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple, dict[str, Any]] = {}
    for item in findings:
        unique[(item["file"], item["line"], item["kind"], item["name"], item.get("symbol", ""))] = item
    return list(unique.values())


def scan_file(path: Path, *, root: Path | None = None) -> list[dict[str, Any]]:
    root = root or Path(__file__).resolve().parents[2]
    if path.suffix == ".py":
        return scan_python_file(path, root=root)
    if path.suffix in {".ts", ".tsx"}:
        return scan_typescript_file(path, root=root)
    return []


def scan_repository(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or Path(__file__).resolve().parents[2]
    findings: list[dict[str, Any]] = []
    for name in SCAN_ROOTS:
        base = root / name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip(path, root):
                continue
            findings.extend(scan_file(path, root=root))
    findings.sort(key=lambda item: (item["file"], item["line"], item["kind"], item["name"]))
    return findings



def unclassified_findings(findings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = findings if findings is not None else scan_repository()
    out: list[dict[str, Any]] = []
    for item in rows:
        klass = classify(item)
        if klass is None:
            enriched = dict(item)
            enriched["fingerprint"] = fingerprint(item)
            out.append(enriched)
    return out


def unbound_configurable_findings(
    findings: list[dict[str, Any]] | None = None,
    *,
    registry: Any | None = None,
) -> list[dict[str, Any]]:
    """Findings labeled configurable without a valid Control Plane binding."""
    from .definitions import create_default_registry

    reg = registry or create_default_registry()
    rows = findings if findings is not None else scan_repository()
    bad: list[dict[str, Any]] = []
    for item in rows:
        entry = classification_entry(item)
        if entry is None or entry.classification != "configurable":
            continue
        problems = validate_configurable_finding(item, reg)
        if problems:
            enriched = dict(item)
            enriched["fingerprint"] = fingerprint(item)
            enriched["binding_problems"] = problems
            enriched["entry"] = entry.to_public()
            bad.append(enriched)
    # Also fail closed on registry entries marked configurable without definition.
    for row in unbound_configurable_entries(reg):
        bad.append({"fingerprint": row["fingerprint"], "binding_problems": ["registry_entry_unbound"], **row})
    return bad


def audit_report(root: Path | None = None) -> dict[str, Any]:
    findings = scan_repository(root)
    unclassified = unclassified_findings(findings)
    unbound = unbound_configurable_findings(findings)
    by_class: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for item in findings:
        klass = classify(item) or "unclassified"
        by_class[klass] = by_class.get(klass, 0) + 1
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    return {
        "total": len(findings),
        "unclassified": len(unclassified),
        "unbound_configurable": len(unbound),
        "by_class": by_class,
        "by_kind": by_kind,
        "unclassified_samples": unclassified[:50],
        "unbound_configurable_samples": unbound[:50],
    }
