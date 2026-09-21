"""Language-server-aware helpers with regex/heuristic fallback (Milestone 2 / WP3).

Starts with Python and TypeScript/JavaScript. Prefers real language servers when
available and actually usable; always reports which method produced the result.
Falls back to lsp_light with an explicit degraded flag — never claims LSP success
from a regex/heuristic path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _resolve_within_root(path: Path, root: Path) -> Path | None:
    """Resolve a candidate path and fail closed when it escapes the workspace root."""
    try:
        resolved_root = root.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_root)
        return resolved_path
    except (OSError, RuntimeError, ValueError):
        return None


def probe_language_servers() -> dict[str, Any]:
    """Report which language-server / typechecker binaries are on PATH."""
    jedi_ok = False
    try:
        import jedi  # noqa: F401

        jedi_ok = True
    except Exception:
        jedi_ok = False
    tools = {
        "pyright": bool(shutil.which("pyright")),
        "pyright_langserver": bool(shutil.which("pyright-langserver")),
        "tsserver": bool(shutil.which("tsserver")),
        "tsc": bool(shutil.which("tsc")),
        "jedi": jedi_ok,
    }
    any_installed = any(tools.values())
    return {
        "tools": tools,
        "any_installed": any_installed,
        "definition_capable": bool(tools["jedi"]),
        "diagnostics_capable": bool(tools["pyright"] or tools["tsc"] or tools["jedi"]),
        "note": (
            "Installed binaries are preferred when they can produce real results. "
            "Regex/lsp_light paths are always marked degraded and never reported as language_server success."
        ),
    }


def _try_jedi_definitions(root: Path, symbol: str, *, limit: int = 20) -> dict[str, Any] | None:
    """Use Jedi for Python definitions when the package is importable."""
    try:
        import jedi
    except Exception:
        return None
    root = Path(root).expanduser().resolve()
    definitions: list[dict[str, Any]] = []
    # Seed project from preferred python files under root. Resolve each file first
    # so a workspace symlink cannot make HADES read a file outside the approved root.
    py_files: list[Path] = []
    for candidate in root.rglob("*.py"):
        resolved = _resolve_within_root(candidate, root)
        if resolved is None or not resolved.is_file():
            continue
        py_files.append(resolved)
        if len(py_files) >= 80:
            break
    if not py_files:
        return None
    try:
        project = jedi.Project(path=str(root))
    except Exception:
        project = None
    seen: set[str] = set()
    for path in py_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Search for symbol occurrences; ask Jedi for definitions at each hit.
        for lineno, line in enumerate(text.splitlines(), start=1):
            col = line.find(symbol)
            if col < 0:
                continue
            try:
                script = jedi.Script(code=text, path=str(path), project=project)
                got = script.goto(lineno, col + len(symbol), follow_imports=True)
            except Exception:
                continue
            for item in got:
                try:
                    item_path = Path(str(getattr(item, "module_path", None) or "")).resolve()
                except Exception:
                    continue
                if not item_path.is_file():
                    continue
                try:
                    rel = item_path.relative_to(root).as_posix()
                except ValueError:
                    rel = item_path.as_posix()
                key = f"{rel}:{getattr(item, 'line', 0)}:{getattr(item, 'name', symbol)}"
                if key in seen:
                    continue
                seen.add(key)
                definitions.append(
                    {
                        "name": str(getattr(item, "name", symbol) or symbol),
                        "kind": str(getattr(item, "type", "definition") or "definition"),
                        "path": rel,
                        "line": int(getattr(item, "line", 0) or 0),
                        "snippet": (getattr(item, "description", None) or line.strip())[:240],
                        "source": "jedi",
                    }
                )
                if len(definitions) >= limit:
                    break
            if len(definitions) >= limit:
                break
        if len(definitions) >= limit:
            break
    if not definitions:
        return {
            "definitions": [],
            "method": "jedi",
            "lsp_success": False,
            "degraded": True,
            "reason": "jedi_installed_no_definitions",
        }
    return {
        "definitions": definitions[:limit],
        "method": "jedi",
        "lsp_success": True,
        "degraded": False,
        "reason": None,
    }


def _try_jedi_references(root: Path, symbol: str, *, limit: int = 40) -> dict[str, Any] | None:
    try:
        import jedi
    except Exception:
        return None
    root = Path(root).expanduser().resolve()
    refs: list[dict[str, Any]] = []
    py_files: list[Path] = []
    for candidate in root.rglob("*.py"):
        resolved = _resolve_within_root(candidate, root)
        if resolved is None or not resolved.is_file():
            continue
        py_files.append(resolved)
        if len(py_files) >= 80:
            break
    if not py_files:
        return None
    try:
        project = jedi.Project(path=str(root))
    except Exception:
        project = None
    seen: set[str] = set()
    for path in py_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            col = line.find(symbol)
            if col < 0:
                continue
            try:
                script = jedi.Script(code=text, path=str(path), project=project)
                got = script.get_references(lineno, col + len(symbol), include_builtins=False)
            except Exception:
                continue
            for item in got:
                try:
                    item_path = Path(str(getattr(item, "module_path", None) or "")).resolve()
                except Exception:
                    continue
                if not item_path.is_file():
                    continue
                try:
                    rel = item_path.relative_to(root).as_posix()
                except ValueError:
                    rel = item_path.as_posix()
                key = f"{rel}:{getattr(item, 'line', 0)}"
                if key in seen:
                    continue
                seen.add(key)
                refs.append(
                    {
                        "name": symbol,
                        "kind": "reference",
                        "path": rel,
                        "line": int(getattr(item, "line", 0) or 0),
                        "snippet": (line.strip())[:240],
                        "source": "jedi",
                    }
                )
                if len(refs) >= limit:
                    break
            if len(refs) >= limit:
                break
        if len(refs) >= limit:
            break
    if not refs:
        return {
            "references": [],
            "method": "jedi",
            "lsp_success": False,
            "degraded": True,
            "reason": "jedi_installed_no_references",
        }
    return {
        "references": refs[:limit],
        "method": "jedi",
        "lsp_success": True,
        "degraded": False,
        "reason": None,
    }


def _try_pyright_probe(root: Path) -> dict[str, Any] | None:
    """Detect pyright; definitions still require a definition-capable backend (jedi)."""
    pyright = shutil.which("pyright") or shutil.which("pyright-langserver")
    if not pyright:
        return None
    return {
        "definitions": [],
        "method": "pyright_detected",
        "lsp_success": False,
        "degraded": True,
        "reason": "pyright_installed_definition_protocol_not_wired",
        "binary": pyright,
    }


def _try_typescript_server_probe(root: Path) -> dict[str, Any] | None:
    tsserver = shutil.which("tsserver")
    if not tsserver:
        return None
    return {
        "definitions": [],
        "method": "tsserver_detected",
        "lsp_success": False,
        "degraded": True,
        "reason": "tsserver_installed_definition_protocol_not_wired",
        "binary": tsserver,
    }


def _scope_rank(path: str, preferred_paths: list[str] | None) -> int:
    if not preferred_paths:
        return 0
    rel = path.replace("\\", "/")
    for index, pref in enumerate(preferred_paths):
        pref_n = pref.replace("\\", "/")
        if rel == pref_n:
            return 1000 - index
        if rel.startswith(str(Path(pref_n).parent).replace("\\", "/") + "/"):
            return 500 - index
        # Same basename package hint
        if Path(rel).name == Path(pref_n).name:
            return 100 - index
    return 0


def _fallback_definition_payload(
    root: Path,
    symbol: str,
    *,
    limit: int,
    preferred_paths: list[str] | None,
    probe: dict[str, Any],
    ls_attempt: dict[str, Any] | None,
) -> dict[str, Any]:
    from lsp_light import find_definition

    result = find_definition(root, symbol, limit=max(limit * 3, 40))
    defs = list(result.get("definitions") or [])
    method = str(result.get("mode") or "regex-index")
    # Never allow regex mode to be labeled as language_server.
    if "language_server" in method.lower() or method in {"jedi", "pyright", "tsserver"}:
        method = "regex-index"
    lsp_installed = bool(probe.get("any_installed"))
    reason = None
    if ls_attempt and ls_attempt.get("reason"):
        reason = ls_attempt.get("reason")
    elif lsp_installed:
        reason = "installed_ls_not_definition_capable_using_regex"
    else:
        reason = "no_language_server_installed_using_regex"
    defs_sorted = sorted(
        defs,
        key=lambda d: (-_scope_rank(str(d.get("path") or ""), preferred_paths), str(d.get("path") or "")),
    )[:limit]
    return {
        "symbol": symbol,
        "definitions": defs_sorted,
        "count": len(defs_sorted),
        "method": method,
        "mode": method,
        "scoped": bool(preferred_paths),
        "disambiguated": len(defs) > len(defs_sorted) or (len(defs) > 1 and bool(preferred_paths)),
        "degraded": True,
        "fallback": True,
        "lsp_success": False,
        "lsp_installed": lsp_installed,
        "probe": probe,
        "reason": reason,
        "note": "Degraded regex/lsp_light fallback — not a language-server success.",
    }


def find_definition_scoped(
    root: Path,
    symbol: str,
    *,
    limit: int = 20,
    preferred_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Definitions with scope preference for same-named symbols."""
    root = Path(root).expanduser().resolve()
    probe = probe_language_servers()
    ls = _try_jedi_definitions(root, symbol, limit=max(limit * 3, 40))
    if ls is None:
        # Record installed-but-unwired servers without claiming success.
        ls = _try_pyright_probe(root) or _try_typescript_server_probe(root)

    if ls and ls.get("lsp_success") and ls.get("definitions"):
        defs = list(ls["definitions"])[: max(limit * 3, 40)]
        method = str(ls.get("method") or "language_server")
        defs_sorted = sorted(
            defs,
            key=lambda d: (-_scope_rank(str(d.get("path") or ""), preferred_paths), str(d.get("path") or "")),
        )[:limit]
        return {
            "symbol": symbol,
            "definitions": defs_sorted,
            "count": len(defs_sorted),
            "method": method,
            "mode": method,
            "scoped": bool(preferred_paths),
            "disambiguated": len(defs) > len(defs_sorted) or (len(defs) > 1 and bool(preferred_paths)),
            "degraded": False,
            "fallback": False,
            "lsp_success": True,
            "lsp_installed": True,
            "probe": probe,
            "reason": None,
            "note": "Language server / Jedi produced definitions.",
        }

    return _fallback_definition_payload(
        root,
        symbol,
        limit=limit,
        preferred_paths=preferred_paths,
        probe=probe,
        ls_attempt=ls,
    )


def find_references_scoped(
    root: Path,
    symbol: str,
    *,
    limit: int = 40,
    preferred_paths: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    probe = probe_language_servers()
    ls = _try_jedi_references(root, symbol, limit=max(limit * 2, 80))
    if ls and ls.get("lsp_success") and ls.get("references"):
        refs = list(ls["references"])
        method = str(ls.get("method") or "language_server")
        refs_sorted = sorted(
            refs,
            key=lambda d: (-_scope_rank(str(d.get("path") or ""), preferred_paths), int(d.get("line") or 0)),
        )[:limit]
        return {
            "symbol": symbol,
            "references": refs_sorted,
            "count": len(refs_sorted),
            "method": method,
            "mode": method,
            "scoped": bool(preferred_paths),
            "degraded": False,
            "fallback": False,
            "lsp_success": True,
            "lsp_installed": True,
            "probe": probe,
            "reason": None,
            "note": "Language server / Jedi produced references.",
        }

    from lsp_light import find_references

    result = find_references(root, symbol, limit=max(limit * 2, 80))
    refs = list(result.get("references") or [])
    method = str(result.get("mode") or "regex-scan")
    if "language_server" in method.lower():
        method = "regex-scan"
    refs_sorted = sorted(
        refs,
        key=lambda d: (-_scope_rank(str(d.get("path") or ""), preferred_paths), int(d.get("line") or 0)),
    )[:limit]
    lsp_installed = bool(probe.get("any_installed"))
    return {
        "symbol": symbol,
        "references": refs_sorted,
        "count": len(refs_sorted),
        "method": method,
        "mode": method,
        "scoped": bool(preferred_paths),
        "degraded": True,
        "fallback": True,
        "lsp_success": False,
        "lsp_installed": lsp_installed,
        "probe": probe,
        "reason": (
            (ls or {}).get("reason")
            if ls
            else ("no_language_server_installed_using_regex" if not lsp_installed else "installed_ls_not_reference_capable_using_regex")
        ),
        "note": "Degraded regex-scan fallback — not a language-server success.",
    }


def read_diagnostics(root: Path, *, paths: list[str] | None = None) -> dict[str, Any]:
    """Collect diagnostics for Python (py_compile / pyright) and TS (tsc --noEmit) when present."""
    root = Path(root).expanduser().resolve()
    probe = probe_language_servers()
    issues: list[str] = []
    methods: list[str] = []
    requested_targets = list(paths or [])
    if not requested_targets:
        requested_targets = [p.relative_to(root).as_posix() for p in list(root.rglob("*.py"))[:20]]

    # Normalize every requested target against the approved workspace before any
    # file access or external diagnostic tool sees it. Canonical resolved paths
    # also make an in-workspace symlink safe while rejecting one that points out.
    targets: list[str] = []
    target_paths: dict[str, Path] = {}
    for raw_target in requested_targets:
        candidate = root / str(raw_target)
        resolved = _resolve_within_root(candidate, root)
        if resolved is None or not resolved.is_file():
            continue
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in target_paths:
            continue
        targets.append(rel)
        target_paths[rel] = resolved

    # Python: py_compile for syntax.
    import py_compile

    for rel in targets:
        path = target_paths[rel]
        if path.suffix == ".py":
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                issues.append(f"{rel}: {exc}")
                methods.append("py_compile")
        elif path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            # Lightweight: unmatched braces heuristic only unless tsc available.
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if text.count("{") != text.count("}"):
                issues.append(f"{rel}: unbalanced braces")
                methods.append("brace_heuristic")

    used_real_ls = False
    pyright = shutil.which("pyright")
    if pyright and any(str(t).endswith(".py") for t in targets):
        try:
            proc = subprocess.run(
                [pyright, "--outputjson", *targets[:12]],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "CI": "1"},
            )
            raw = (proc.stdout or "").strip()
            if raw.startswith("{"):
                payload = json.loads(raw)
                for diag in (payload.get("generalDiagnostics") or [])[:20]:
                    file = str(diag.get("file") or "")
                    msg = str(diag.get("message") or "")
                    issues.append(f"{file}: {msg}"[:240])
                methods.append("pyright")
                used_real_ls = True
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            methods.append("pyright_failed")

    tsc = shutil.which("tsc")
    if tsc and any(str(t).endswith(ext) for t in targets for ext in (".ts", ".tsx")):
        try:
            proc = subprocess.run(
                [tsc, "--noEmit", "--pretty", "false"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=45,
            )
            for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines()[:20]:
                if "error TS" in line:
                    issues.append(line[:240])
            if any("error TS" in i for i in issues):
                methods.append("tsc")
                used_real_ls = True
            elif proc.returncode == 0:
                methods.append("tsc")
                used_real_ls = True
        except (OSError, subprocess.SubprocessError):
            methods.append("tsc_failed")

    method = "+".join(dict.fromkeys(methods)) if methods else "none"
    degraded = not used_real_ls
    return {
        "issues": issues[:30],
        "method": method,
        "count": len(issues),
        "degraded": degraded,
        "fallback": degraded,
        "lsp_success": used_real_ls,
        "lsp_installed": bool(probe.get("any_installed")),
        "probe": probe,
        "note": (
            "Language-server / typechecker diagnostics used."
            if used_real_ls
            else "Heuristic/py_compile diagnostics only — not a language-server success."
        ),
    }


def impact_for_change(
    root: Path,
    *,
    changed_paths: list[str],
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Relevant dependents for multi-file change impact (LS + heuristics)."""
    deps: list[dict[str, Any]] = []
    methods: list[str] = []
    lsp_success_any = False
    for sym in symbols or []:
        refs = find_references_scoped(root, sym, limit=30, preferred_paths=changed_paths)
        methods.append(str(refs.get("method")))
        lsp_success_any = lsp_success_any or bool(refs.get("lsp_success"))
        for ref in refs.get("references") or []:
            path = str(ref.get("path") or "")
            if path and path not in changed_paths:
                deps.append({"path": path, "symbol": sym, "line": ref.get("line"), "method": refs.get("method")})
    # Import dependents via code_intel when available.
    try:
        from code_intel import analyze_file

        for rel in changed_paths[:12]:
            info = analyze_file(root, rel)
            for imp in info.get("imported_by") or info.get("importers") or []:
                deps.append({"path": str(imp), "symbol": None, "method": "code_intel"})
            methods.append("code_intel")
    except Exception:
        pass
    # Dedupe
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for d in deps:
        key = f"{d.get('path')}:{d.get('symbol')}:{d.get('line')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)
    return {
        "dependents": uniq[:40],
        "method": "+".join(dict.fromkeys(methods)) or "none",
        "count": len(uniq),
        "degraded": not lsp_success_any,
        "lsp_success": lsp_success_any,
    }
