"""Release confidence: local gate inventory + optional dry-run metadata.

Does not fake VERIFY_HADES success on non-Windows cloud agents. Reports what
can be checked locally and what requires the Windows release gate.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

FAIL_LINE_RE = re.compile(
    r"^(?P<label>(FAIL|ERROR|FAILED|AssertionError|TypeError|SyntaxError).+)$",
    re.M,
)
UNITTEST_FAIL_RE = re.compile(r"^(FAIL|ERROR):\s+(?P<test>.+)$", re.M)
SUMMARY_RE = re.compile(r"(FAILED\s*\(.*\)|FAILED|OK|errors?=\d+|failures?=\d+)", re.I)


def parse_what_broke(*blobs: str) -> list[dict[str, str]]:
    text = "\n".join(b for b in blobs if b)
    items: list[dict[str, str]] = []
    for match in UNITTEST_FAIL_RE.finditer(text):
        items.append({"kind": match.group(1).lower(), "label": match.group("test").strip()[:240]})
    if not items:
        for match in FAIL_LINE_RE.finditer(text):
            label = match.group("label").strip()[:240]
            if label in {"FAILED", "OK"}:
                continue
            items.append({"kind": "log", "label": label})
    # de-dupe
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = f"{item['kind']}:{item['label']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:40]


def inventory_gates(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    docs = root / "docs" / "TESTING_RELEASE_GATES.md"
    verify_bat = root / "VERIFY_HADES.bat"
    backend_tests = root / "backend" / "tests"
    frontend_tests = [
        root / "tests" / "source-contracts.test.mjs",
        root / "tests" / "ui-components.test.mjs",
    ]
    verify_stages: list[dict[str, str]] = []
    verify_read_error: str | None = None
    if verify_bat.is_file():
        try:
            bat_text = verify_bat.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            bat_text = ""
            verify_read_error = str(exc)
        for line in bat_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("echo [") and "]" in stripped:
                verify_stages.append({
                    "id": stripped[5:].split("]", 1)[0],
                    "label": stripped.split("]", 1)[-1].strip(". "),
                    "status": "manual",
                    "detail": "Windows VERIFY_HADES.bat — niet automatisch uitgevoerd vanuit deze inventaris",
                })
    items = [
        {
            "id": "docs_gates",
            "label": "Release gate documentatie",
            "status": "ok" if docs.is_file() else "error",
            "detail": str(docs) if docs.is_file() else "docs/TESTING_RELEASE_GATES.md ontbreekt",
        },
        {
            "id": "verify_bat",
            "label": "VERIFY_HADES.bat",
            "status": "error" if verify_read_error else ("ok" if verify_bat.is_file() else "warn"),
            "detail": (
                f"Bestand bestaat maar kon niet worden gelezen: {verify_read_error}"
                if verify_read_error
                else (
                    f"Windows release gate · {len(verify_stages)} stage(s)"
                    if verify_bat.is_file()
                    else "Ontbreekt"
                )
            ),
            "stages": verify_stages,
        },
        {
            "id": "backend_tests",
            "label": "Backend unittest suite",
            "status": "ok" if backend_tests.is_dir() else "error",
            "detail": f"{len(list(backend_tests.glob('test_*.py')))} test modules" if backend_tests.is_dir() else "Geen testmap",
        },
        {
            "id": "frontend_contracts",
            "label": "Frontend source contracts",
            "status": "ok" if frontend_tests[0].is_file() else "warn",
            "detail": ", ".join(str(p.name) for p in frontend_tests if p.is_file()) or "Geen contracttests",
        },
    ]
    # Cheap syntax probe of critical backend modules — surfaces concrete breakage.
    critical = [
        root / "backend" / "main.py",
        root / "backend" / "build_agent.py",
        root / "backend" / "workspace_symbols.py",
        root / "backend" / "release_confidence.py",
    ]
    syntax = syntax_check_python(critical)
    items.append(
        {
            "id": "python_syntax_critical",
            "label": "Python syntax (kritieke modules)",
            "status": "ok" if syntax["ok"] else "error",
            "detail": (
                f"{syntax['checked']} bestanden OK"
                if syntax["ok"]
                else "; ".join(f"{err['path']}: {err['error']}" for err in syntax["errors"][:5])
            ),
            "errors": syntax["errors"],
        }
    )
    overall = "ok"
    if any(item["status"] == "error" for item in items):
        overall = "error"
    elif any(item["status"] == "warn" for item in items):
        overall = "warn"
    what_broke = [
        {"kind": "gate", "label": f"{item['label']}: {item.get('detail') or item['status']}"}
        for item in items
        if item["status"] == "error"
    ]
    return {
        "overall": overall,
        "gates": items,
        "platform": sys.platform,
        "verify_stages": verify_stages,
        "what_broke": what_broke,
        "note": "Volledige VERIFY_HADES.bat draait op Windows na PREPARE_HADES. Dit rapport is inventaris + optionele lokale smoke.",
    }


def run_focused_unittest(repo_root: Path, module: str = "tests.test_world_class_capabilities") -> dict[str, Any]:
    root = Path(repo_root).resolve()
    backend = root / "backend"
    # Allow only dotted module names under tests.* to avoid shell injection.
    if not re.fullmatch(r"tests(?:\.[A-Za-z_][\w]*)+", module or ""):
        return {
            "ok": False,
            "module": module,
            "exit_code": None,
            "stdout": "",
            "stderr": "Ongeldige module — alleen tests.* toegestaan.",
            "what_broke": [{"kind": "policy", "label": "Ongeldige smoke-module"}],
            "note": "Lokale smoke geweigerd.",
        }
    cmd = [sys.executable, "-m", "unittest", module, "-v"]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(backend),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "module": module,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "what_broke": [{"kind": "start", "label": str(exc)[:240]}],
            "note": "Lokale smoke mislukt te starten.",
        }
    stdout = (completed.stdout or "")[-8_000:]
    stderr = (completed.stderr or "")[-4_000:]
    what_broke = parse_what_broke(stdout, stderr)
    if completed.returncode != 0 and not what_broke:
        summary = SUMMARY_RE.findall(stdout + "\n" + stderr)
        if summary:
            what_broke = [{"kind": "summary", "label": item[:240]} for item in summary[-5:]]
        else:
            what_broke = [{"kind": "exit", "label": f"unittest exit {completed.returncode}"}]
    return {
        "ok": completed.returncode == 0,
        "module": module,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "what_broke": what_broke,
        "note": "Focused unittest smoke — geen vervanging van VERIFY_HADES.bat.",
    }


def syntax_check_python(paths: list[Path]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    checked = 0
    for path in paths:
        if not path.is_file() or path.suffix != ".py":
            continue
        checked += 1
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append({"path": str(path), "error": f"{exc.msg} (line {exc.lineno})"})
    return {"checked": checked, "errors": errors, "ok": not errors}
